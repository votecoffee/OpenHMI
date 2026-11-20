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
| Schema ownership/import compatibility | `test_project_models.py`: direct family/domain imports, no service/HTTP/Pillow/SQLite dependency, shared canonical/legacy classes and project round trips | Import isolation is not a runtime performance or packaging benchmark |
| Runtime faults and status | Domain tests and selected browser fault-injection workflows for stale/bad data, malformed responses and recovery | Response DTO parity is not yet a complete cross-language schema contract |

## Closed in this increment

Command buttons and the transaction console now use `command-api.mjs`. Existing
latest-status query ordering, console defaults, pagination filters and download
URLs are preserved. Tests use actual generated requests and the real registrar;
invalid limits, cursors, state values, names and transaction IDs must fail before
service calls. The query tests include string-form signed-64-bit limits without
converting them through a JavaScript Number.

This does not make large numeric JSON response IDs lossless. Existing command
status validators require safe JavaScript integers. A broader wire-format change
for IDs needs a separate compatibility decision; do not silently round an ID or
coerce it just to satisfy a test.

## Next bounded work

1. Cover image-library search/pagination builders and actual router binding.
   Uploads and picker browser behavior are covered, but GET query construction is
   still embedded in `image-picker.jsx` and absent from the shared request harness.
2. Add equivalent coverage for historian/trend read-window and export queries.
   Existing Python and browser tests remain useful, but these queries are not
   exercised by the new command-query contract test.
3. Prioritize response contracts for shared operator status pages using the
   actual browser validators and representative server responses, including
   malformed/missing fields and permission loss. Review older nullable/history
   data before adding strict response filtering to a production endpoint.

Keep further refactoring tied to a boundary or contract gap in this list rather
than file size alone. See [extending controls](extending-controls.md) for the
contributor workflow and [architecture](architecture.md) for retained lock,
transaction, transport and quality ownership.
