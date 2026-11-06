# M2 ControlLogix bench acceptance

Use this procedure on the designated non-production controller. Confirm the
controller and firmware, route, allowlisted read-only tags, permitted scan rates,
controller load limits, disconnect method and evidence owner before starting.
Keep actual routes, addresses, diagnostics and controller exports in private
evidence storage.

The [driver readiness roadmap](runtime-readiness-roadmap.md#m2--controllogix-acquisition-and-recovery)
defines the fault profile, supported tag checks and measurements. Agree the
scan, acquisition age, recovery and controller load limits for this bench.

The operator header labels a route **Scan overdue** when a scheduled scan
remains in flight for at least five seconds or the configured socket timeout,
whichever is longer. Diagnostics shows the elapsed time. A completed scan
clears the in-flight warning. Tag quality and the route's disconnect/reconnect
status continue to reflect their own evidence.

## Run the offline scan baseline

From a source checkout with OpenHMI installed, create a report at a new path in
the existing local evidence directory.

```powershell
New-Item -ItemType Directory -Force .local | Out-Null
python scripts/benchmark-logix.py --output .local/driver-baseline.json
```

The baseline uses the actual driver scheduler and a synthetic adapter. It runs
the same workload on one route and then on two routes, with fixed adapter delays
of 3 ms and 80 ms. Two viewers request 100 ms and 500 ms updates. Each route has
24 scalar addresses, a shared UDT, an indexed element and separate alarm and
historian demand. The tool checks that overlapping aliases and UDT members
collapse into one address, then injects a disconnect on the slower route and
checks that the primary route keeps good sample quality while it recovers.

The JSON report includes per-alias good sample age, quality observation counts,
scheduler dispatch time, adapter read time, scan lateness, read calls,
requested addresses and route recovery time. Timing summaries use bounded
nearest-rank p50/p95/p99 windows. Route counters and rolling scan timings include
the initial warm-up and are cumulative within a scenario. Sample age is observed
at the scheduler tick, so observations can reuse the same acquired sample.
Compare runs on the same host and record concurrent workload. The numbers describe
synthetic adapter calls and scheduler behavior. Wire packets, PLC load, metadata
upload cost and production scan limits require the controller bench below.

## Prepare the read-only project

From a source checkout, create a bench project and backup using the reviewed
route, screen intervals and logical bindings. The generator works offline.
This example uses a placeholder route and tag names:

```json
{
  "route": "192.0.2.10/0",
  "overview_update_ms": 2000,
  "comparison_update_ms": 1000,
  "comparison_tags": ["BenchRunning"],
  "tags": [
    {"name": "BenchRunning", "address": "Motor.Status.Running", "type": "boolean"},
    {"name": "BenchLevel", "address": "LevelSamples[3]", "type": "number"}
  ]
}
```

```powershell
python -m examples.build_bench bench-input.json .local/bench-run
```

The output directory must be new. The database has a `.hold` sidecar and the
backup is held when imported. Keep the sidecar beside the database when opening
it directly. The generator creates display controls for up to 100 scalar
bindings, including UDT members and individual indexed elements. Supported types
are `boolean`, `integer`, `number` and `string`. Labels, scale and offset are
optional. Omit both comparison fields for an overview-only project. Set
`program_tags` to `true` when the approved addresses include program-scoped
tags. Once acquisition is enabled, pycomm3 still discovers controller metadata
and may read the underlying word for a bit binding. Review that traffic within
the approved controller limits.

1. Record the controller identity and firmware, OpenHMI source commit or package
   SHA-256, and the driver/runtime versions from `openhmi --self-check`.
2. Use a dedicated project with the agreed read-only bindings. Verify tag write
   flags are clear. Omit command and recipe-transfer channels, PLC identity
   publication and custom Python handlers. Review imported projects while
   acquisition is held.
3. Include the approved representatives of each required scalar, UDT member and
   indexed array type. Document the expected type, dimensions, scale and source
   value from an independent engineering view of the controller. Leave the
   controller and its tag values under the bench owner's control. Record the
   discovered integer widths and declared STRING capacities for later controlled
   write tests.
4. Start with one approved slow-rate screen. Record which viewers, alarms and
   historian settings contribute demand. Apply the reviewed configuration to
   start acquisition.

For the overlap check, leave the overview open in one viewer and open
`/runtime?screen=comparison` in another. The comparison screen requests only
the approved subset at its configured interval.

## Record read-only results

| Check | Evidence to retain |
| --- | --- |
| Binding and quality | Logical tag, controller address, expected/observed type and value, quality and source time. Record unsupported types or address shapes explicitly. |
| Stable scan and grouping | Capture Diagnostics before and after a stable interval. Record the requested screen rates, actual effective groups, pycomm3 call/requested-address deltas, recent scan duration/lateness and representative tag timestamp changes. Repeat with the approved overlapping screen demand to check shared-tag grouping. |
| Controller load | Record independent controller-side load and communication measurements before OpenHMI, then during the agreed demand. Compare with the owner's limits. Stop acquisition if a limit is exceeded. |
| Communication loss and recovery | With the approved disconnect method, retain before/loss/recovery Diagnostics. Record quality transitions, elapsed recovery time, resumed scan groups and whether readings matched the engineering reference after recovery. |
| Decision | Record date, operator/owner, environment, measured limits, evidence filenames, and pass, fail or deferred for each check. Keep failures and their retest results. |

In **Diagnostics**, use the JSON export twice with the same open project, connection
and screen demand. Use a stable interval long enough to represent the selected
rates. Keep the runtime running and the configuration fixed between captures.
Run the comparison from a source checkout, using a new output path:

```powershell
python scripts/compare-plc-diagnostics.py before.json after.json --connection bench --output comparison.json
```

The comparison requires the same runtime session, connection instance and scan
groups at both endpoints. It reports average pycomm3 read calls and requested
addresses per second over the observed interval. Current exports also reject
an interval where the driver detected a route failure. Record controller load,
wire-packet counts and per-tag sample cadence separately.

Keep the individual snapshots for the disconnect test. Each route's rolling
timing summaries include up to 256 observations per metric and show the last
value, sample count and nearest-rank p50/p95/p99. These windows can include
observations from before the capture interval.

* **Read cycle** measures a scheduled batch from when it can access the route
  until its read returns or fails. It includes connection setup if needed.
* **Scan start lateness** measures how late the batch started relative to the
  earliest existing deadline among its due addresses. First reads with no
  prior deadline do not contribute.
* **Scan worker queue** measures submission to the start of the worker.
  **Route lock wait** measures how long that worker waits to acquire the route,
  including contention with commands and writes. Both cover due scan batches.
* **Adapter read call** measures a call to pycomm3 after route acquisition and
  connection setup. It includes failed attempts and recipe verification reads.
  A scheduled batch can make several calls. Direct write readbacks have their
  own transaction path.
* **Initial connection** and **Reconnect** report successful open and tag
  metadata setup time. **Loss to first good read** measures from the first
  detected route failure to the acquisition time of the first good sample
  published after recovery. Keep demand active for a comparable result.

## Release to controlled write tests

Close the read-only portion only after the owner accepts the recorded evidence.
Before controlled writes, agree the exact writable tags, expected outcomes,
recovery procedure and the PLC-side [command](command-transactions.md) and
[recipe transfer](recipe-transfers.md) contracts. The demo controller and its
read-only preview have a separate purpose. They do not establish bench acceptance.
