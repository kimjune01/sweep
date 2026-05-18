# Hypothesis Graph: domaindrivendev/Swashbuckle.AspNetCore#3936

Investigation date: 2026-05-18
Issue: https://github.com/domaindrivendev/Swashbuckle.AspNetCore/issues/3936
Status: diagnosis converged, PR not possible from this environment

## Environment / Perturbation Access

- Local repository clone: unavailable.
- Shell network: unavailable (`git ls-remote https://github.com/domaindrivendev/Swashbuckle.AspNetCore.git HEAD` failed with DNS resolution error).
- `dotnet`: unavailable in PATH.
- `codex exec`: installed but sandbox initialization failed with `Operation not permitted`.
- Perturbation surface used: upstream GitHub issue text, raw source inspection, related issue/PR history, and static execution tracing.

Confidence is downgraded by ~10% because no local repro or test run could be executed.

## Blind-Blind Pushout

### Primary A

Root cause: dictionary `object` values resolve to Swashbuckle's dynamic data contract, which generates an `OpenApiSchema` with no `Type`. The dictionary member nullability path then calls `SetNullable()` on that untyped schema. `SetNullable()` seeds missing `Type` as `JsonSchemaType.Null`, so a dynamic dictionary value collapses to null-only.

Fix shape: special-case dynamic/object dictionary value schemas before nullability mutation, preferably in the dictionary-value nullability path, so `additionalProperties` becomes `object|null` or remains unconstrained rather than becoming `null`.

### Pushout B

Root cause: independently converged on the same interaction: `object` dictionary values use `DataContract.ForDynamic`, `GenerateConcreteSchema()` returns `new OpenApiSchema()` with no type, then dictionary nullability calls `SetNullable()`, which turns no type into `Null`.

Preferred fix shape: narrow fix in dictionary-value handling when value type is `object` or resolves to dynamic, rather than broad changes to all untyped schemas.

### Where A and B Diverge

- A initially considered changing `SetNullable()` globally to seed `Object | Null` for missing types.
- B argued for a narrower change because missing `Type` can intentionally mean unconstrained JSON Schema, and globally changing it to `object` could break dynamic schemas that may serialize strings, numbers, arrays, booleans, or objects.

Merged edge: investigate whether the decisive fix should live in `SetNullable()` or only in dictionary additional-properties handling.

## Graph State

| Node | Hypothesis | Status | Trajectory | Confidence |
| --- | --- | --- | --- | --- |
| H0 | `IDictionary<XXX, object>` generates null-only dictionary value schema in v10.1.7/.NET 10 | confirmed by issue observation only | divergent from expected schema | 80% |
| H1 | `SetNullable()` seeds untyped dynamic dictionary value schema as `Null` | confirmed by static trace | divergent supporting | 86% |
| H2 | Dictionary detection misses `IImmutableDictionary` | killed by static trace | divergent against | 82% |
| H3 | Serializer contract maps `object` to normal object schema and bug is downstream OpenAPI serialization only | killed by source trace | divergent against | 85% |
| H4 | Broadly changing `SetNullable()` is the safest fix | refined / too broad | oscillatory | 70% |
| H5 | Narrowly seed object type only for dynamic dictionary additionalProperties before nullability | partial, candidate fix | convergent | 78% |

## Nodes

### H0: Baseline Observation

Hypothesis: The issue reporter's schema output is a real regression in Swashbuckle 10.1.7/.NET 10: dictionary values of type `object` emit `type: null`.

Null: The output is expected for dynamic values or caused by a user configuration issue.

Perturbation: Read issue #3936 and trace claimed behavior against current upstream source.

Trajectory: The issue describes `System.Object` as dynamic/unknown, then nullable dictionary property handling replacing missing type with `Nullable`. Current source contains that exact path.

Shape: Divergent from expected behavior.

Kill condition: If source did not contain a path from dictionary `object` value to `OpenApiSchema.Type = Null`, H0 would be killed.

Edge: Trace dictionary generation and nullability mutation.

Reasoning mode: Induction from issue report plus deduction from code.

### H1: Dynamic Schema + Nullability Mutation

Hypothesis: `SetNullable()` collapses dictionary `object` values to null-only.

Null: `SetNullable()` receives a schema with an existing non-null type, or the null-only type comes from Microsoft.OpenApi serialization.

Perturbation:

