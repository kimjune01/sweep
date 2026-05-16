# domaindrivendev/Swashbuckle.AspNetCore#3931 — Empty `<param example="">` dropped from OpenAPI

Issue: an XML doc `<param name="petId" example="">` should serialize as `"example": ""` in the generated OpenAPI document, but the empty value is suppressed. Reporter pinpointed `XmlCommentsParameterFilter.cs:77`.

## H₀ — The cited line filters empty strings

**Mode:** deduction. **Confidence:** 99%. **Status:** confirmed.

`XmlCommentsParameterFilter.ApplyParamTags` (line 76-80):
```csharp
var example = paramNode.GetAttribute("example");
if (!string.IsNullOrEmpty(example))
{
    concrete.Example = XmlCommentsExampleHelper.Create(...);
}
```

`XPathNavigator.GetAttribute` returns `""` when the attribute is **missing** *and* when it is **present-but-empty**. The two are indistinguishable through the return value. `!string.IsNullOrEmpty` therefore drops both cases, silently coalescing "no example was authored" with "an explicit empty example was authored."

**Provenance:** `git blame` shows this guard predates the v10 rewrite and was likely written when distinguishing missing/empty wasn't a concern. The reporter's own JSON shows property-level empty examples *do* survive — because property handling (line 39-44) uses `if (exampleNode != null)`, gated on element presence, not value emptiness. Only the attribute path is buggy.

**Edge generated:** the same `string.IsNullOrEmpty(example)` pattern likely exists wherever `GetAttribute("example")` is read. Fan out.

## H₁ — The bug is parameter-only

**Perturbation:** `grep "GetAttribute(\"example\")"` across `src/`.

**Result (divergent against):** four call sites, three of them buggy in the same way:

| File | Line | Pattern | Status |
|---|---|---|---|
| `XmlCommentsParameterFilter.cs` | 76-77 | `var example = paramNode.GetAttribute("example"); if (!string.IsNullOrEmpty(example))` | **buggy** |
| `XmlCommentsRequestBodyFilter.cs` | 61 | same | **buggy (form parameters)** |
| `XmlCommentsRequestBodyFilter.cs` | 145, 159 | same (request body) | **buggy** |
| `XmlCommentsSchemaFilter.cs` | 55-56 | same (record default ctor params) | **buggy** |

H₁ killed: the bug is systemic across attribute-based example handling. The fix must touch all four sites or live in a shared helper. **Status:** killed → refined as H₂.

## H₂ — Add an `XPathNavigator.HasAttribute` helper

**Mode:** abduction → deduction. **Confidence:** 95%. **Status:** confirmed.

Cleanest fix: extend `XPathNavigatorExtensions` so callers can ask "is the attribute present?" separately from "what is its value?" Two API options:

- **A** `bool HasAttribute(string name)` — caller does `if (nav.HasAttribute("example")) { var v = nav.GetAttribute("example"); ... }`
- **B** `string GetAttributeOrNull(string name)` — returns `null` when absent, value (possibly `""`) when present.

B is more compact at call sites (one read instead of two) and matches the element-side pattern (`SelectFirstChild` returns `null` when absent). Pick B.

Implementation uses `XPathNavigator.MoveToAttribute` on a clone (XPathNavigator is mutable; never mutate the caller's nav):

```csharp
internal static string GetAttributeOrNull(this XPathNavigator navigator, string name)
{
    var clone = navigator.Clone();
    return clone.MoveToAttribute(name, EmptyNamespace) ? clone.Value : null;
}
```

Then each buggy call site becomes:
```csharp
var example = paramNode.GetAttributeOrNull("example");
if (example != null)
{
    concrete.Example = XmlCommentsExampleHelper.Create(...);
}
```

`XmlCommentsExampleHelper.Create` already handles `""` correctly (line 22-25 short-circuits to `JsonValue.Create(exampleString)` for string-typed schemas; `null` doesn't enter the helper).

## H₃ — Provenance check on the fix shape

**Perturbation:** check whether anyone in the upstream issue tracker has filed a competing PR.

```
gh pr list --repo domaindrivendev/Swashbuckle.AspNetCore --search "empty example 3931"
```

(Run during Phase 8 idempotency guard, before push.)

**Risk assessment:** the fix changes externally-observable JSON for users who currently author `example=""` and expect it to be omitted. Mitigation: that behavior was already inconsistent (worked for `<example></example>` elements, dropped for `example=""` attributes), so users couldn't reasonably depend on suppression. The reporter is explicitly asking for the present-empty case to survive.

## Graph state

| Node | Status | Mode | Confidence |
|---|---|---|---|
| H₀ | confirmed | deduction | 99% |
| H₁ | killed → refined (systemic, not parameter-only) | induction | 95% |
| H₂ | confirmed (fix design) | deduction | 95% |
| H₃ | pending (idempotency, ship gate) | — | — |

## Frontier

- Phase 5 (prework): trivial — add unit test that fails on master, passes with fix. No separate experiment repo needed; the bug is mechanical.
- Phase 6 (benchmark): N/A — correctness fix, no performance dimension.
- Phase 7 (bug hunt): run codex on the diff.
- Phase 8 (ship): human-gated.

## Pruning log

- "Maybe `XmlCommentsExampleHelper.Create` mishandles `""`" — refuted by reading line 22-25; it produces `JsonValue.Create("")` correctly.
- "Maybe property/element handling has the same bug" — refuted by reading line 40 (`if (exampleNode != null)`) and confirmed by the reporter's own output showing Species' example survived.
