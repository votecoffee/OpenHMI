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

The current control/router/driver/schema-store separation baseline is delivered.
Prioritize separating diagnostics projection from HTTP registration next. Keep further module extraction tied
to a concrete responsibility or compatibility gap.

Each increment must pass relevant regression tests and contract checks before
publication. See [module boundaries](architecture.md#module-boundaries-and-compatibility-checks).
