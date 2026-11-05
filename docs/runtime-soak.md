# Offline runtime fault rehearsal

Run from a source checkout with the test dependencies installed
(openhmi[test]). Choose a new evidence folder. The runner creates its own
project and two synthetic PLC routes. It uses in-process ASGI requests,
blocks the real pycomm3 driver, and accepts no controller or project inputs.

Start with a short rehearsal:

    python scripts/soak-runtime.py --work .local/soak-short --seconds 60 --fault-every 12 --viewers 4

For the proposed 24-hour offline run, record the source commit and agree the
load and acceptance limits before starting:

    python scripts/soak-runtime.py --work .local/soak-24h --seconds 86400 --fault-every 60 --viewers 4 --recovery-timeout 10 --max-p95-ms 1000

The duration covers the repeating fault/load phase. Startup and the final
restart drill add time. Each viewer keeps a screen lease active and makes
concurrent tag requests. The runner alternates delayed route disconnects and
malformed reply batches. Each cycle verifies usable data from the healthy
route, exercises a local operator action, temporarily makes SQLite read-only,
checks that the historian reports a retry, and checks that the journal blocks
a command before dispatch. Both routes and the historian must recover. The
final drill closes and reopens the runtime on the same database with one
synthetic command pending. It verifies the applied project and audit entry,
rejects a duplicate dispatch, and reconciles from PLC-owned readback with
exactly one synthetic write.

Retain the following evidence from the new folder:

- **report.json** records pass/fail, profile, phase recovery, total request
  count, maximum latency, and p95 for the most recent 4,096 requests. The
  p95 limit check counts all requests in the run, including earlier samples
  outside that window.
- **events.jsonl** records fault boundaries, recovery times, operation IDs,
  and periodic process CPU time, Python heap and SQLite file sizes. The
  Python heap figure comes from tracemalloc and excludes native allocations.
- **runtime.log** and its bounded rotations retain worker exception traces.
  SQLite read-only errors are expected during injection.
- **Soak.openhmi.sqlite3** retains the synthetic project and its durable
  activity, history and command records.

The phase timeout bounds the runner's recovery checks between ASGI calls.
Process watchdog behavior, hard shutdown, actual network and controller
load, native memory, and operator-station validation are separate acceptance
work. Run the [pilot matrix](pilot-acceptance.md) on the target Windows station.
