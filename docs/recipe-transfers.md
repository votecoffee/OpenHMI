# Versioned recipe transfer to a PLC-owned copy

OpenHMI can stage a complete recipe through a dedicated command UDT, verify it,
send the commit sequence last and verify the resulting PLC copy. The visual
designer supplies transfer profiles and parameter mapping; the generic recipe
viewer/editor supplies transfer controls and history. Python is optional.

This is an offline-verified software contract. Actual controller type/firmware,
PLC logic, UDT fragmentation/coherency and commissioning remain open in M2/M3.
OpenHMI does not install PLC logic or contact a chosen machine implicitly.

## PLC contract and designer configuration

Start with the [command handshake](command-transactions.md). Use one dedicated
command per transfer target, with its own UDT root. Keep request, acceptance,
completion, result and optional permit members outside the recipe payloads.
The root also declares two matching member sets, under the default prefixes
`Staging` and `Running` (prefixes are configurable):

| Member under each prefix | Declared type / typical PLC type | Meaning |
| --- | --- | --- |
| `RecipeCode` | string / STRING | Recipe library code |
| `RevisionId` | integer / DINT | Immutable content revision identity |
| `RevisionNumber` | integer / DINT | Revision number within that recipe |
| `ContentHash` | string / STRING, capacity at least 64 | SHA-256 of the complete canonical recipe content |
| `TransferHash` | string / STRING, capacity at least 64 | SHA-256 of this sequence and transferred parameters/metadata/production BOOL |
| `RecipeProductionApproved` | boolean / BOOL | Approval status captured for this transfer |
| Parameter members | matching scalar types | Every recipe parameter, mapped by name |

In the tag manager, declare all paths such as `Staging.Speed` and `Running.Speed`.
The UDT root must be writable. Ordinary HMI writes to this protocol-owned root
remain blocked. Staging/running prefixes, metadata, parameter paths and handshake
members cannot overlap. Existing overlapping PLC aliases are rejected.

1. Create the UDT tag and a dedicated command in **Commands**. Configure its
   HMI groups, PLC permit, timeout and protocol update rate there.
2. In **PLC recipes**, add a transfer profile bound to that command. Set the
   prefixes and the PLC string capacity, then map recipe parameter names to UDT
   member paths. Member dropdowns show compatible staging/running pairs.
3. Apply live. Recipe commit commands cannot also be bound to generic command
   buttons: the validated recipe transfer workflow must supply the full payload.
4. In **Recipes** or **Recipe editor**, choose a saved revision, enter a reason,
   select the transfer target and click **Transfer revision to PLC**.
   A live apply that changes the project revision requires a fresh target
   selection. The server rejects a request from the previous revision before
   reserving a sequence or staging parameters. API clients can pass
   `expected_project_revision` alongside `expected_revision_version` to use
   the same check.

The recipe's parameter set must exactly match the profile: no missing or extra
parameters. Types must match, with recipe `text` mapping to string. Integers and
revision identities must fit signed DINTs; numbers must fit the REAL range.
Numeric verification accepts the exact value or its IEEE REAL round trip, without
a broad absolute tolerance that could treat a small nonzero setpoint as zero.

`max_string_length` defaults to 82, and can be 64–1000 to match commissioned PLC
string storage. The pinned pycomm3 1.2.16 `FixedSizeString` uses ISO-8859-1:
unencodable parameter text is rejected before staging. Unicode remains available
in the SQL recipe library, image/title/description and HMI translations; this
initial PLC STRING transfer contract does not provide a Unicode wire encoding.
Actual PLC member types, capacities and encoding require bench acceptance.

## Dispatch and copy ownership

The server resolves the authenticated user and checks recipe loading roles,
change policy, optional loading permit, command operation permission/groups,
fresh good-quality UDT data, the command permit and an idle/unreserved channel.
There is no mandatory machine-stopped condition and no approval prerequisite.
The PLC retains its own interlocks and run/reject/inhibit decisions.

Under a single channel reservation the server captures the saved content,
review version, approving user, production status, image reference and transfer
reason. A stale expected review version is rejected before any staging writes.
The reservation, immutable transfer snapshot, payload hash and recipe audit event
are committed together in SQL before driver side effects. Operator journal
dispatch markers are also committed before those effects.

Dispatch then:

1. Writes only declared staging members, with individual write/readback checks.
2. Explicitly reads the entire UDT root and verifies every staged parameter,
   revision/hash and production BOOL. The channel must still be idle with its
   original sequence/result values, its permit true and its deadline unexpired.
