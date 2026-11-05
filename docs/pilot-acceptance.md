# M6 Windows pilot acceptance

Use a designated non-production Windows station and an approved project copy.
Record the runtime and operator accounts separately. Before connecting a PLC,
complete the relevant [M2 bench checks](plc-bench-acceptance.md) and agree the
[M3 command](command-transactions.md) and [recipe transfer](recipe-transfers.md)
contracts. Keep project backups, controller addresses, identity mappings and
site evidence private.

## Identify the trial

Record the pilot machine and acceptance owner, Windows edition/build, domain or
workgroup, runtime account, browser/version, display resolution and scale, input
devices, languages, PLC model/firmware, and the approved tag/write boundary.
Record the package source commit and ZIP SHA-256, project backup SHA-256, active
project revision and an identifier for any trusted external handler.

Agree which rows below apply, who will execute them, and what limits determine a
pass. For each row retain the expected result, observed result, time, evidence
file and a disposition of pass, fail, deferred or owner-approved out of scope.

## Acceptance matrix

| Check | Run on the designated station | Evidence to retain |
| --- | --- | --- |
| Install and preflight | Verify the archive hash. Extract or install under the intended account. Run `--self-check` and `--preflight` against the intended library, log directory and port. Start with the approved launch command. | Manifest and hash, Windows build, account role, preflight JSON, runtime startup log and observed URL. |
| Runtime ownership and restart | Stop with Ctrl+C and wait for shutdown. Restart on the same port and library. Try a second launch against the same test library on a different free port. | Shutdown and restart logs, return codes and second-launch rejection. Verify the existing runtime kept serving its project. |
| Accounts and permissions | Run the [Windows mapping check](security.md#review-saved-mappings-on-the-target-windows-host) and [credential rehearsal](security.md#rehearse-windows-credentials-and-hmi-grants) if Windows login is in scope. With approved test accounts, exercise local and intended Windows login in the HMI. Check direct and group mappings, allowed and denied edits/actions, session expiry, logout, revocation and domain-unavailable behavior where applicable. | Private SID and credential rehearsal reports, expected and observed HMI groups, visible lock legend, denied operations and activity IDs. Exclude passwords and tokens. |
| Normal, abnormal and disconnected display | Use the approved normal and fault scenarios. Check color-independent state cues, bad-quality indicators, touch entry, focus order, dense screens and translated text at the intended display scale. | Operator-reviewed screenshots and observed input/display behavior by language and state. |
| Runtime fault isolation and recovery | Exercise the agreed [fault and endurance profile](runtime-readiness-roadmap.md#m6--resilience-and-pilot-gate). Interrupt one PLC route while another serves fresh data. Verify quality and age, bounded recovery, continued independent work and reconciliation without replay after runtime restart. | Route and worker status, quality transitions, downtime, resource usage, logs and operation IDs. |
| Camera view, when in scope | Verify the approved camera on the operator browser and network. Exercise PLC address quality, manual and PLC-triggered refresh, and blocked or unavailable camera behavior. | Camera model/firmware, browser version, private test evidence and supported viewing modes. |
| Alarms, trends and history | Exercise the approved trigger, cause/recovery text, acknowledgement, history and any authorized shelving. Run and stop a trend or use approved trigger tags. Export the agreed history window. | Alarm occurrence and journal IDs, recovery text, trend/CSV samples and quality/timestamp observations. |
| Commands and recipes | On approved M3 channels only, verify permits, acceptance/completion, timeout/recovery and readback of the PLC-owned recipe copy and production bit. | PLC and HMI trace for each sequence, result, staging/copy verification and observed recovery. |
| Controller communication | Use the representative screen, alarm and historian demand. Compare the HMI read-call and address counters with independent controller-load and acquisition measurements. Perform only the agreed communication-loss drill. | M2 diagnostics snapshots, comparison, controller-side load readings, timing limits and recovery observations. |
| Live editing and revision recovery | On the project copy, apply a visible edit, compare the prior revision, stage a screens-only rollback, review the staged draft and apply it. | Old, edited and rollback revision IDs, source revision, reason, retained recovery copy and operator-visible result. |
| Backup and restore | Export a complete backup. Import it under a new project ID and check acquisition hold before any apply. Inspect saved users/groups, recipe data/images, alarms, history and recovery records as applicable. | Archive hash, original and clone IDs, hold status and observed preserved records. Confirm no command replay. |
| Application update and rollback | Back up the project, stop the runtime, then install and select the new binary. After checking the copy, select the retained prior binary. Use the matching pre-update project backup if database compatibility requires it. | Both binary hashes, selected version and startup evidence, preserved external files and recovery results. |
| Deployment and handoff | Record the chosen foreground or separately validated startup model, access scope, release/signing decision, support contacts and response to a failed check. | Owner-approved deployment configuration, deferred items and final decision. |

## Rehearse recovery before the pilot

The [Windows package drill](windows-package.md#contributor-build) verifies an
extracted executable with synthetic local data. It imports a backup, checks
acquisition hold, and exercises a staged screens-only rollback on the restored
copy. The rollback creates a new applied revision and keeps the saved image and
trend CSV. The [package manager drill](package-management.md#contributor-check)
checks application selection and rollback separately.

For target recovery, preserve the original package, project, backup and logs.
Keep imported PLC connections held while reviewing the restore. Applying a
reviewed configuration can release hold, so use the PLC-free rehearsal copy
until controller acceptance permits an actual apply.

## Sign-off

Review all applicable results with the engineering and operator owners. Record
the owner, decision, date and any accepted limits or remaining actions. The local
software drills can supply rehearsal evidence. Clean-machine, credential,
controller and operator acceptance require observations from their designated
environments.
