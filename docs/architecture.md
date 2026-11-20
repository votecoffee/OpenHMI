# Live HMI builder architecture

Decision date: 2026-11-04. Status: working local simulation prototype.

OpenHMI is a live HMI builder for automation developers. A basic application
must be possible without code: drop controls, select tags, configure formatting
and built-in actions, and apply the screen to a running viewer. Python is the
customization language. HTML, CSS, JavaScript, React and npm must not appear in
the HMI developer workflow. These remain implementation tools for OpenHMI contributors.

AdvancedHMI compatibility is no longer a requirement. The earlier
[compatibility investigation](advancedhmi-compatibility.md) is historical context.
FUXA is a feature/interaction reference only; it is not a dependency, integration
candidate or mandatory comparison gate.

## Editor assessment

| Reference | Useful capability | Decision |
| --- | --- | --- |
| [Anvil](https://anvil.works/docs/client/quickstart.html) | Visual forms, property editing and Python event handlers | Model the development experience; do not assume its visual editor is part of the open-source runtime |
| [Puck](https://puckeditor.com/docs/getting-started) | Ready editor interface, registered React controls, fields and a matching runtime renderer | Selected next prototype base; hide React and editor serialization behind OpenHMI |
| [Craft.js](https://craft.js.org/docs/overview/) | Building blocks for highly customized drag/drop React editors | Keep as an alternative if spatial editing or custom interaction exceeds Puck's fit; more editor UI must be authored |
| [GrapesJS core](https://github.com/GrapesJS/grapesjs) | General HTML/template editing | Retire the first prototype; its web styling concepts and separate runtime renderer do not match the new workflow |
| [FUXA](https://github.com/frangoteam/FUXA) | HMI control, alarm, trend and engineering interaction examples | Ideas only; no adoption or integration |

Puck and Craft.js both publish MIT licenses. Puck's
[component configuration](https://puckeditor.com/docs/api-reference/configuration/component-config)
allows an HMI-specific property inspector. Its
[Render component](https://puckeditor.com/docs/api-reference/components/render)
lets editing and runtime use the same control implementations. Puck does not
provide Python execution, PLC drivers or persistence; OpenHMI supplies those.
Craft.js's documentation explicitly describes editor building blocks rather than
a complete tailored editor. This comparison is based on primary documentation;
Craft.js and Anvil have not been prototyped locally.

Anvil's [open-source runtime](https://github.com/anvil-works/anvil-runtime)
can host apps independently, while its README identifies the visual builder as
the cloud editor. Anvil's
[deployment environments](https://anvil.works/docs/deployment)
associate an application version with a deployment. We borrow the distinction
between editing a draft and applying a version, not an undocumented promise of
arbitrary hot code replacement.

## Live development contract

1. The editor displays current simulated tag values while controls and properties
   are edited. Interacting with an editor control selects/configures it; it does
   not invoke an equipment command.
2. Draft changes autosave on the Python server. Runtime viewers continue to use
   the active screen until the developer applies the draft.
3. Applying a validated screen changes the active revision. Existing viewers
   receive it without a manual page refresh or a Python process restart.
4. Draft saves and apply operations include the expected revision. Conflicting
   writers receive a conflict rather than silently replacing another draft.
5. Tag state and driver ownership belong to Python and survive screen-only changes.
   Editing a binding does not recreate the driver or replay an action.
6. Python customization uses named application actions. The browser chooses a
   registered action; it does not submit Python source for execution.

The initial single-screen simulation has expanded to multiple screens/popups,
shared pycomm3 polling, UDT faceplate definitions, SQL history and a project library.
Tag delivery uses bounded polling. Hardware commissioning, full operator-action
audit and screen rollback remain separate work. Live Python code replacement is a future feature with a
module lifecycle; initially custom handlers are loaded at startup.

## Project and runtime ownership

```text
HMI editor -> validated OpenHMI draft -> active screen revision -> runtime viewers
      |                                      |
      +-- shared control catalog ------------+
                                             |
                                  Python tags and named actions
                                             |
                                   independent driver adapters
```

Persist an OpenHMI schema with typed control properties, tag references and named
actions, not raw HTML/CSS or Puck internals. An adapter translates between that
schema and the editor. Use identical controls for editor previews and viewers.
The initial layout is a configurable control grid in a gray ME-derived screen
frame; [the HMI style guide](hmi-style-guide.md) records its source decisions.
Reusable UDT faceplate definitions and multiple screens now share that catalog.
Free placement and richer graphics remain future work.

## Priorities

* No-code: tag browser, numeric display, indicator, action button, format/units,
  analog ranges, explicit alarm indicators, screen navigation and reusable equipment controls.
* Python customization: local handler modules first; later an integrated editor,
  event templates, diagnostics, dependency management and deliberate reload.
* Live engineering: autosaved drafts, apply without viewer reload, revision conflict
  feedback, later history/rollback and collaborative editing.
* Industrial runtime: quality/timestamps, subscriptions, reconnect, typed writes,
  richer alarm workflows/trends, access control and a separately accepted first protocol adapter.
* Installation: contributors may need Node; released end-user builds should ship
  assets and present project/open/run controls without web tooling.

Track the next work in [project/editor lifecycle](https://github.com/votecoffee/OpenHMI/issues/1),
[Python customization and subscriptions](https://github.com/votecoffee/OpenHMI/issues/2),
and [first PLC adapter](https://github.com/votecoffee/OpenHMI/issues/3).

## Current validation

Local Python tests cover rejected bindings/schema data, draft/apply separation,
stale revision rejection, persistence across server restarts, built-in actions
and loading/invoking a custom Python action. Browser checks exercise actual
drag/drop, property editing, autosave/reload, apply to an already-open viewer,
live tag updates after a Python action, disconnected values and stale-editor
conflicts. Editor preview actions stay disabled. These are simulation checks,
not PLC, production deployment or arbitrary Python hot-reload acceptance.

Project-wide [languages and alarm monitoring](languages-and-alarms.md) are now
implemented separately from screen controls. The Python lifespan owns the alarm
sampling task; SQLite retains alarm occurrences and events. Runtime graphics
consume its status without driving the monitor. Draft language/alarm settings
share the screen's validation, revision checks and Apply live boundary.

[SQL recipes](recipes.md) use a separate revision and review lifecycle. Python
owns immutable content revisions, approval identity, field-change audit, images
and operation policy in SQLite. Loading takes a separate snapshot of the content
and its production-approval Boolean. Library changes do not alter the simulator's
loaded copy. Test recipes may be loaded; the eventual controller owns run/reject
decisions. Legacy recipe-only accounts remain supported in unsecured projects;
application-wide authorization now uses [HMI security groups](security.md).
A real controller transfer handshake remains future work.

HMI security stores local users, application groups, Windows SID assignments and
security audit in the project database. Local password verification and native
Windows credential verification produce the same application principal. Browser
controls consume its permissions; Python validates permissions and active control
bindings before actions or writes. The numeric input control adds bounded,
group-protected value editing. Unconfigured projects explicitly remain unsecured
simulation; no default account is created. Windows SSO remains future work.

[Runtime and project workflows](runtime-and-projects.md) describe shared screen-rate
polling, UDT member resolution, conditional/no-code actions, SQL trends and complete
backup import/export. A workspace switch drains the previous application service;
browser mutation headers identify the originating project instance to reject stale
cross-project edits. Imported connections stay held until explicit apply, and
imported Python source never executes automatically. The integrated Python IDE
is explicitly deferred by the project owner.

## Module boundaries and compatibility checks

Refactor one family at a time while preserving saved-project schemas, endpoint
paths, authorization, revision guards and lock ownership.

- `frontend/controls.jsx` assembles the palette and screen composition.
  `display-controls.jsx` owns readouts and basic indicators; `process-controls.jsx`
  owns analog ranges and setpoint comparison; `alarm-controls.jsx` owns priority
  symbols and alarm indicators. `action-button.jsx`, `faceplate.jsx`,
  `screen-frame.jsx` and `conditional-control.jsx` own their respective runtime
  behavior. Input, chart, machine-state and image families retain their focused
  modules. `control-common.jsx` supplies shared display helpers. Components do
  not import the palette back into their implementation. `palette-fields.jsx`
  builds fresh shared fields, tag filters, defaults and security-group editors
  for each catalog; it does not cache descriptors across projects. Definition
  factories in `palette-inputs.jsx`, `palette-images.jsx`, `palette-process.jsx`,
  `palette-machine.jsx` and `palette-readouts.jsx` own the matching fields,
  defaults and renderer selection. `palette-components.jsx` composes them with
  duplicate/missing-component guards and preserves the established control order.
  Faceplate rendering receives a deferred lookup of the completed configuration
  so nested child renderers still use the shared conditional wrappers.
- `openhmi/history_routes.py` registers a focused FastAPI router for historian
  queries, recorded-tag search and CSV export. It receives the historian and
  project instance explicitly. `server.py` remains the composition root and
  retains the live-apply boundary. `acquisition_routes.py` owns tag snapshots,
  viewer leases and protected connection metadata. `control_routes.py` owns
  Python actions, button activation and value writes, retaining the command lock
  and journal reservation/dispatch/confirmation order. `control_contracts.py`
  shares request models and input families with project binding validation.
  `project_lifecycle_routes.py` owns project snapshots, draft saves and live
  apply, preserving apply validation, identity-publication guards, lock ordering
  and runtime reconfiguration. `alarm_ack_routes.py` owns alarm snapshots and
  individual, selected and all acknowledgements, with request models in
  `alarm_contracts.py`. Existing review/history, note and shelving APIs remain
  in `alarm_routes.py`. Command history/export, trend recording, canvas-image and
  identity-publication HTTP registration now live in `command_routes.py`,
  `trend_routes.py`, `canvas_routes.py` and `identity_routes.py`. Their request
  contracts are shared through `command_contracts.py`, `trend_contracts.py` and
  `identity_contracts.py`. Existing registrar/model imports from service modules
  remain compatible; `server.py` imports the focused registrars directly.
  Service authorization, query limits, error mapping, upload bounds and response
  headers retain their prior behavior. Legacy request-model imports from `server.py` remain
  compatible. `engineering_routes.py` owns the draft engineering catalog, and
  `project_validation.py` supplies the same binding validator to save, staging,
  merge and apply. The validator closes over explicit services and the asset
  directory; it does not retain a previous project snapshot. The entry point
  now orchestrates focused rule groups in `binding_project.py` (protocols,
  tag indices, identity outputs, assets, faceplates/history and expanded IDs),
  `binding_controls.py` (shared guards, edits and action/value fallback),
  `binding_displays.py` (display/state/browser bindings), and
  `binding_charts.py` (chart series and trend triggers). Project-wide checks
  run in their established order. Each expanded control then completes common
  guards and its type checks before the next control is inspected. The groups
  consume the same current project/tag context and perform no controller I/O.
- `openhmi/logix_transport.py` owns the pycomm3 connection, metadata, batching,
  response receipts, reconnect backoff and write readback. It has no screen,
  lease, historian or sample-cache dependency. `logix.py` retains route workers,
  locks, project-generation fences and writes. `tag_scheduling.py` owns physical
  rates, deadlines, renewed-demand fences and bad-tag retry policy;
  `scan_publication.py` publishes accepted receipts and updates route recovery
  using the currently requested aliases. Viewer leases,
  sequence retention, screen-rate demand and trend demand live in
  `tag_subscriptions.py`. Cached PLC samples, scalar/UDT decoding, good/stale/bad
  projection and usable-generation checks live in `tag_samples.py`. Pure value/type/freshness
  rules live in `tag_values.py`; bounded timing statistics live in
  `scan_timings.py`. Logical write type checks, inverse scaling and readback
  comparison live in `tag_writes.py`; transport retains physical metadata limits
  and the single write/readback transaction. Failed-write deadline invalidation
  belongs to the scheduler, and affected sample mutation belongs to the cache.
  Existing imports from `openhmi.logix` remain compatible, including address
  overlap checks now shared through `tag_values.py`.
- `openhmi/tag_catalog.py` owns logical definitions, UDT source aliases, physical
  address groups and the set of configured local tags. Reconfiguration preserves
  edited local values for unchanged definitions, initializes changed definitions,
  removes retired local values and invalidates samples on changed routes.
  `route_status.py` projects diagnostic DTOs, with optional groups and timing
  details. The driver invokes both under its existing state lock. Connection
  replacement remains in the driver under `io_lock`; retired connections close
  after releasing the state lock. Project copying, assignment and obsolete-scan
  rejection retain their existing boundaries.

- `openhmi/project_models.py` defines control/project schemas, revision request
  models and the default project. Schema-only consumers import it directly;
  import and validation do not load the revision store or SQLite. `projects.py`
  retains `ProjectStore`, `RevisionConflict`, migration, recovery, revision
  integrity checks and save/apply/stage/merge transactions. Existing model,
  type-alias, domain-schema and default-factory imports from `projects.py` are
  explicit compatibility exports of the same objects. No model rules, defaults,
  storage SQL, version or transaction boundaries change in this separation.
  `control_models_base.py` holds shared strict, state, numeric and range bases.
  Focused `control_models_inputs.py`, `control_models_images.py`,
  `control_models_process.py`, `control_models_machine.py` and
  `control_models_readouts.py` own their control schemas and nested helper models.
  Family modules import shared bases without importing the project schema or
  revision store. `project_models.py` explicitly reexports these models and
  retains the original discriminated union, member order and project validators.
  `canvas_models.py` owns boxes, containers, decorations and layout consistency;
  `identity_models.py` owns publication settings and privilege-bit mappings.
  Project schemas import these directly. Their former service modules explicitly
  reexport the same class objects, while image processing and station publication
  retain their service boundaries. Schema-only use does not load these services,
  their routers, FastAPI/Starlette or Pillow.

`tests/test_frontend_contract.py` invokes the real `createConfig`, `toEditor`
and `toProject` functions through a DOM-free Node test entry. It compares every
palette control kind against Pydantic's discriminated union, validates defaults
with required bindings configured, checks every nonempty palette select option,
and round-trips every serialized control field. Field-set checks ensure backend
defaults cannot conceal a dropped field.
Fixtures include nondefault options, Unicode text, image references, security
and limit bindings, trend settings, secondary screens and UDT faceplates.
The pure `faceplate-model.mjs` resolver is compared with Python faceplate
expansion on Overview and secondary screens, including indexed UDT roots,
conditions, edit limits, nested lamps/checks, chart axes and trend capture tags.
Both paths must preserve the original template. Relative trend tags and pen
settings are resolved together before rendering.

`runtime-api.mjs` owns browser value-write, activation and lease requests. The
contract runner records those actual helpers through a fake fetch implementation
and validates their methods, paths, project headers, keepalive release and
strict Pydantic payloads, including Boolean, numeric and Unicode text values.
`project-api.mjs` and `alarm-api.mjs` similarly centralize the actual browser
save/apply and acknowledgement payloads. Compatibility tests validate them
against the lifecycle models, including revision numbers, Unicode comments,
selected IDs, default apply reasons and project identity headers. Additional
catalog cases check unscaled integer, real, text-only, read-only and empty tag
sets, plus isolation after a prior configuration's options/defaults are mutated.
`trend-api.mjs` and `identity-api.mjs` centralize the browser's capture and station
ownership requests. Their contract checks validate start/stop/delete payloads,
strict IDs, claim/renew/release bodies, Unicode names, encoded control paths and
project headers. Existing `uploadProjectImage` is tested with a binary File,
encoded filename, unchanged bytes, a timeout signal and browser-supplied media
headers. Invalid capture actions/IDs, station types/lengths and extra fields are
rejected by the Pydantic models. The DOM-free contract tests send no
runtime/controller requests.

`tests/test_engineering_contract.py` additionally uses an in-process TestClient
to feed the real draft catalog through `engineeringCatalog` and palette tag
pickers. It checks writable and unscaled integer filtering, UDT aliases,
relative template members and nested-faceplate suppression, while ensuring
unapplied draft tags have not reached the runtime. Invalid saved bindings must
return 422 without changing the draft or its revision. Its PLC fixture is
disabled and the runtime starts with acquisition held; no controller I/O is used.

These checks run in normal Python unittest discovery and require Node 20+ and
`npm ci`. To run only the contract checks:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_frontend_contract -v
```

`tests/test_binding_rules.py` checks the observable order of conflicting
project/control failures and confirms that rejection preserves both the draft
and its revision. Correcting the failures in sequence must allow the same
candidate to save without an apply.

The catalog, subscription, sample and scheduling components deliberately own no
locks or worker pools. The driver retains its state `RLock`, configuration/write `io_lock` and
per-route locks. Lease mutation and sample projection use the existing state
lock; a route lock is never acquired while projecting samples. Transport work
still runs outside the state lock, and the project-generation fence is checked
before publishing a completed scan. The existing caller-coordinated `demands`
contract is unchanged. Concurrent component access requires the driver's state
lock.

Legacy `samples`, `leases`, `trend_demands`, `_screen_demands` and
`_lease_sequences` attributes forward to live component-owned dictionaries,
including replacement assignments. Scheduling attributes `deadlines`,
`last_rates`, `_refresh_after`, `_bad_tag_retry_at` and `_demanded_aliases`
similarly forward to the scheduler. Catalog attributes `definitions`, `sources`,
`address_aliases` and `local_names` forward to the live catalog, also supporting
replacement. No detached compatibility copies are kept.
The sample cache owns timing access, freshness tightening and receipt storage.
Reconciliation and publication execute within the original state-lock boundary;
publication also retains the route lock. Bad tags retain the 30-second retry
when the route has usable requested data, and retry promptly when it does not.
The metadata-only diagnostics regression now guards the cache owner's copy
function so it still detects an accidental deep copy of tag values.
`tests/test_tag_state.py` checks shared consumer demand after expiry/release,
sequence ordering, independent driver state, nested snapshot isolation, legacy
dictionary replacement and cache cleanup. It also verifies external deadline-map
access and changes to requested UDT members during an in-flight read. Failed
member writes invalidate only overlapping aliases on the affected route;
sibling paths and identical addresses on other routes retain their samples and
deadlines. Successful readback clears the written root's deadline and bad-tag
retry without publishing the readback as a displayed sample. Tests require the
next normal poll to update that value. Existing blocked-route, freshness,
bad-tag retry, reconnect and in-flight-write tests remain applicable.

Write helpers and cache invalidation acquire no locks or workers. The driver
retains the configuration/write `io_lock`, per-route write lock and nested state
lock at their original boundaries. Transport does not retry or replay a write.
Runtime-owned identity/command guards, local-tag edits and multi-step write
scopes remain in the driver.

`tests/test_driver_configuration.py` covers preserved local edits, nested initial
value isolation, reset/removal, independent route replacement and acquisition
hold. It verifies the retired-connection lock boundary, live catalog replacement,
independent driver instances, status DTO isolation and lazy optional diagnostics.
Existing blocked-read/project-switch tests continue to check obsolete receipts.

`tests/test_project_models.py` checks schema-only validation in a fresh process,
legacy/canonical model identity and canonical requests passing through the
existing store's save/apply/history contract. Direct family imports must not load
`project_models`, the revision store or SQLite. Family ownership checks require
unique class objects and ensure every union member is a canonical family model;
legacy identity checks include every imported OpenHMI model, not only classes
still defined in the project composition module. Frontend compatibility checks now
use the canonical schemas while existing persistence tests retain legacy imports.
A domain round-trip check combines positioned controls, a grid container, locked
background decoration and privilege mappings, validating both canonical and
legacy layout/publication models without applying anything to a controller.

The current control-family, HTTP-registration, driver and schema/store separation
baseline is delivered, including control families and independent domain models.
The [contributor workflow](extending-controls.md) traces schema, palette,
serialization, binding, faceplate and runtime changes. The bounded
[contract audit](contract-coverage.md) records covered and outstanding boundaries.
Command query builders now live in `command-api.mjs`; buttons and transaction
console share these production helpers. `test_command_contract.py` sends their
actual generated URLs through the real registrar with stubbed service/security,
covering history-state parity, filters, limits, IDs and JSON export headers.
`image-api.mjs` similarly owns picker queries and page validation.
`test_image_contract.py` binds generated requests through the real registrar,
rejects out-of-range queries before service calls and feeds real SQLite listing
pages through the production browser validator. Invalid or unsafe cursors and
malformed entries never replace the last readable page. Access denial clears
retained metadata; newer requests and close keep their original sequence guard.
Browser regressions cover paging, malformed-page recovery and denial/recovery.
`history-api.mjs` and `trend-api.mjs` own sparkline, live/capture history,
recorded-tag search and CSV query paths. Their router contract tests preserve
window/tag limits, context flags, fixed ends, complete-export project guards,
CSV quoting and export-slot cleanup. UTC/local parsing and bounded-export response
project checks remain in the History panel. Its recorded-tag pages are now
validated before React state is updated, with real SQLite pages and malformed
response/browser recovery coverage. `test_command_responses.py` compares actual
SQL service detail, page, export and restart-reconciled responses with production
JS validators across every transaction state, without driver calls. Sequence bounds
and coherent descending page cursors are validated before replacing readable
evidence. Nullable results/errors and empty event histories remain compatible.
Next, extend response parity to history/trend status. Preserve model/import
compatibility, project-instance identity, write non-replay behavior, apply
rollback, command locks and journal ordering in further extractions. Extend the contract fixtures whenever a request
model, saved control field or editor serialization branch changes. These software
checks do not establish controller or operator-station acceptance.
