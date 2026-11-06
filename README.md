# OpenHMI

Build and change an HMI live, without web development skills. Customize it with Python.

## Table of Contents

- [Background](#background)
- [Install](#install)
- [Usage](#usage)
- [Architecture](#architecture)
- [Development plan](#development-plan)
- [Maintainers](#maintainers)
- [Contributing](#contributing)
- [License](#license)

## Background

OpenHMI is becoming a visual HMI development environment for the automation
community. Simple applications should need no code: drop controls, choose tags,
configure formatting and actions, and apply the screen. Python is the extension
language when an application needs custom behavior.

The prototype uses Puck with an HMI control catalog. The developer sees screen,
tag, units, decimal places and action properties rather than HTML, CSS or React.
The editor and runtime use the same controls and show live tag values.

Implemented: numeric displays, binary indicators, analog ranges, alarm indicators,
action buttons, tag/action dropdowns,
server-side draft autosave, validated screen data, explicit apply, revision
conflict detection and automatic updates in already-open runtime viewers. Applied
project revisions retain hashes, users/reasons and rollback provenance; engineers
can compare/stage older screens and recover/merge stale editor candidates.
Python modules can register custom named actions at startup. Project languages
support translated operator text and a keyboard-accessible flag selector. A project-wide Python alarm
service monitors tag triggers and retains occurrences, acknowledgement and history.
SQL recipes include a generic editor/viewer, product images, typed parameters,
revision history, recorded approvals and an independent loaded recipe copy.
No-code transfer profiles stage/verify a revision and its production BOOL, commit
through a dedicated PLC command and verify the PLC-owned running copy.
HMI security supports local accounts and Windows user/group assignments to local
application groups, with protected buttons and numeric/text edits, touch keypads,
login dialogs, colored group lock legends and optional PLC identity publication.
An operator journal records command/write/acknowledgement attempts and outcomes;
protected Activity and Diagnostics pages expose traceability and cached runtime state.
Configurable no-code PLC command buttons track requested, accepted and completed
sequences with durable outcomes, timeout uncertainty and no automatic replay.
The runtime includes a pycomm3 ControlLogix adapter, shared screen-rate polling,
multiple screens with keyboard-accessible popups and Overview fallback when a live
update removes the active screen,
UDT-bound faceplate definitions,
conditional bindings,
no-code tag/navigation actions and SQL history/trends. A project library supports
create/open and complete database backup export/import.

Initial controls follow [the HMI style guide](docs/hmi-style-guide.md), based on
the supplied high-performance HMI references and FactoryTalk View ME templates.
The default screen uses a gray header/body/sidebar/footer layout, compact Noto Sans SC
labels, subdued blue live values, flat navy commands and neutral normal states.
Alarm symbols combine priority number, shape and the ME template palette.

Current limits: configurable grids rather than free placement, best-effort polling,
no integrated Python editor/hot reload. Project revisions and recovery have
offline software checks; deployment and operator acceptance remain separate.
The ControlLogix adapter has offline protocol and browser checks; live PLC
commissioning and Windows/domain password logon still need validation with
configured hardware/accounts. HMI recipe selection and PLC recipe transfer are
separate operations. Command/recipe handshakes have offline checks; their PLC
logic, memory-copy behavior and hardware acceptance remain open.

## Install

### Portable Windows preview

The portable Windows x64 package includes Python, dependencies and browser assets.
Extract the complete package into a new folder, then run:

```powershell
.\OpenHMI.exe --self-check
.\OpenHMI.exe --open-browser
```

Projects default to `%LOCALAPPDATA%\OpenHMI\projects`, separately from application
files. Stop with Ctrl+C. Use `--create-admin admin` while stopped to create a local
administrator with a prompted password. No Python, Node or npm installation is
needed by the packaged HMI developer. This is an unsigned development preview;
clean-machine, Windows service and pilot acceptance remain open.

See [Windows package instructions](docs/windows-package.md) for building a preview,
project selection, logs, update/rollback and data preservation. Use `--preflight`
under the intended Windows account to check package, folder access and the local
port before starting. Use `--check-windows-mappings` to compare saved Windows
account and group SIDs with the target host. Use `--check-windows-login
<account>` to rehearse credential login and review the mapped HMI permissions.
No public release installer is published yet.

The bundled `package` commands provide verified side-by-side installation, version
selection and rollback while retaining project data. To stop a managed launch,
press Ctrl+C and wait for the command to return. See
[managed package installation](docs/package-management.md).

### Contributor installation

Prerequisites: Python 3.11+, Node.js 20+/npm for building browser assets, and a
browser. Windows/Python 3.14 is the locally checked environment. From the checkout:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
npm.cmd ci
npm.cmd run build
```

Assets are bundled locally, with no CDN or cloud editor requirement. The running
server needs Python and a browser; Node is a build/contributor dependency.
Portable preview builds use [pinned Windows build/runtime dependencies](requirements/windows-build.lock).
Source installs retain the cross-version dependency ranges in `pyproject.toml`.

## Usage


### Freeform screens

Select **Enable freeform layout** on the screen you want to design. Set the
canvas size, upload a machine image, then drag and resize controls over it.
The designer supports layer ordering, snapping, grouping, alignment, equal spacing,
matching object sizes, pan and fit-to-view zoom,
object search, drag-box selection, copy and paste, keyboard nudging, undo and redo,
grid containers and scrollable stacks. Lock image and shape objects behind
interactive controls. On a live freeform screen, use **Fit width** to show the
full canvas width or **Actual size** for configured pixel sizes. Freeform
positions and backgrounds are included in project backups. See [screen layout](docs/screen-layout.md).

### Sample project

Build a self-contained simulation project with preloaded recipes, history and a
saved trend capture. Run these commands from the repository root after the
contributor installation steps.

```powershell
.\.venv\Scripts\python.exe -m examples.build_demo .local/OpenHMI-Demo
.\.venv\Scripts\openhmi.exe --project .local/OpenHMI-Demo/OpenHMI-Demo.openhmi.sqlite3 --open-browser
```

The generator also creates a complete backup ZIP. See the
[demo walkthrough](docs/demo-project.md) for the featured screens and the
optional live-only, read-only PLC demo with tag history and trend capture.

Start the local simulation builder:

```powershell
.\.venv\Scripts\openhmi.exe
```

Open <http://127.0.0.1:8000>. Keep [the live screen](http://127.0.0.1:8000/runtime)
open in another tab while editing.

1. Drag a numeric display, binary indicator, analog range, alarm indicator or action
   button from the toolbox.
2. Select a control. Choose a tag or action from its property dropdown; edit its
   label, units and formatting as appropriate. No code is needed for these steps.
3. Changes autosave to the Python server after a short pause. Wait for the saved
   status or click **Save draft** before closing the editor.
4. Click **Apply live**. The existing runtime tab updates without reloading the
   page or restarting Python. Draft edits do not change the active screen until applied.
5. In the runtime tab, **Toggle simulated motor** invokes a built-in Python action.
   The indicator changes in both tabs. Editor preview buttons do not execute actions.

For an analog range, select scale endpoints and a normal band. The band supplies
context and does not generate alarms. Alarm indicators require an explicit
Boolean alarm tag and a priority. These legacy graphics remain indicators.
Use **Alarm setup** to register project-wide tag monitoring separately from graphics.
The header summarizes active/unacknowledged monitored alarms across the project.
Communication loss or invalid values are displayed explicitly. Existing saved
screens are retained; the expanded five-control example appears in new projects.

### PLC command transactions

Use **Commands** to map a writable UDT to request/accepted/completed sequences,
a result code and an optional PLC permit. Choose **PLC command transaction** on
an action button and select the contract. Runtime feedback and the **Commands**
page distinguish dispatch, acceptance, completion, failure and uncertainty.
Command buttons link to the latest transaction for their contract.
Filter command history by command ID, state or all unresolved transactions.
Download a transaction and its event timeline as JSON from the detail view.
Timeout/restart never replay a command. See the [contract and offline example](docs/command-transactions.md).
Use **PLC recipes** for dedicated recipe transfer profiles and complete parameter
mapping, then **Transfer revision to PLC** in the recipe viewer/editor. Reselect
the transfer target after a live project revision change. The panel keeps the
transaction ID visible if the status refresh fails. Operators with runtime
operation permission can open that transaction directly. Use **Transfer details**
to download the captured recipe transfer and command evidence as JSON.
History remains available after a target is retired and can be filtered by
captured target ID or production approval. The verification card uses the applied
target contract. The PLC
keeps its running copy; test recipes carry production status false. See the
[recipe transfer contract and workflow](docs/recipe-transfers.md).

### Connections, screens and reusable controls

1. In **Connections**, add a ControlLogix/CompactLogix pycomm3 route, enable it and
   apply. Tags remain read-only until explicitly configured for writing.
2. In **Tags**, browse the connection and add logical HMI names for PLC addresses,
   or create local tags. A selected PLC tag shows its native type, access, array
   dimensions and known numeric range or STRING capacity. Set numeric scaling
   and write permission as needed.
3. In **Screens**, add screens/popups and set each tag update interval. The server
   merges requests across viewers, reads shared tags at the fastest needed rate
   and batches due addresses through pycomm3.
4. In **Faceplates**, declare a UDT/member contract, design controls with relative
   member tags and choose a live UDT for preview. Drop a **UDT faceplate** onto a
   screen and bind its definition and compatible root UDT.
5. Select an action button's **Action type** for set/toggle tag, navigation, popup
   or registered Python actions. Boolean tag properties control visibility,
   enabled state and value color. Server checks also enforce conditional enablement.
   The server rejects clicks from a screen revision superseded by a live apply.
6. In **History**, choose tags, sampling, deadband and retention. Set **Logging
   mode** to **On change** for steady tags. Use **Export
   recorded data** to download a CSV for selected tags using a preset or exact
   start and end times in local time or UTC. Select **Export all retained rows
   in this range** for a complete download. Use **Find recorded tags** to
   include tags removed from the logging configuration. Drop a **Trend**
   onto a screen and add up to 12 numeric or Boolean tags. Set each numeric tag's
   decimal places and choose fixed or observed Y-axis bounds. Boolean tags appear
   as separate step traces under the analog chart. **On change** tags hold their
   last recorded value across short gaps until quality drops or the heartbeat
   expires. The control shows current live values alongside time-range/end-time
   selection and CSV export.
   Set a 10-second, 1-minute or custom viewing window and move the cursor
   across the plot to read every tag at the same time. Tap or use the arrow keys
   to pin the cursor to a timestamp. Enable **Saved trend
   recording** for manual Run/Stop or optional Boolean triggers, independent
   rolling sample retention, saved capture review and full capture CSV export.
   Configure trend labels and capture controls in **Languages**.
7. In the **Live charts** palette section, drop in a **Tank level indicator**
   for a live fill and normal band, a **Bar graph** to compare numeric tags on
   one scale, or a **Radar chart** with independently scaled axes. Set tags,
   labels, units and precision in the designer. See the [control catalog](docs/hmi-style-guide.md#initial-catalog).

Update intervals are best-effort acquisition requests, not PLC cyclic I/O
subscriptions. Alarm/history demand continues without an open viewer. See
[runtime, UDT and history semantics](docs/runtime-and-projects.md) for quality,
write/readback behavior, supported types and current limits.

### Projects and backups

Start through `openhmi`, then open **Projects**. Create/open projects in the local
library beside the selected database, export a complete backup ZIP or import one
under a new project ID. New projects inherit the current HMI security configuration.
Project administration and complete backups require security administration rights
when security is configured.

Backups contain the database (screens, connections, tags, faceplates, recipes and
images, security, alarm and tag history), plus the configured startup Python entry
file and legacy recipe account file when present. Imports verify checksums and
preserve existing projects. PLC connections remain held until explicit **Apply live**;
imported Python is saved for review and never executed automatically.
The browser backup/import limit is 256 MiB; external Python dependencies and the
OpenHMI installation are separate. See [backup details](docs/runtime-and-projects.md).

### Activity and diagnostics

OpenHMI schedules scans independently per PLC route so a slow read on one
route does not hold up the others. When a route fails, its cached values become
unavailable to live controls and permits until fresh reads succeed. Open the
runtime header's PLC status to see each route. Affected controls label held,
disabled, waiting, stale and disconnected data.

Use **Activity** to inspect operator identity, control/tag context, requested
values and confirmed/denied/uncertain outcomes. Filter and export the journal;
its operation IDs also appear in API response headers. **Diagnostics** shows
connection/scan counters, tag quality/age and errors without requesting new scan
tags or writing equipment. The runtime header and Diagnostics identify routes
waiting for the first usable sample of a requested PLC tag or UDT member.
They also flag an established route whose requested samples are all unusable,
even while its transport stays connected. Open a control's quality badge to see
its logical tag, configured PLC address and route, and the reported fault.
With diagnostics viewing permission, the badge can open a filtered Diagnostics
tab while the original screen continues scanning.
Per-route timing separates worker queue delay, route lock wait, adapter reads,
scan start lateness and recovery.
Filter diagnostic tags by name, sample quality, and PLC connection or local HMI
source. JSON exports use the same tag filters.
Diagnostics also shows background worker health and retry state. Grant `activity.view` / `diagnostics.view` through HMI
groups; security administrators can inspect both. See
[journal behavior, recovery and retention](docs/activity-and-diagnostics.md).

### Languages

Open **Languages** in the builder, enter a language code/name, choose a flag, and
click **Add language**. Fill translations for the screen, controls, alarm messages
and operator UI text. Apply the draft, then use the flag button in the live screen
to switch languages. The dropdown contains only other configured languages;
new projects start with English only. Missing translations use source text.

The supplied Noto Sans SC font and 4:3 flag-icons SVGs are bundled locally. HMI
font sizes are reduced by approximately 4.5% to match Arial's x-height. The font
covers the tested Latin/Chinese/Japanese samples, but does not cover every script;
browser/system fallback remains available. The engineering editor stays in English.

### Alarm tag monitoring

In **Alarm setup**, add a trigger tag, type (`value`, `bit`, `lsbit`), trigger
value/position, message, priority and acknowledgement policy. Apply the draft.
The service samples the active configuration every 250 ms with no browser required.
Bit positions are one-based: position 1 represents PLC bit 0 in a 32-bit word.

Open [Alarms](http://127.0.0.1:8000/alarms) for searchable, filtered alarm lists,
selected/individual/all acknowledgement, direct banner links to captured causes and recovery steps,
related-screen navigation, attributed operator notes and event CSV export.
Acknowledgement records the first user and never clears the source tag.
Returned but unacknowledged occurrences remain visible. The project database
retains alarm state/history across restarts; simulator tag values themselves reset.
The built-in **Toggle simulated process alarm** action can be assigned to a button
for testing. Timed shelving supports required reasons, automatic expiry and early
restoration through a separate group permission. Monitoring/history continue;
global totals still include shelved alarms and the runtime banner shows their count.
Polling can miss short pulses. Remote PLC handshakes and audible/silence behavior
remain open; production commissioning remains separate work.

See [operator alarm workflows](docs/alarm-workflows.md) for filters, permissions,
export and retention, and [language and alarm semantics](docs/languages-and-alarms.md) for trigger,
translation, persistence, quality and retention details and the FactoryTalk ME references.

The default project database is `.local/project.sqlite3`, relative to the working
directory. It retains draft and active screens across restarts. Simulated tag
values reset when Python restarts. To use a separate project database:

```powershell
.\.venv\Scripts\openhmi.exe --project .local/another-project.sqlite3
```

Concurrent editors use revision checks. A stale save/apply opens a three-way
recovery review with explicit choices for overlapping edits. Local candidates
survive reload in per-project/account/tab browser storage, and can be retained or
merged on the server. Revisions supports comparison, screen-only/full-project
draft staging and rollback into a new applied revision. See
[project history, migration and recovery](docs/project-recovery.md). Previous browser-local GrapesJS prototype saves are
left in browser storage and are not automatically imported into this format.

### Login and security groups

Enable HMI login by creating the first local administrator (password is prompted):

```powershell
.\.venv\Scripts\openhmi-security.exe --project .local/project.sqlite3 --user admin
.\.venv\Scripts\openhmi.exe --project .local/project.sqlite3
```

Choose **Open HMI login** and open **Security** after signing in. Create HMI groups, choose
their permissions, and assign local users or Windows users/groups. Windows login
verifies credentials on the Windows server and maps authenticated SIDs to HMI groups.
It uses an explicit credential prompt; automatic browser SSO is not implemented.

Select an **Action button**, **Numeric input** or **Text input** in the designer,
choose its allowed HMI groups, and apply. Unauthorized users see colored lock
symbols; clicking a locked area opens the group/permission legend. Python
checks the same permissions and active binding on every action or value write.
Project editing, alarm acknowledgement and recipe operations also use HMI permissions.
New projects show **Unsecured simulation** until the first administrator exists.
Numeric/text edits support HMI limits or limit-tag bindings and touch entry.
A live apply requires fresh input for any edit already in progress.
Runtime keypad and login text can be translated in **Languages**. On-screen
keys edit at the cursor and replace selected text. Key rows wrap on narrow displays.
The **Current login user** control displays the signed-in user. **PLC login**
settings optionally publish a claimed station's user and mapped DINT privilege bits.
See [touch entry and PLC identity](docs/touch-entry-and-identity.md) and
[security setup, permissions and Windows behavior](docs/security.md).

### Recipes

Use **Security** to assign recipe permissions to HMI groups and their users.
For example, assign Engineers and Approvers to an author who also approves changes.

Open **Recipes** and **Recipe editor** to create recipes, add parameters and a
PNG/JPEG product image, and record a reason for each change. Each save creates a
new content revision. Submit and approve it for production; the author may also
approve when their account has that role. Approval records the signed-in user.
The SQL history retains field changes, review decisions and load operations.

Both test and approved recipes may be loaded. Loading copies the recipe and its
`RecipeProductionApproved` Boolean to the simulator. Later library changes leave
that copy unchanged until explicitly loaded again. The PLC will own the decision
to run, reject parts or inhibit operation; there is no mandatory stopped-machine
gate. Actual PLC transfer is future adapter work.

Drop **Selected recipe** onto a screen to show the loaded product and its image.
An administrator can freeze editing, approval or loading separately and optionally
bind those operations to Boolean permit tags. See [recipe setup and semantics](docs/recipes.md)
for account roles, change policy, persistence and transfer boundaries.

### Python customization

Start with the included example:

```powershell
.\.venv\Scripts\openhmi.exe --handlers examples/custom_actions.py
```

Select an action button and choose **Half fill simulated tank** in its Action
property, then apply the screen. The example module contains:

```python
def half_fill(app):
    app.driver.write("TankLevel", [50.0])

def register(app):
    app.register_action("half_fill", "Half fill simulated tank", half_fill)
```

The selected local module runs as trusted Python at startup. Project data stores
only action names; the browser cannot upload/execute Python source. Handler edits
currently require restarting the server. An integrated Python editor and deliberate
module reload are planned. Screen-only changes already apply without a restart.
If a saved screen uses a custom action, start with that handler module again.

The server binds to loopback. Without configured HMI security accounts it provides
unsecured simulation actions; after bootstrap, mutations require HMI permissions.
Real equipment access and commissioning remain separate work.
Stop it with Ctrl+C.

## Architecture

See [the live builder architecture](docs/architecture.md) for requirements and the
Anvil, Puck and Craft.js assessment. Puck is the current editor foundation; Anvil
informs the Python-focused development experience; Craft.js remains an alternative
for deeper editor customization. FUXA is a feature reference only and will not be adopted.
AdvancedHMI interface/project compatibility is no longer a project requirement.

The server validates a typed, versioned OpenHMI screen schema rather than storing
raw HTML/CSS or Puck internals. SQLite transactions protect draft/active updates.
Existing viewers poll for new active revisions; tag state remains owned by Python.

Next work: [packaged installation and lifecycle](https://github.com/votecoffee/OpenHMI/issues/9),
[Python IDE and reload (deferred)](https://github.com/votecoffee/OpenHMI/issues/2),
[PLC hardware acceptance](https://github.com/votecoffee/OpenHMI/issues/3),
and [equipment controls/operator validation](https://github.com/votecoffee/OpenHMI/issues/4).

## Development plan

The next work focuses on ControlLogix scan performance and recovery, visible
PLC data quality, and Windows runtime resilience. The no-code
[Web Browser / Camera View](docs/web-browser-camera.md) supports a fixed address
or PLC STRING selection and an optional PLC refresh trigger. See the
[runtime readiness roadmap](docs/runtime-readiness-roadmap.md) for the driver
assessment, product references, and acceptance gates. The
[offline restart drill](docs/runtime-soak.md#forced-process-restart-drill) checks
that pending commands reconcile without replay after a forced runtime process
exit. Endurance testing is deferred. Managed Windows [package launch](docs/package-management.md)
also provides a configurable Ctrl+C shutdown deadline and an opt-in exit
watchdog that starts recovery with PLC acquisition held.

See the [milestone-based development plan](docs/project-plan.md) and
[GitHub milestones](https://github.com/votecoffee/OpenHMI/milestones).
The verified software baseline and M1 operator activity/diagnostic workflows are
complete as software checkpoints. M3 now includes offline-verified command
contracts, no-code bindings and versioned recipe transfer/copy verification.
Equipment acceptance remains open. M4 project revision/diff/staging, stale-editor
merge recovery and migration/restore checks are also delivered offline. Bench
commissioning, operator review and packaged pilot acceptance follow. Use the
[offline scan baseline](docs/plc-bench-acceptance.md#run-the-offline-scan-baseline)
and [read-only PLC bench procedure](docs/plc-bench-acceptance.md) for M2 evidence.
Use the [Windows pilot acceptance matrix](docs/pilot-acceptance.md) for M6.
The integrated Python IDE remains deferred.

## Maintainers

[@votecoffee](https://github.com/votecoffee).

## Contributing

Keep end-user workflows free of web implementation details. Prefer declarative
bindings and common actions before requiring custom code. Keep drivers independent
of editor controls and preserve active tag state during screen updates.

Run local Python and browser checks (browser checks require installed Google Chrome):

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npx.cmd playwright test
```

Browser checks manage in-memory simulation servers on ports 8765 and 8766,
using synthetic accounts for recipe and HMI security validation.
No automatic GitHub Actions workflows are configured. Keep machine/customer data
and credentials outside tracked source; `.local/` is ignored for local artifacts.

## License

[MIT](LICENSE), copyright 2026 votecoffee. Puck, React and other dependencies retain
their own licenses; the asset build includes dependency license texts and bundle
notices. No Anvil, Craft.js, FUXA or AdvancedHMI code or assets are vendored.
The supplied Noto Sans SC font is included under SIL OFL 1.1 and flag-icons SVGs
under MIT; their license files accompany the assets. See
[language asset details](docs/languages-and-alarms.md).