1. `JsonSerializerDataContractResolver.GetDataContractForType(object)` maps `object`, `JsonDocument`, and `JsonElement` to `DataContract.ForDynamic(...)`.
2. `DataContract.ForDynamic(...)` sets `DataType.Unknown`.
3. `SchemaGenerator.GenerateConcreteSchema()` falls through to `default` for unknown and returns `new OpenApiSchema()` with no `Type`.
4. `CreateDictionarySchema()` sets `AdditionalProperties = GenerateSchema(dataContract.DictionaryValueType, schemaRepository)`.
5. `GenerateSchemaForMember()` detects generic dictionaries and runs `SetNullable(additionalProperties, !memberInfo.IsDictionaryValueNonNullable())`.
6. `SetNullable()` does `schema.Type ??= JsonSchemaType.Null; schema.Type |= JsonSchemaType.Null;`.

Trajectory: Every step monotonically supports the hypothesis.

Shape: Divergent supporting.

Kill condition: A local repro showing `AdditionalProperties.Type` not null before `SetNullable()` would kill or refine this.

Edge: Candidate fix should avoid treating missing dynamic type as null-only.

Provenance:

- Origin commit/PR: the .NET 10 / Microsoft.OpenApi v2 migration landed in PR #3283, merged 2025-11-11 by martincostello. The PR's stated purpose was .NET 10 support and Microsoft.OpenApi v1 to v2 migration.
- Related issue: #3387 reported that bitwise nullability operations did nothing when `OpenApiSchema.Type` was null; it proposed exactly the `schema.Type ??= JsonSchemaType.Null` pattern now present.
- Related issue: #3649 reports another v10 `type: "null"` interaction with reference/allOf schemas.
- Risk assessment: `schema.Type ??= Null` fixed missing-nullability cases but is unsafe for schemas where missing type means "unconstrained" rather than "unknown bug."

### H2: Immutable Dictionary Detection Miss

Hypothesis: `IImmutableDictionary<TKey, object>` fails because the dictionary-type nullability block only checks `IDictionary<,>` and `IReadOnlyDictionary<,>`.

Null: `IImmutableDictionary<TKey,TValue>` implements an interface that passes existing detection.

Perturbation: Inspect dictionary detection in `JsonSerializerDataContractResolver.IsSupportedDictionary()` and `GenerateSchemaForMember()`; both inspect generic interfaces for `IDictionary<,>` / `IReadOnlyDictionary<,>`.

Trajectory: `IImmutableDictionary<TKey,TValue>` is expected to implement `IReadOnlyDictionary<TKey,TValue>`, so the same bug path should apply rather than a separate detection miss.

Shape: Divergent against separate-root-cause hypothesis.

Kill condition: A runtime reflection test showing `IImmutableDictionary<,>` lacks `IReadOnlyDictionary<,>` would reopen this.

Edge: Include immutable dictionary in regression test because the issue names it, but do not fix a separate detector unless test fails.

### H3: OpenAPI Serialization-Only Bug

Hypothesis: Swashbuckle holds a valid schema internally and Microsoft.OpenApi serializes it incorrectly.

Null: Swashbuckle internally sets `Type = JsonSchemaType.Null`.

Perturbation: Static trace of `SetNullable()` shows the internal `OpenApiSchema.Type` is assigned `Null` when missing.

Trajectory: Divergent against serialization-only explanation.

Shape: Divergent against.

Kill condition: Local debug trace showing `Type == null` immediately before serialization while output is `type: null`.

Edge: Fix belongs in schema generation before serialization.

### H4: Global `SetNullable()` Change

Hypothesis: Change `SetNullable()` so any schema with no `Type` becomes `Object | Null` when nullable.

Null: Some no-type schemas intentionally mean unconstrained JSON Schema and should not become object-only.

Perturbation: Compare dynamic `object` schema semantics. C# `object` can carry any JSON value under System.Text.Json, while JSON Schema `type: object` means JSON object only.

Trajectory: Oscillatory. Global change fixes issue #3936 but risks narrowing standalone dynamic object schemas and possibly schema-filter-produced untyped schemas.

Shape: Oscillatory.

Kill condition: If project convention already maps all dynamic/object schemas to `object`, a global change becomes safer; current source maps dynamic to no type.

Edge: Prefer a narrow dictionary additional-properties fix.

### H5: Narrow Dictionary AdditionalProperties Fix

Hypothesis: Before applying dictionary-value nullability, if the generated `AdditionalProperties` schema has no `Type` because the dictionary value type is `object`/dynamic, seed it with `JsonSchemaTypes.Object`, then call `SetNullable()`.

Null: The correct schema for `Dictionary<string, object?>` should remain unconstrained `{}` and nullable should not be represented with `type` at all.

Perturbation: Compare issue expectation and existing behavior. The reporter explicitly expects `object` or `object|null`, and Swashbuckle's dictionary schema already frames dictionary values through `additionalProperties`, where an explicit value schema is expected.

