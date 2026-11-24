# Runtime, screens and project lifecycle

The runtime uses pycomm3 1.2.16 for ControlLogix/CompactLogix explicit messaging.
The driver is optional in use: projects start with simulation and no PLC connection.
No controller has been contacted during development/validation.

Applied-screen GET snapshots also finish their SQL projection, serialization and
middleware under the workspace lock, then send outside it. A slow reply retains its
original revision, layout and project identity even if a newer layout is applied
or another project opens before delivery completes. Existing revision/instance
checks protect writes; failed reads return sanitized private 503 feedback and can
recover. Cancelled preparation drains before a source store can close.

Alarm GET snapshots use the same finite-response boundary. Prepared occurrence
IDs, sampled metadata, quality/staleness and recovery information remain fixed while
acknowledgements, switching and shutdown proceed. Acknowledgements retain their
permission, audit and project-instance checks; an old snapshot cannot acknowledge
an identically numbered occurrence in a newly opened project. Send failures never
repeat the snapshot or create an acknowledgement/journal operation. Unexpected read
failures return sanitized private 503 feedback and recover on a later request.

The main browser polls require a matching, valid response project header before
adopting tags, alarm status, selected-recipe data or identity. Invalid/missing source
identity produces the normal unavailable indication; a matching later reply recovers.
Applied-project reads require paired body/header identities so runtime viewers can
reload on a confirmed switch. Editors keep the previous layout/metadata and draft
until explicit reload. The API's original project pin stays fixed, including for
writes; only fresh page initialization can adopt the replacement. Catalogue loading
also checks that it follows the same initialized project. These checks are opt-in
for these reads. The alarm console also checks occurrences, event history, detail,
notes and shelving before validation/adoption. Source failures retain only the
last confirmed data for the same endpoint, mark it unavailable and block dependent
actions; matching reads recover without discarding filters or text drafts. An
event-history failure alone leaves a healthy occurrence page usable. Permission
denial still clears the affected data. These checks do not repin the client or
replay acknowledgement, note or shelf operations. Other operator readers remain
subject to separate audits; CSV links are outside this JSON-read boundary.
Command history/detail and runtime latest-command reads now use the same guard.
Missing/foreign source identity retains confirmed evidence with unavailable
feedback and blocks command dispatch/forward paging. Permission denial clears the
affected evidence. Matching reads recover without repinning or replaying commands;
transaction ID, command ID and sequence validation still apply. Transaction download
links remain outside this JSON-read boundary.
Activity and diagnostics readers now check source identity as well. Missing or
foreign success replies retain confirmed data only for the same query/page, mark
it unavailable and disable forward paging. A failed older-page request cannot show
the previous page as its result and continues to retry normally. Denial clears the
affected records, tag-quality rows and worker health. Matching-source replies
recover while unapplied filters remain intact. These cached reads do not create
operator actions or change subscriptions. CSV/JSON export links remain separate.
Trend and sparkline history, saved-capture history and recording-status JSON reads
now verify project identity before payload validation. Foreign/missing history
replies retain only the current query's trace with unavailable feedback; changing
the query hides that trace until valid data arrives. Recording-status failures
retain confirmed capture details but block Run, Stop and Delete, including an open
delete confirmation. History failure alone leaves healthy recording controls
usable. Matching-source reads recover without command replay, while permission
denial clears the affected data. Live tag readouts remain independent. CSV links
and recorded-tag browsing are outside this increment.
Recipe workspace refreshes now guard both library and recipe-session JSON reads.
Revisions, audit history, policy and identity must come from the initialized
project before the paired refresh is adopted. Missing/foreign identities use the
existing failed-refresh path: the last readable library, selected revision and
unsaved content/reason remain visible, while edits and dependent operations are
blocked until a matching refresh succeeds. Failed initial loading shows Retry
without installing foreign data. Existing denied-refresh handling also retains
the public library and draft while blocking operations. Sign-in/out and recipe
mutation helpers retain their existing receipt and non-replay behavior. Independent
recipe-transfer status reads remain a separate audit.

## Connection and tag contract

