# HMI login and security groups

An HMI group is an OpenHMI application group, stored in the project SQLite
database. It is independent of Windows group names. Local HMI users, authenticated
Windows users and authenticated Windows groups can be assigned to it. A user
receives the union of their assigned HMI groups and those groups' permissions.
Windows membership is matched by SID, not by a name sent by the browser.

## First administrator

From the checkout, with the environment installed:

```powershell
.\.venv\Scripts\openhmi-security.exe --project .local/project.sqlite3 --user admin
.\.venv\Scripts\openhmi.exe --project .local/project.sqlite3
```

The bootstrap command prompts for a password of 12–256 characters and preserves
existing accounts. Use the same database for bootstrap and runtime. It creates
an account in **Administrators**. No default password or user is shipped. The
server detects new security accounts without a restart.

Until a project has security accounts, its login bar explicitly reports
**Unsecured simulation**. Existing simulation editing/actions remain available.
A control with an explicit group requirement stays locked even in that mode.
Creating the first administrator enables login enforcement across project edits,
runtime actions, value writes, alarm acknowledgement and recipe mutations.
Reading screens and values remains public. Disabling a user does not return the
project to unsecured simulation.

## Administer groups and users

Sign in through the HMI login bar and open **Security**. An administrator can:

* Create or update an HMI group and its operation permissions.
* Create a local user, set/reset a password, enable/disable the account and assign
  one or more HMI groups. Leaving the password blank retains an existing password.
* Enable Windows login and assign Windows users or groups to HMI groups.
* Remove a Windows assignment. Multiple Windows assignments may target one HMI
  group; a Windows identity may also receive multiple HMI groups.

Each change needs a reason, is version checked and is recorded with the acting
user and time. The page displays the latest 200 events; SQL retains the history.
Password hashes are never returned to the browser or stored in audit details.
At least one enabled local security administrator must remain. Group definitions
are edited in place; deletion/renaming and nested HMI groups are not implemented.

Initial groups are Administrators, Engineers, Operators and Approvers. They are
editable defaults, not fixed Windows roles. Supported permissions:

| Permission | Allows |
| --- | --- |
| `project.edit` | Save/apply screen, language and alarm configurations |
| `runtime.operate` | Invoke an action bound to an active button |
| `runtime.write` | Write a value through an active numeric/text edit with current bounds |
| `identity.publish` | Explicitly claim the station publishing its authenticated PLC identity |
| `alarms.acknowledge` | Acknowledge selected/individual/all monitored alarms |
| `alarms.comment` | Append attributed operator notes to alarm occurrences |
| `alarms.shelve` | Start timed alarm shelves and restore them early, with a reason |
| `security.manage` | Manage security; override control-specific group membership |
| `activity.view` | Inspect/export the runtime operator activity journal |
| `diagnostics.view` | Inspect/export cached runtime connection and tag diagnostics |
| `recipes.engineer` | Create/edit/submit/load recipes |
| `recipes.approver` | Approve/reject/withdraw recipes, including one's own changes |
| `recipes.operator` | Load/clear recipe copies |
| `recipes.administrator` | Manage recipe policy and perform recipe role operations |

`security.manage` does not implicitly grant the other operation permissions.
Administrators initially receive all permissions. Engineers initially receive
project editing, runtime operation/writing, alarm acknowledgement/commenting and recipe
engineering. Operators receive runtime operation, alarm acknowledgement/commenting and recipe
loading. Approvers receive recipe review. Add the groups needed for a user's job.
Existing groups retain their saved permissions; grant `alarms.comment` explicitly
when upgrading an existing project. Alarm lists/details/history remain public
read-only views, consistent with the existing alarm monitor.
Only new Administrators initially receive `alarms.shelve`; explicitly grant it
to authorized groups, including existing Administrators, as appropriate. A shelf
does not grant acknowledgement, runtime operation or value-write permission.

New Engineers groups also receive activity/diagnostics viewing. Existing group
definitions are preserved; grant new permissions through Security as needed.
Security administrators can inspect both views without changing older groups.

## Protect buttons and values

Select an **Action button** or **Numeric input** in the screen designer. Check
**Allowed HMI groups (any selected)** and apply the screen. No groups selected
means only the operation permission is required. Otherwise the signed-in user
also needs at least one listed HMI group. Security administrators may override
the group requirement when they have the operation permission.

For example, create **Maintenance**, grant it `runtime.operate` and
`runtime.write`, assign technicians to it and select it on protected controls.
Other operators can still see the current value, but their input and button are
disabled. The Python API enforces the same rule on every operation. Unavailable
login status, expired sessions and missing memberships lock the controls.

Numeric inputs bind to existing numeric logical tags, including UDT members, and have server
validated minimum/maximum values. Writes are accepted only through an active
input binding. The API does not accept an arbitrary tag name or group claim.
Buttons send their active control ID; older clients without an ID must satisfy
every active binding of the requested action. Editor previews never execute.
Users with `project.edit` can change screen bindings and their group requirements;
that permission is an engineering privilege.

