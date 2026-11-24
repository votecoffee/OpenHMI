# Schema and API contract coverage

This audit covers the production palette/serializers and the request paths named
below. It is not a claim that every API response or every possible query is
formally modeled. Controller, Windows station and operator acceptance remain in
the [project plan](project-plan.md). No PLC access or soak is required here.

| Boundary | Automated evidence | Practical limit |
| --- | --- | --- |
| Saved control schemas and palette | `test_frontend_contract.py`: real palette kinds, family/category uniqueness, defaults, select options and complete field-preserving round trips | Nondefault fixtures must be extended as behavior is added |
| Tag catalog and binding rejection | `test_engineering_contract.py`, `test_binding_rules.py`: real draft catalog to JS pickers, tag-type filtering, validation order and unchanged rejected drafts | A valid binding does not prove a physical PLC address exists |
| UDT faceplates | Real browser resolver compared with backend expansion across eligible controls, secondary screens and nested tag fields | Adding a new tag-bearing property requires both resolvers and fixtures |
| Value/actions, leases, project lifecycle and alarms | Actual browser helpers validated against strict request models; methods, headers, revisions and payload fields checked | Fake-fetch contract checks do not authenticate a real user or dispatch a controller write |
| Trend recording, station ownership and image upload | Actual capture/claim/renew/release helpers plus binary File upload contract checks | Read-page query construction and response payloads are separate boundaries |
| Command history queries and transaction export | `test_command_contract.py`: production builders to the real FastAPI registrar through an in-process client; every UI state matches the server enum, Unicode filters, bounds, integer IDs and export headers | History data and the security hook are stubbed; domain/browser tests cover behavior and permissions |
| Command transaction/history responses | `test_command_responses.py`: real SQL detail, filtered/cursor pages, exports and restart reconciliation across all eight states through production JS validators; malformed sequence/page browser recovery | Seeded offline lifecycle states do not prove PLC execution; nullable results/errors and empty event histories remain compatible |
| Image listing queries and pages | `test_image_contract.py`: production queries to the real registrar, Unicode search, cursor/page bounds, real SQLite pages to the actual JS validator and malformed-page rejection | Listing fixtures do not test image decoding; JSON paging cursors must be safe positive JS integers |
| Historian/trend reads and exports | `test_history_contract.py`: production paths through both real registrars; live/fixed windows, context, recorded tags, bounded/complete CSV, capture reads/CSV, invalid ranges and stale project guards | Data services are stubbed for query binding; existing domain/browser tests cover actual acquisition and export behavior |
| History windows and recording status responses | `test_trend_responses.py`: actual SQL sampling/query/listing through real HTTP registrars into production JS validators; context, truncation, quality, rollover, stopped/restarted captures and malformed replies | Offline sample snapshots do not prove acquisition; history supports equal epochs and different ordering between tags; optional legacy pen metadata remains accepted |
| Recorded-tag catalog responses | Real SQLite historian pages through `isRecordedTagPage`, malformed-page fixtures and browser no-crash/recovery regression | This is a bounded catalog response contract, not complete history/capture response parity |
| Schema ownership/import compatibility | `test_project_models.py`: direct family/domain imports, no service/HTTP/Pillow/SQLite dependency, shared canonical/legacy classes and project round trips | Import isolation is not a runtime performance or packaging benchmark |
| Activity/diagnostics queries and exports | `test_operations_contract.py`: actual production read helpers/URLs through the registrar; Unicode filters, UTC conversion, precise cursors, limits/defaults, project headers, CSV quoting/formula escaping and export permissions | Journal is real SQLite; driver metadata/security hooks are controlled offline fixtures; no browser-local timezone or controller acceptance claim |
| Activity/diagnostics responses | `test_operations_responses.py`: real SQL journal outcomes/pages/restart and actual driver/worker projections through the registrar into production JS validators; malformed paging and scan-age checks | Security is stubbed in contract fixtures; browser tests cover denial/recovery; fake transport does not establish PLC or station acceptance |
| Read-only diagnostics projection | `test_diagnostics.py`: catalog replacement at snapshot release, common snapshot time, worker read outside the driver lock, route fault precedence, filter/paging and value omission | Controlled boundary regression, not a concurrency stress benchmark; HTTP and browser contracts remain separate checks |
| Identity-session snapshots | `test_security_session_contract.py`: real SQL security service/session route into the production guard; local/expired sessions, live permission changes, mocked Windows mappings/disable, public fields and malformed payloads; validated read-helper errors | Windows authentication is mocked, not OS/domain acceptance; UI retains generation fences and last-confirmed identity behavior |
| Selected-recipe snapshots | `test_recipe_selection_contract.py`: actual SQL create/load/approve/revise/withdraw/clear/reopen responses into the production guard; images, Unicode, typed/safe-integer boundaries and malformed payloads | Security principal and local publication callback are stubbed; display guard covers consumed fields, while request models enforce full recipe limits; no PLC transfer or controller acceptance |
| Live alarm snapshots | `test_alarm_snapshot_contract.py`: real SQL/HTTP monitor snapshots for priorities, acknowledgement, shelving, quality/staleness, retirement/reopen and legacy/malformed payloads; read endpoint does not acquire source data | Guard validates live-banner fields and legacy fallbacks, not complete occurrence/history DTOs; source values are synthetic and no controller acceptance is implied |
| Applied-project snapshots | `test_applied_project_contract.py`: real palette/Pydantic/SQLite save/apply and active HTTP responses through the production guard; all control kinds, screens, faceplates, freeform/flow layout metadata, legacy and malformed replies | Runtime callbacks are stubbed; schema/display compatibility does not prove PLC binding validity, asset availability or native station acceptance |
| Tag-status snapshots | `test_tag_snapshot_contract.py`: real acquisition/cache responses with FakePLC through the production normalizer; held/pending, partial bad-tag faults, stale recovery, disabled and status-only metadata; GET cannot poll/subscribe or copy samples in status-only mode | Top-level validation retains per-tag fault isolation; control-specific quality/type handling remains separate; FakePLC is not controller acceptance |
| Alarm-console queries and exports | `test_alarm_query_contract.py`: generated occurrence/event/detail/note/CSV URLs through real SQL-backed routes; UI enum parity, Unicode/UTC/cursors, limits, errors and CSV escaping | Read contracts do not validate detailed response DTO parity or exercise note-write authorization; source sampling is excluded and detail trigger values are omitted |
| Detailed alarm responses | `test_alarm_response_contract.py`: real SQL occurrence/event/note pages and cached details through DOM-free production validators; legacy null attribution/metadata, shelving, wrong identities and malformed paging | Validators cover fields consumed by each view, not strict HTTP response filtering; CSV bulk pages are a separate boundary |
| Alarm mutations | `test_alarm_mutation_contract.py`: actual browser note/shelve/restore payloads through strict models and secured SQL-backed routes; attribution, denials, stale restore guards and receipt/error propagation | No PLC source acquisition or writes; operating-system authentication and controller acceptance remain separate |
| Shelving-list queries/responses | `test_alarm_shelf_contract.py`: actual browser URLs and DOM-free guard through SQL-backed routes; ordered pages, encoded cursors, strict bounds, row compatibility and restoration of a 100-character alarm ID | Guard covers consumed fields; no strict response DTO filtering or PLC acceptance; browser regression covers retained-data recovery |
| Recipe write requests | `test_recipe_mutation_contract.py`: production create/revise/transition/select helpers and content normalization through strict models and SQL-backed lifecycle routes; same-user approval, stale conflicts, loaded-copy independence, denials and HTTP error propagation | Identity and publication hooks are stubbed; browser/domain tests cover local authentication and workflow; synthetic receipt headers do not add journal semantics to recipe routes |
| Recipe policy/image uploads | `test_recipe_settings_contract.py`: actual policy PUT and raw File POST through strict models and SQL-backed routes; version conflicts, Boolean permit fixtures, reason encoding, binary fidelity, PNG/JPEG normalization, denials and upload bounds | Identity hooks and permit values are mocked; HTTP streaming size limit is tested using generated URL/headers with a bounded synthetic payload; no PLC acceptance |
| Recipe authentication/session requests | `test_recipe_session_contract.py`: production read/login/logout helpers through real RecipeAuth and SQL-backed HMI Security; strict models, cookie rotation/expiry, origin rejection, account delegation and group permission changes | Windows identity provider is mocked; browser tests cover local form/logout errors and HMI UI delegation; no new session-response guard or OS/domain acceptance |
| Recipe transfer requests/queries | `test_recipe_transfer_contract.py`: actual browser helpers through SQL-backed routes with simulator-only staging; filter/status query separation, precise cursors, strict bounds/models, stale guards, receipts and JSON export | Transport factory is forbidden; domain/browser regressions cover completion and running-copy verification; no live controller acceptance or full response guard contract |
| Recipe transfer responses | `test_recipe_transfer_responses.py`: real SQL/HTTP history/detail/verified responses through production record/page guards; all eight modeled command states, verified records outside the page, retired targets, nullable metadata and malformed paging | States are seeded offline; browser guards validate consumed fields, while server checks enforce hashes/integrity; no controller acceptance or strict response DTO filtering |
| Transfer dispatch receipts | `test_recipe_transfer_receipts.py`: actual simulator-backed success/pending/uncertain HTTP outcomes through pure receipt correlation and error-formatting helpers; malformed identities and no confirmation/replay | A validated receipt confirms request dispatch, not PLC completion; server/domain checks retain hash and running-copy authority; optional legacy receipt headers remain supported |
| Recipe library responses | `test_recipe_library_contract.py`: SQL/HTTP lifecycle snapshots through the production guard; all six revision states, typed values, policy/gates, audit differences, legacy optional fields and unavailable permits | Guard covers workspace-consumed fields, not full write-schema validation or hash integrity; selection/live-copy status and recipe session replies are separate boundaries |
| Recipe session responses | `test_recipe_session_responses.py`: actual local/HMI auth/session replies through production guards; expiry/logout, mock-Windows mappings, empty roles, legacy metadata, malformed names/roles/confirmations and input preservation | Guards cover consumed fields and identity confirmation; role authority remains on the server; no OS/domain acceptance or automatic replay |
| Recipe component import compatibility | `test_frontend_contract.py`: legacy picture/loaded/selected exports and direct readout palette binding retain focused-module function identity; recipe browser workflow checks all four parameter types, preview/images and loaded values | Component bodies and saved schemas are unchanged; existing project/palette contracts cover persistence; no controller acceptance implied |
| Recipe authentication registrar | `test_recipe_auth_routes.py`: standalone HTTPS cookie/origin/rate-limit/shared-authorizer behavior, HMI delegation, idempotent HMI logout, stable model/OpenAPI ownership and fresh-process import isolation | Auth/recipe/transfer service construction remains in the combined registrar; Windows identity is mocked and no OS/domain acceptance is claimed |
| Main project library and acknowledgements | `test_workspace_contract.py`: real SQL/HTTP listings and create/import/open replies through canonical Pydantic models and production JS helpers; current-row uniqueness, legacy/Unicode names, request serialization, matching filenames, import hold, malformed JSON/replies and HTTP error non-replay; workspace browser faults | Confirmation validates wire identity/semantics, not PLC or physical installation; ambiguous operations require review and do not imply rollback; existing wire fields/OpenAPI are unchanged |
| Project-library artifact inventory | `test_workspace_inventory.py`: actual protected workspace ASGI queries, canonical Pydantic pages through production JS guards, known publication companions, metadata-only access, Unicode cursors, scan bounds, link/unavailable cases, query/response rejection and HMI/legacy permissions; workspace browser faults | Top-level known filenames only, 10,000 scanned entries and 100 returned rows maximum; metadata is not integrity/repair evidence; no contents/link-target reads or file actions; existing FastAPI OpenAPI is unchanged |
| Project file publication | `test_workspace_publication.py`: staged create initialization/retry, import short write and mid-publication rollback/retry, all companion/journal collision guards, destination race, changed/unremovable artifact retention and uncertain completed database/hold preservation | Synthetic local SQL/ZIP fault injection on the host filesystem; no multi-file crash/power-loss or adversarial external-writer guarantee; no existing files are replaced; OpenAPI is unchanged |
| Workspace background jobs | `test_workspace_jobs.py`: repeated cancellation during real create/import/export, queued switch/shutdown ordering, complete SQL/ZIP results and imported hold, failure during cancellation, ordinary HTTP error identity, cancelled upload before dispatch and no replay | Synthetic local projects and held connections; completed files are retained after request cancellation; partial publication/filesystem failure recovery is separate; OpenAPI is unchanged |
| Workspace runtime handoff | `test_workspace_switch.py`: candidate construction/startup failure, cancellation before/after ownership switch, blocked competing reads, stale-write rejection, post-switch error guidance without replay, lifespan cancellation/startup notification failure and store closure | Synthetic local databases, held connections and forbidden PLC factories; generic create/import/export thread cancellation is separate; OpenAPI is unchanged |
| Worker startup and cancellation | `test_worker_startup.py`: failed first/later task creation, unscheduled coroutine disposal, original failure retention, real app cleanup after startup failure, repeated cancellation during callbacks/executor/resource cleanup and initial sampling, unexpected task failure collection | Bounded event-controlled callbacks and in-memory SQL; no network/PLC access, forced process termination or indefinitely blocked vendor call acceptance; OpenAPI is unchanged |
| PLC shutdown isolation | `test_transport_shutdown.py`: first/last client-close failures, route-wrapper exceptions, per-route logging, independent close attempts, state cleanup, repeated close, bounded active-read draining, no late samples/replacement scans and explicit reopen | Fake PLCs only with no writes; a vendor close exception cannot prove its physical socket was released; no automatic reconnect or close retry |
| Runtime lifecycle ownership | `test_runtime_lifecycle.py`, `test_runtime_workers.py`: partial assembly across driver/configuration/services/routes/assets, real handler failure, initial sample and worker entry/exit failures, original-error preservation, cleanup isolation/order and no pre-worker identity publication | In-memory SQLite and default simulator with forbidden PLC factory; worker scheduling/transport remain separate; complete OpenAPI is unchanged |
| HTTP project context and operation receipts | `test_http_context.py`: runtime/workspace stale guards before handlers, read/headerless compatibility, generated HTTP error headers, real SQL journal outcomes through the actual JS API, pinned browser identity and no automatic write replay | Simulator/default runtime and controlled journal callbacks only; generic unhandled server exceptions remain outside this response policy; OpenAPI is unchanged |
| Recipe library registrars | `test_recipe_library_routes.py`: public reads, six canonical typed mutation adapters, identity/identifier forwarding, invalid body/path rejection before authorization, denied identity and error propagation; focused import isolation | Adapter stubs do not duplicate service policy; existing real SQL/JS/browser contracts cover revisions, self-approval, loaded copies and policy behavior; complete OpenAPI and route order are preserved |
| Recipe transfer registrar | `test_recipe_transfer_routes.py`: standalone history/export bounds, role checks, binary-safe query forwarding, export headers, recipe-local/HMI journal identity, conditional group authorization and journal-before-dispatch guards | In-memory SQL journal and controlled transfer callback; existing transfer domain/HTTP/browser contracts cover actual service and simulator behavior; complete OpenAPI output is preserved |
| Recipe image registrar | `test_recipe_image_routes.py`: standalone read/upload HTTP adapter, public headers, byte/reason/identity forwarding, role/MIME/query guards, exact/overflow bounds and early stream termination; focused import isolation | Service normalization/storage/policy/audit ownership is unchanged; existing SQL/browser tests exercise actual PNG/JPEG handling; complete OpenAPI output is preserved |
| Runtime faults and status | Domain tests and selected browser fault-injection workflows for stale/bad data, malformed responses and recovery | Response DTO parity is not yet a complete cross-language schema contract |

