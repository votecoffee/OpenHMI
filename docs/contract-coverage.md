# Schema and API contract coverage

This audit covers the production palette/serializers and the request paths named
below. It is not a claim that every API response or every possible query is
formally modeled. Controller, Windows station and operator acceptance remain in
the [project plan](project-plan.md). No PLC access or soak is required here.

| Boundary | Automated evidence | Practical limit |
| --- | --- | --- |
| Saved control schemas and palette | `test_frontend_contract.py`: real palette kinds, family/category uniqueness, defaults, select options and complete field-preserving round trips | Nondefault fixtures must be extended as behavior is added |
| Tag catalog and binding rejection | `test_engineering_contract.py`, `test_binding_rules.py`: real draft catalog to JS pickers, tag-type filtering, validation order and unchanged rejected drafts | A valid binding does not prove a physical PLC address exists |
| UDT faceplates | Real browser resolver compared with backend expansion across eligible controls, secondary screens and nested tag fields | Adding a new tag-bearing property requires both resolvers and fixtures |
| Value/actions, leases, project lifecycle and alarms | Actual browser helpers validated against strict request models; methods, headers, revisions and payload fields checked | Fake-fetch contract checks do not authenticate a real user or dispatch a controller write |
| Trend recording, station ownership and image upload | Actual capture/claim/renew/release helpers plus binary File upload contract checks | Read-page query construction and response payloads are separate boundaries |
| Command history queries and transaction export | `test_command_contract.py`: production builders to the real FastAPI registrar through an in-process client; every UI state matches the server enum, Unicode filters, bounds, integer IDs and export headers | History data and the security hook are stubbed; domain/browser tests cover behavior and permissions |
| Command transaction/history responses | `test_command_responses.py`: real SQL detail, filtered/cursor pages, exports and restart reconciliation across all eight states through production JS validators; malformed sequence/page browser recovery | Seeded offline lifecycle states do not prove PLC execution; nullable results/errors and empty event histories remain compatible |
| Image listing queries and pages | `test_image_contract.py`: production queries to the real registrar, Unicode search, cursor/page bounds, real SQLite pages to the actual JS validator and malformed-page rejection | Listing fixtures do not test image decoding; JSON paging cursors must be safe positive JS integers |
| Historian/trend reads and exports | `test_history_contract.py`: production paths through both real registrars; live/fixed windows, context, recorded tags, bounded/complete CSV, capture reads/CSV, invalid ranges and stale project guards | Data services are stubbed for query binding; existing domain/browser tests cover actual acquisition and export behavior |
| History windows and recording status responses | `test_trend_responses.py`: actual SQL sampling/query/listing through real HTTP registrars into production JS validators; context, truncation, quality, rollover, stopped/restarted captures and malformed replies | Offline sample snapshots do not prove acquisition; history supports equal epochs and different ordering between tags; optional legacy pen metadata remains accepted |
| Recorded-tag catalog responses | Real SQLite historian pages through `isRecordedTagPage`, malformed-page fixtures and browser no-crash/recovery regression | This is a bounded catalog response contract, not complete history/capture response parity |
| Schema ownership/import compatibility | `test_project_models.py`: direct family/domain imports, no service/HTTP/Pillow/SQLite dependency, shared canonical/legacy classes and project round trips | Import isolation is not a runtime performance or packaging benchmark |
| Activity/diagnostics queries and exports | `test_operations_contract.py`: actual production read helpers/URLs through the registrar; Unicode filters, UTC conversion, precise cursors, limits/defaults, project headers, CSV quoting/formula escaping and export permissions | Journal is real SQLite; driver metadata/security hooks are controlled offline fixtures; no browser-local timezone or controller acceptance claim |
| Activity/diagnostics responses | `test_operations_responses.py`: real SQL journal outcomes/pages/restart and actual driver/worker projections through the registrar into production JS validators; malformed paging and scan-age checks | Security is stubbed in contract fixtures; browser tests cover denial/recovery; fake transport does not establish PLC or station acceptance |
| Read-only diagnostics projection | `test_diagnostics.py`: catalog replacement at snapshot release, common snapshot time, worker read outside the driver lock, route fault precedence, filter/paging and value omission | Controlled boundary regression, not a concurrency stress benchmark; HTTP and browser contracts remain separate checks |
| Identity-session snapshots | `test_security_session_contract.py`: real SQL security service/session route into the production guard; local/expired sessions, live permission changes, mocked Windows mappings/disable, public fields and malformed payloads; validated read-helper errors | Windows authentication is mocked, not OS/domain acceptance; UI retains generation fences and last-confirmed identity behavior |
| Selected-recipe snapshots | `test_recipe_selection_contract.py`: actual SQL create/load/approve/revise/withdraw/clear/reopen responses into the production guard; images, Unicode, typed/safe-integer boundaries and malformed payloads | Security principal and local publication callback are stubbed; display guard covers consumed fields, while request models enforce full recipe limits; no PLC transfer or controller acceptance |
| Runtime faults and status | Domain tests and selected browser fault-injection workflows for stale/bad data, malformed responses and recovery | Response DTO parity is not yet a complete cross-language schema contract |

