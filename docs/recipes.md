# SQL recipes and management of change

OpenHMI recipes are versioned product/setup records, with typed parameters and an
optional image identifying the product to operators. They live in SQL tables in
the project's SQLite database, separately from screen drafts and alarm history.

## Change model

* Every content save creates a new immutable revision: title, description,
  parameter definitions/values, image ID, author, parent revision and change reason.
* Draft revisions can be submitted for review. Submitted content is frozen.
  An approver records approval or rejection with a reason and timestamp.
* Approved content is immutable. A later edit starts another draft; it does not
  replace the approved revision or current production selection.
* Approval references the exact content hash. Images are immutable SQL blobs,
  addressed by the hash of their normalized PNG content, and are part of that revision.
* Concurrent saves/reviews/selections use expected version checks. Stale requests
  fail instead of overwriting a newer operation.
* A chronological audit records creation, content changes, review decisions,
  withdrawal, production selection, policy changes and simulator interlock changes.
  Content revisions and history have no deletion endpoint.

## Management structure

Recipe mutations require a signed-in account configured on the server. Roles are
engineer (author/submit), approver (review/withdraw), operator (select), and
administrator (manage policy and perform role operations). By default an author
cannot approve their own revision, including when they are an administrator.
Policy changes are version checked and require an administrator's reason.

Editing and approval can each be frozen, or tied to a configured Boolean permit
tag. Production selection starts disabled. When enabled, it requires an approved
revision, a true recipe-change permit and, by default, a stopped machine.
Missing, invalid or unavailable interlock values block the operation. The server
checks policy, role, exact revision and interlocks in the same operation that
records a change. The UI cannot bypass these checks.

Selection records the approved revision ID and its content hash. New approvals
never select themselves. Selecting an older approved revision is an explicit,
audited selection under the same operating rules. A selected revision cannot be
withdrawn until another approved revision is selected or the selection is cleared.

## Screens

The generic editor manages recipes, parameter rows, images, reasons, revision
comparisons and review/history. The operator viewer shows approved recipes and
the selected production revision, with its image and parameter values. Previewing
a recipe is distinct from selecting it. A reusable HMI control shows the current
selection so the operator can identify the selected product on a custom screen.

## Initial scope

This is a local application workflow. Recipe authentication does not retroactively
authenticate the existing simulator/alarm APIs. Server-managed accounts establish
identity for recipe operations; this is not a qualified electronic-signature or
regulatory-compliance claim. Trusted Python code and database administrators remain
inside the application's trust boundary.

Selection is an HMI-side record, not proof of a controller download or readback.
The first PLC adapter will need an explicit transfer/acknowledgement transaction
and commissioning checks. Images identify products; no customer images are shipped.