## Windows login

### Review saved mappings on the target Windows host

Run the mapping check against the pilot project before testing logon:

```powershell
.\OpenHMI.exe --project 'D:\HMI Data\projects\Pilot.openhmi.sqlite3' --check-windows-mappings
```

The command opens the project database read-only and resolves each saved Windows
name using the current host. It reports the saved SID, the resolved SID when
available, and `matched`, `mismatch` or `unresolved` for each assignment. It
returns exit code 1 if there are no assignments or any assignment needs review.
The check is available with Windows login disabled. An unresolved name can
indicate a rename or an unavailable domain. The saved SID remains the binding.
Keep the report private because it contains account and group information.
Verify credential login and token group membership separately on the target host.

### Rehearse Windows credentials and HMI grants

Use an approved test account and a pilot project with Windows login enabled.
Run this from an interactive console on the target host:

```powershell
.\OpenHMI.exe --project 'D:\HMI Data\projects\Pilot.openhmi.sqlite3' --check-windows-login 'DOMAIN\TestOperator'
```

OpenHMI prompts for the password with echo disabled. The check uses the same
Windows logon and enabled-token-group rules as the HMI, then reports the HMI
groups and permissions from the saved project. It opens the database read-only
and creates no session or project audit record. Windows account policies and
Windows auditing still apply. A disabled Windows provider, rejected logon or
authenticated account with no HMI assignment returns exit code 1. Keep the
report private. Use the actual HMI for browser login, session and authorization
acceptance.

Windows authentication runs on the Windows machine hosting Python. In **Security**,
enable Windows login, enter `DOMAIN\Group` or `MACHINE\User`, choose its identity
type and select the target HMI group. The server resolves the account SID and
checks the requested user/group type before saving the assignment. An OS account
or group is not created or modified by OpenHMI.

The login bar then offers **Windows account**. Users enter `DOMAIN\User`, a UPN
such as `user@example.test`, or a machine-local user name. The server calls
[LogonUserW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-logonuserw)
with network logon and reads the authenticated token's user/group SIDs. It grants
membership only from enabled groups, excluding deny-only groups as specified by
[Windows token group attributes](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-token_groups).
Domain/nested membership is whatever the authenticated Windows token contains;
OpenHMI does not reconstruct it from browser claims or LDAP name searches.
Canonical Windows account names identify recipe approvals and security changes.

This is an explicit Windows credential login, not automatic browser SSO.
Windows logon rights, domain availability and OS account policy apply. There is
no fallback to local HMI credentials after a failed Windows login. Windows
passwords/tokens are not saved: only a user SID, enabled group SIDs and display
name remain in the server's one-hour session after the native token is closed.
Windows group changes are refreshed at the next login/session expiry. HMI group
permission and mapping changes are evaluated on each request. Disabling Windows
login invalidates Windows sessions immediately.

## Sessions, migration and boundaries

Local passwords use salted PBKDF2-HMAC-SHA256 with 600,000 iterations. Sessions
are server-side, expire after one hour and are not persisted. Cookies are
HttpOnly/SameSite Strict and Secure when served over HTTPS. Logout invalidates
the server session. Local account changes invalidate that account's sessions;
group permission changes take effect on the next operation. Failed sign-ins
are limited per client address across user names and providers. Mutation routes
check browser Origin when present.

The CLI binds to loopback for local use. A remote deployment requires HTTPS to
protect login credentials and an appropriate hosted deployment setup. Trusted
Python handlers and database/OS administrators are inside the trust boundary.
This is application authorization, not controller safety logic or an independent
security certification. The pycomm3 adapter is available, but live PLC commissioning
has not been performed. Unavailable/bad-quality input tags also block value writes.

Old `openhmi-users` recipe-only files are supported in projects that have no HMI
security accounts. After bootstrap, HMI accounts/groups are authoritative for
recipe operations too; legacy recipe sessions cannot bypass the HMI login.
Recreate desired legacy users/group assignments through Security. The old file
is preserved and is not automatically granted application-wide permissions.
Existing recipe author/approval history remains unchanged.

Local tests cover unauthorized API mutations, group revocation, session expiry,
restart persistence, rate limits, conflicts, direct Windows user/group SID
mapping and deny-only filtering using synthetic identities. Native Windows token
parsing, canonical account resolution and SID lookup were checked read-only using
the current process token, with the credential boundary replaced in the test.
Actual Windows password/domain logon and
browser SSO have not been commissioned against a domain or production accounts.

Touch login, current-user controls, group colors/lock legends and optional PLC
identity publication are described in [touch entry and identity](touch-entry-and-identity.md).
Changing PLC publication configuration requires security administration as well
as project editing. Existing groups retain their saved grants.
