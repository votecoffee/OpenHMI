# Runtime readiness roadmap

The ControlLogix driver has a working software baseline. Production readiness
and optimization remain open until the supported controller, tag and load
profiles are measured. The next work prioritizes reliable acquisition and
truthful operator feedback. The camera control can be prototyped independently.

## Product references

| Reference | Expected capability for OpenHMI | Scope |
| --- | --- | --- |
| Ignition tag groups and quality overlays | Reusable scan profiles, screen-demand polling, clear per-tag quality and timestamps. OpenHMI already accepts screen rates and merges demand. Add explicit scan profiles or triggered acquisition where measured demand warrants them. | M2/M5 quality and timing first. [Tag Groups](https://docs.inductiveautomation.com/docs/8.3/platform/tags/tag-groups), [Quality Codes and Overlays](https://docs.inductiveautomation.com/docs/8.3/platform/tags/quality-codes-and-overlays) |
| Ignition Perspective and FactoryTalk View ME | Parameterized equipment views, popups, shared navigation and station chrome, and controller-linked display status. Build on the existing UDT faceplates and high-performance visual templates. | M5 equipment library, chosen with operators. [Perspective Views](https://www.docs.inductiveautomation.com/docs/8.3/ignition-modules/perspective/views-in-perspective), [FactoryTalk View ME User's Guide, chapters 8 and 25](https://literature.rockwellautomation.com/idc/groups/literature/documents/um/viewme-um004_-en-e.pdf) |
| Ignition alarming and FactoryTalk View ME | Operator alarm review, recovery guidance, journal, acknowledgement and audible workflows. OpenHMI already has the alarm list and history. Define PLC acknowledgement and silence ownership during commissioning. | M5 handshakes and operator review. Consider remote notifications and escalation after the pilot. [Ignition Alarming](https://docs.inductiveautomation.com/docs/8.3/platform/alarming), [FactoryTalk View ME User's Guide, chapters 9 and 10](https://literature.rockwellautomation.com/idc/groups/literature/documents/um/viewme-um004_-en-e.pdf) |
| Ignition Inline Frame and PanelView Plus | An embeddable web view and a way to put a camera on a machine screen. Treat camera media support as a separate compatibility check. | M5 browser and camera control. [Ignition Inline Frame](https://docs.inductiveautomation.com/docs/8.3/appendix/components/perspective-components/perspective-display-palette/perspective-inline-frame), [Ignition Video Player](https://www.docs.inductiveautomation.com/docs/8.3/appendix/components/perspective-components/perspective-display-palette/perspective-video-player), [PanelView Plus 7 Standard manual](https://literature.rockwellautomation.com/idc/groups/literature/documents/um/2711p-um007_-en-p.pdf) |

## M2 — ControlLogix acquisition and recovery

The [driver](../openhmi/logix.py) merges active screen leases and background
demand, picks the fastest requested interval for shared demand and deduplicates
addresses per connection. It issues scheduled reads and caps each pycomm3 call
at 200 addresses. pycomm3 handles CIP Multiple Service Packet packing and
fragmented transfers. A pycomm3 read call may generate multiple wire packets.
The runtime already records sample quality and age, applies reconnect backoff,
and reads back writes. [pycomm3 LogixDriver documentation](https://github.com/ottowayi/pycomm3/blob/master/docs/usage/logixdriver.rst)

1. **Isolate routes.** Each configured route now has at most one outstanding
   scan and serializes its reads, writes and readbacks. The acquisition loop
   continues scheduling healthy routes during a slow read or reconnect. Route
   loss invalidates all its aliases, and each alias needs a fresh read before
   its value becomes available again. A simulated two-route regression verifies
   isolation and rejects results from a superseded configuration. Verify this
   behavior on the bench and keep tag-level errors distinct from route failures.
2. **Measure before tuning.** The current schedule includes scan duration and
   the polling loop delay. Diagnostics now reports rolling p50/p95/p99 for
   scan duration and start lateness, successful opens and loss to first good
   data. Record these along with requested rates, representative tag ages,
   controller load and errors on the bench. Test mixed-rate screens, overlapping aliases, alarm/history demand,
   multiple routes, and a slow or disconnected route. Label calls and requested
   addresses separately from packet counts measured by a capture or controller
   diagnostics. Agree load and latency bounds for the intended project profile.
3. **Reduce avoidable work.** Profile repeated control expansion, alias matching
   and tag metadata discovery on reconnect. Cache resolved demand and alias
   indexes with explicit invalidation when project bindings change. Keep a
   bounded schedule that coalesces missed polls. Tune batching and metadata
   initialization using evidence from the profile and type checks.
4. **Document the supported tag contract.** Exercise BOOL, integer, REAL and
   STRING values, controller and program scopes, nested UDT members and arrays,
   packed bits, fragmented reads, and tag-level failures. Check string capacity,
   64-bit integer precision across the browser boundary, and unsupported types.
   A grouped read can span multiple transfers. Use the PLC transaction contract
   when a coherent snapshot matters. Record the supported controller, firmware,
   route and pycomm3 version for each tested profile.

Run deterministic faults and benchmarks first. Then follow the
[read-only bench procedure](plc-bench-acceptance.md) on an identified
non-production controller before any separately approved write testing.
Track [driver hardening #12](https://github.com/votecoffee/OpenHMI/issues/12)
and [bench acceptance #3](https://github.com/votecoffee/OpenHMI/issues/3).

## M5 — Operator quality and camera control

**Data quality.** The [runtime](../frontend/live-quality.jsx) now separates
browser-to-runtime reachability from individual PLC routes. The header names
affected routes during partial outages. Bound displays, charts, current trend
readouts and edit controls distinguish waiting, held, disabled, disconnected,
recovering, stale and bad data. Inspect a quality badge for the source time,
age and reason when available. Stale values remain unavailable for display and
permit decisions. Preserve gaps and quality in history and trends. Loss of a
sample must never appear as an alarm returning to normal. Verify partial outages
and fresh recovery on the target display in dense screens and popups.
[Operator quality #13](https://github.com/votecoffee/OpenHMI/issues/13)

**Web Browser and Camera View.** The [drag-and-drop control](web-browser-camera.md)
is available in the designer. Accept a fixed address or bind a PLC STRING containing a host
or approved HTTP(S) URL. Configure the scheme, host allowlist, port and path
in the project. Validate the address before navigation and show unavailable
when its quality is bad or stale. Support manual reload and an optional
read-only PLC BOOL rising edge or sequence change. The first good value
establishes the trigger baseline. Coalesce requests, rate-limit reloads and
resume on fresh trigger data. No PLC writes are needed for the first version.

The initial control uses a restricted iframe and an operator-visible unavailable state. Test
blocked framing, mixed content, local-network access, vendor authentication,
unreachable cameras and stale PLC address/refresh tags. An iframe load event
alone cannot establish that video is healthy. Offer an explicitly configured
open-in-tab or a tested still-image/browser-video mode for supported endpoints.
Keep arbitrary proxying, camera admin functions and RTSP conversion out of
the initial scope. Validate with controlled fixtures and then the representative
camera, operator browser and station network.
[Camera control #14](https://github.com/votecoffee/OpenHMI/issues/14),
[HTML iframe rules](https://html.spec.whatwg.org/multipage/iframe-embed-object.html#the-iframe-element),
[Chrome local-network access](https://developer.chrome.com/docs/modern-web-guidance/guides/security/local-network-access)

## M6 — Resilience and pilot gate

The [server](../openhmi/server.py) now schedules acquisition, commands,
alarms, trends, historian, activity maintenance and PLC identity independently.
Each worker has one invocation in flight and retries exceptions with backoff.
[Diagnostics](activity-and-diagnostics.md#runtime-diagnostics) reports last
success, retries and overdue work. Workers still depend on shared resources such
as SQLite. Shutdown drains in-flight work before releasing resources and logs
delayed or failed cleanup. A hard upper bound on shutdown and I/O waits remains
part of qualification. Verify restart under
the supported Windows launch method and recovery when the network, controller,
database or a trusted Python handler fails. Preserve durable command/recipe
state and require reconciliation of uncertain operations after restart.

Inject timeouts, repeated disconnects, controller reboot, malformed results,
unavailable storage, handler failures and process restarts in an isolated
test profile. Verify the runtime stays available through recoverable faults,
healthy routes and unrelated features continue, and operator quality reflects
the fault. A proposed starting gate is a 24-hour offline load and fault soak
with zero unexpected exits and zero command replay or duplication. Agree
resource, latency and recovery bounds for the test profile before running it.
The [offline soak runner](runtime-soak.md) provides a repeatable ASGI rehearsal
with simulated PLC faults, read-only storage and a durable command reopen check.
Confirm the relevant cases on the designated Windows station with the
[pilot matrix](pilot-acceptance.md).
[Runtime resilience #15](https://github.com/votecoffee/OpenHMI/issues/15)

## Post-pilot candidates

Prioritize from operator feedback and measured demand. Candidates include more
equipment templates and I/O diagnostics, reusable scan profiles, alarm
escalation and shift reporting, then broader device connectivity such as OPC UA
and Modbus. Consider multi-station deployment and redundancy once the
single-runtime failure and recovery contracts are proven. M7 remains deferred.
