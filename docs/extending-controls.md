# Extending OpenHMI controls

This guide is for repository contributors. HMI authors should configure controls
and bindings in the designer without needing these implementation details.
See [architecture](architecture.md#module-boundaries-and-compatibility-checks)
for ownership and [contract coverage](contract-coverage.md) for current checks.

## Define the saved contract first

Choose a stable `kind` and the appropriate `control_models_*` family. Reuse the
shared strict/state/numeric/range bases. Keep field types, bounds and defaults
explicit; validators should reject inconsistent settings with useful messages.
Use `canvas_models.py` and `identity_models.py` for those domain configurations.
Schema modules must not import services, routers, transport or persistence.

Import the new class explicitly in `project_models.py` and add it to the canonical
`Control` discriminated union. Preserve existing union members and their order.
Add its explicit compatibility export in `projects.py`; keep model objects shared
rather than redefining a class under the legacy import path. Adding a field to an
existing model should preserve older saved projects through a suitable default.
Changing storage or schema versions requires a separate migration decision.

## Register the designer and renderer

Add the saved-kind/component-name mapping to `frontend/model.mjs`. Implement the
palette definition in the matching `palette-inputs`, `palette-images`,
`palette-process`, `palette-machine` or `palette-readouts` factory. Reuse fresh
field descriptors from `palette-fields.jsx`; do not share mutable catalog options
between projects. Keep renderers in their focused control modules.

Register the component in `palette-components.jsx`'s explicit order and in the
appropriate designer category in `controls.jsx`. Composition must still reject
missing or duplicate components. Make incomplete bindings clear in the designer;
a default needing operator configuration should not become a silent runtime tag.

Review both `toEditor` and `toProject` in `model.mjs`. The serializer has explicit
branches: a new property is not saved automatically because it appears in a
Pydantic model or palette field. Keep false, zero, empty text and numeric-looking
strings where they carry meaning. Use a nondefault round-trip fixture so a
backend default cannot conceal a dropped field.

## Integrate bindings and runtime behavior

Add binding checks to the applicable `binding_controls`, `binding_displays` or
`binding_charts` module. Keep `project_validation.py`'s project-first and
per-control ordering intact; rejected saves must preserve draft and revision.
Read schema validity separately from binding validity: a syntactically valid tag
name does not establish a configured, writable or type-compatible binding.

If a control introduces tag-bearing fields or nested collections, update both
`frontend/faceplate-model.mjs` and backend expansion/acquisition in `screens.py`.
Check relative UDT members, secondary screens, conditions and limit tags. Let the
driver aggregate consumer demand; renderers must not perform PLC transport I/O.

For operator edits, use the existing audited value route and touch-entry/security
components where applicable. Update `control_contracts.py` input families and
`control_routes.py` dispatch only when the new kind needs it. Preserve permission
checks, group restrictions, project revision guards, limits and journal ordering.
Do not turn a command timeout or communication error into an automatic write retry.
Display bad/stale quality for affected bindings without hiding healthy data.

Put new HTTP registration in a focused router and request serialization in a
production browser helper. Contract tests should call that helper, not a test-only
copy of the payload. For query parameters, bind generated URLs through the actual
router as in `test_command_contract.py`; Pydantic body checks alone do not test
path/query parsing. Preserve encoded names, project headers and integer precision.

## Trace an existing example

`NumericStepper` spans `control_models_inputs.py`, the canonical `Control` union,
`palette-inputs.jsx`, `model.mjs` and `control_contracts.py`. Its `step` is preserved
explicitly by serialization; binding checks require unscaled numeric tags and a
whole-number step for integer targets. Runtime edits reuse audited value writes.
The contract round-trip fixture sets `step=0.25` and nondefault decimal precision.
Trace these connections before using it as a starting point for another control.

## Validate the change

Install the documented Python dependencies, Node 20+ and `npm ci`. From the repo:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_frontend_contract tests.test_project_models tests.test_engineering_contract tests.test_binding_rules -v
npm.cmd run build
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Extend the nondefault/Unicode/security/limit/faceplate fixture when adding a field.
The existing checks cover palette/schema kinds, family/category uniqueness,
select options, field preservation, request payloads and UDT expansion. Add a
focused browser workflow for changed interaction, quality or security behavior.
Run only relevant browser workflows during development; broaden after resolving
actual failures or concerns. Google Chrome is required by the Playwright config.

These checks are offline software evidence. They do not establish native display,
Windows identity or controller acceptance. Do not start a soak or access a PLC as
part of this workflow. Keep application logic and authored inputs in retained
storage. Put disposable runs in a unique project/chat/round folder under the
user's CodexScratch root; retain compact useful evidence in ignored `.local`,
verify it, then remove only the completed scratch owned by the round.
