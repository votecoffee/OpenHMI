# Project revisions and recovery

OpenHMI retains applied project configurations with content hashes, recorded
users, reasons and rollback provenance. **Revisions** supplies history, comparison,
draft staging and recovery review. Rollback stages a draft; **Apply live** records
a new revision. It never rewinds the active revision counter or PLC memory.

## Applied history and staged rollback

Every changed live apply commits its configuration snapshot and history row in
the same SQLite transaction. A history insert failure leaves the active project
unchanged. Ordinary no-change apply adds no duplicate history entry. A deliberately
staged historical revision creates a new applied revision even when its final
content matches the active content. Subsequent edits remain derived from that
staged source. Apply reasons are optional in the builder; a staged rollback reason
is retained when the default apply reason is used.

The server records the authenticated HMI user/provider. With global HMI security
unconfigured it explicitly records `unsecured-simulation`; trusted Python calls
without an identity use `system`. Revision/recovery APIs require `project.edit`,
including read-only comparison and export. History is configuration evidence,
not a tamper-proof signature or an equipment commissioning record.

1. Open **Revisions** and choose **Compare revision**.
2. Select the scope and review differences against both the current draft and the
   active project. Paths use stable object identities, such as
   `/controls/@level/label`; `@order` describes collection order.
3. Enter a restore reason and choose **Stage revision as draft**. The server
   retains the previous draft as a recovery copy before replacing it.
4. Open the staged draft in the editor, review it, then choose **Apply live**.
   The new history row identifies the source revision and actual applying user.

**Screens and presentation only** is the default. It restores title, columns,
controls, update rates, screens/popups, faceplates and language presentation.
It retains the current draft's connections, tags, command/recipe transfer
contracts, historian and alarm-monitor configuration. Existing unapplied changes
to those settings remain in the draft and must also be reviewed before apply.

**Full project configuration** stages all configuration fields, including drivers,
tag definitions and application contracts. Current binding validation applies:
unavailable Python actions, unknown groups or incompatible tags can prevent
staging. Outstanding command/recipe transactions prevent an incompatible live
apply. No rollback path bypasses those checks or sends tag/command writes.

Unchanged driver configurations retain their connections and current local tag
values. Deliberately changed full-project driver/tag settings follow normal apply
semantics, which may reconnect a changed source or reset a changed local tag's
initial value. This is configuration restoration, not restoration of live values.
Recipes/reviews/images/selections, accounts/groups, alarms/history, command and
recipe-transfer records are separate SQL data and are not rolled back.

## Stale editors and browser recovery

Autosave keeps the editor's last acknowledged base and current local candidate.
Pending local edits are retained in browser storage before the debounce expires.
Each project identity, account and browser tab has its own key, so another tab's
successful save cannot clear this tab's candidate. A server restart keeps the
project identity; opening another project changes it. A backup import receives a
new clone identity so its browser candidates are not confused with the original.

On a revision conflict, saves are blocked and **Recover editor changes** opens.
Reloading the same tab restores a retained candidate into this review rather
than autosaving it over the server draft. The **Revisions** page also lists browser
copies for the current project/account, including copies left by closed tabs.
Storage is local to the browser profile, not an authenticated server vault.
A transient identity-status poll failure retains the last confirmed sign-in with
a visible availability notice; it does not grant server permission. Every operation
is authorized by the server, and a confirmed logout/expiry updates the UI normally.
If storage is unavailable/full, the builder reports that export is needed;
unsaved memory/browser candidates are not part of a server backup until retained
or merged on the server. Browser profile deletion removes unexported browser data.

The review compares three documents: the acknowledged **base**, the **local**
candidate, and the **current** server draft. Independent edits combine by stable
control/screen/tag/etc. identity. Overlapping value changes, delete-versus-edit
and incompatible types require a local/current choice. JSON Boolean values remain
distinct from numeric 0/1. Unrecognized arrays (including tag initial-value arrays)
are atomic conflicts rather than silently merged by index.

Collection order changes are reviewed separately. When both editors add different
objects, choosing an order retains the other editor's surviving additions.
Every overlapping change needs an explicit choice. The resulting draft still has
to satisfy the project schema and current binding rules.

Choose **Save reviewed merged draft** after review. The server recomputes against
the expected current draft counter and preserves both the current server draft
and the local candidate in SQL in the same transaction. A concurrent save causes
a new conflict; it never forces an overwrite. **Refresh comparison** obtains the
latest server version and clears old choices without discarding the candidate.
Saving the merged draft does not apply it or change runtime subscriptions.

**Keep editing locally** closes review with server saves still blocked. The
builder's **Review local recovery / merge** reopens review. **Save recovery copy
on server** retains a copy without changing any draft/active project. Server
copies are shared project engineering records, visible to `project.edit` users.

## Export, import and retained copies

**Export local recovery JSON** downloads the complete base/local pair and its
reported base draft counter. **Import local recovery JSON** on Revisions opens
that pair for review. If a project identity is present, a mismatched project is
rejected. These files contain project configuration, not the application account/password
tables or the complete SQL application database. Recovery JSON imports are
bounded to 32 MiB. They are not complete project backups.
Exported applied revision JSON is for inspection; use history staging or a
complete backup for restoration.

History and recovery lists use bounded, paginated queries. Comparison displays
up to 500 change rows, explicitly showing the total when limited; individual long
values are abbreviated. Full revision/candidate exports retain complete content.
History and SQL recovery copies are retained for the project lifetime with no
automatic pruning. Their configuration hashes are checked on read, and all
retained copies/history are validated before an imported backup is published.

## Storage migration and restore boundaries

Project storage version 1 adds `project_storage`, `project_revision` and
`project_recovery` while keeping project document schema version 1. A supported
legacy database is validated first, then receives one baseline at its existing
active revision counter in an additive transaction. Existing draft/active data,
counters and unrelated application SQL tables remain intact. The baseline is
marked with migration time and actor `unknown`/provider `legacy`: it does not
invent earlier revision content, authors or original apply times.

Newer storage/document versions, incomplete history storage, damaged active
history and unrelated databases are rejected before migration writes. A current
active configuration must match its recorded applied revision. Stored hashes
detect corruption; privileged database edits remain inside the trust boundary.
No arbitrary future-version conversion is attempted. Broader future migrations
must declare supported versions and add corresponding validation.

Complete backups include applied history, server recovery copies and the rest of
the application SQL data. Import validates and migrates a temporary copy, checks
all history/recovery hashes/schemas, assigns a new clone identity and publishes
only under a new filename. The original source and existing projects are not
overwritten. Imported PLC connections remain held and imported Python remains
saved for review, with no automatic execution or command replay.

Offline checks cover history/apply transaction failure, provenance, identity-aware
merges, concurrent writers, permissions, legacy/future/corrupt storage, original
file preservation, driver/local-value preservation, unresolved command gating,
and complete backup/restore. Browser checks cover history comparison/staging/apply,
reload recovery, two-tab isolation, explicit merge choices and JSON export/import.
Actual PLC, native display/operator and Windows domain deployment acceptance
remain separate milestones. Packaged installation belongs to M6, not this storage
and recovery checkpoint.

Checkpoint evidence: 81 Python tests and 14 browser tests passed. The final
project-history browser checks also cover the completed dialog styling. Browser
assets and the Python wheel built with source/assets verified in the package.
No real PLC commissioning or Windows domain password logon was performed.
