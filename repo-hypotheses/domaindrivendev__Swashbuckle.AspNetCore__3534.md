# Swashbuckle.AspNetCore #3534 — Nested required properties marked required when outer is optional

**Issue:** [FromForm] `Model(Inner? inner, [Required] string other)` where `Inner` has `[Required] string prop`. Swashbuckle emits `inner.prop` as required, even though `inner` itself is optional. Reporter narrowed scope: only multipart/form-data (form-flattening codepath); JSON body produces correct nested schema.

## H₀ — Observation

Form parameters bound to a complex type get flattened by ASP.NET Core's `ApiExplorer` into dotted-name `ApiParameterDescription`s (e.g. `inner.prop`). Swashbuckle's `GenerateSchemaFromFormParameters` (`SwaggerGenerator.cs:916`) iterates these and adds each to `requiredPropertyNames` if `IsRequiredParameter()` is true. The leaf's `[Required]` propagates up; the container's optionality does not.

**Perturbation surface:** read code, write a unit test that simulates ApiExplorer's flattened output.

**Mode:** deduction (reading code). Confidence: 95%.

## H₁ — Root cause (proposed)

`GenerateSchemaFromFormParameters` treats each flattened parameter in isolation. `IsRequiredParameter()` looks only at the leaf's attributes / `apiParameter.IsRequired`. Nothing in the loop walks the container chain to ask "is any ancestor optional?" The bug fires whenever there's a `.` in the parameter name and any intermediate property is `Nullable<T>`, a nullable reference (`Inner?`), or lacks `[Required]/[BindRequired]`.

**Kill condition:** add a unit test that passes a flattened parameter `inner.prop` with `IsRequired=true` whose original action parameter is `Model(Inner? inner, ...)`. Current code emits `required: [inner.prop]`. The fix must emit `required: []` for `inner.prop`.

**Mode:** abduction → deduction. Confidence: 85%.

## H₂ — Fix shape

Before adding the leaf to `requiredPropertyNames`, walk the property path implied by the dotted name from the action's root `ParameterInfo.ParameterType`. If any intermediate property is optional (nullable reference, `Nullable<T>`, or lacks `[Required]`/`[BindRequired]`), drop the required claim. Leaf-only parameters (no `.`) keep current behavior.

Helper: `IsRequiredFlattenedFormParameter(ApiParameterDescription)`.

**Edge cases handled:**
- Single-segment name → original behavior preserved
- `ParameterInfo` null → fall back to original behavior (don't get clever)
- `[Required] Inner? inner` → ancestor IS required; leaf stays required (the user opted into "object present, then prop required")
- `[FromForm(Name="x")]` rename → property lookup is case-insensitive against declared property names

**Mode:** abduction. Confidence: 70% before test; raise after fail-on-master / pass-with-fix verification.

## Provenance

- File `SwaggerGenerator.cs:947` — `if (formParameter.IsRequiredParameter()) requiredPropertyNames.Add(name)`
- File `ApiParameterDescriptionExtensions.cs:27` — `IsRequiredParameter` (leaf-only)
- Reporter's narrowing comment (multipart-only) matches: only `GenerateSchemaFromFormParameters` flattens via dotted names. Body codepath uses `GenerateSchema` directly on the complex type, which honors nested nullability.
- `gh pr list` for `nested required form` and `#3534`: no open or merged PRs.
- npenza commented 2025-09-03 "happy to help" — no PR followed (8+ months silent). Not duplicate.

## Frontier edges

- E₁ (test): does a flattened `inner.prop` parameter actually arrive with `IsRequired=true` from real ApiExplorer? Test by simulating in unit test (ApiExplorer behavior reproducible by hand-constructed `ApiParameterDescription`).
- E₂ (regression): does the fix change existing snapshot tests for `FromFormObject*`? Re-run verify suite.

## Status table

| Node | Status | Shape | Mode |
|------|--------|-------|------|
| H₀ observation | confirmed | divergent | deduction |
| H₁ root cause | confirmed (code-trace) | divergent | deduction |
| H₂ fix shape | confirmed (test passes) | divergent | induction |

## Verification

- Added test `GetSwagger_Drops_Required_For_Flattened_Form_Property_When_Ancestor_Is_Optional`.
- Fails on master (`Inner.Prop` is in `Required`).
- Passes with fix (`Inner.Prop` dropped from `Required`; `Other` retained).
- Full SwaggerGen.Test suite green: 719/719 (net9.0).
- One subtle: the test fixture must use `[property: Required]` to land the attribute on the auto-generated record property; the runtime `IsRequiredParameter` path for `ControllerParameterDescriptor` reads `PropertyInfo.GetCustomAttributes`, not the constructor parameter's attributes. The real ApiExplorer in MVC populates `ApiParameterDescription.IsRequired` from richer ModelMetadata that already considers the property/required attribute; this test simulates the post-flattening state directly.