## Delivered query contracts

Command buttons and the transaction console now use `command-api.mjs`. Existing
latest-status query ordering, console defaults, pagination filters and download
URLs are preserved. Tests use actual generated requests and the real registrar;
invalid limits, cursors, state values, names and transaction IDs must fail before
service calls. The query tests include string-form signed-64-bit limits without
converting them through a JavaScript Number.

The project image picker now uses `image-api.mjs`. Query contracts preserve the
unfiltered URL, before/search ordering, Unicode search and server defaults, and
exercise explicit page limits. Real SQLite listing pages pass the production
browser validator. Missing/malformed/unsafe cursors, empty pages with a cursor,
duplicate IDs and malformed image entries are rejected. Browser regressions cover
forward/back paging, retaining the prior page on malformed replies, retry recovery
and clearing rows on access denial. Closing/new requests retain the sequence guard.

This does not make large numeric JSON response IDs lossless. Existing command
status validators require safe JavaScript integers. A broader wire-format change
for IDs needs a separate compatibility decision; do not silently round an ID or
coerce it just to satisfy a test. Image paging similarly rejects unsafe numeric
response cursors rather than rounding them into a different query.

Historian/trend query paths now come from `history-api.mjs` and `trend-api.mjs`.
Contracts preserve live versus fixed end times, epoch zero, fractional seconds,
context flags and CSV links without context parameters. Tests bind recorded-tag
prefix/cursors, enforce window/tag/count limits, preserve complete-export project
fences, check CSV quoting/headers and verify release of the complete-export slot.
The bounded History-panel CSV path retains its response project-header check;
complete exports retain their query project-instance fence.

