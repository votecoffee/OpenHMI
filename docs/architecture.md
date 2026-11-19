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
  in `alarm_routes.py`. Legacy request-model imports from `server.py` remain
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
  lease, historian or sample-cache dependency. `logix.py` coordinates physical
  scan deadlines, route workers, writes and sample publication. Viewer leases,
  sequence retention, screen-rate demand and trend demand live in
  `tag_subscriptions.py`. Cached PLC samples, scalar/UDT decoding, good/stale/bad
  projection and usable-generation checks live in `tag_samples.py`. Pure value/type/freshness
  rules live in `tag_values.py`; bounded timing statistics live in
  `scan_timings.py`. Existing imports from `openhmi.logix` remain compatible.

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
The DOM-free contract tests send no runtime/controller requests.

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

The subscription and sample components deliberately own no locks or worker
pools. The driver retains its state `RLock`, configuration/write `io_lock` and
per-route locks. Lease mutation and sample projection use the existing state
lock; a route lock is never acquired while projecting samples. Transport work
still runs outside the state lock, and the project-generation fence is checked
before publishing a completed scan. The existing caller-coordinated `demands`
contract is unchanged. Concurrent component access requires the driver's state
lock.

Legacy `samples`, `leases`, `trend_demands`, `_screen_demands` and
`_lease_sequences` attributes forward to live component-owned dictionaries,
including replacement assignments. No detached compatibility copies are kept.
The metadata-only diagnostics regression now guards the cache owner's copy
function so it still detects an accidental deep copy of tag values.
`tests/test_tag_state.py` checks shared consumer demand after expiry/release,
sequence ordering, independent driver state, nested snapshot isolation, legacy
dictionary replacement and cache cleanup. Existing blocked-route, freshness,
bad-tag retry, reconnect and in-flight-write tests remain applicable.

The next move is separating physical deadline policy and receipt publication
while retaining the same atomic state-lock boundary. Preserve project-instance
identity, apply rollback, command locks and journal ordering in further extractions. Extend the contract fixtures
whenever a saved control field or editor serialization branch is added. These
software checks do not establish controller or operator-station acceptance.