Tag and status-only readout responses use cached data through the normal API route.
Preparation, serialization and middleware completion stay protected from project
switch/shutdown; finished responses then send outside the workspace lock. Slow
viewers do not block subscription renewal or other HMI requests. Values, quality
and source identity are fixed at preparation, so a received frame can describe the
previous project after a switch; normal project-instance guards still protect writes.
Responses are private/no-store, and unexpected preparation failures return sanitized
503 feedback. Readout staging does not poll controllers or renew viewer leases.

A connection has a unique ID, route such as `192.0.2.10/1/0`, enabled setting,
socket timeout and program-tag discovery setting. Logical HMI tags map names to
PLC addresses and types. Numeric tags may have scale/offset; writes reverse that
mapping. Tags start read-only unless writing is deliberately enabled. PLC external
access must also permit writes. A write is issued once, followed by readback;
connection recovery never replays it. Floating-point readback uses a small
numeric tolerance. Boolean readback must return a Boolean. If the adapter
identifies a result as belonging to a different address, the route reconnects
and the write remains unconfirmed.
This confirms a tag value, not a PLC application's command-complete acknowledgement.
The adapter supports Boolean, integer, floating-point, string and declared UDT
members. Add indexed scalar addresses for arrays; array root editors are not
implemented. PLC integers must be within ±9,007,199,254,740,991, the
[JavaScript safe integer range](https://tc39.es/ecma262/multipage/numbers-and-dates.html#sec-number.issafeinteger).
A wider value is marked bad. A UDT containing one is unavailable as a whole,
while individually declared members with valid values stay available. Inverse
scaling for writes must yield a finite value and, for integer tags, a whole
number in that same range before the driver calls the adapter. Where PLC
metadata resolves the target, OpenHMI also checks its signed or unsigned integer
width and the maximum finite REAL magnitude. For PLC STRINGs recognized by
pycomm3 it checks the declared DATA byte capacity and ISO-8859-1 encoding.
These checks apply after scaling and support indexed scalar and nested member
targets. Other address forms and types depend on adapter validation.
The **Tags** browser shows cached PLC metadata for the selected route. Select
a tag to see its native type, external access, array dimensions and known
numeric range or STRING byte capacity. Native 64-bit bounds are displayed as
exact decimal text. To bind an array element, enter its indexed address. Scalar
STRING members of a browsed UDT are offered as strings.
Built-in simulation/recipe tags cannot be replaced by PLC aliases.

Local tags have typed initial values. UDT tags expose a configured member/type
contract and may bind reusable faceplate definitions. Relative `$.Member` bindings
resolve against each instance's root tag. Instance controls receive unique IDs,
and server-side security/conditional-enable checks apply to the expanded controls.
When an instance enable tag is off, its child actions and edits are disabled.
If the enable data is unavailable, the instance's quality badge can still be
opened for details. Specific equipment faceplates are left for later design.

## Shared polling

Each screen has an update interval, bounded to 100–60,000 ms. Viewers lease the
screen/popups they currently use. Leases expire after 15 seconds unless refreshed.
An empty subscription releases the viewer. When the page is left, the browser
tries to send a release. The 15-second timeout still applies if it cannot.
A page restored from the browser's back/forward cache renews its lease.
Browser requests carry a sequence
number so a delayed heartbeat cannot replace a newer request for the same
viewer. The runtime remembers the last sequence for its 2,000 most recently
updated sequenced clients, including released viewers. When demand for an
address ends, the driver drops its next scan deadline. When the scheduler
sees demand return, the address waits for a fresh receipt. A reply received
before demand resumed cannot satisfy the reopened screen. The server merges demand
across viewers and selects the fastest requested rate for each source
address. Multiple UDT members are acquired through a single root
UDT read. Alarm tags demand 250 ms; historian tags demand their sampling interval,
independent of viewers. Idle screen tags are not kept on a scan solely because
their screen exists.
Faster demand immediately tightens the freshness limit for cached samples of
that address to the greater of one second or three times the requested interval.
A later slowdown changes the limit only for newly received samples. It can
defer a future read to the slower cadence, capped by the cached sample's
freshness limit. Already-due reads keep their deadlines. If faster demand
arrives during a scan, a sample received before that demand leaves the address
due for the next scan.
A scan waiting for the route rechecks the scheduler's due addresses before
sending a PLC read. A connected route skips the read if no addresses remain due.
After a connection failure, the first scan after backoff refreshes all
currently requested addresses on that route, even if a separate verification
read already reopened the connection.

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
switches screens; button action types can navigate/open/close popups. Keyboard
focus stays within the top popup. Press Escape to close it and return focus to
the control that opened it. If a live apply removes an open popup, the runtime
closes that popup and any popups opened from it, then updates its tag subscriptions.
If the current main screen is removed or becomes a popup, the operator returns
to Overview and its tag subscriptions. Restoring the old screen makes it
available in navigation again.
**Faceplates**
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
and a maximum row count. **Periodic** is the default logging mode. **On change**
records the first sample, changes in value or quality, and a heartbeat on the
first due sample after 60 seconds without a record. Numeric deadband is measured
from the last recorded value. Both modes use the configured sample interval, so
changes between samples can be missed. Trends for applied **On change** tags hold
the last good recorded value across the window boundary and between samples.
The trace breaks at bad quality or when the last record is older than 60 seconds
plus the configured sample interval. Cursor values on those segments represent
the held value. CSV exports include recorded rows only. The query API bounds result size
and reports truncation. In **History → Export recorded data**, select up to 12
tags and choose a preset range or **Custom start and end**. **Find recorded tags**
includes tags with retained rows even after they are removed from the logging
configuration. Use a case-sensitive name prefix to narrow the search. Selections
stay checked when you search again or move to the next page.
An empty end time uses the current time. Custom ranges can span up to 365 days.
Choose local browser time or UTC. Use UTC to distinguish the two occurrences of
an hour repeated when daylight saving time ends. Both range boundaries are inclusive.
The CSV includes recorded values, quality and UTC timestamps. The quick export
warns when it is limited to the newest 20,000 rows per tag. Select **Export all
retained rows in this range** to download the complete selection. OpenHMI stages
that CSV in temporary storage before sending it to the browser. One complete
export can run per project at a time, with a 1 GiB file limit. If retention
removes a selected record before it is copied, the export reports an error and
you can retry with a shorter range. Spreadsheet
formula-like text values receive a leading apostrophe in the CSV. SQLite keeps
the original values.
A **Trend** shares one time axis across up to 12 tags. Each numeric tag has an
independent scale, shown in the legend. **Observed min/max** uses the returned
good samples for that tag in the selected window and centers a constant value.
**Fixed** uses the configured bounds and clips the trace at the chart edges.
Choose 0 to 8 decimal places per numeric live readout. Existing trend controls
default to observed ranges and one decimal place.

Boolean tags have individual 0/1 step lanes below the analog plot. Transitions
appear at recorded sample times, so pulses between acquisitions can be missed.
Bad-quality records break both analog and Boolean traces. The legend's current
values continue updating from the runtime even when the plot shows a historical
window. Each plotted tag needs a **History** entry for persistent traces.

Operators can choose a time range/end time or return to live viewing. Acquisition
timestamps reflect when Python receives each PLC read batch. If a later batch
fails, the scan does not publish a partial update. Queries retain the newest
bounded results and report truncation. Observed ranges use those returned points.
If a history request fails or returns malformed data, the trend marks the last
received window with its end time. It keeps live tag readouts separate and
retries the selected window. Changing the query clears the previous trace until
the new window arrives. Export is limited to 20,000 records per requested tag.

### Saved trend captures

If recording status is unavailable, the trend labels any retained capture
information and disables Run, Stop and Delete until a valid status arrives.
Previously listed captures remain available to inspect and export during a
transient status failure, subject to their own history and export responses.

Set the default viewing window in the designer. In runtime, choose a preset
such as **10 s** or **1 min**, or enter a custom window of 1 to 604,800 seconds.
Hover over a trace to align the cursor across all lanes. Tap a trace or use
Left/Right with the timeline focused to pin the cursor to a timestamp as the
live window advances. Use **Clear trend cursor** or press Escape with the
timeline focused to clear it. The marker disappears when its timestamp leaves
the viewing window. Analog cursor values
interpolate between good points. Boolean values follow the preceding good state
between good points. Gaps and times outside the recorded traces show a dash.
The live value column remains separate.

Enable **Saved trend recording** in the Trend properties and **Apply live**.
Choose a sample interval of 100 to 60,000 ms and retain 10 to 20,000 samples per
capture. One sample records every configured tag from the runtime cache. Timing
depends on the driver and runtime cycle. Retention is a sample count independent
of the viewing window. The capture rolls over its oldest samples as it fills.
Continuous tag history keeps its own schedule and retention.

**Run trend** starts a new capture, and **Stop trend** saves it in the project
database. Each configured Boolean start/stop tag acts on a sampled, good
false-to-true transition. A configured stop tag must be good and false for an
automatic start. Tags are monitored at 250 ms or the recording interval,
whichever is faster, subject to PLC communication timing. Short pulses can be
missed. Recording and triggers work with the browser closed while the Python
runtime is running. A restart preserves the captured data and stops the run.
Changing recording settings or tag acquisition definitions also stops the run.

Use **Trend data** to select a saved capture and **Capture position** or **End
time** to review it. The plot shows up to 2,000 samples from the chosen window
and reports truncation. **Export entire capture CSV** exports all retained
samples, with timestamps and quality, independently of that window. Project
backups include captures. Projects reserve at most 100,000 samples across up to
100 captures. Operators with runtime permission can run and stop recording.
An engineer with project editing permission can delete a stopped capture to
free space.

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
Preparation retains the workspace lock until source work and cancellation cleanup
finish. Sending the prepared archive releases that lock, so slow download clients
do not prevent HMI requests, switching projects or shutting down the runtime.
The download retains its source project's bytes and identity after a switch.
This does not establish how quickly a particular web server exits with open clients.
The ZIP contains a versioned manifest and SHA-256 checksums, the database and,
when configured, the startup Python entry file and legacy recipe account file.
SQL includes screens, UDT definitions, connections/tags, recipes/images/reviews,
selected recipe copy, HMI security/password hashes, alarms, tag history and
the runtime operator activity journal.
It does not capture a controller's running memory, external Python modules,
environment dependencies or the OpenHMI installation. Backups contain private
account/project data; checksums detect corruption, not publisher authenticity.

Project-library and file-inventory GET snapshots are fully prepared before their
responses leave the workspace lock. Slow readers can continue receiving the fixed
snapshot while other requests, project switching or runtime shutdown proceed.
Responses retain the source identity and are private/no-store, including handled
errors. Authorization and owned inventory-scan cleanup still finish under the lock.

Create/open JSON bodies receive outside the runtime lock, with a 4 KiB streaming
limit, 30-second receive deadline and at most four pending requests. Additional
requests return 429 without reading their bodies. Before dispatch, the current
permission, source project identity and shutdown state are checked again. A body
that times out, disconnects, exceeds the limit or contains invalid JSON cannot
start an operation. The browser retains draft fields after these errors; retry is
explicit. An interrupted request after dispatch still requires completion review.
Completed acknowledgements send outside the runtime lock, retaining source identity.

Uploads receive outside the runtime lock with a 30-second deadline and one import
in progress per workspace. Busy requests return 429; receive timeout returns 408
without importing. The selected browser file remains available for explicit retry.
Permission and project identity are rechecked after receipt; switching projects,
signing out or shutting down during upload prevents import dispatch. Validation
and publication retain the runtime lock and drain owned work before propagating
cancellation. The browser allows two minutes overall, but an interrupted request
after dispatch can still have completed: review the library before retrying.

Import is bounded to 256 MiB, rejects unexpected/duplicate ZIP entries, verifies
checksums, checks SQLite integrity/schema and validates project models. It creates
a new project rather than overwriting existing data. Imported PLC configuration
is retained, but a persistent hold prevents opening connections until a user
explicitly applies the reviewed project. The Python entry file is saved alongside
the database as `.handlers.py` for review, and is never executed on import/open.
After review, select it explicitly with `openhmi --project PATH --handlers PATH`.
[Project revisions, comparison, staged rollback and merge recovery](project-recovery.md)
are now available. Installer packaging remains M6 work.

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

M3 [recipe transfers](recipe-transfers.md) add complete staging/readback, commit-last
dispatch, revision/hash/production association and acknowledged PLC-copy
verification. Transfer snapshots, recipe audits and images are included in backups;
startup/restore never replay staging or commit writes. HMI selection stays separate.