Recorded-tag search pages are checked before entering React state. Real SQLite
pages pass the validator; missing items, invalid dates/cursors and duplicate tags
are rejected while readable prior choices remain usable with an error. Browser
checks require the editor to survive malformed success replies and recover.

Command response contracts now compare actual SQL-backed detail, export, filtered
and cursor pages, including restart reconciliation, with production validators.
Positive signed-DINT sequences, descending unique IDs, the 200-row bound and
last-row cursors are enforced. Malformed replies retain evidence with warnings;
buttons remain blocked and older-page navigation is disabled until recovery.
No strict HTTP response filtering or controller dispatch was added.

History/capture response validators are exported from `history-api.mjs` and
`trend-api.mjs`, shared by the production React controls and contract tests.
History must be chronological within each tag; equal epochs and interleaved tags
remain valid. Duplicate capture IDs and retained counts exceeding capacity are
rejected. Browser regressions retain readable traces/status through these faults
and restore normal controls after valid replies. Existing quality-gap handling,
nullable fields and source-time metadata are preserved.

Activity pages now validate positive safe IDs, descending unique rows, unique
operation IDs, the 1,000-row bound and last-row cursors. Diagnostics checks unique
tag names and coherent offset/count/cursor/truncation metadata, including empty
pages beyond the current result set. Nullable scan ages remain valid; objects
are rejected before numeric formatting. Browser regressions retain prior data,
disable forward paging, clear data on denial and recover on valid replies.