Trajectory: Convergent. It addresses the reported invalid null-only schema while minimizing blast radius relative to global `SetNullable()` changes.

Shape: Convergent / candidate fix.

Kill condition: A maintainer preference or test showing `{}` is the intended schema for dynamic dictionary values would refine the fix to "skip `SetNullable()` when `AdditionalProperties.Type` is null" instead.

Edge: Implement test for `IDictionary<string, object?>` and `IImmutableDictionary<string, object?>`, then apply narrow fix.

## Candidate Patch Shape

Target: `src/Swashbuckle.AspNetCore.SwaggerGen/SchemaGenerator/SchemaGenerator.cs`

Likely insertion point: inside `GenerateSchemaForMember()`, in the dictionary nullability block immediately before `SetNullable(additionalProperties, ...)`.

Sketch:

```csharp
if (isDictionaryType && schema.AdditionalProperties is OpenApiSchema additionalProperties)
{
    if (additionalProperties.Type is null &&
        dataContract.DictionaryValueType == typeof(object))
    {
        additionalProperties.Type = JsonSchemaTypes.Object;
    }

    SetNullable(additionalProperties, !memberInfo.IsDictionaryValueNonNullable());
}
```

Potential refinement: use `GetDataContractFor(dataContract.DictionaryValueType).DataType == DataType.Unknown` instead of `== typeof(object)` if `JsonDocument` / `JsonElement` should also get object/null treatment. This needs tests because JSON document/element may represent any JSON value, not only object.

## Regression Tests To Add

Target likely belongs in the SwaggerGen schema generator tests near existing dictionary/nullability cases.

Test models:

```csharp
public class DictionaryOfObjectContainer
{
    public IDictionary<string, object?> Values { get; set; } = new Dictionary<string, object?>();
}

public class ImmutableDictionaryOfObjectContainer
{
    public IImmutableDictionary<string, object?> Values { get; set; } = ImmutableDictionary<string, object?>.Empty;
}
```

Assertions:

- `schema.Properties["values"].AdditionalProperties.Type` is not `JsonSchemaType.Null`.
- For nullable value type, expected type is `JsonSchemaTypes.Object | JsonSchemaType.Null` if maintainers accept issue reporter's expected shape.
- Add a non-nullable `object` dictionary value test if nullable annotations are enabled: expected `JsonSchemaTypes.Object` without `Null`.
- Existing dictionary value types such as `string?`, `int?`, and custom DTO values should remain unchanged.

## Frontier Edges

| Edge | Experiment | Predicted Classification | Status |
| --- | --- | --- | --- |
| E1 | Local repro on v10.1.7 with `IDictionary<string, object?>` and OpenAPI 3.1 serialization | divergent supporting H1 | blocked: no clone/dotnet |
| E2 | Apply narrow patch and run schema generator tests | convergent if `additionalProperties.type` becomes object/null | blocked: no clone/dotnet |
| E3 | Test standalone `object?` property after narrow patch | no change | pending |
| E4 | Test `JsonElement?` and `JsonDocument?` dictionary values | may split object vs unconstrained semantics | pending |
| E5 | Search/open PR idempotency guard | no current PR directly addressing #3936 found in web search; GitHub issue showed no linked branch/PR | partial |

## Reasoning Mode Table

| Claim | Mode | Confidence |
| --- | --- | --- |
| Issue #3936 is open and unlinked to a PR as loaded | Induction from GitHub issue page | 90% |
| `object` maps to `DataContract.ForDynamic` | Deduction from source | 95% |
| Dynamic data contract returns untyped schema | Deduction from source | 95% |
| Dictionary member nullability calls `SetNullable()` on `AdditionalProperties` | Deduction from source | 95% |
| `SetNullable()` produces `Null` for missing type | Deduction from source | 95% |
| Narrow dictionary-only fix is safest | Abduction + risk analysis | 78% |
| Global `SetNullable()` change is too broad | Abduction + semantic analysis | 70% |

## Pruning Log

- Killed H2 as a primary cause: immutable dictionaries likely flow through `IReadOnlyDictionary<,>`, same path as `IDictionary<,>`.
- Killed H3: source assigns `JsonSchemaType.Null` internally; not merely writer serialization.
- Refined H4: broad fix addresses symptom but risks changing intentionally untyped dynamic schemas.

## Halt / Ship Status

No PR can be prepared or shipped from this environment because the target repository is not present, shell network cannot fetch it, and `dotnet` is unavailable. The investigation converged to a small candidate fix and regression test plan, but Phase 5-8 are blocked until a writable clone with the .NET SDK is available.
