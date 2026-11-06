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
| M2 — ControlLogix driver readiness and bench acceptance | Driver hardening and bench acceptance open | Isolate routes, improve scheduling and quality propagation, and measure supported types, scan/load and reconnect. Start hardware acceptance with an identified read-only bench. | [M2](https://github.com/votecoffee/OpenHMI/milestone/3), [#12](https://github.com/votecoffee/OpenHMI/issues/12), [#3](https://github.com/votecoffee/OpenHMI/issues/3) |
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
The camera prototype can proceed with local fixtures while driver readiness
work is underway. Validate the approved camera on the operator station.

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

## Execution order and inputs

1. Start M2 route isolation and measurement. Define and test the M5 data
   quality contract alongside it.
2. Prototype the M5 browser/camera control with controlled fixtures in parallel.
   Continue operator workflow review and select equipment faceplates with the owner.
3. Complete the read-only M2 bench gate, then validate approved M3 command and
   recipe contracts on the nominated controller.
4. Run the M6 resilience qualification and complete the Windows station pilot
   after its relevant driver, PLC contract and operator gates.
5. Use pilot feedback to rank the post-pilot candidates. M7 stays deferred.

The owner will supply the bench controller/route/read-only tags, intended PLC
transaction/recipe structure, equipment choices, Windows/group environment and
pilot machine/display/acceptance owner when those milestones are ready. Software
implementation continues on work that does not require those inputs.

No calendar dates, controller access or named human assignments are assumed.
Use small verified commits and frequent pushes to `main`; keep the README and
GitHub issues/milestones current. Run local checks proportionate to each change;
no automatically triggered GitHub Actions jobs are introduced.