Activity/diagnostics list reads and export links now share focused API helpers.
Generated requests preserve existing filter order, local-date-to-ISO conversion,
string-form cursor precision and export scopes (without list paging parameters).
Contract tests bind those requests through the real registrar, verify explicit
limits and defaults, reject invalid bounds before reads, and require permission
checks before list/export service calls. Download formats remain unchanged.

The command/activity/diagnostics views now have focused modules. The app imports
them directly, with compatible component exports retained in `operations.jsx`.
View bodies and hook logic are preserved; existing browser regressions exercise
command feedback, stale actions, retained pages, access denial and recovery.
No saved-project schema, HTTP response shape or permission model changed.

Identity-session validation is now shared through `security-session.mjs` by
background polling, explicit login refresh and contract tests. The validated
read helper retains API timeouts and HTTP error status. The guard retains its
previous rules and returns the original object; contract tests reject malformed
identity/group/permission structures without coercion or mutation. Real service
responses exercise local and mock-Windows lifecycles without OS account changes.

Selected-recipe validation and its polling path now live in `recipe-selection.mjs`.
The app retains its prior failure/clear behavior, with guard rules unchanged. Real
SQL contracts preserve loaded copies across later approval, revision edits and
withdrawal, then validate clear/reopen results. Typed boundary fixtures include
zero/false values, Unicode text and exact integer limits; malformed shapes are
rejected without mutation. These fixtures use a stubbed local publication callback
and do not execute a PLC recipe transfer.

