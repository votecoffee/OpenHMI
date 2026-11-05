# M2 ControlLogix bench acceptance

Use this procedure on the designated non-production controller. Confirm the
controller and firmware, route, allowlisted read-only tags, permitted scan rates,
controller load limits, disconnect method and evidence owner before starting.
Keep actual routes, addresses, diagnostics and controller exports in private
evidence storage.

## Prepare the read-only project

1. Record the controller identity and firmware, OpenHMI source commit or package
   SHA-256, and the driver/runtime versions from `openhmi --self-check`.
2. Use a dedicated project with the agreed read-only bindings. Verify tag write
   flags are clear. Omit command and recipe-transfer channels, PLC identity
   publication and custom Python handlers. Review imported projects while
   acquisition is held.
3. Include the approved representatives of each required scalar, UDT member and
   indexed array type. Document the expected type, dimensions, scale and source
   value from an independent engineering view of the controller. Leave the
   controller and its tag values under the bench owner's control.
4. Start with one approved slow-rate screen. Record which viewers, alarms and
   historian settings contribute demand. Apply the reviewed configuration to
   start acquisition.

## Record read-only results

| Check | Evidence to retain |
| --- | --- |
| Binding and quality | Logical tag, controller address, expected/observed type and value, quality and source time. Record unsupported types or address shapes explicitly. |
| Stable scan and grouping | Capture Diagnostics before and after a stable interval. Record the requested screen rates, actual effective groups, pycomm3 call/requested-address deltas and representative tag timestamp changes. Repeat with the approved overlapping screen demand to check shared-tag grouping. |
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
addresses per second over the observed interval. It cannot establish intervening
demand or network state, controller load, wire-packet counts or per-tag sample
cadence from two snapshots. Record those separately as required by the matrix.
For the disconnect test, keep the individual snapshots and times instead of a
steady-interval comparison.

## Release to controlled write tests

Close the read-only portion only after the owner accepts the recorded evidence.
Before controlled writes, agree the exact writable tags, expected outcomes,
recovery procedure and the PLC-side [command](command-transactions.md) and
[recipe transfer](recipe-transfers.md) contracts. The demo controller and its
read-only preview have a separate purpose. They do not establish bench acceptance.
