# domaindrivendev/Swashbuckle.AspNetCore#3915 — `[MinLength]` on dictionary emits `minLength` instead of `minProperties`

Reporter: `[MinLength(1)]` on `IReadOnlyDictionary<string, string?> Values` produces `"minLength": 1` in the generated schema. Expected: `"minProperties": 1`. Same shape applies to `MaxLength` and the combined `Length` attribute. Found by `vacuum` linter — `minLength` is a string-only keyword in OpenAPI; on an object schema it's a spec violation.

## H₀ — `ApplyMinLengthAttribute` branches on Array-vs-else, with no Object branch

**Mode:** deduction. **Confidence:** 99%. **Status:** confirmed.

`src/Swashbuckle.AspNetCore.SwaggerGen/SchemaGenerator/OpenApiSchemaExtensions.cs:182-192`:

```csharp
private static void ApplyMinLengthAttribute(OpenApiSchema schema, MinLengthAttribute minLengthAttribute)
{
    if (schema.Type is { } type && type.HasFlag(JsonSchemaTypes.Array))
    {
        schema.MinItems = minLengthAttribute.Length;
    }
    else
    {
        schema.MinLength = minLengthAttribute.Length;
    }
}
```

The branch only distinguishes Array from everything-else. Dictionary schemas are emitted with `Type = JsonSchemaType.Object` and `AdditionalProperties` set (`SchemaGenerator.cs:CreateDictionarySchema`), so they fall into the `else` and get `MinLength` instead of `MinProperties`. `MaxLength` is invalid here too: OpenAPI specifies `min/maxLength` for strings, `min/maxItems` for arrays, `min/maxProperties` for objects.

**Provenance:** the four Apply* helpers all share the binary branch — they predate OpenAPI 3.x's clearer separation of object-cardinality keywords, or simply weren't extended when dictionary support landed. Git blame on the surrounding `ApplyValidationAttributes` shows it's been stable for years.

**Edge generated:** the same Array-vs-else split exists in `ApplyMaxLengthAttribute` (l.206), `ApplyMinLengthRouteConstraint` (l.194), `ApplyMaxLengthRouteConstraint` (l.218), and `ApplyLengthAttribute` (l.230). Fan out to verify all five paths and confirm the fix shape.

## H₁ — Bug is systemic across all five length-attribute helpers

**Mode:** induction. **Perturbation:** grep `HasFlag(JsonSchemaTypes.Array)` in `OpenApiSchemaExtensions.cs`.

**Result (divergent confirming):** five sites, all using the same `Array → MinItems/MaxItems, else → MinLength/MaxLength` pattern. None has an Object branch.