3. Commits a durable requested marker and writes the new request sequence last.
4. Observes PLC acceptance/completion through normal shared protocol polling.
5. On result 0, verifies **every running member**, including both hashes and the
   production BOOL, from the same acquired UDT result as the matching handshake.
   Only then does the transaction become completed. A nonzero PLC result is a
   failed/rejected transfer and does not claim a newly verified running copy.

The PLC must ignore partial staging and copy staging into its own running storage
only when processing the new request. It owns acceptance, copying, any downstream
production publication, result code and completion; publish completion last and
retain the identity/data/result until the next request. The hashes are identity
tokens the PLC can copy; PLC-side SHA-256 computation is not required. OpenHMI
compares actual running parameter values as well as the tokens.

Individual writes/readback and a UDT read are not an atomic PLC transaction.
Validate PLC copying/publication order, task interruption, communication failure
and fragmented reads on the selected controller. Use one writer/process/project
per physical channel; a second independent HMI is outside this ownership model.

## Approval, HMI selection and history

Authors may approve their own revisions. The actual approving user remains in
the captured SQL snapshot. An approved revision transfers with
`RecipeProductionApproved=true`; draft, in-review, rejected, superseded or
withdrawn revisions can transfer for testing with the BOOL false.

Library edits, approval, withdrawal, HMI selection or clearing selection do not
write the running PLC copy or alter a previously dispatched snapshot. Another
explicit transfer captures the then-current review state. PLC transfers do not
change the independent HMI-side selection used by the existing selected-recipe
control. The viewer labels that distinction.

The transfer panel displays identity, image, captured production status, approving
user, state/result, hashes, event history and an operator-activity link. A verified
record is historical evidence at its displayed timestamp: it does not assert that
the PLC has never changed its copy since then. Unavailable status is explicit and
retained rows are marked potentially outdated. History is permission protected
and paginated; unresolved target state is checked independently of the page.

After dispatch returns a transaction ID, the panel keeps that receipt if the
status read fails. Further transfers wait for a successful status refresh and
the target's normal unresolved-transfer checks.

Local/Windows HMI users need recipe operator/engineer authority and runtime
operation permission, plus configured command groups. Legacy recipe accounts
remain supported without global HMI security; the journal identifies their
server-resolved user with provider `recipe-local`. Configured HMI group gates
require an HMI identity, and are never bypassed by legacy recipe roles.

## Failure and recovery

SQL/journal reservation failure prevents staging/commit. A partial staging
failure, readback mismatch, changed permit/channel, expired staging deadline or
lost commit reply leaves the transaction uncertain. The event timeline shows
whether staging or commit dispatch had begun. No remaining fields, commit,
cancel, reset or request are automatically replayed. Staged data may be partial;
the PLC must never interpret it as a running recipe without its commit protocol.

A matching successful PLC acknowledgement with the wrong running payload remains
uncertain and retains channel ownership. Matching late completion plus a verified
copy may resolve uncertainty; acceptance alone cannot. Nonzero completion results
provide the PLC-owned rejection/recovery path. When identity/data were lost, the
machine owner must reconcile the actual outcome through the commissioned PLC
recovery procedure before another request. There is no generic HMI clear-and-retry
action that could silently release an unresolved transfer.

Prepared reservations interrupted before driver dispatch become interrupted on
restart; staging/requested/accepted become uncertain. Startup only observes and
never writes. Changing a reserved command, transfer mapping, UDT or connection is
blocked until resolution. Complete backups include transfer snapshots, command
events, approvals and recipe images; import retains the PLC connection hold and
does not replay transfers. History is retained for the project lifetime.

## Verification

Offline tests cover staged-before-commit ordering; scalar typing/ranges; complete
mapping; production/test status and self-approval; library withdrawal; independent
running/HMI copies; permits/groups; concurrency; stale review versions;
partial/lost writes; wrong values/hash/production BOOL after acknowledgement;
SQL outages; restart and complete backup restore without replay. The browser
workflow configures a profile/mapping, transfers both approved and withdrawn
recipes, simulates PLC copy/completion, and inspects images/history.

For the local demonstration use the `CycleCommand` UDT and default prefixes with
`examples/command_simulator.py`. Its existing success action copies local
`Staging` into `Running` before publishing completion. It refuses network-backed
roots. This is a simulation example, not commissioning evidence or PLC code.

Checkpoint evidence: 70 Python tests and 12 browser tests passed, plus the final
recipe-transfer browser check after the table alignment adjustment. Browser assets
and the Python wheel built and package contents were verified. No actual PLC
commissioning or Windows domain password logon was performed.
