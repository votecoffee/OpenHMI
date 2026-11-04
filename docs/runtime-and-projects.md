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

## SQL history

History records logical tag values, quality, acquisition time and record time in
the project SQLite database. Configure sampling, numeric deadband, retention days
and a maximum row count. Quality changes are always retained; unchanged deadband
values receive at least a one-minute heartbeat. The query API bounds result size
and reports truncation. CSV export includes quality and timestamps.

The new backend contracts have offline checks for batched polling, rate merging,
UDT member reads, reconnect/write behavior, history quality/deadband and resolved
faceplate/no-code actions. Designer and workspace workflows are the next layer
of this implementation. Hardware timing, controller writes and commissioning
remain unvalidated against a real controller.
