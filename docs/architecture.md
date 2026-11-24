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
History and capture validators now live in their focused API modules rather than
React components. `test_trend_responses.py` feeds actual SQL-backed history and
recording responses through those functions, including change context, truncation,
quality gaps, rollover, stopping and restart reconciliation. Per-tag chronological
order, unique capture IDs and coherent retention counts are checked before state
is replaced; equal sample epochs and optional legacy pen fields remain compatible.
Activity and diagnostics validators now live in `activity-api.mjs` and
`diagnostics-api.mjs`. Real journal pages and runtime/worker projections pass
through those production validators in `test_operations_responses.py`. Activity
IDs/order/cursors and diagnostic offset/row/truncation metadata are checked
before state replacement; optional legacy metadata remains compatible. Scan-age
values are checked before the UI formats them. These modules also own list/read
and export query construction; `test_operations_contract.py` binds their actual
requests through the real registrar. Tests preserve Unicode filters, UTC date
conversion, exact string-form cursors, defaults, bounds, project headers and
read/export authorization. UI polling, retention and permission-loss handling
remain in React. `diagnostics.py` now owns read-only snapshot/filter/projection
logic; the router retains permissions, query bounds and JSON download metadata.
The driver snapshot keeps one shared-lock boundary and common monotonic time;
worker health is read after release. Regression checks replace the catalog at
snapshot release and require consistent old-generation tags/routes, preserving
route-state precedence, filters, paging and value-free output. Synthetic bench
comparisons patch both HTTP capture and projection clocks to match driver polls.
The command, activity and diagnostics views now live in `command-console.jsx`,
`activity-console.jsx` and `diagnostics-console.jsx`. The app imports these modules
directly; `operations.jsx` retains compatible exports with identical component
identity. Polling effects, retained responses, permissions, filters and render
bodies remain unchanged. Diagnostic timing/worker presentation stays with its
console. Identity-session validation, its URL and the validated read helper now
live in `security-session.mjs`. App polling and login-refresh paths share the
production guard while retaining generation fences and last-confirmed identity
handling. `test_security_session_contract.py` compares real SQL-backed local and
mock-Windows responses with that guard, including expiry, permission changes,
logout/disable and public-field exposure. Malformed payloads remain rejected
without mutation or coercion. Selected-recipe validation and its polling URL now
live in `recipe-selection.mjs`; the existing guard rules remain unchanged.
`test_recipe_selection_contract.py` feeds real SQL lifecycle responses through
that guard, covering null selections, typed values, images, self-approval, source
revision changes, independent loaded copies and service reopen. Display validation
remains separate from full recipe request-model limits and server permissions.
The live alarm snapshot guard and polling URL now live in `alarm-api.mjs`,
with its previous legacy defaults and display-field rules preserved.
`test_alarm_snapshot_contract.py` checks real SQL/HTTP monitor snapshots across
priorities, acknowledgement, shelving/restoration, bad trigger quality, stale
evaluation, retirement and reopen. Snapshot reads must not acquire fresh source
data. Detailed occurrence/history validation remains a separate boundary.
Applied-project validation and its polling URL now live in `project-api.mjs`,
using the canonical browser control-kind map. The previous guard body is preserved.
`test_applied_project_contract.py` uses the shared real-palette fixture, Pydantic
validation, SQLite saves/applies and the actual active-read registrar to check all
control kinds, secondary screens, faceplates, containers and locked backgrounds.
Unapplied drafts do not replace the active response. Display-level legacy defaults
remain accepted; full project/request validation and runtime binding checks stay
on their existing boundaries. Tag-status validation/default normalization and
normal/status-only polling URLs now live in `runtime-api.mjs`. The previous guard
rules are preserved; per-tag fault handling remains with quality-aware controls.
`test_tag_snapshot_contract.py` compares real acquisition-route/cache responses
using FakePLC: held/pending, one bad tag among good data, stale/recovered and
disabled routes. GET reads cannot poll or subscribe, and status-only reads cannot
copy tag samples or subscription groups. All five live app snapshot boundaries
now use focused modules while polling/lifecycle ownership remains in the app.
Alarm-console occurrence/event/detail/note query builders and CSV links now live
in `alarm-api.mjs`, along with the UI state/shelving/event filter lists. Existing
URL order, local-date conversion, history/export scope and note POST paths remain
intact. `test_alarm_query_contract.py` binds generated URLs through the real
SQL-backed registrar, covering defaults, bounds, precise cursors, Unicode,
metadata-only detail reads and CSV quoting/formula escaping. UI validation,
polling and recovery remain in the console/read hook. Detailed alarm validators
now live in DOM-free `alarm-responses.mjs`; `alarm-read.mjs` retains its message
helper compatibility export. Occurrence/event/note pages require bounded counts,
strictly descending unique IDs and a cursor matching the last row. Existing row/
detail and nullable metadata rules remain compatible. Real SQL/HTTP response
contracts cover paging, shelving, notes, cached trigger details and legacy null
event attribution; browser tests retain readable pages and block older navigation
through incoherent replies. Note/shelve/restore request helpers also live in
`alarm-api.mjs`, retaining duration conversion, payload fields, project headers,
timeouts and audit receipts/errors. Secured SQL-backed registrar contracts bind
actual browser payloads through strict models, permissions and journal dispatch
guards; anonymous/limited users and stale restore attempts cannot mutate state.
These routes do not sample or write the source. The shelving-list URL builder
also lives in `alarm-api.mjs`, with its DOM-free response guard in
`alarm-responses.mjs`. Pages require ascending unique alarm IDs, at most 200 rows
and a matching final-row cursor; existing row/message/date rules remain intact.
SQL-backed contracts cover encoding, bounds, paging and restoration. Cursor and
restore path limits now match the project model's 100-character alarm IDs rather
than rejecting valid IDs above 60 characters. Browser faults retain the readable
page and disable restore/next-page actions until valid replies recover.
Recipe create/revise/transition/select requests and numeric content normalization
live in `recipe-api.mjs`. The workspace retains reason checks, permission gates,
selection-version capture, dirty state, refresh sequencing and feedback. Actual
browser requests pass strict Pydantic models and SQL-backed lifecycle contracts
for same-user approval, independent loaded copies, stale conflicts and denied
operations. Receipt/error propagation is tested with synthetic headers; the
recipe routes keep their existing recipe-audit behavior. Identity/publication
hooks are stubbed in contract tests; existing browser/domain tests cover local
authentication and UI workflows. Policy saves and raw image uploads also share
`recipe-api.mjs`, preserving expected versions, query-reason encoding, MIME type,
file bytes and the existing API timeout. SQL-backed contracts cover policy
conflicts, defaults, Boolean permit checks, role/gate denials and normalized
PNG/JPEG retrieval. HTTP size/type/reason failures retain their existing status
codes. The workspace keeps input reset, image attachment, dirty state and policy
refresh sequencing; browser tests cover stale policy feedback and refresh recovery.
The recipe-local session component now lives in `recipe-session.jsx`, with
read/login/logout helpers in `recipe-auth.mjs`. Form state, error feedback,
password clearing and callback timing remain unchanged; the workspace owns
HMI-session delegation and concurrent recipe/session refresh. Real local auth
and SQL-backed HMI security contracts cover cookie rotation/expiry/sign-out,
strict request models, origin rejection and live group permission changes.
Configured HMI security ignores legacy recipe cookies. Browser regressions cover
failed logout retention, recovery and HMI sign-in/out permission delegation.
No new session-response filtering or authentication policy is introduced. Recipe
transfer history/status query builders, detail/export paths and dispatch requests
now live in `recipe-transfer-api.mjs`. History query identity remains independent
of the verified target; polling, selection revision, refresh fences, permissions
and receipt ownership stay in the panel. Actual browser requests bind through
SQL-backed routes with simulator-only staging, checking bounds, filters, exact
cursors, request models, version rejection, audit receipts and JSON export.
The transport factory is forbidden in these fixtures. DOM-free transfer record/
page guards now live in `recipe-transfer-responses.mjs`, reusing command-record
validation and checking consumed snapshot/profile fields, safe IDs, matching
transaction identity, bounded descending pages and final-row cursors. Optional
attribution/image metadata and empty event lists remain readable; retired targets
and verified records outside the history page are supported. Invalid replies
retain readable history and block dispatch/paging; 401/403 clears inaccessible
data. SQL-backed response fixtures model all eight command states and exercise
renamed/retired profiles without controller observations. Browser faults cover
malformed nested data, retained rows, denial discard and valid-reply recovery.
Dispatch receipts now pass a pure validator that correlates target/recipe revision,
transaction IDs, sequence/envelope, operation identity and requested state. Valid
legacy headerless replies and pending journal finalization remain supported. An
invalid receipt cannot create an acknowledgement link; known operation IDs and
verification guidance survive error feedback. The shared API reader retains
operation headers if success-body parsing or receipt attachment fails. Transport/JSON failures and uncertain
HTTP outcomes prompt verification; errors trigger read-only status refresh and
clear prior receipt links, without replaying dispatch. SQL/HTTP tests cover real
simulator success, pending audit finalization and uncertain commit failure; browser
faults prove a corrupted reply still results in one dispatch and a readable record.
Recipe library reads now use `recipe-library.mjs`, validating consumed revision,
parameter, policy, gate and audit fields before committing workspace state. Safe
ordered identities and typed values are required; optional legacy attribution,
image/description/unit fields remain compatible. The independently selected-copy
field and raw permit samples are not newly constrained. Failed refreshes retain
readable library/draft state and block writes; an initial failure offers retry.
Successful refresh restores actions without discarding dirty content. SQL/HTTP
contracts cover all six revision states and unavailable permits; browser faults
cover nested malformed policy, HTTP failure, no writes and draft recovery. Recipe
session reads, sign-in replies and sign-out confirmations now have consumed-field
guards in `recipe-auth.mjs`. Local and HMI users require a string name and string
role list; empty/future roles and extra provider metadata remain compatible. A
malformed session cannot replace confirmed identity, and the existing workspace
read-failure gate blocks writes until recovery. Invalid auth confirmations retain
identity with refresh guidance, without replaying login/logout. Confirmed identity
updates clear stale form errors and credentials. Real auth/security tests and
browser faults cover recovery, including mock-Windows mappings. Recipe picture,
loaded-copy, value-table and selected-recipe controls now live in
`recipe-controls.jsx`; parameter editing lives in `recipe-parameters.jsx`. The
workspace imports them directly and retains state/API orchestration. Existing
`recipes.jsx` picture/loaded/selected exports are aliases to the same functions;
the readout palette imports its renderer directly. Moved component bodies and
saved schemas are unchanged. An export/palette identity contract and expanded
typed-parameter browser workflow protect this boundary. Authentication/session
HTTP handlers and the shared recipe-user authorizer now live in
`recipe_auth_routes.py`. The combined registrar still constructs the same auth,
recipe and transfer services and delegates registration/authorization. Login/Empty
request models remain owned by `recipe_routes.py` and are passed to the focused
registrar, preserving legacy imports and qualified OpenAPI references when both
recipe and HMI Login models are present. A before/after comparison verified the
complete OpenAPI document unchanged. Standalone HTTPS tests cover cookies, origin/
rate-limit guards, HMI delegation and logout behavior without recipe/driver setup.
Focused-module imports do not load recipe services or the application server.
Recipe image read/upload handlers now live in `recipe_image_routes.py`. The
combined registrar supplies its existing service, user authorizer and domain-error
translator; normalization, storage, policy and audit ownership remain in the
service. Handler bodies and complete OpenAPI output are unchanged. Standalone
HTTP tests verify public cache/security headers, byte/reason/identity forwarding,
role/MIME/model guards and exact/overflow upload limits. A chunked-request test
confirms overflow stops consumption before later chunks or service dispatch.
Focused imports do not load Pillow, recipe services or the server. Transfer history,
detail/export and dispatch handlers now live in `recipe_transfer_routes.py`.
The combined registrar retains service construction and supplies the existing
journal, authorization and error translation. Handler bodies, route order,
canonical request models and complete OpenAPI output are unchanged. Standalone
HTTP tests with an in-memory journal cover bounded queries, role checks, export
headers, recipe-local/HMI identity attribution, conditional group authorization,
and journal-before-dispatch ordering. Validation, denied identity and unavailable
journal cases prevent dispatch. Focused imports do not load recipe services,
pycomm3 or the server. Recipe library snapshot/selected reads and protected
create/revise/transition/select/policy/simulator-permit adapters now live in
`recipe_library_routes.py`. Public read and protected mutation registrars preserve
the existing route order around transfer registration. `recipe_routes.py` now
owns assembly, stable legacy model aliases and shared authorization/error
translation; SQL, approval, loaded-copy and permit rules remain in `RecipeService`.
Standalone HTTP tests cover all six typed mutation adapters, public reads,
identity forwarding, validation before authorization, denied users and translated
HTTP failures. Focused imports do not load recipe services, Pillow, pycomm3 or
the server. Complete OpenAPI and route registration order are unchanged.
Project-instance guards and response context now live in `http_context.py`, shared
by runtime middleware and the workspace boundary. Stale mutation guards still run
before handler/authentication/body validation, and GET/HEAD/OPTIONS plus legacy
headerless callers retain their existing behavior. Stale 409 responses and caught
workspace HTTP errors now include `X-OpenHMI-Project`; successful workspace open
responses retain the identity captured before the switch. Receipt operation IDs
and audit status remain attached only when the request owns an activity operation.
Real HTTP/SQL responses passed through the production JS API cover succeeded,
denied, rejected, uncertain and pending outcomes. The browser retains its initial
project identity after refresh/conflict and does not replay writes. Complete
OpenAPI is unchanged. Request context does not add a generic unhandled-exception
response policy.
Runtime assembly/startup/shutdown ownership now lives in `runtime_lifecycle.py`.
The public `create_app` signature delegates assembly under a failure cleanup scope;
store, driver, trend recorder and identity publisher are tracked as construction
succeeds. Failed assembly closes constructed trends/acquisition/storage, including
handler, configuration and late route/static registration failures. It does not
invoke identity shutdown/publication before workers have been attempted. Lifespan
cleanup now also covers failure of the initial alarm sample or worker context
entry. Worker exit precedes trend/identity/acquisition/store cleanup, and one
cleanup exception is logged without skipping the remaining resources or replacing
the original startup/body/worker-exit exception. Callback methods are resolved at
cleanup time, preserving runtime instrumentation. Worker scheduling, transport
ownership, HTTP models, route order and complete OpenAPI remain unchanged. Tests
inject failures using real in-memory SQL resources and a forbidden PLC factory;
no hardware acceptance is implied.
PLC client close failures are now logged with the route ID rather than silently
ignored; the transport still detaches its client and marks the route disconnected.
Runtime driver shutdown isolates each route's close method, so a wrapper/route
exception does not skip later routes. The scan pool still drains before any route
close, `_closing` prevents new scans and late sample publication, and scan/cache/
schedule cleanup still runs afterward. Closes remain outside the state lock under
the I/O lock. Tests use fake clients, a bounded blocked read and explicit reopening;
they issue no writes and do not establish physical socket-close success after a
vendor close error. No automatic close retry or reconnect was added.
Worker task creation now runs inside the scheduler cleanup scope. A rejected task
creation closes its unscheduled coroutine and drains tasks already created, even
if the first task could not be scheduled. `_run` records stopped health in a
finally block. Drain collects/logs unexpected task failures while waiting for
peers, then joins its executor off the event loop so a cancelled scheduler cannot
hide a still-running synchronous callback. `async_cleanup.py` shields owned work
from caller cancellation until completion, then propagates cancellation; repeated
cancellation cannot detach worker draining or resource cleanup. The same helper
protects initial alarm sampling before workers start. Tests use bounded event
gates and real in-memory SQL to prove ordering, original startup failure retention,
event-loop progress, no post-close access and no pre-worker identity publication.
Public models, HTTP routes and complete OpenAPI remain unchanged. Forced process
termination and indefinitely blocked vendor operations remain outside these
bounded offline checks; no timeout closes resources underneath active work.
Workspace project handoff distinguishes failures before and after ownership changes.
Candidate construction/startup failure is logged and returns a sanitized 503 saying
the current project remains open. Candidate cancellation completes its lifecycle
cleanup before the workspace request lock releases. After a successful start,
ownership switches atomically before previous-runtime retirement; retirement is
shielded through repeated cancellation. An ordinary retirement exception returns
a 503 explicitly saying the requested project is already open, with reload/review
guidance, rather than attempting rollback or replaying the open. Project headers
retain the request's original identity. Workspace lifespan uses finally cleanup;
shutdown serializes with switching and closes the runtime currently owned, even
if startup notification or lifespan receive fails. Bounded in-memory/synthetic SQL
tests cover both sides of handoff, competing reads, stale-write rejection, held
PLC routes and closure of both old/candidate stores. Complete OpenAPI is unchanged.
Workspace create/import/export threads now use the same owned-work completion
boundary. Repeated request cancellation cannot release the workspace lock while
one of these threads is still accessing its source runtime or publishing files;
queued project switches and shutdown wait for completion. A job failure after
cancellation is logged, with cancellation still propagated. Ordinary HTTP failures
retain their existing status/detail and project headers. Cancellation during an
incomplete upload still releases the lock without starting import. Event-gated
SQL/ZIP tests verify completed create/import files, imported connection hold,
export source identity, no replay, store-close ordering and error handling. This
cancellation boundary does not roll back completed operations. Complete OpenAPI
remains unchanged.
Project file publication now lives in `workspace_publication.py`, separate from
HTTP operations and SQL initialization. Create builds and closes its database in
a same-filesystem temporary directory before publication. Import validates/forks
its database and stages all companions before publishing. Windows exclusive
rename (POSIX exclusive hard link) exposes complete files without replacement;
the database is published last, after the hold and any review-only Python/accounts.
Existing databases, support files, dangling companion links and SQLite journal/
WAL/SHM artifacts block reuse. Ordinary filesystem errors return sanitized 503
guidance; collisions remain 409 and invalid backups remain 422. Failed pre-database
publication removes only artifacts whose identity, mode, size and modification
time still match this attempt. Changed or unremovable artifacts remain for review.
If a database is already visible after an error, its companions are retained,
particularly the PLC hold, rather than guessing whether publication completed.
Tests inject initialization, short write, mid-publication, collision, changed-file,
rollback and uncertain post-commit failures. These are process-level complete-file
checks, not multi-file crash/power-loss durability or adversarial external-writer
acceptance. Original files and uncertain outcomes are preserved. Complete OpenAPI
is unchanged.
`workspace_inventory.py` owns metadata scanning plus canonical query/page models
for the new workspace ASGI GET `/api/workspace/artifacts`. The existing HMI
`security.manage` and legacy recipe-administrator gates run before scans. Default
pages contain at most 50 entries (100 maximum), using filename cursors and a
10,000-entry directory scan bound. Known top-level hold/Python/accounts/WAL/SHM/
journal names are associated with expected database filenames using lstat metadata
only. Contents and link targets are never opened; directory/link/unavailable and
missing-database states remain explicit. Byte sizes are nullable and JS-safe.
Limited scans or names that cannot be represented in UTF-8 mark results incomplete.
`workspace-api.mjs` validates canonical identity, enums, sizes, uniqueness, code-point
ordering and cursors before display. `workspace-artifacts.jsx` owns the read-only
panel: manual paging/refresh, last-good data on malformed/unavailable replies and
clearing on permission denial. It offers no cleanup/repair/open actions. Python/JS
contracts cover actual metadata and HTTP query bounds, including Unicode beyond
the BMP; browser faults cover preservation, denial and refresh. This is neither a
database-integrity check nor a verdict that WAL/SHM/journals are abnormal. Existing
FastAPI OpenAPI is unchanged; the manual workspace route has direct Pydantic/JS
contract coverage.
`workspace_contracts.py` now defines canonical library listings and create/import/
open acknowledgements. A listing has unique filenames and exactly one current
row matching its current filename; the active database can retain a legacy or
Unicode filename. Create/import filenames follow the existing project ID rules,
imported PLC holds must be true, and open must acknowledge success. Existing wire
fields and FastAPI OpenAPI remain unchanged. `workspace-api.mjs` validates these
responses, correlates operation filenames to requests and sends each operation
once. Malformed/transport/5xx results show completion-review guidance without
retry. `workspace.jsx` retains confirmed listings and user drafts on read faults,
clears denied listings and disables operations while data is unavailable. Field
reset and explicit open navigation require a valid operation acknowledgement;
confirmed messages remain after listing refresh. Import is now an explicit button
action and retains its selected File until confirmation. Real SQL/HTTP contracts
feed production JS guards and serializers; browser cases cover listing/receipt
faults, denial/recovery, retained fields/backups and absence of replay/redirect.
`workspace-backup.mjs` owns binary download validation and save initiation,
using `projectRequestHeaders()` from the shared API client without changing its
initial project-instance pinning. A backup GET with a stale supplied identity is
rejected before export. Success and handled errors carry no-store/nosniff headers;
export exceptions become sanitized 503 guidance. Both raw archive content and
final ZIP bytes respect the 256 MiB limit. The browser validates status, MIME,
attachment filename, pinned identity, optional length and bounded ZIP directory/
local-header structure before creating a download. It does not decompress payloads
or verify checksums/SQL; import retains that responsibility. Requests are never
retried automatically. The project panel preserves drafts, clears denied data and
requires review after stale identity; success says prepared, not saved. Real SQL/
HTTP replies pass through the production JS helper; browser failures never start
a save, and explicit recovery preserves exact archive bytes. FastAPI OpenAPI is
unchanged.
Backup GET responses now leave the workspace lock after preparation and response
context are complete, before sending either headers or body. Their bytes and
source project identity are independent of the runtime; slow sends therefore allow
ordinary reads, switching and runtime shutdown without rebinding the archive.
Preparation, including cancelled thread completion, remains serialized so its
source store cannot close early. Handled backup errors detach in the same way;
other workspace/runtime response lock behavior is preserved. Synthetic ASGI
backpressure tests pause headers and body, switch and close both runtimes, then
verify exact archive bytes and source identity. Cancellation/send failures never
restart export or retire the active runtime. This establishes lock ownership,
not web-server process exit timing or real network throughput.
`workspace_import.py` now owns backup-upload admission, bounded receive and import
HTTP orchestration. The workspace supplies one upload slot and its runtime lock,
plus a shared management authorizer used by all project operations. Admission
checks the supplied project header and permission without consuming denied bodies.
Receive runs outside the runtime lock, capped at 256 MiB and 30 seconds; a second
import returns 429 without waiting or reading its body. Before dispatch, the lock
is reacquired and shutdown state, captured project identity (including headerless
callers) and authorization are rechecked. An upload cannot migrate across a switch
or use a closed runtime after shutdown. Import's thread and cancellation cleanup
remain serialized until completion, retaining the upload slot. Receive timeout,
disconnect, overflow and cancellation never dispatch; the slot always releases.
Immutable JSON replies send outside the lock with source identity and private
headers. Existing publication/checksum/hold semantics remain unchanged. Browser
import requests use a two-minute overall deadline instead of the ordinary five
seconds; ambiguous post-dispatch failures still require review without replay.
`workspace_mutations.py` now owns create/open HTTP ingress and dispatch. Admission
checks management permission, supplied project identity and stopping state before
reading a body. A workspace-owned bounded semaphore admits up to four requests;
excess requests return 429 without reading or waiting. Receipt runs outside the
runtime lock with a 4 KiB streaming cap and a 30-second deadline. Overflow stops
before appending the offending chunk or reading later chunks. Timeout/disconnect/
cancellation do not dispatch and return admission capacity. Under the reacquired
lock, shutdown state, captured identity (including headerless callers) and current
permission are checked before JSON decoding and dispatch. Existing invalid-JSON/
non-object validation is retained, and excessive nesting returns 422. Create's
owned thread cleanup and open's handoff/retirement retain their serialized lifetime.
Once complete, immutable JSON acknowledgements/errors send outside the lock with
source project identity and private headers. Existing model re-exports, payloads,
FastAPI OpenAPI and browser deadlines remain unchanged; ambiguity never replays.
The app now waits for the initial validated identity before mounting the project
form. Previously, a fast library reply could expose editable fields before identity
resolved; the user-keyed form would then remount and erase early input. Identity
changes still reset the keyed form as before. A held-identity browser test verifies
that edits cannot start during hydration and remain after normal library refresh.
Project-library and file-inventory GET responses now share the prepared-backup
send boundary: authorization, snapshot construction, serialization and source
identity are completed under the workspace lock, then immutable responses send
outside it. Success and handled errors carry no-store/nosniff headers. Paused
headers/body therefore allow ordinary reads, project switches and runtime shutdown
without rebinding bytes or context. Inventory thread cancellation still drains
owned scanning before the lock releases; cancellation/disconnect during send does
not repeat preparation or retire a runtime. Existing permission/query/paging,
Pydantic/JS payloads and FastAPI OpenAPI are unchanged. These event-gated offline
checks establish resource ownership, not web-server exit timing or throughput.
Cached GET `/api/tags` (including status-only and query-validation responses) now
uses `http_snapshot.py` to stage the complete finite ASGI response under the workspace
lock. The existing route, FastAPI serialization and identity middleware run normally;
encoded body frames and copied raw headers retain their contents, including duplicate
headers. Only after the full application call finishes does delivery leave the lock.
The workspace drains preparation through cancellation, so synchronous projection
and middleware cleanup cannot outlive their source runtime. A slow send then allows
subscriptions, other requests, switching and shutdown without depending on runtime
resources. Responses are private/no-store; unexpected preparation errors become a
sanitized 503 with source identity. No poll/lease is added by staging. This helper
is restricted to explicitly allowlisted finite tag/applied-project/alarm endpoints,
not streaming/file responses.
Public fields, status-only omission, query validation and OpenAPI remain unchanged.
GET `/api/project/active` now shares that finite-response staging boundary. The
existing store snapshot, route serializer and identity middleware finish under the
workspace lock before immutable delivery leaves it. Revision, applied layout and
body/header project identity cannot rebind to a later apply or switch. Slow clients
allow draft saves, local apply, reads and switching; existing revision/instance write
fences reject operations from the older screen. Cancelled preparation drains SQL
projection before source closure, while send failures never repeat it. Unexpected
store/projection errors return sanitized private 503 feedback, and stopped workspaces
reject reads without touching closed stores. Payloads and OpenAPI remain unchanged.
GET `/api/alarms` now shares this boundary through an explicit path-to-label map.
Its existing monitor snapshot, serializer and middleware complete under the lock;
immutable delivery then permits acknowledgements, reads, switching and shutdown.
Occurrence IDs, sampled revision, quality/staleness fields, recovery text and source
header remain those prepared, even if acknowledgement state later changes. Reads
never dispatch acknowledgements or operator-journal operations. Acknowledgement
routes retain permission, attribution, transaction and project-instance guards;
old-project requests are rejected before journaling even when IDs collide. Cancelled
preparation drains the monitor/SQL work before source closure; send failures do not
repeat it. Unexpected read failures are sanitized/recoverable and stopped runtimes
reject monitor access. Payloads and OpenAPI remain unchanged.
`readRuntimeSnapshot()` adds opt-in project context checks to the shared API client.
It captures the initially pinned project at dispatch, requires a valid matching
response header for ordinary reads, and strips its internal option before fetch.
Missing/malformed/foreign success headers are rejected before JSON adoption; no
request is replayed and the pin never changes. Applied-project reads may describe
a new instance only when header/body identities agree, allowing the existing
runtime reload flow. Editors now return after flagging a changed project instead
of installing its active metadata. Main tag/alarm/recipe/identity polls and explicit
identity refresh use these checks; initial catalogue loading follows the pinned
project read sequentially. Existing unavailable-state/generation handlers remain.
Default API mutation/receipt behavior and legacy unguarded callers are unchanged.
Same-project synthetic browser fixtures now supply realistic context headers via a
scoped test helper; missing/foreign cases deliberately bypass it. No server schema
or OpenAPI changed. Independent operator detail/history readers remain a follow-up.

Preserve model/import
compatibility, project-instance identity, write non-replay behavior, apply
rollback, command locks and journal ordering in further extractions. Extend the contract fixtures whenever a request
model, saved control field or editor serialization branch changes. These software
checks do not establish controller or operator-station acceptance.