The live alarm snapshot guard and polling path are shared through `alarm-api.mjs`.
Guard rules remain unchanged, including fallback annunciation/count fields for
legacy snapshots. Real monitor responses preserve outstanding conditions while
shelving alters annunciation, bad quality does not invent a return, acknowledgement
does not clear the condition, and project retirement remains explicit. The contract
rejects malformed consumed shapes without mutation; detailed history/query payloads
remain a separate contract.

Applied-project snapshot validation and polling URL are shared through
`project-api.mjs`. Guard rules remain unchanged and use the canonical control-kind
map. The shared palette fixture supplies every control family for real saved/
applied-response checks. Draft-only changes leave the live response intact;
freeform/flow layouts, scoped screens, faceplates, containers, groups and locked
background metadata survive apply. Consumed malformed shapes are rejected without
mutation, preserving legacy defaults. Runtime bindings/assets stay separate checks.

Tag-status validation/default normalization and both polling URLs are shared
through `runtime-api.mjs`. Existing rules preserve legacy normal-response defaults
and require explicit connection/hold metadata for status-only replies. Per-tag
null/stale/bad samples do not invalidate an otherwise readable payload; malformed
top-level collections do. Contracts preserve zero/false/text/structured values
without mutation, with cache-only reads and lightweight diagnostic polling.
This completes extraction of the five live app snapshot validation boundaries.

