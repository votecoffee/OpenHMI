# Alarm operator workflows

Open **Alarms** to review the project-wide alarm monitor. The operator does not
need to build an alarm graphic or write Python for these workflows.

## Configure guidance

In **Alarm setup**, enter a **Possible cause**, **Recovery steps** and an optional
**Related screen** for each alarm. Write each recovery step on its own line.
Related screens must exist and cannot be popups. **Languages** exposes
`alarm.<id>.cause` and `alarm.<id>.response` translation entries alongside the
message. Apply the draft to publish these settings.

An occurrence captures its message, priority, guidance, configured translations
and related-screen identifier when raised. Editing guidance does not rewrite
past occurrences or retrigger an unchanged condition. Missing translations fall
back to the captured source text. A removed related screen is shown as unavailable.
Guidance is authored project content; it is not an inferred diagnosis.

## Review and acknowledge

Apply search, priority, occurrence-state and local start/end time filters. Search
matches alarm identifiers, tag names, source messages and captured message
translations; `%` and `_` are literal characters. The list shows 50 occurrences
per page, newest identifiers first. **Older** and **Newest** navigate without
loading the complete retained history into the list.

Select individual unacknowledged occurrences or **Select unacknowledged on this
page**, then **Acknowledge selected**. Filtering clears the selection. An optional
comment accompanies acknowledgement. The server validates the whole selection
before changing any occurrence. Repeated acknowledgement preserves the first
user, provider, timestamp, operation identifier and comment.

The counts are project-wide. **Acknowledge all** still acknowledges all pending
occurrences, including occurrences hidden by the filters. Acknowledgement records
awareness; it does not reset, silence or write a PLC tag. Automatic acknowledgement
is attributed to `system / automatic`. Old acknowledgements without identity
records are labelled as legacy rather than assigned an invented user.

## Details, notes and history

The occurrence list and event history refresh independently. If either page
becomes unavailable, the console labels its last received results for the
current filters. Occurrence-dependent acknowledgements pause when the
occurrence list is unavailable. Access denial clears retained results.

Select the alarm message in the runtime banner to open the details for that
occurrence directly. Focus moves to the details heading when the data loads.
If a trigger cannot be evaluated, the banner links to the affected definitions
in the alarm console, including triggers that have no recorded occurrence.
The banner shows that evaluation is pending until the monitor has sampled
the applied revision and evaluated its enabled triggers. Known alarm
occurrences remain visible during that interval. If five seconds pass after
the last completed evaluation, the monitor reports stale evaluation. The banner
keeps the last recorded headline and counts visible with a warning, including
when the alarm status request fails or returns an invalid snapshot after a
prior successful response. The console disables Acknowledge all while the
status is stale or unavailable.

**Alarm details** shows the captured cause and recovery steps, related-screen navigation,
first acknowledgement and append-only operator notes. Details and notes
refresh independently, so a notes outage leaves the recovery instructions
and current trigger quality readable. During a detail outage, retained
trigger quality is labeled as last received. Note entry waits for both reads
to recover. Trigger quality/time comes
from the cached driver sample. Open the quality badge to inspect the trigger
tag, reason, sample age and source time when available. Opening details
creates no additional PLC scan lease. Notes record the authenticated
user/provider and an activity operation ID.
The unsecured simulator is explicitly attributed as `unsecured-simulation`.

The event table supports an event-type filter and separate paging. It shares
priority, message search and time filters with the list; its time filter applies
to event timestamps. Occurrence-state filtering applies only to the list.
CSV exports the matching newest 20,000 events with source-language messages and
attribution. Spreadsheet formula prefixes are escaped. The API response header
`X-OpenHMI-Truncated: true` indicates additional matching events.

Read-only alarm queries follow the existing public alarm-monitor visibility.
Acknowledgements require `alarms.acknowledge`; notes require `alarms.comment`.
New Engineers and Operators groups include both. Existing saved groups keep their
permissions: explicitly grant `alarms.comment` in **Security** where needed.
Mutations use the durable activity journal and same-origin protection. An
uncertain receipt requires checking the recorded outcome before retrying.

## Timed shelving

Enter a **Reason for shelving or restoring** and a duration, inspect an outstanding
occurrence, then choose **Shelve this alarm**. The browser offers 15 minutes through
24 hours; the API accepts 60–86,400 seconds. There is no indefinite shelf. The
separate `alarms.shelve` permission grants both shelving and early restoration.
New Administrators receive it; other groups and all existing saved groups require
an explicit grant in **Security**.

A shelf applies to one alarm definition and its matching retriggers, not its PLC
tag or other alarm definitions using that tag. Monitoring, bad-quality handling,
new occurrences, return-to-normal and history continue. Shelving neither
acknowledges nor writes a PLC tag. Changing/disabling/removing the trigger,
acknowledgement policy or priority invalidates the shelf. Text/guidance edits do
not extend or rewrite it.

The default console list hides shelved occurrences. Choose **Shelving filter** to
show shelved or all occurrences. Global counts and **Acknowledge all** still
include shelved occurrences. The runtime banner annunciates unshelved alarms and
always provides a separate count/link when definitions are shelved. Legacy
Boolean alarm graphics remain direct tag indicators. Existing clients of
`/api/alarms` retain the full `outstanding` list and totals; the updated runtime
uses the additive `annunciated_*` fields.

The shelf registry is independent of alarm list filters and shows the initiating
user/provider, reason and absolute expiry. Enter a restoration reason and choose
**Restore alarm** to return it early. Repeated shelving cannot extend an existing
interval. Restoration requires the current shelf operation ID so an old browser
cannot restore a replacement interval accidentally. These operations use the
durable activity journal; events/CSV record shelving, restoration, expiry and
configuration invalidation. Registry reads share the alarm monitor's public
read-only visibility, including recorded users and reasons.

Expiry uses server UTC and becomes effective on reads even if the monitor has not
sampled again. The next monitor pass records the expiry event. Keep the server
clock synchronized. Restart and complete backup/restore retain the original
expiry without extending it. Review the registry when restoring a project; an
unexpired shelf remains active in the restored copy. Alarm events follow the
existing history cap; active shelves retain their captured definition separately
if their starting occurrence is pruned. An event whose occurrence was pruned
falls back to the alarm identifier in history/CSV.

## Persistence and boundaries

Notes and first acknowledgements are stored in companion SQLite tables, preserving
the original occurrence/event table formats. Complete project backups include
them. The alarm history limit bounds events and completed occurrences; unresolved
occurrences survive the cap. Notes and acknowledgement records follow occurrence
retention, while event attribution follows event retention. This is operational
history, not indefinite archival storage.

The new query routes bound occurrence/event pages to 200 rows and note pages to
100. The legacy `/api/alarms` payload remains compatible and still includes its
complete retained snapshot for existing clients/header polling.

Audible/silence behavior and PLC acknowledgement handshakes remain future work.
Specific equipment faceplates, target-display touch/keyboard review,
translated text expansion and real-controller commissioning remain M5 acceptance
items. These local software checks do not establish those acceptance results.
