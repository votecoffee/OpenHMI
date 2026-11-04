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
| M2 — ControlLogix bench acceptance | Awaiting identified bench inputs | Measured reads, data types, scan/load and reconnect behavior; subsequently controlled write acceptance with evidence. | [M2](https://github.com/votecoffee/OpenHMI/milestone/3), [#3](https://github.com/votecoffee/OpenHMI/issues/3) |
| M3 — PLC transactions and recipe deployment | In progress; command software checkpoint delivered | Configurable sequence contracts and no-code command binding delivered offline; recipe transfer and hardware acceptance remain open. | [M3](https://github.com/votecoffee/OpenHMI/milestone/4), [#7](https://github.com/votecoffee/OpenHMI/issues/7), [#8](https://github.com/votecoffee/OpenHMI/issues/8) |
| M4 — Project revisions and recovery | Planned; parallel software track | Persisted project revision history, useful diff/rollback, conflict recovery and migration/restore checks. | [M4](https://github.com/votecoffee/OpenHMI/milestone/5), [#1](https://github.com/votecoffee/OpenHMI/issues/1) |
| M5 — Operator workflows and equipment library | Planned; equipment selection remains open | Agreed equipment faceplates, richer alarm workflows and target-display/operator review. | [M5](https://github.com/votecoffee/OpenHMI/milestone/6), [#4](https://github.com/votecoffee/OpenHMI/issues/4) |
| M6 — Packaged pilot release | Planned | Clean-machine installation, local/Windows identity acceptance and documented pilot/recovery results. | [M6](https://github.com/votecoffee/OpenHMI/milestone/7), [#9](https://github.com/votecoffee/OpenHMI/issues/9), [#10](https://github.com/votecoffee/OpenHMI/issues/10), [#11](https://github.com/votecoffee/OpenHMI/issues/11) |
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

M2 starts with an identified non-production PLC, route and read-only tags. Record
controller/firmware, pycomm3/runtime versions, representative tag/UDT/indexed-array
coverage and requested-versus-observed acquisition behavior. Check communication
loss/recovery and measured controller load before controlled writes. M1 provides
traceability for write tests. Do not choose a live machine or test tags implicitly.

M3 [command software contracts](command-transactions.md) are implemented against
a deterministic simulator while bench access is pending. Designer contracts,
no-code bindings, persistent lifecycle records and restart/timeout handling are
available; hardware acceptance and recipe staging/transfer remain open. The
configurable contract defines request/sequence/acknowledgement/result/timeout and
reset ownership; the selected PLC implementation must be agreed at commissioning. Keep requested, accepted and completed states distinct; handle
lost acknowledgements and restart without replay. Hardware completion requires
the corresponding M2 evidence and agreed test tags.

For recipes, stage parameters and associate revision/hash/production BOOL with one
transfer. Verify the resulting PLC copy and report partial/uncertain transfers.
Library editing, approval and withdrawal do not mutate the PLC's running copy.
The PLC retains authority over testing, rejection, inhibit and production behavior.

## M4–M6 delivery and acceptance

M4 supplies persisted applied revisions, visible comparison and deliberate rollback
into a new revision. Preserve current tag/driver ownership and retain stale-editor
protection. Add migration checks and restore drills without overwriting originals
or replaying commands. Screen rollback does not roll back PLC memory.

M5 selects equipment faceplates with the owner, then validates normal/abnormal/
disconnected presentation, permissive/interlock explanations and alarm workflows.
Review font coverage, translation expansion, keyboard focus and touch targets on
the actual operator display. Generic UDT capability is already available; no
motor/valve/pump layout is preselected by this plan.

M6 supplies an installation/update/run workflow that hides Node/npm and contributor
tooling. Verify a clean supported Windows installation, process/service lifecycle,
project restore and preservation of data/security. Test actual local/Windows
credentials and intended group membership in the target environment. Automatic
browser SSO is optional future scope, not a pilot prerequisite.

The pilot acceptance matrix covers operation, permissions, commands/recipes,
alarms/history, live engineering, language/display behavior and recovery. Record
results, limitations and owner acceptance. Passing software tests alone does not
close a bench, domain or pilot acceptance gate.

## Execution order and inputs

M1's operator journal and runtime diagnostics are delivered; see
[behavior and validation](activity-and-diagnostics.md). M2 read-only bench
preparation can proceed when hardware details are supplied. M3 command contracts
are delivered offline. Next develop recipe staging/transfer and M4 recovery
features; hardware-dependent parts of M3 wait for M2. M5 choices/review can proceed alongside those tracks.
M6 closes only after the relevant preceding acceptance gates. M7 stays deferred
and is not a dependency of the no-code/runtime milestones.

The owner will supply the bench controller/route/read-only tags, intended PLC
transaction/recipe structure, equipment choices, Windows/group environment and
pilot machine/display/acceptance owner when those milestones are ready. Software
implementation continues on work that does not require those inputs.

No calendar dates, controller access or named human assignments are assumed.
Use small verified commits and frequent pushes to `main`; keep the README and
GitHub issues/milestones current. Run local checks proportionate to each change;
no automatically triggered GitHub Actions jobs are introduced.