| Helper | Line | Array branch | Else branch | Missing Object branch? |
|---|---|---|---|---|
| `ApplyMinLengthAttribute` | 182 | MinItems | MinLength | yes |
| `ApplyMaxLengthAttribute` | 206 | MaxItems | MaxLength | yes |
| `ApplyMinLengthRouteConstraint` | 194 | MinItems | MinLength | yes (less critical — route params aren't dictionaries) |
| `ApplyMaxLengthRouteConstraint` | 218 | MaxItems | MaxLength | yes (less critical) |
| `ApplyLengthAttribute` | 230 | MinItems+MaxItems | MinLength+MaxLength | yes |

H₁ confirmed: fix must touch the three attribute helpers (`MinLength`, `MaxLength`, `Length`). Route-constraint helpers are technically wrong by the same logic but unreachable for dictionaries (you can't bind a dictionary from a route segment); patch them anyway for consistency, no behavior change for any real user.

**Status:** confirmed.

## H₂ — Detect dictionaries via `Type.HasFlag(Object)` (cheap and sufficient)

**Mode:** abduction → deduction. **Confidence:** 95%. **Status:** confirmed.

Two candidate detectors:

- **A.** `schema.Type.HasFlag(JsonSchemaTypes.Object)` — fires on any object schema, including plain classes.
- **B.** `schema.Type.HasFlag(JsonSchemaTypes.Object) && schema.AdditionalProperties != null` — fires only on dictionary-shaped schemas.

`[MinLength]` on a plain class is meaningless in MVC (the attribute targets strings/arrays/collections by `IList`/`ICollection`), so A and B differ only on (a) authoring mistakes and (b) types that happen to surface as objects without `AdditionalProperties`. In both cases `MinProperties` is a strictly more spec-compliant landing than `MinLength`. Pick A — smaller diff, no need to thread `AdditionalProperties` through, and the OpenAPI document stays valid in the corner case where someone slaps `[MinLength]` on a class.

Resulting fix shape per helper:

```csharp
private static void ApplyMinLengthAttribute(OpenApiSchema schema, MinLengthAttribute minLengthAttribute)
{
    if (schema.Type is { } type)
    {
        if (type.HasFlag(JsonSchemaTypes.Array))
        {
            schema.MinItems = minLengthAttribute.Length;
            return;
        }
        if (type.HasFlag(JsonSchemaTypes.Object))
        {
            schema.MinProperties = minLengthAttribute.Length;
            return;
        }
    }
    schema.MinLength = minLengthAttribute.Length;
}
```

Same shape for `MaxLength`, `Length` (writes both Min/MaxProperties on the Object branch), and the two Route constraints.

## H₃ — Inlined-only

**Mode:** deduction. **Status:** confirmed.

`SchemaGenerator.GenerateSchemaForMember:130` only calls `ApplyValidationAttributes` when the schema is `OpenApiSchema concrete` (inlined). When the dictionary surfaces as `OpenApiSchemaReference` (self-referencing dictionaries), validation attributes are dropped entirely — pre-existing behavior, unchanged by this fix. The reporter's `IReadOnlyDictionary<string, string?>` is not self-referencing, so its schema is inlined and the fix applies.

## H₄ — Provenance / idempotency

`gh pr list --repo domaindrivendev/Swashbuckle.AspNetCore --search "minProperties MinLength dictionary"` — run during ship gate. The issue is labelled `help-wanted`, no assignee, no PRs at investigation time.

**Risk:** users currently receiving spec-invalid `"minLength"` on an object schema will start receiving `"minProperties"`. Any downstream tooling that silently ignored the bogus `minLength` keeps working; any tooling that errored on it now stops erroring. No realistic user can be depending on the broken output.

## Graph state

| Node | Status | Mode | Confidence |
|---|---|---|---|
| H₀ | confirmed (root cause in `OpenApiSchemaExtensions.cs:182`) | deduction | 99% |
| H₁ | confirmed (systemic across 5 helpers) | induction | 99% |
| H₂ | confirmed (fix shape — Object branch via `HasFlag(Object)`) | deduction | 95% |
| H₃ | confirmed (inlined-only; references untouched) | deduction | 95% |
| H₄ | pending (idempotency at ship gate) | — | — |

## Frontier

- Phase 5 (prework): add `DictionaryWithMinMaxLength` + `DictionaryWithLength` properties to `TypeWithValidationAttributes` fixture; assert `MinProperties`/`MaxProperties` on the generated schema. The current test asserts only string/array variants — extending it covers the new branch.
- Phase 6 (benchmark): N/A — correctness fix.
- Phase 7 (bug hunt): codex on the diff.
- Phase 8 (ship): human-gated.

## Pruning log

- "Maybe the bug is in `CreateDictionarySchema` mis-emitting Type" — refuted by reading `SchemaGenerator.cs:386-410`; dictionary schema is correctly `Type=Object` with `AdditionalProperties`. The bug is downstream, in attribute application.
- "Maybe `OpenApiSchema.MinProperties` isn't exposed in this version of Microsoft.OpenApi" — refuted by `JsonObjectValidator.cs` already reading `schema.MinProperties` / `schema.MaxProperties`.