## Delivered query contracts

Command buttons and the transaction console now use `command-api.mjs`. Existing
latest-status query ordering, console defaults, pagination filters and download
URLs are preserved. Tests use actual generated requests and the real registrar;
invalid limits, cursors, state values, names and transaction IDs must fail before
service calls. The query tests include string-form signed-64-bit limits without
converting them through a JavaScript Number.

The project image picker now uses `image-api.mjs`. Query contracts preserve the
unfiltered URL, before/search ordering, Unicode search and server defaults, and
exercise explicit page limits. Real SQLite listing pages pass the production
browser validator. Missing/malformed/unsafe cursors, empty pages with a cursor,
duplicate IDs and malformed image entries are rejected. Browser regressions cover
forward/back paging, retaining the prior page on malformed replies, retry recovery
and clearing rows on access denial. Closing/new requests retain the sequence guard.

This does not make large numeric JSON response IDs lossless. Existing command
status validators require safe JavaScript integers. A broader wire-format change
for IDs needs a separate compatibility decision; do not silently round an ID or
coerce it just to satisfy a test. Image paging similarly rejects unsafe numeric
response cursors rather than rounding them into a different query.

Historian/trend query paths now come from `history-api.mjs` and `trend-api.mjs`.
Contracts preserve live versus fixed end times, epoch zero, fractional seconds,
context flags and CSV links without context parameters. Tests bind recorded-tag
prefix/cursors, enforce window/tag/count limits, preserve complete-export project
fences, check CSV quoting/headers and verify release of the complete-export slot.
The bounded History-panel CSV path retains its response project-header check;
complete exports retain their query project-instance fence.

Recorded-tag search pages are checked before entering React state. Real SQLite
pages pass the validator; missing items, invalid dates/cursors and duplicate tags
are rejected while readable prior choices remain usable with an error. Browser
checks require the editor to survive malformed success replies and recover.

Command response contracts now compare actual SQL-backed detail, export, filtered
and cursor pages, including restart reconciliation, with production validators.
Positive signed-DINT sequences, descending unique IDs, the 200-row bound and
last-row cursors are enforced. Malformed replies retain evidence with warnings;
buttons remain blocked and older-page navigation is disabled until recovery.
No strict HTTP response filtering or controller dispatch was added.

History/capture response validators are exported from `history-api.mjs` and
`trend-api.mjs`, shared by the production React controls and contract tests.
History must be chronological within each tag; equal epochs and interleaved tags
remain valid. Duplicate capture IDs and retained counts exceeding capacity are
rejected. Browser regressions retain readable traces/status through these faults
and restore normal controls after valid replies. Existing quality-gap handling,
nullable fields and source-time metadata are preserved.

Activity pages now validate positive safe IDs, descending unique rows, unique
operation IDs, the 1,000-row bound and last-row cursors. Diagnostics checks unique
tag names and coherent offset/count/cursor/truncation metadata, including empty
pages beyond the current result set. Nullable scan ages remain valid; objects
are rejected before numeric formatting. Browser regressions retain prior data,
disable forward paging, clear data on denial and recover on valid replies.

Activity/diagnostics list reads and export links now share focused API helpers.
Generated requests preserve existing filter order, local-date-to-ISO conversion,
string-form cursor precision and export scopes (without list paging parameters).
Contract tests bind those requests through the real registrar, verify explicit
limits and defaults, reject invalid bounds before reads, and require permission
checks before list/export service calls. Download formats remain unchanged.

The command/activity/diagnostics views now have focused modules. The app imports
them directly, with compatible component exports retained in `operations.jsx`.
View bodies and hook logic are preserved; existing browser regressions exercise
command feedback, stale actions, retained pages, access denial and recovery.
No saved-project schema, HTTP response shape or permission model changed.

Identity-session validation is now shared through `security-session.mjs` by
background polling, explicit login refresh and contract tests. The validated
read helper retains API timeouts and HTTP error status. The guard retains its
previous rules and returns the original object; contract tests reject malformed
identity/group/permission structures without coercion or mutation. Real service
responses exercise local and mock-Windows lifecycles without OS account changes.

Selected-recipe validation and its polling path now live in `recipe-selection.mjs`.
The app retains its prior failure/clear behavior, with guard rules unchanged. Real
SQL contracts preserve loaded copies across later approval, revision edits and
withdrawal, then validate clear/reopen results. Typed boundary fixtures include
zero/false values, Unicode text and exact integer limits; malformed shapes are
rejected without mutation. These fixtures use a stubbed local publication callback
and do not execute a PLC recipe transfer.

## Next bounded work

1. Extract alarm snapshot validation and verify state/annunciation responses,
   followed by applied-project snapshot compatibility.
2. Continue response parity across other operator pages as concrete gaps arise.
   Review older nullable/history data before adding strict response filtering.

Keep further refactoring tied to a boundary or contract gap in this list rather
than file size alone. See [extending controls](extending-controls.md) for the
contributor workflow and [architecture](architecture.md) for retained lock,
transaction, transport and quality ownership.
