# Alarm operator workflows

Open **Alarms** to review the project-wide alarm monitor. The operator does not
need to build an alarm graphic or write Python for these workflows.

## Configure guidance

In **Alarm setup**, enter a possible cause, an operator response and an optional
related screen. Related screens must exist and cannot be popups. **Languages**
exposes `alarm.<id>.cause` and `alarm.<id>.response` translation entries alongside
the message. Apply the draft to publish these settings.

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

**Alarm details** shows the captured cause/response, related-screen navigation,
first acknowledgement and append-only operator notes. Trigger quality/time comes
from the cached driver sample; opening details creates no additional PLC scan
lease. Notes record the authenticated user/provider and an activity operation ID.
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

Shelving, audible/silence behavior and PLC acknowledgement handshakes remain
future work. Specific equipment faceplates, target-display touch/keyboard review,
translated text expansion and real-controller commissioning remain M5 acceptance
items. These local software checks do not establish those acceptance results.