Alarm-console query construction now shares `alarm-api.mjs` helpers and filter
lists. Contracts bind generated URLs through SQL-backed routes, preserving empty
filters, UTC dates, signed-64-bit string cursors, history state/export scope and
notes URL ordering. Invalid HTTP bounds fail before query/cache calls; domain
filter/date errors and missing IDs retain their existing status codes. CSV export
retains quoting, formula escaping, full matching scope and truncation headers.
Console polling, generation guards and read-error retention are unchanged.

Detailed alarm response validators now live in `alarm-responses.mjs`, with the
message helper re-exported from the existing read hook for compatibility. Real
query-service payloads validate across cursor pages, shelved/acknowledged alarms,
notes, cached/unavailable triggers and legacy null event attribution. Pages must
be strictly descending with unique safe IDs and last-row cursors, bounded at
200 occurrences/events or 100 notes. Malformed paging retains prior readable
results with warnings and disables older navigation; valid replies recover.
Row/detail nullable-field rules remain unchanged, without strict HTTP filtering.

Alarm note/shelve/restore helpers now share `alarm-api.mjs`. Contracts bind actual
browser POST paths and payloads through secured SQL-backed routes, preserving
Unicode/comments, numeric duration conversion and server-owned attribution.
Strict-model/path failures precede journal creation; anonymous/limited-user
denials and stale restore conflicts precede mutation dispatch. Receipts, pending
audit status and HTTP errors propagate without automatic replay. Tests use
synthetic sources and never acquire or write PLC data.

Shelving-list URL construction now shares `alarm-api.mjs`, preserving existing
query encoding/order. The response guard in `alarm-responses.mjs` requires at
most 200 ascending unique IDs and a cursor matching the final row. Existing
row/message/date rules and legacy fields remain compatible. Real SQL-backed
contracts cover defaults, bounds, encoded cursors and restoration. The API cursor
and restore path limits now match the 100-character project alarm IDs, fixing
paging/restoration for valid IDs above 60 characters. Browser regressions retain
the last readable page and disable restore/next-page actions on incoherent replies,
discard inaccessible data and recover when valid replies return.

Recipe create/revise/transition/select helpers and numeric content normalization
now share `recipe-api.mjs`. Actual browser payloads retain numeric/limit conversion,
blank-numeric errors before fetch, zero/false/text values, explicit null clear
fields and exact version guards. Strict models and SQL-backed routes exercise
all review actions, same-user approval, independent test/production loaded copies,
server-attributed audit records, stale conflicts and denied operations. Invalid
models fail before service calls. Mock identity/publication hooks keep these
contracts offline; existing browser/domain workflows cover local authentication.
HTTP errors and optional audit receipts propagate without automatic replay;
recipe-audit behavior is unchanged.

Recipe policy saves and image uploads now use shared request helpers. Contract
fixtures verify strict policy defaults/versions, Boolean permit values, Unicode
query-reason encoding, raw File bytes/MIME types, API timeout wiring and normalized
PNG/JPEG retrieval. Invalid models fail before service calls; role/gate checks,
HTTP upload bounds and malformed images preserve existing statuses. Synthetic
receipt/error propagation does not change recipe-audit behavior. Identity and
permit reads are stubbed; no live acquisition occurs. Browser tests cover stale
policy feedback, refresh recovery and the existing image-backed recipe workflow.

Recipe authentication helpers and the local session component now have focused
modules. Real authentication/security contracts preserve read/login/logout paths,
exact credential strings, strict Login/Empty models, cookie rotation/expiry and
origin checks. Once HMI security is configured, recipe-local cookies cannot grant
access; current HMI group permissions determine recipe roles. Contract fixtures
exercise local security with a mocked Windows adapter and no driver acquisition.
Browser checks cover bad credentials, retained identity on failed logout, cleared
password after successful sign-out, and HMI sign-in/out delegation. Component
state/callback ordering and existing server response behavior are unchanged.

