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
engineer (author/submit/load), approver (review/withdraw), operator (load), and
administrator (manage policy and perform role operations). One person may hold
multiple roles and approve their own changes. Approval records the actual signed-in
user, timestamp and review comment. Policy changes are version checked and require
an administrator's reason.

Editing, approval and loading can each be enabled/frozen, or optionally tied to a
configured Boolean application permit tag. They start enabled with no application
permit. Missing/invalid permit values block only operations that use that permit.
There is no stopped-machine requirement and no approval-based loading prohibition:
unapproved recipes may be loaded for testing. The PLC decides whether to run, reject
parts or inhibit operation. Server checks for role, exact revision, policy and any
configured permit are applied to the operation that records a change.

Loading records an independent snapshot of the recipe content, image, revision ID,
content hash and production-approval state. The simulator exposes
`RecipeProductionApproved` (BOOL), `RecipeCode` (STRING) and `RecipeRevision` (integer),
plus a copied parameter payload through `driver.recipe_copy()` / `app.recipes.selected()`.
An approved library revision loads with the Boolean true; other states load false.
New edits, approvals and withdrawals leave the already-loaded copy unchanged.
Reload explicitly when the PLC copy or its approval flag should change.

## Screens

The generic editor manages recipes, typed parameter rows and limits, images,
reasons, field-level change history and review decisions. The operator viewer
shows library revisions and the loaded copy with their images and parameters.
Previewing a recipe is distinct from loading it. The **Selected recipe** toolbox
control shows the loaded product on a custom screen. The library begins empty;
no customer or production recipe is created automatically.

## Accounts and use

With [HMI security](security.md) configured, recipe operations use the signed-in
local or Windows HMI account. Assign `recipes.engineer`, `recipes.approver`,
`recipes.operator` and/or `recipes.administrator` permissions to its HMI groups.
The author can approve when they have the review permission. Windows groups can
map to the same HMI groups as local users. HMI login is authoritative once enabled;
legacy recipe-only sessions cannot bypass it.

The following recipe-only setup remains supported for older unsecured simulation
projects. For new projects, use `openhmi-security` and the Security page instead.

Create an account from the checkout; passwords are prompted and are not command-line
arguments. The user file belongs under ignored `.local/`, outside Git:

```powershell
.\.venv\Scripts\openhmi-users.exe --user engineer --roles engineer approver operator
.\.venv\Scripts\openhmi-users.exe --user manager --roles administrator
.\.venv\Scripts\openhmi.exe --recipe-users .local/recipe-users.json
```

Accounts use salted PBKDF2-HMAC-SHA256 hashes with 600,000 iterations, server-side
one-hour sessions and HttpOnly/SameSite cookies. The work factor follows the
[OWASP password-storage guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html).
Account changes require a server restart; sessions are not persisted. There are
no default credentials or browser-selectable roles. Existing accounts are preserved
by the account-creation command. Protect the local account file and database with
the operating system's normal access controls.

Open `/recipe-editor`, sign in, create a recipe and provide a reason. Each save
creates a draft revision. Submit it, enter another reason and approve or reject it.
The approver may be the author when their account has the approver role.
Open `/recipes` to preview or load either test or approved recipes. A load reason
is required. The administrator's change-policy panel controls each operation and
optional application permits; every policy change is audited.

Images are uploaded as PNG/JPEG (maximum 5 MiB input, 4096x4096 pixels), decoded,
orientation-corrected, stripped of metadata and stored as canonical PNG SQL blobs
(maximum 8 MiB). Updating an image requires a new recipe content revision.
Numeric values are type/limit checked, and integer values are bounded to the exact
range supported by the browser editor. Operator UI labels use the project's
language system; recipe content text is displayed as authored.

## Initial scope

This is a local application workflow. With HMI security enabled, simulator actions,
screen editing and alarm acknowledgement also require HMI permissions. Legacy
recipe-only authentication protects recipe operations alone. This is not a qualified electronic-signature or
regulatory-compliance claim. Trusted Python code and database administrators remain
inside the application's trust boundary.

The current load publishes to the in-process simulator, not a real controller.
Its last loaded copy is retained in SQL and restored to that simulator on restart.
A real adapter needs a transfer/acknowledgement transaction and readback that
associates parameters and `RecipeProductionApproved` with the same copied revision.
The PLC's running copy and run/reject logic remain independent of library editing.
