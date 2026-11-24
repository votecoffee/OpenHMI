# OpenHMI development plan

## Product direction

Build and change industrial HMI applications live through a visual designer.
Simple applications require no code or web development skills; trusted Python
customization remains available. Use the supplied high-performance HMI guidance
and FactoryTalk View ME visual references. Puck supplies editor infrastructure.
FUXA is a feature reference only. AdvancedHMI compatibility is not a requirement.

ControlLogix/CompactLogix communication uses pycomm3 with shared, screen-rate
polling. Reusable faceplates bind to UDT contracts; specific equipment designs
will be chosen with the owner. The PLC owns machine interlocks, its running
recipe copy and run/reject/inhibit decisions. Recipe self-approval is allowed
and the actual approving user is recorded. Unapproved recipes remain usable
for testing with production status false.

The integrated Python IDE and deliberate Python hot reload are deferred.

## Milestone overview

| Milestone | Status | Outcome / exit gate | Tracking |
| --- | --- | --- | --- |
| M0 — Verified software baseline | Complete software checkpoint | Existing visual/runtime/project foundations verified at `8a2deb5`: 34 Python tests, 9 browser tests and package checks. No hardware/domain acceptance implied. | [M0](https://github.com/votecoffee/OpenHMI/milestone/1) |
| M1 — Operational traceability and diagnostics | Complete software checkpoint | Durable journal and readable diagnostics delivered; 44 Python tests and 10 browser tests passed. Hardware/domain acceptance remains separate. | [M1](https://github.com/votecoffee/OpenHMI/milestone/2), [#5](https://github.com/votecoffee/OpenHMI/issues/5), [#6](https://github.com/votecoffee/OpenHMI/issues/6) |
| M2 — ControlLogix driver readiness and bench acceptance | Offline baseline delivered; bench validation next | Grouped polling, route isolation and quality propagation are available. Measure supported tag types, scan/load and reconnect on an identified read-only bench. | [M2](https://github.com/votecoffee/OpenHMI/milestone/3), [#12](https://github.com/votecoffee/OpenHMI/issues/12), [#3](https://github.com/votecoffee/OpenHMI/issues/3) |
| M3 — PLC transactions and recipe deployment | Offline software delivered; hardware acceptance open | Guarded command handshakes, versioned recipe staging and PLC copy verification, durable lifecycle/history and evidence exports are available. Validate the named PLC contracts after M2. | [M3](https://github.com/votecoffee/OpenHMI/milestone/4), [#7](https://github.com/votecoffee/OpenHMI/issues/7), [#8](https://github.com/votecoffee/OpenHMI/issues/8) |
| M4 — Project revisions and recovery | Complete software checkpoint | Applied history, identity-aware diff/merge, staged rollback and browser/server recovery with validated migration/restore; 81 Python and 14 browser tests passed. | [M4](https://github.com/votecoffee/OpenHMI/milestone/5), [#1](https://github.com/votecoffee/OpenHMI/issues/1) |
| M5 — Operator workflows and equipment library | Operator baseline delivered; quality, camera and equipment acceptance open | Alarm review/recovery, trends, chart controls, localization, touch entry and generic UDT faceplates are available. Per-route and per-binding quality and the PLC-bound browser/camera control are available. Select equipment faceplates and review workflows on the target display. | [M5](https://github.com/votecoffee/OpenHMI/milestone/6), [#13](https://github.com/votecoffee/OpenHMI/issues/13), [#14](https://github.com/votecoffee/OpenHMI/issues/14), [#4](https://github.com/votecoffee/OpenHMI/issues/4) |
| M6 — Packaged pilot release | Portable Windows preview delivered; resilience and pilot acceptance open | Complete fault isolation and recovery checks, clean installation, identity and target-station acceptance. Endurance testing is deferred. | [M6](https://github.com/votecoffee/OpenHMI/milestone/7), [#15](https://github.com/votecoffee/OpenHMI/issues/15), [#9](https://github.com/votecoffee/OpenHMI/issues/9), [#10](https://github.com/votecoffee/OpenHMI/issues/10), [#11](https://github.com/votecoffee/OpenHMI/issues/11) |
| M7 — Python IDE and deliberate reload | Deferred by owner | Integrated Python editing, event templates, autocomplete, diagnostics and a defined reload lifecycle. | [M7](https://github.com/votecoffee/OpenHMI/milestone/8), [#2](https://github.com/votecoffee/OpenHMI/issues/2) |

M0 is a source/test checkpoint, not a production release. GitHub issues are the
task/status record; this document defines scope, sequencing and acceptance gates.
Milestone numbers are sequence labels, not promised release dates.

## M0 baseline already available

* Shared designer/runtime controls, autosaved drafts, explicit live apply and
  optimistic revision checks.
* Multiple screens/popups, per-screen update rates, conditional visibility/
  enablement/color, no-code tag/navigation actions and UDT faceplate definitions.
* pycomm3 adapter, tag browsing/aliases/scaling, grouped acquisition, quality,
  timestamps, reconnect handling and write readback.
* SQL alarms, recipes/reviews/images, history/trends and CSV export.
* Local/Windows identity integration into HMI groups, with server-side permissions.
* Project create/open and checksummed complete database backups; imported PLC
  connections are held and imported Python is never executed automatically.

## M1 deliverables and acceptance

The operator journal must identify the server-authenticated user/provider, the
active control/action/tag and the request's operation ID. Record last cached
before value/quality/time and requested values without recording credentials.
Persist an attempt before dispatch and record dispatch before side effects.
Distinguish denied/rejected requests, confirmed outcomes and uncertain outcomes.
A crash or lost acknowledgement must never cause automatic command replay.

Journal storage failure before dispatch prevents the command. Failure to finalize
the journal after an executed command must not imply that the command was not
executed. Keep the durable pending/uncertain record and expose the operation ID.
Provide permission-protected filtering, pagination and export, documented retention,
and backup/restore coverage. Existing recipe/security histories remain intact.

Diagnostics must show connection state/error, effective scan groups, counters,
hold/disabled status, and tag source/type/quality/acquisition age. Export is bounded
and contains no credentials. Counters remain labeled as pycomm3 calls/requested
addresses, not wire-packet measurements. Diagnostic viewing performs no PLC writes.

Exit evidence: unit/API tests for permissions, interlocks/limits, success,
readback/callback failure, journal I/O failure, restart and retention; browser
checks for protected journal/diagnostic workflows; complete backup restore check.

## M2 and M3 acceptance boundaries

The [runtime readiness roadmap](runtime-readiness-roadmap.md) defines the
driver hardening, supported tag matrix, and scan/load measurements. Run
isolated software faults and multi-controller benchmarks before recording
the live bench results.

M2 starts with an identified non-production PLC, route and read-only tags. Record
controller/firmware, pycomm3/runtime versions, representative tag/UDT/indexed-array
coverage and requested-versus-observed acquisition behavior. Check communication
loss/recovery and measured controller load before controlled writes. M1 provides
traceability for write tests. Do not choose a live machine or test tags implicitly.
Use the [read-only bench procedure and diagnostics comparison](plc-bench-acceptance.md)
to prepare and record the M2 evidence.

M3 [command software contracts](command-transactions.md) are implemented against
a deterministic simulator while bench access is pending. Designer contracts,
no-code bindings, persistent lifecycle records and restart/timeout handling are
available. [Recipe staging/transfer and running-copy verification](recipe-transfers.md)
are also delivered offline; hardware acceptance remains open. The
configurable contract defines request/sequence/acknowledgement/result/timeout and
reset ownership; the selected PLC implementation must be agreed at commissioning.
Keep requested, accepted and completed states distinct; handle lost acknowledgements
and restart without replay. Hardware completion requires
the corresponding M2 evidence and agreed test tags.

For recipes, stage parameters and associate revision/hash/production BOOL with one
transfer. Verify the resulting PLC copy and report partial/uncertain transfers.
Library editing, approval and withdrawal do not mutate the PLC's running copy.
The PLC retains authority over testing, rejection, inhibit and production behavior.

## M4–M6 delivery and acceptance

M4 [project recovery](project-recovery.md) delivers persisted applied revisions,
visible comparison and deliberate rollback into a new revision. Preserve current tag/driver ownership and retain stale-editor
protection. Add migration checks and restore drills without overwriting originals
or replaying commands. Screen rollback does not roll back PLC memory.

M5 adds [operator data quality and the PLC-bound camera control](runtime-readiness-roadmap.md#m5--operator-quality-and-camera-control).
The browser/camera control is available. When a camera is in pilot scope,
validate the approved camera on the operator station.

M5 delivers [alarm operator workflows](alarm-workflows.md) with filtered review,
first-user acknowledgement, guidance, notes, event export and timed shelving. It still selects
equipment faceplates with the owner, then validates normal/abnormal/
disconnected presentation, permissive/interlock explanations and alarm workflows.
Review font coverage, translation expansion, keyboard focus and touch targets on
the actual operator display. Generic UDT capability is already available; no
motor/valve/pump layout is preselected by this plan.

M6 supplies a [portable Windows preview](windows-package.md) with bundled Python,
dependencies/assets, library ownership locking, rotating logs and a bundled
administrator setup command. The [package manager](package-management.md) verifies archive/file hashes, installs
versions side by side and changes the active selection without changing project
data. Update/removal preserve externally stored projects.
The local software drill covers startup, forced restart and backup/restore with
Python/Node absent from PATH. Clean-machine and service lifecycle acceptance remain
open. Verify a clean supported Windows installation, process/service lifecycle,
project restore and preservation of data/security. Test actual local/Windows
credentials and intended group membership in the target environment. Automatic
browser SSO is optional future scope, not a pilot prerequisite.

The [resilience gate](runtime-readiness-roadmap.md#m6--resilience-and-pilot-gate)
covers background worker isolation, bounded shutdown and restart, and focused
fault and recovery checks before the target-station trial. Revisit endurance
testing at a later maturity checkpoint.

The [pilot acceptance matrix](pilot-acceptance.md) covers operation, permissions, commands/recipes,
alarms/history, live engineering, language/display behavior and recovery. Record
results, limitations and owner acceptance. Passing software tests alone does not
close a bench, domain or pilot acceptance gate.

## Pilot execution order

The pilot should prove that an automation developer can build and change a
useful HMI live with drag-and-drop controls and no Python code for routine work.
Trusted Python remains available for custom behavior. The next checkpoint is
one repeatable operator workflow on a fixed Windows package and project backup.

1. **Prepare the candidate.** Record the source commit, Windows package hash
   and reference project backup hash. On a disposable copy, rehearse placing
   and binding controls, applying a change to an open viewer, restoring a
   backup and recovering from a focused runtime restart. The walkthrough
   should include an alarm with recovery steps, a trend and a protected edit.
2. **Run the M2 read-only bench.** Agree the controller, firmware, route,
   tag list and scan/load limits. Measure mixed screen rates and shared reads,
   one bad binding while healthy tags continue, and approved communication
   loss and recovery. Record source timestamps, controller load and the
   agreed limits. Use results to decide which driver changes are needed.
3. **Check the target station and PLC contracts.** Review the reference
   workflow with an operator on the intended display and accounts. Cover
   dense layout, touch entry, alarms, trends and language switching. On
   separately approved M3 test channels, verify command completion and
   recipe staging, production status and PLC-copy readback. Include the camera
   and selected equipment faceplates when they are part of the trial.
4. **Complete the M6 pilot.** Record the clean Windows install, approved
   identity mappings, backup/restore, restart, PLC recovery and unresolved
   operations in the pilot matrix. Close gates with recorded observations and
   owner sign-off.

Candidate packaging and local rehearsal can start while the owner identifies
the bench and target Windows station. Hardware fault drills and write tests
require an agreed boundary. Prioritize failed acceptance checks and
reproducible reliability defects until the pilot. Rank additional Diagnostics
features, equipment templates and driver tuning using pilot evidence. The
integrated Python IDE and endurance testing stay deferred.

No calendar dates, controller access or named human assignments are assumed.
Use small verified commits and frequent pushes to `main`; keep the README and
GitHub issues/milestones current. Run local checks proportionate to each change;
no automatically triggered GitHub Actions jobs are introduced.

## Incremental maintainability work

Keep this work alongside the offline pilot and palette effort. Refactoring does
not close hardware or operator acceptance gates.

1. Delivered the first display-family extraction, dedicated history router,
   separate pycomm3 transport, pure tag-value rules and timing statistics.
   Added automated Pydantic/browser palette and project-serialization contract
   tests to normal unittest discovery.
2. Delivered remaining renderer separation by family, including buttons,
   alarms, process graphics, motion images, screen composition and faceplates.
   `createConfig` now assembles imported renderers and uses a fresh shared
   palette-field factory. Input, image, process/chart, machine/action and readout
   definitions now have focused family factories with complete/unique coverage
   checks and stable designer order.
3. Delivered acquisition/subscription and operator write/action routers, with
   existing permission, revision, lock and journal behavior retained. Browser
   request helpers and UDT faceplate expansion now have compatibility checks.
   Project lifecycle and alarm acknowledgement routes are now extracted too,
   preserving project-instance guards, apply validation, lock order and durable
   activity ordering. Their browser helpers have payload compatibility checks.
   The engineering catalog now has its own router, and a shared validator
   factory serves draft/save/stage/merge/apply validation. Real catalog-to-picker
   integration tests cover tag-type filtering and rejected-draft preservation.
   Binding rules are now split into project-level, shared/edit, display/state
   and chart groups. The coordinator preserves project-first and per-control
   failure order, with API regression checks for rejected-draft preservation.
4. Delivered separate viewer-subscription/demand and sample-cache components,
   retaining the existing locks and live dictionary compatibility. Fake-PLC
   comparisons cover demand changes, reconnect, bad tags and write/readback.
5. Delivered separate physical scheduling and receipt-publication components.
   Shared reads, long per-tag retry and project-generation fences retain their
   original atomic lock boundaries. Regression checks cover legacy deadline-map
   access and changing requested UDT members during an in-flight scan.
6. Delivered pure logical write preflight, inverse-scaling and readback rules,
   with failed-write invalidation delegated to the scheduler/sample cache.
   Driver/transport lock boundaries and single-attempt write/readback ordering
   remain intact. Tests cover member/root aliases, sibling names, identical
   addresses on another route and polling-owned display updates after a write.
7. Delivered tag-catalog reconciliation and route-status projection modules.
   The driver retains project copying/identity, connection replacement and lock
   ownership. Local edits survive unchanged applies, changed routes invalidate
   their own samples, and retired connections close outside the state lock.
   Tests cover held acquisition, catalog compatibility and diagnostic isolation.
8. Delivered the remaining service-embedded command-history, trend-recording,
   canvas-image and identity-publication registrars in focused router modules.
   Shared request contracts and legacy registrar/model exports preserve callers.
   Production browser capture/station helpers and binary image uploads have
   Pydantic/transport compatibility coverage. Authorization, limits, error mapping
   and service transactions retain their existing boundaries.

9. Delivered canonical project/control schemas and defaults in `project_models.py`,
   separate from the SQLite revision store. Model-only consumers import schemas
   directly, while explicit legacy exports preserve model identity. Migration,
   save/apply/stage/merge, integrity checks and transaction boundaries stay in
   `projects.py`. Tests cover persistence-free schema import/validation and
   canonical requests passing through the existing revision store.

10. Delivered backend control-schema families for inputs, images, process/charts,
    machine/actions and readouts, with shared strict/state/numeric/range bases.
    The canonical union, class definitions, validators and legacy exports retain
    their original contracts. Tests cover independent family imports, ownership
    and canonical/legacy class identity, alongside the full palette contract.

11. Delivered independent canvas-layout and identity-publication configuration
    models, retaining legacy service exports and unchanged class definitions.
    Schema validation no longer imports either service, their HTTP registrars,
    FastAPI/Starlette or Pillow. Expanded checks cover domain model identity and
    complete project round trips with containers, locked backgrounds and
    privilege-bit mappings.

12. Delivered a [control-extension workflow](extending-controls.md) and bounded
    [contract audit](contract-coverage.md). Command buttons and transaction console
    share production query builders. New browser-to-router checks cover all UI
    history states, Unicode filters, pagination bounds, precise string-form IDs,
    JSON export and invalid requests rejected before service calls.

13. Delivered image-library search/pagination query contracts and response checks.
    The production helper is checked against the real registrar; actual SQLite
    pages are checked by the browser validator. Invalid paging metadata retains
    the last readable page with an error; access denial clears it. Browser
    regressions cover paging, malformed response, retry and denial/recovery.

14. Delivered historian/trend query contracts for sparklines, live/captured windows,
    recorded tags and bounded/complete CSV. Tests cover epoch zero/fractional ends,
    tag/window bounds, project fences, CSV quoting and complete-export slot cleanup.
    Recorded-tag replies are validated before entering the editor, with real SQL
    page and malformed-response recovery coverage.

15. Delivered command transaction/history response parity with real SQL detail,
    filtered/cursor pages, JSON exports and restart reconciliation across all eight
    states. Browser validators reject invalid sequences and incoherent paging
    metadata while preserving nullable results/errors and empty event histories.
    Browser regressions cover blocked requests/navigation and valid-reply recovery.
    These are offline fixtures and do not establish controller execution.

16. Delivered shared history/capture response validators in focused API modules
    and SQL-to-browser contracts for history quality/context/truncation and capture
    lifecycle/rollover/restart. Out-of-order per-tag samples, duplicate capture IDs
    and impossible retention counts are rejected with readable-data retention and
    browser recovery coverage. Equal epochs and optional legacy fields remain
    compatible. Acquisition/PLC acceptance stays separate.

17. Delivered focused activity/diagnostics response validators and real SQL/runtime
    response parity, covering journal outcomes, restart reconciliation, filtered
    pages, route holds, worker health and value-free diagnostics exports. Invalid
    IDs/order/cursors, duplicate rows and malformed scan ages are rejected before
    replacing readable data. Browser regressions verify paging lockout, denial
    clearing and valid-reply recovery. Controller/station acceptance stays open.

18. Delivered activity/diagnostics query builders and read helpers in focused API
    modules. Actual generated requests bind through the registrar with Unicode
    filters, UTC dates, precise string-form cursors, bounds/defaults and project
    headers. Export checks preserve scope, CSV quoting/formula escaping, value-free
    diagnostics and authorization before reads. UI polling and recovery stay intact.

19. Delivered read-only diagnostics snapshot/filter/projection in `diagnostics.py`,
    independent of HTTP registration. Permissions, query bounds and download
    metadata stay in the router. Snapshot lock/time ownership and worker snapshot
    ordering remain intact. Tests cover catalog replacement at lock release, route
    fault precedence, paging/filtering and value-free metadata.

20. Delivered focused command/activity/diagnostics console modules. The app uses
    direct imports; `operations.jsx` retains the same component exports and
    identities. View bodies, hooks, permissions, query helpers and retained-data
    recovery remain unchanged. Existing command and operations browser workflows
    validate the moved components without changing saved schemas or API contracts.

21. Delivered focused identity-session validation, URL and validated read helper.
    Real SQL service/session responses pass the production browser guard across
    local sign-in/out, expiry, permission changes and mock-Windows mappings/disable.
    Contracts cover public fields, malformed payloads and HTTP errors. App generation
    fences and last-confirmed identity handling remain intact; Windows/domain
    acceptance is separate.

22. Delivered selected-recipe validation and polling path in a focused module.
    Real SQL/HTTP contracts cover typed values, safe integer boundaries, images,
    approval metadata, independent loaded copies, later source changes and clear/
    reopen results. Guard rules and app failure handling remain unchanged.
    Publication is stubbed; PLC recipe transfer acceptance stays separate.

23. Delivered shared live alarm snapshot validation and polling URL in the alarm
    API module, preserving legacy defaults and display-field rules. Real SQL/HTTP
    contracts cover priorities, acknowledgement, shelving/restoration, bad trigger
    quality, stale evaluation, retirement/reopen and malformed consumed fields.
    Snapshot reads do not acquire source data. Detailed history and controller
    acceptance remain separate.

24. Delivered shared applied-project validation and polling URL in the project
    API module, preserving guard rules and canonical control-kind ownership.
    A shared real-palette fixture drives Pydantic/SQLite/HTTP compatibility checks
    across all control kinds, screens, faceplates, containers, groups and locked
    backgrounds. Unapplied drafts preserve the active response. Legacy defaults
    and malformed consumed fields are covered; runtime bindings/assets and
    controller/station acceptance stay separate.

25. Delivered tag-status validation/default normalization and polling URLs in the
    runtime API module. Real acquisition/FakePLC cache contracts cover held/pending
    states, partial tag faults, stale recovery, disabled routes and status-only
    metadata. GET cannot poll/subscribe; status-only reads cannot copy samples.
    Per-tag quality handling, legacy defaults and app polling ownership remain
    intact. All five live app snapshot validation boundaries now have focused
    modules; controller acceptance remains separate.

26. Delivered alarm-console read-query builders, CSV links and shared UI filter
    lists in the alarm API module. Generated URLs bind through SQL-backed routes
    with Unicode/UTC/cursor/default/bound checks, metadata-only detail reads and
    CSV quoting/formula escaping. History/export scope, note POST paths and UI
    polling/recovery remain unchanged. Detailed response DTO parity is next.

27. Delivered DOM-free detailed alarm response validators with a compatible
    message-helper export. Real SQL/HTTP contracts cover occurrence/event/note
    pages, shelved/acknowledged alarms, cached trigger details and legacy nullable
    metadata. Paging rejects duplicate/reversed IDs, wrong cursors and oversized
    pages. Browser regressions preserve readable results, disable older navigation
    and recover on valid replies; row/detail rules remain compatible.

28. Delivered shared alarm note/shelve/restore request helpers. Secured SQL-backed
    contracts bind actual browser payloads through strict models, authorization,
    server attribution and journal dispatch guards. Invalid/denied requests do not
    mutate state; stale restore conflicts preserve the current shelf. Duration
    conversion, receipt/error propagation, UI feedback and non-replay behavior
    remain intact. Fixtures are offline; no controller acceptance is claimed.

29. Delivered shelving-list URL and DOM-free response validation boundaries.
    SQL-backed contracts cover encoding, bounds, ascending unique pages, cursors
    and legacy row metadata. Cursor/restore routes now accept the project model's
    full 100-character alarm IDs, fixing a 60-character mismatch. Browser faults
    retain readable data, block restore/paging and recover on valid replies;
    authorization failures still clear inaccessible data. No PLC access required.

30. Delivered recipe create/revise/transition/select helpers and content
    normalization in a focused API module. Actual browser requests pass strict
    models and SQL-backed lifecycle checks, covering all review actions, same-user
    approval, independent loaded copies, stale versions and denials. Numeric
    conversion, blank-value errors, explicit clear fields, UI workflow ownership
    and existing audit behavior remain intact. Identity/publication hooks are
    stubbed in contracts; local authentication is covered by domain/browser tests.

31. Delivered shared recipe policy and raw image-upload helpers. Strict models
    and SQL-backed contracts cover versions/defaults, Boolean permit fixtures,
    reason encoding, raw bytes/MIME type, PNG/JPEG normalization, upload bounds
    and permission/gate denials. Browser coverage includes stale policy feedback
    and refresh recovery. Workspace state/input/feedback ownership and existing
    audit semantics remain intact; fixture permit reads are synthetic.

32. Delivered a focused recipe-local session component and authentication
    request helpers. Real auth/SQL security contracts cover strict requests,
    cookie rotation/expiry/sign-out, origin rejection, HMI-account delegation and
    live group permission changes. Browser tests cover bad credentials, logout
    failure/recovery and HMI permission delegation. Form state, password clearing,
    callbacks and workspace refresh ownership remain intact. Windows/domain
    acceptance and stricter session response filtering remain separate.

33. Delivered recipe transfer query/dispatch/export helpers. SQL-backed
    simulator-only contracts cover separate history/status queries, encoding,
    precise cursors, bounds, strict request models, stale guards before staging,
    unauthenticated requests, durable receipts and JSON export parity. Panel
    polling, selection/project revision fences, permissions, retained-history
    identity and non-replay behavior remain intact. Transport creation is
    forbidden in the contract fixture; controller acceptance remains separate.

34. Delivered DOM-free recipe transfer record/page guards and SQL response
    contracts. Consumed fields, safe/matching IDs, command records and bounded
    descending paging are checked; optional history metadata remains compatible.
    Fixtures model all eight states and retained history after target retirement,
    while renamed signatures clear current verification. Malformed replies retain
    readable data and block dispatch/paging; authentication denial clears rows.
    Browser regressions cover failure/recovery. No controller outcome is inferred
    from seeded states; hash/integrity checks remain server-owned.

35. Delivered correlated transfer dispatch receipt validation and error
    feedback. Target/revision, transaction/sequence/envelope and operation IDs
    must agree before confirmation. Optional legacy headers and pending audit
    finalization remain compatible. Invalid/ambiguous replies retain operation
    hints, clear stale receipt links and refresh status without replay. Operation
    headers survive API success-body parse/attachment failures. Simulator
    HTTP success/pending/uncertain tests and a corrupted-reply browser regression
    preserve the distinction between dispatch and verified PLC completion.

36. Delivered focused recipe library validation/read ownership. SQL/HTTP
    contracts cover six revision states, typed parameters, policy/gates, audit
    changes, legacy optional metadata and unavailable permits. Failed refreshes
    retain readable state and unsaved edits while blocking writes; initial load
    can be retried. Recovery preserves dirty content and restores actions. Browser
    faults verify no write or page error. Live selected-copy and raw permit
    metadata remain independent; hash/write rules stay server-owned.

37. Delivered recipe session/sign-in/sign-out response validation. Local and
    HMI identity shapes, expiry/logout, mock-Windows mappings, empty/future roles
    and legacy metadata are covered. Malformed replies retain confirmed identity;
    refresh reconciles actual cookie state without replay. Read faults block
    workspace writes, while confirmed updates clear stale errors/passwords. Browser
    regressions cover corrupted auth confirmations and session recovery. Earlier
    checkpoint notes are preserved in [history](maintainability-checkpoints.md)
    so the GitHub issue can retain its acceptance criteria within the body limit.

38. Delivered focused recipe display and parameter-editor components. The
    workspace retains orchestration; legacy picture/loaded/selected exports alias
    the same functions, and the palette imports the selected renderer directly.
    Moved bodies and saved schemas remain unchanged. Export identity, palette/
    project contracts and expanded browser coverage preserve typed parameters,
    image previews, loaded copies and runtime behavior.

39. Delivered a focused recipe authentication HTTP registrar and shared
    user authorizer. The combined registrar retains service ownership and public
    request models, preserving qualified OpenAPI references and imports. Complete
    OpenAPI parity, standalone HTTPS cookies/origin/rate-limit behavior, HMI
    delegation, logout semantics and focused import isolation are verified.
    Recipe/domain/driver responsibilities and existing permissions remain intact.

40. Delivered a focused recipe image HTTP registrar. The combined registrar
    retains its service, authorizer and error translator; normalization/storage/
    policy/audit behavior remains unchanged. Handler and complete OpenAPI parity,
    standalone header/byte/reason/identity checks, role/MIME/query guards, exact
    upload limits and early stream termination are verified. Focused imports do
    not load Pillow, recipe services or the server.

41. Delivered a focused recipe transfer HTTP registrar for history, detail/export
    and dispatch. The combined registrar retains service ownership; canonical
    request models, handler bodies, route order and complete OpenAPI are unchanged.
    Standalone HTTP tests use an in-memory journal to verify query/role/export
    boundaries, recipe-local/HMI attribution, conditional security checks and
    journal-before-dispatch ordering. Invalid requests, denied identity and an
    unavailable journal do not dispatch. Existing domain, SQL and browser contracts
    continue to protect transfer behavior without controller access.

42. Delivered focused recipe library HTTP adapters for public snapshots and
    protected revision, selection, policy and simulator-permit changes. Assembly
    retains service construction, shared authorization/error translation and
    legacy model imports. Read and mutation registrars preserve route order;
    canonical models and complete OpenAPI are unchanged. Standalone HTTP checks
    cover all six typed mutations, identity/identifier forwarding, validation
    before authorization, denied identity and error propagation. SQL policy,
    self-approval, loaded-copy and transfer semantics remain in their services.

43. Delivered shared project-instance guards and HTTP response context for the
    runtime and workspace. Stale mutation rejections and caught workspace HTTP
    errors now include the request project identity. Existing guard precedence,
    read/headerless compatibility and workspace switch identity remain intact.
    SQL-backed journal outcomes pass through the actual JavaScript API with their
    receipt metadata; browser identity stays pinned and writes are not replayed.
    Complete OpenAPI is unchanged. This scope does not add a generic unhandled
    exception response policy or change lifecycle ownership.

44. Delivered focused runtime lifecycle ownership across assembly, startup and
    shutdown. Constructed resources close after configuration, handler, service,
    route or asset setup failures. Initial-sample and worker-entry/exit failures
    also run cleanup; cleanup errors are logged independently and do not replace
    the original failure. Assembly/initial-sample cleanup skips identity publication.
    Normal shutdown retains worker-drain then trends/identity/acquisition/store
    order. Worker scheduling and transport remain separate; public factory,
    models, route order and complete OpenAPI are preserved.

45. Delivered PLC shutdown fault isolation. Client-close errors are logged with
    route identity while transport detaches the client; a route-close exception
    does not skip later route attempts. Scan draining still precedes every route
    close, new scans/late sample publication remain blocked during shutdown, and
    scan/cache/schedule state is cleared. Bounded fake-PLC tests cover multiple
    failures, repeated close, lock ownership, active-read draining and explicit
    reopen, with no writes. No automatic reconnect or close retry was added;
    physical socket release after a vendor exception remains unproven.

46. Delivered partial worker startup and cancellation cleanup. Task creation is
    inside the drain scope; rejected coroutines close and already-created tasks
    finish before owned resources close. Unexpected task failures are collected
    and logged while peers drain. Executor joining runs off the event loop, even
    if a scheduler is cancelled while its synchronous callback remains active.
    Repeated caller cancellation cannot detach initial sampling, worker draining
    or resource cleanup; cancellation propagates afterward. Bounded event/SQL
    checks preserve ordering, startup errors and pre-worker identity behavior.
    Public models, routes and complete OpenAPI remain unchanged.

47. Delivered workspace handoff failure and cancellation handling. Candidate
    startup failures return sanitized 503 guidance and keep the current runtime.
    Cancellation before commit drains the candidate; cancellation after commit
    drains the old runtime and retains ownership of the new one. Post-switch
    retirement errors explicitly report that the new project is already open,
    without rollback/replay. The request lock remains held through cleanup;
    original project headers and stale-write guards are preserved. Workspace
    lifespan finally closes its current runtime after cancellation or failed
    startup notification. Synthetic SQL/event tests cover competing reads and
    store closure with held PLC routes. Complete OpenAPI is unchanged.

48. Delivered workspace background-job cancellation safety. Create/import/export
    threads finish before a cancelled request releases the workspace lock; queued
    switches and shutdown cannot close their source runtime early. Repeated
    cancellation is propagated after completion. Job failures during cancellation
    are logged without hiding cancellation; ordinary HTTP errors retain their
    status/detail and project identity. Incomplete upload cancellation never
    starts import. SQL/ZIP/event tests verify completed files, imported hold,
    export source consistency, store-close ordering and no replay. Completed
    files are not rolled back by cancellation. Complete OpenAPI is unchanged.

49. Delivered focused project file publication. Create initializes a closed,
    staged database; import stages all companions and publishes its completed
    database last, without replacing existing files. Orphan support and SQLite
    recovery files block name reuse. Failed attempts roll back only unchanged
    artifacts they own; changed/unremovable files and companions beside any
    visible database remain for review, preserving imported holds and uncertain
    completed records. Filesystem errors return sanitized 503 guidance. Synthetic
    SQL/ZIP fault checks cover initialization, short writes, publication/rollback
    failure, destination races and uncertain completion. Complete OpenAPI is
    unchanged; process-crash/power-loss durability is not claimed.

50. Delivered protected read-only project file inventory and an engineering panel.
    Known support/recovery files show their associated database, entry type and
    nullable size from metadata only; contents and link targets are not read.
    Query/page Pydantic models and production JS guards share real HTTP metadata
    contracts, including Unicode ordering and bounded cursors. Directory scans
    stop at 10,000 entries, pages at 100, and incomplete scans are explicit.
    The panel preserves confirmed results on bad replies, clears denied data and
    recovers by refresh without file actions or operation replay. Normal SQLite
    recovery files are not labeled corrupt. Existing FastAPI OpenAPI is unchanged;
    the manual workspace route is covered directly by schema/HTTP/browser checks.

51. Delivered main project-library response contracts. Canonical Pydantic and
    production JS guards validate unique/current listings and request-correlated
    create/import/open acknowledgements, preserving legacy/Unicode active names.
    Bad listings retain confirmed data/drafts and disable operations; denied data
    clears. Ambiguous operation replies require refresh and never replay. Field
    reset/open navigation require confirmation, and success messages survive
    listing refresh. Import now uses an explicit button and keeps the selected
    backup until confirmation. SQL/HTTP/JS and browser faults cover these paths;
    existing wire fields and FastAPI OpenAPI remain unchanged.

52. Delivered complete-backup download contracts and failure feedback. A focused
    binary helper shares pinned project identity, bounds response reads and checks
    headers/ZIP structure before starting a save. Stale supplied identities are
    rejected before export; permission/export errors are private and sanitized.
    Final ZIP bytes also respect the size limit. Drafts survive failures, denial
    clears protected data, and recovery requires explicit action with no replay.
    SQL/HTTP/JS tests verify real manifests/bytes and bad-response/overflow paths;
    headless browser faults verify no save on failure and exact bytes on recovery.
    Browser checks do not replace full import checksum/SQL validation or confirm
    that a prepared download was saved. FastAPI OpenAPI remains unchanged.

53. Delivered backup-transfer lock ownership. Fully prepared backup GET responses,
    including handled errors, send outside the workspace lock with frozen bytes
    and source identity. Slow headers/body no longer block reads, project switches
    or runtime shutdown. Archive preparation and cancellation cleanup retain the
    lock until source work finishes. Real SQL/ZIP and event-gated ASGI tests verify
    reads/switch/shutdown during sends, source closure ordering, exact bytes and
    identity after switching, and cancellation/disconnect without export replay.
    Existing API/OpenAPI contracts remain unchanged. Web-server process exit timing
    and network throughput remain outside this offline verification.

54. Delivered bounded import-upload orchestration in a focused module. Upload
    receipt leaves the runtime lock, with one active import slot, a 256 MiB cap
    and a 30-second receive deadline. Admission and dispatch check permission;
    captured identity prevents even headerless uploads from crossing a switch.
    Shutdown rejects dispatch before accessing a closed store. Timeout, disconnect,
    overflow, denial and cancellation never start import and release the slot;
    dispatched threads retain lock/slot ownership through cancellation cleanup.
    Private replies send outside the lock. Browser imports have a two-minute
    overall deadline and retain selected files on timeout/busy feedback for an
    explicit retry. SQL/HTTP/JS and browser contracts cover these paths. Existing
    payload/OpenAPI fields, immutable publication and imported PLC holds remain.

55. Delivered create/open ingress in a focused mutation module. Bodies receive
    outside the runtime lock with a streaming 4 KiB cap, 30-second deadline and
    four pending admission slots. Denied/stale/busy requests do not read bodies.
    Dispatch rechecks shutdown, captured identity and permission; malformed JSON,
    excessive nesting, overflow, timeout, disconnect and cancellation never start
    an operation. Create thread cleanup and open handoff stay serialized. Completed
    private acknowledgements send outside the lock with source identity. SQL/HTTP/
    JS and browser tests cover exact limits, retained drafts, explicit recovery,
    slot reuse, switch/session/shutdown rejection and slow response delivery.
    Initial identity gating also prevents early draft edits from being erased by
    sign-in hydration; a delayed-identity browser test covers it. Model re-exports,
    payload/OpenAPI fields and mutation non-replay remain intact.

56. Delivered immutable project-library and file-inventory response delivery
    outside the workspace lock. Preparation, permission checks, serialization and
    source identity stay protected; success/handled errors are private/no-store.
    Slow headers/body allow reads, switching and runtime shutdown without changing
    prepared bytes or context. Scan cancellation drains owned work before a queued
    switch can close its source; send cancellation/disconnect never repeats work or
    retires a runtime. SQL/HTTP/Pydantic/JS contracts verify these boundaries plus
    denial/error privacy. Existing query/paging, payload and OpenAPI fields remain.

57. Delivered prepared tag/quality readout delivery. Full/status-only `/api/tags`
    responses pass through their existing route, FastAPI serializer and middleware
    under the workspace lock, then send immutable bytes/headers outside it. Slow
    viewers allow subscription renewal, reads, switching and runtime shutdown.
    Cancelled preparation drains synchronous projection and middleware before
    source closure; send failures never replay it. Mixed per-tag qualities, source
    identity, status-only omission and query errors remain intact. Unexpected
    preparation failures return sanitized private 503 feedback and can recover.
    Real SQL/HTTP/ASGI and production JS contracts cover these boundaries. No PLC
    polling/subscription is added, and payload/OpenAPI fields remain unchanged.

58. Delivered prepared applied-screen snapshot delivery. `/api/project/active`
    finishes its normal store projection, serializer and middleware under the
    workspace lock, then sends immutable data outside it. Revision/layout and
    body/header project identity stay paired through newer local apply, switching
    and shutdown. Existing revision/instance guards reject stale dispatch. Cancelled
    SQL preparation drains before source closure; send failures never repeat work.
    Unexpected projection failures are sanitized/recoverable, and stopped workspaces
    reject closed-store access. SQL/HTTP/ASGI, canonical Project and production JS
    contracts cover these paths; payload/OpenAPI fields remain unchanged.

59. Delivered prepared alarm snapshot delivery through the explicit finite-read
    allowlist. Monitor projection, serializer and middleware stay protected; finished
    responses send outside the runtime lock, permitting acknowledgements, reads,
    switching and shutdown. Occurrence identity, quality/staleness and recovery
    information stay frozen. Existing acknowledgement permission/audit/instance
    boundaries remain; overlapping IDs cannot dispatch into a different project.
    Cancelled projection drains before source closure; failed sends never repeat
    it or create journal operations. Sanitized read failures recover and stopped
    runtimes reject monitor access. SQL/HTTP/ASGI and production JS contracts verify
    these paths; payload/OpenAPI fields remain unchanged.

60. Delivered opt-in browser project-identity checks for main runtime polls,
    identity refresh and initial catalogue loading. Matching source headers are
    required before data adoption; missing/malformed/foreign replies use existing
    unavailable states without repinning or replay. Applied-project change replies
    require paired header/body identities, preserving runtime reload. Editors keep
    their old active metadata/layout and draft when a different project is detected.
    Real HTTP-to-production-JS and headless cases cover rejection/recovery, source
    pairing, initialization, real switch/reload and stale-write pinning. Existing
    same-project synthetic fixtures now provide realistic identity headers. Default
    API mutation/receipt behavior and server payload/OpenAPI fields remain intact.

The current control/router/driver/schema-store and live-snapshot separation baseline is delivered.
Recipe HTTP separation is complete for this scope. Next extend the source-identity
audit to independent alarm-console list/detail/history readers, preserving retained
filters/drafts, permission handling and acknowledgement non-replay while a project
switch is being detected. Preserve scan/resource draining
and transport ownership. Prioritize observable failure behavior and contract
coverage over further file splitting. Controller, operator-station and endurance
acceptance stay deferred.

Each increment must pass relevant regression tests and contract checks before
publication. See [module boundaries](architecture.md#module-boundaries-and-compatibility-checks).