Recipe transfer query/dispatch/export helpers now share `recipe-transfer-api.mjs`.
History identity excludes the verified target, while the status endpoint includes
it when selected. Tests bind actual browser requests through SQL-backed routes
using simulator-only staging and a forbidden transport factory. Contracts cover
empty/default/filter queries, Unicode encoding, signed-64-bit cursor strings,
query/model rejection before service calls, stale project/revision rejection
before staging, unauthenticated reads/dispatch, durable operation receipts and
JSON detail/export parity. Optional synthetic receipt/error propagation verifies
non-replay. Panel polling, selection/revision fences, permission checks and
retained history ownership remain unchanged.

Transfer record/page guards now share `recipe-transfer-responses.mjs` and reuse
the existing command-record validator. They validate consumed fields, matching
record/transaction IDs, safe integers, at most 100 descending unique rows and a
matching final-row cursor. Optional attribution/image metadata, null errors/results
and empty events remain compatible; unused parameter/envelope fields are not
newly constrained. SQL fixtures cover all eight modeled command states, verified
records outside the page, retained history after target rename/removal and cleared
verification when target signatures change. Invalid replies retain readable data
and disable dispatch/paging; 401/403 responses discard inaccessible data. Browser
faults cover malformed nested records and valid-reply recovery. Hash integrity
and actual PLC completion remain server/domain responsibilities.

Dispatch receipt validation now checks the requested target/revision, matching
transaction identity/state, envelope sequence and durable operation ID before
creating a confirmation link. Optional legacy headers and pending finalization
remain compatible; malformed replies preserve known operation hints and require
verification. The shared API reader preserves operation headers on invalid JSON
or receipt attachment failures. Transport/JSON failures and uncertain HTTP errors also receive
verification guidance. Any dispatch error refreshes status and clears stale
receipt links without sending another POST. Real simulator HTTP success, pending
audit finalization and commit-failure outcomes are tested; the browser corrupts
a real reply and confirms one request, no false acknowledgement, retained history
and subsequent valid receipt handling. Completion still requires PLC acknowledgement
and running-copy verification.

Recipe library validation and its read helper now share `recipe-library.mjs`.
The guard checks consumed revision/parameter/policy/gate/audit fields, safe
ordered identities and typed values. Optional historical attribution, description,
image and unit fields remain compatible. Independently selected-copy metadata and
raw permit samples are not used by this view guard; a bad permit disables its
gate without invalidating an otherwise readable library. SQL/HTTP tests cover
all six revision states, typed limits, audit differences and malformed shapes.
Failed refreshes retain readable library and unsaved content, block writes and
keep a manual recovery path. Initial failure offers retry. Browser regressions
confirm retained identity/draft fields, no recipe writes and valid-reply recovery.

Recipe session/sign-in/sign-out guards now share `recipe-auth.mjs`. Real local
authentication and SQL-backed HMI security replies pass across expiry, logout,
mock-Windows mappings and empty role grants. Legacy user fields, future string
roles and extra metadata remain compatible. Malformed replies do not replace
confirmed identity or imply successful logout. Session-read faults reuse the
workspace write gate; manual refresh reconciles the actual server session without
replaying auth requests. Confirmed identity updates clear stale form errors and
password state. Browser faults exercise real cookie-changing login/logout with
corrupted confirmations, malformed session reads and recovery without page errors.

Recipe readouts/value rendering and parameter editing now have focused component
modules. The workspace retains API, state and dirty-draft ownership. Public
picture/loaded/selected exports retain function identity through aliases; the
palette binds directly to the focused selected-recipe renderer. Saved schemas
and moved bodies are unchanged. Browser coverage includes add/remove parameter
rows, all four types, disabled nonnumeric limits, Unicode/leading-zero text and
typed values read back from the SQL-loaded copy, alongside image/approval/runtime
workflows.

