# Operator activity and runtime diagnostics

## Operator journal

Open **Activity** from the runtime navigation. Runtime button/Python actions,
numeric writes and alarm acknowledgement receive an operation ID and a durable
SQL attempt record before dispatch. The identity/provider/groups come from the
server's current HMI session, not a user name supplied with the command. Unsecured
simulation and anonymous denied requests are labeled separately.

Records identify the active control/action/tag and requested value. When a target
tag is known, the before value includes its cached quality and sample timestamp;
it is not a fresh PLC read or an atomic capture of controller state. Python
callbacks may have arbitrary effects, so their individual tag effects are not
inferred. Context text is bounded to 1,000 characters, lists/maps to 100 entries
and nested structures to six levels.

A dispatch marker is committed before entering a driver write, callback or alarm
acknowledgement. The phases describe the HMI path, not proof that an EtherNet/IP
packet reached the controller. Outcomes are:

| Outcome | Meaning |
| --- | --- |
| `pending` | An attempt exists without a durably finalized result. It may still be executing or waiting for journal finalization. |
| `succeeded` | The configured HMI verification returned successfully. Read the verification type below. |
| `denied` | A permission or tag-condition check rejected the request before dispatch. |
| `rejected` | A binding, limit or other pre-dispatch check rejected the request. |
| `uncertain` | Dispatch started but an error/restart prevented a dependable final outcome record. Inspect before manually retrying. |
| `interrupted` | The application restarted with an attempt that had no dispatch marker. Recovery does not execute it. |

Verification names distinguish local writes, adapter tag readback, Python callback
return, alarm acknowledgement and a navigation response. None is an equipment
command-complete handshake. The HMI-observed result time is separate from the
journal's finalization/recovery time and from a PLC's source clock.

Journal failure before attempt/dispatch persistence refuses the operation. If
the operation returned successfully but final journal storage fails, the API
preserves the successful response and exposes `X-OpenHMI-Audit-Status: pending`.
The UI reports pending finalization with its operation ID. An in-memory queue
retries only the SQL outcome write, at most once per maintenance cycle; it never
reissues the command. After a crash, unresolved dispatch markers become uncertain
and prepared attempts become interrupted. No command is replayed during recovery.

API responses expose `X-OpenHMI-Operation-ID` and `X-OpenHMI-Audit-Status`. HTTP
validation failures before the operation handler and stale-project rejections
before admission do not create an operator row. Recipe/security operations retain
their own dedicated histories. Login bodies, passwords and session tokens are
not recorded in this runtime journal. Browser/network timeouts still require
outcome inspection; idempotent PLC application transactions belong to M3.

## Viewing, export and retention

The page filters by user, outcome, control/tag/operation ID and time range. Newest
pages refresh every five seconds; older pages use ID-based pagination. API time
filters require a UTC offset; browser date fields are converted to UTC. CSV export
uses the active filters, is limited to 20,000 records and reports truncation in
`X-OpenHMI-Truncated`. Formula-like CSV text is exported as literal text.

Resolved records retain up to 365 days and the newest 100,000 resolved entries.
Pending and uncertain records are not automatically pruned. Maintenance runs
about once a minute. There is no API to rewrite or delete an event. The journal
is included in complete project backups; unresolved rows in restored copies are
classified on construction without executing their commands.

Use one application process per project database. Trusted Python and OS/database
administrators remain inside the trust boundary. This journal covers the
instrumented runtime API paths; independent/background Python activity is not
automatically attributed to an operator.

## Runtime diagnostics

Open **Diagnostics** to inspect cached connection and tag state. The page shows
configured routes, connected/disconnected/disabled/held status, errors, effective
scan groups and counters. Counters mean pycomm3 read calls/requested addresses,
not measured wire packets. Scan intervals remain best effort.

Tag rows show logical source/type, quality, observation timestamp, age and error.
An unsuccessful read's timestamp describes that failure observation, not the
last valid PLC acquisition. Bad/stale values are not presented as usable values.
Filtering/pagination bounds the display; JSON export includes at most 5,000 matching
tag rows and indicates truncation. Diagnostic exports omit tag values and HMI
authentication credentials.

The view reads cached state and does not introduce screen-tag scan demand or PLC
writes. Other viewers, expiring prior leases, alarms and historian demand may keep
acquisition active. Normal polling/reconnect remains owned by the runtime service.

## Permissions and validation

`activity.view` and `diagnostics.view` control these views/exports. Security
administrators can inspect both, including projects whose administrator group
predates these permission names. New Engineers groups include both; existing
groups are preserved and can be granted the permissions through **Security**.
Unsecured simulation keeps its explicit unsecured behavior. Neither viewing
permission grants command, value-write or acknowledgement privileges.

Local API checks cover attribution, denials/limits, partial effects, storage
failure, retry-without-replay, restart, retention, CSV safety and backup/restore.
Diagnostics checks cover pending/stale/bad/disabled/held states without network
PLC access. Browser checks cover the protected pages, filtering and export.
Controller and Windows/domain commissioning remain separate milestones.
