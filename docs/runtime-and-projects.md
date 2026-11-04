# Runtime, screens and project lifecycle

The runtime uses pycomm3 1.2.16 for ControlLogix/CompactLogix explicit messaging.
The driver is optional in use: projects start with simulation and no PLC connection.
No controller has been contacted during development/validation.

## Connection and tag contract

A connection has a unique ID, route such as `192.0.2.10/1/0`, enabled setting,
socket timeout and program-tag discovery setting. Logical HMI tags map names to
PLC addresses and types. Numeric tags may have scale/offset; writes reverse that
mapping. Tags start read-only unless writing is deliberately enabled. PLC external
access must also permit writes. A write is issued once, followed by readback;
connection recovery never replays it. FLOAT readback uses a small numeric tolerance.
This confirms a tag value, not a PLC application's command-complete acknowledgement.
The adapter supports Boolean, integer, floating-point, string and declared UDT
members. Add indexed scalar addresses for arrays; array root editors are not
implemented. Browser numeric integers are limited to the exact JavaScript range.
Built-in simulation/recipe tags cannot be replaced by PLC aliases.

Local tags have typed initial values. UDT tags expose a configured member/type
contract and may bind reusable faceplate definitions. Relative `$.Member` bindings
resolve against each instance's root tag. Instance controls receive unique IDs,
and server-side security/conditional-enable checks apply to the expanded controls.
Specific equipment faceplates are intentionally left for later design.

## Shared polling

Each screen has an update interval, bounded to 100–60,000 ms. Viewers lease the
screen/popups they currently use. Leases expire after 15 seconds unless refreshed.
The server merges demand across viewers and selects the fastest requested rate
for each source address. Multiple UDT members are acquired through a single root
UDT read. Alarm tags demand 250 ms; historian tags demand their sampling interval,
independent of viewers. Idle screen tags are not kept on a scan solely because
their screen exists.

Due addresses share a single pycomm3 connection per configured PLC and are read
in batches. pycomm3 splits requests to fit EtherNet/IP Multiple Service Packets
and connection sizes. These are application polling groups, not CIP cyclic I/O
subscriptions. See [pycomm3's LogixDriver documentation](https://pycomm3.readthedocs.io/en/stable/usage/logixdriver.html).
Connection status exposes the effective groups and request counters. Connections
back off after failures. Samples carry quality and acquisition time; bad/stale
values are omitted from the usable value snapshot rather than treated as current.
Rates are best effort, subject to controller response, fragmentation and other
connection work. Counters describe pycomm3 read calls and requested addresses,
not measured wire-packet counts. Screen-only applies preserve unchanged
connections and values. Route changes invalidate their cached samples.

## Designer workflow

Use **Connections** to configure and enable a PLC route, then **Apply live**.
**Tags** browses cached PLC metadata, adds logical aliases, sets scale/offset and
marks explicitly writable tags. Local tag initial values use typed fields; local
UDT initial data is built from member fields. Draft changes do not open connections.

The original overview remains compatible with existing saved projects. **Screens**
adds named screens and popups with independent update rates. Runtime navigation
switches screens; button action types can navigate/open/close popups. **Faceplates**
defines a UDT type/member contract. Design its controls using `$.Member` tags,
select an active UDT instance for live preview, then bind screen instances to
compatible root tags. Nested faceplates are currently rejected. Equipment-specific
motor/valve/pump designs are intentionally deferred.

Boolean bindings control visibility, enablement and value color. Missing/bad
visibility/enable conditions fail closed. Python enforces enablement on commands
and writes as well as HMI group permissions. Button modes include set, toggle,
navigation, popup, close popup and registered Python actions. Preview controls
never invoke actions or writes. PLC tag readback does not implement an equipment
handshake, pulse lifecycle or machine interlock; those remain PLC/application work.

## SQL history

History records logical tag values, quality, acquisition time and record time in
the project SQLite database. Configure sampling, numeric deadband, retention days
and a maximum row count. Quality changes are always retained; unchanged deadband
values receive at least a one-minute heartbeat. The query API bounds result size
and reports truncation. CSV export includes quality and timestamps.
Trend controls plot recorded numeric values and break lines at bad-quality points.
Operators can choose a time range/end time or return to live viewing. Sampling
and deadband are configured through **History**. Acquisition timestamps are from
Python's reception of values, not a synchronized PLC source clock. Queries retain
the newest bounded results and report truncation; they do not perform min/max
aggregate downsampling. Export is limited to 20,000 records per requested tag.

## Project library and complete backups

The `openhmi` CLI hosts a project library in the selected database's directory.
**Projects** lists the current database and `*.openhmi.sqlite3` projects. Create
uses a new ID and copies the current HMI security configuration. Open switches
the server's project for all clients, closes the prior acquisition service and
invalidates prior sessions. Viewers detect a new project instance and reload;
editor requests carry an instance ID so stale saves cannot land in another
project even when revision numbers coincide. Signed-out editors retain their
local draft and disable save/apply until authorized again.

The library does not accept arbitrary filesystem paths from the browser. Use
`openhmi --project PATH` to select a database outside the current library.
Project management/export/import require `security.manage` when HMI security is
configured. Legacy recipe-only projects require a recipe administrator. An empty
unsecured simulation library remains available for initial project creation.

Export uses SQLite's online backup API to create a consistent database snapshot.
The ZIP contains a versioned manifest and SHA-256 checksums, the database and,
when configured, the startup Python entry file and legacy recipe account file.
SQL includes screens, UDT definitions, connections/tags, recipes/images/reviews,
selected recipe copy, HMI security/password hashes, alarms, tag history and
the runtime operator activity journal.
It does not capture a controller's running memory, external Python modules,
environment dependencies or the OpenHMI installation. Backups contain private
account/project data; checksums detect corruption, not publisher authenticity.

Import is bounded to 256 MiB, rejects unexpected/duplicate ZIP entries, verifies
checksums, checks SQLite integrity/schema and validates project models. It creates
a new project rather than overwriting existing data. Imported PLC configuration
is retained, but a persistent hold prevents opening connections until a user
explicitly applies the reviewed project. The Python entry file is saved alongside
the database as `.handlers.py` for review, and is never executed on import/open.
After review, select it explicitly with `openhmi --project PATH --handlers PATH`.
Screen revision history, diff/rollback UI and installer packaging remain deferred.

The new backend contracts have offline checks for batched polling, rate merging,
UDT member reads, reconnect/write behavior, history quality/deadband and resolved
faceplate/no-code actions. Browser checks cover tag browsing with a fake PLC,
scaling, faceplate design/instantiation, screen rates, popups/trends, retained
operator input, and project backup/open/import. Hardware timing, controller writes and commissioning
remain unvalidated against a real controller.

M1 [activity and diagnostic workflows](activity-and-diagnostics.md) add durable
operator attempts/outcomes, interruption/uncertainty handling and protected
connection/tag-quality inspection. These views read cached runtime data without
adding screen scan demand. The journal is included in project backup/restore.

M3 [command transactions](command-transactions.md) add configurable no-code
PLC handshakes, durable lifecycle records and continuously polled protocol UDTs.
Command records/events are included in complete backups. Restore observes
outstanding requests without replay; PLC feedback determines completion.