Recipe authentication HTTP registration and shared recipe-user authorization now
have a focused module. Request-model ownership stays in the combined registrar
and is supplied explicitly so existing imports and qualified OpenAPI references
remain stable. A full before/after OpenAPI comparison is unchanged. Standalone
HTTPS tests verify cookies, same-origin checks, rate limits, legacy/HMI delegation
and the existing difference between anonymous legacy and idempotent HMI logout.
Fresh-process imports do not pull in recipe/transfer services or the server;
application service ownership remains unchanged. Existing model, session, recipe
and transfer regressions exercise the delegated authorization path.

Recipe image HTTP registration now has a focused module with the same service,
authorizer and error translator supplied by the combined registrar. Moved handler
bodies and complete OpenAPI output are unchanged. New adapter tests preserve
public read headers, raw byte/reason/identity forwarding, pre-dispatch role/MIME/
query rejection and exact 5 MiB acceptance versus overflow. A streamed overflow
reads only the first two chunks and never calls the service or consumes later
chunks. Focused import tests exclude Pillow and recipe/server services. Existing
SQL/domain and browser tests retain actual normalization, images and approvals.

Complete-backup contracts now exercise real SQL exports through the HTTP boundary
and production JavaScript binary helper. Tests compare bytes, ZIP integrity and
manifest checksums for successful exports; reject malformed headers, truncated or
unsupported ZIP structures, length/stream overflow, stale identity and permissions;
and preserve sanitized export failures. The browser helper validates bounded ZIP
structure only; full checksum/database checks remain with import. Headless browser
faults verify no download or replay on bad replies/denial, retained drafts and an
explicit successful retry with byte-for-byte saved output. All handled backup
responses are private/no-store, and final ZIP overhead is included in the size limit.

Backup-transfer ASGI checks now pause both headers and body while real SQL/ZIP
responses are ready. Reads, project switching and runtime shutdown finish before
the send resumes; downloaded bytes and project identity remain those prepared from
the source runtime. Other tests hold export preparation in a thread, proving queued
requests cannot close its source store early, and cover cancellation/disconnect
without replay plus detached error responses. Existing cancellation contracts
continue to own preparation cleanup. These are bounded offline event tests, not
network-throughput or server-process shutdown acceptance.

Import-upload contracts now cover bounded receive outside the runtime lock and
one active import slot. Real SQL/ZIP and event-gated HTTP tests prove reads/switches
continue during uploads, headerless and pinned uploads cannot cross a switch,
logout revokes admission before dispatch, and shutdown never accesses a closed
store. Denied/stale/busy requests do not read bodies; timeout, disconnect, overflow
and cancellation release the slot without dispatch or replay. Actual receive-error
HTTP replies feed production JS serializers and error handling. Browser faults
verify timeout/busy messages, retained names/files and explicit recovery. Existing
job cancellation tests retain lock ownership through import thread completion.

Create/open ingress now has real SQL/event-gated HTTP contracts for exact 4 KiB
Unicode requests, streaming overflow without later reads, malformed encoding/JSON
and excessive nesting, timeout/disconnect, four-request admission and cancellation
capacity recovery. Slow bodies allow reads and switches; captured identities and
permission rechecks prevent stale/headerless or signed-out requests from dispatching.
Shutdown during receipt rejects work before touching closed state; slow completed
acknowledgements allow runtime shutdown and preserve source identity. Actual error
replies feed production JS operation handling without retry. Browser faults retain
create fields on timeout/busy replies, require explicit retry, then exercise real
SQL create/open and successful field reset/navigation. A delayed initial-identity
test verifies no editable form appears before sign-in is confirmed; this closes a
race found by the ambiguous-acknowledgement browser test without weakening its
draft-retention assertions. Existing handoff/job
cancellation regressions retain thread, candidate and retirement ownership.

## Next bounded work

1. Review immutable project-library and file-inventory response delivery so slow
   read clients cannot hold the runtime lock after their snapshots are prepared,
   preserving permission, source identity and owned scan cleanup.
2. Continue response parity across other operator pages as concrete gaps arise.
   Review older nullable/history data before adding strict response filtering.

Recipe authentication, images, transfers and library HTTP separation is delivered.
Project-instance and operation receipt context now has a shared implementation
and real HTTP-to-JavaScript coverage.

Keep further refactoring tied to a boundary or contract gap in this list rather
than file size alone. See [extending controls](extending-controls.md) for the
contributor workflow and [architecture](architecture.md) for retained lock,
transaction, transport and quality ownership.
