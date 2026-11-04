# PLC command transactions

OpenHMI now has an offline-verified, configurable application handshake above
pycomm3. An action button can dispatch a **PLC command transaction** without
Python code. A request-tag write/readback establishes dispatch only. Equipment
acceptance and completion require PLC-owned feedback for that exact sequence.
Real controller/firmware, scan coherency and equipment logic acceptance remain M2/M3
bench work; this protocol is a proposed configurable contract, not existing PLC logic.

## Ownership and contract

Each command owns one writable, unscaled logical UDT root. Declare these members
as integers in the tag manager (use DINT members on the PLC):

| Default member | Owner | Meaning |
| --- | --- | --- |
| `RequestSequence` | HMI | Positive request identity; written once, never automatically retried |
| `AcceptedSequence` | PLC | PLC has accepted or processed this request identity |
| `CompletedSequence` | PLC | The associated result is final for this accepted request |
| `ResultCode` | PLC | 0 = success; any other signed DINT = application failure/rejection |
| optional `Permit` | PLC | Boolean dispatch permit; a convenience check, not a machine interlock |

Member names, permit, timeout, polling interval and required HMI groups are
configurable in the designer's **Commands** tab. Request/accepted/completed/result
members must be distinct. Sequence values are nonnegative signed DINTs; zero is
initial/idle. OpenHMI allocates the next positive sequence above both the live
channel's sequences and its durable SQL high water mark. It never wraps at DINT
exhaustion. Reusing another host/project/backup's channel or resetting its PLC
memory requires engineering reconciliation; OpenHMI cannot infer exclusive
ownership across independently running HMIs.

The PLC must retain request/accepted/completed identity and the final result until
the next request. Publish the result before publishing completion. Retain accepted
and completed identities across PLC restarts if transactions can survive them.
Process each new request at most once. Before issuing another request OpenHMI
requires a fresh good-quality root with request = accepted = completed and no
unresolved SQL transaction. A rejected request should still publish matching
accepted/completed identities and a nonzero result, allowing the channel to finish.
No new request clears or resets PLC feedback. Cancellation/reset are PLC-owned;
there is no HMI cancellation, automatic reset or "clear uncertain and retry" action.

Protocol polling is continuous at the configured rate, including when its screen
is closed. It joins the existing fastest-rate deduplication/batch mechanism.
The UDT root is acquired together and observations predating dispatch are ignored.
That is one adapter result, **not a guarantee of an atomic PLC scan snapshot**:
PLC logic, UDT size/fragmentation and retention/publication behavior must be
validated on the chosen controller. Use a separate channel per command.
Ordinary HMI writes to this UDT are blocked; overlapping configured PLC tag aliases
are rejected. Trusted Python and other PLC clients remain outside this boundary.

## Designer and offline demonstration

1. Add a local writable **struct** tag named `CycleCommand`. Declare the first
   four members above as `integer`, initialized to 0; add `Permit` as `boolean`,
   initialized true. The tag manager creates the local member values.
2. In **Commands**, add ID `cycle`, name `Cycle request` and UDT `CycleCommand`.
   Choose `Permit` if desired. Defaults are 30 s completion timeout / 250 ms polling.
3. Drop an action button, choose **PLC command transaction**, then the command
   contract. Apply live. Preview buttons never dispatch requests.
4. Open the runtime and click the button. It reports **requested**, not completed.
   Inspect the **Commands** page for the durable sequence/state/event timeline.
5. For manual offline feedback, start with
   `openhmi --handlers examples/command_simulator.py` and bind three additional
   Python buttons to its simulated acceptance, success and rejection actions.
   These refuse network-backed roots. Acceptance alone must not show completion.
   Success completes with result 0; rejection finishes as failed with result 17.

Use fresh project-local SQL storage, one OpenHMI process and a single writer per
channel. The live hardware version substitutes an enabled PLC UDT mapping with
the same member contract; never implicitly enable or target a live machine.

## Persistence, errors and recovery

The server checks control conditions, HMI permission/groups, the optional PLC
permit and source quality. It reserves the channel in SQL, links the reservation
to the authenticated operator journal's operation ID, and commits dispatch
markers before touching the driver. SQL/journal failure before those markers
prevents dispatch. A readback/connection failure after dispatch is **uncertain**;
the request is never replayed. Multiple clicks/clients cannot reserve the same
channel concurrently in the supported single-process project runtime.

| State | Evidence / behavior |
| --- | --- |
| prepared | SQL reservation exists; driver dispatch has not begun |
| requested | Dispatch marker committed; PLC acceptance not yet observed |
| accepted | Fresh PLC accepted sequence matches the request; completion pending |
| completed | Fresh request/accepted/completed sequences all match; result 0 |
| failed | Same matching completion evidence with a nonzero result |
| uncertain | Timeout, lost write/readback, inconsistent protocol or restart after dispatch; channel remains reserved |
| interrupted | Restart before dispatch marker, or unavailable journal dispatch; no replay |

Timeout does not establish failure, cancel the PLC request or make retry safe.
A later coherent matching completion may resolve uncertainty to completed/failed;
late acceptance alone cannot. Communication loss provides no success evidence.
After restart prepared reservations become interrupted; requested/accepted become
uncertain. Startup only observes; it sends no command. If PLC identity was lost,
the machine owner must reconcile what happened and publish an appropriate final
result through PLC-owned recovery before another request can be issued.

The command table is the equipment lifecycle record; the M1 operator journal
records the dispatch attempt and links its transaction ID/sequence. A succeeded
journal row with verification `request_tag_readback` is **not equipment completion**.
Later state transitions and observations are persisted in `command_event`.
Command records are retained for the project lifetime and included in complete
backups; no automatic command retention pruning is performed. Restore never
replays writes; imported PLC connections remain held. Applying a changed/remapped
contract, UDT or connection is blocked while that channel has an unresolved record.
Editing library recipes does not interact with command channels; recipe staging
and revision-associated transfer remain the next M3 work item.

## Validation boundary

Local tests exercise sequence allocation, same-sequence acceptance/completion,
nonzero result, permit/groups, duplicate/concurrent submissions, stale/failed
observations, SQL/journal outages, partial write/lost reply, timeout/late feedback,
restart, reserved UDT protection, contract remapping and backup restore.
The browser workflow checks designer configuration/binding, runtime states and
the durable Commands view. Hardware commissioning, actual PLC logic and specific
machine command semantics remain open in issues #3 and #7.

Checkpoint evidence: 56 Python tests and 11 browser tests passed, including the
manual-feedback simulator workflow. The browser bundle and Python wheel built;
wheel contents include the command service and local designer assets. No actual
PLC or Windows domain password logon was used for this checkpoint.
