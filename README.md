# OpenHMI

Build and change an HMI live, without web development skills. Customize it with Python.

## Table of Contents

- [Background](#background)
- [Install](#install)
- [Usage](#usage)
- [Architecture](#architecture)
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
The editor and runtime use the same controls and show simulated values live.

Implemented: numeric displays, binary indicators, analog ranges, alarm indicators,
action buttons, tag/action dropdowns,
server-side draft autosave, validated screen data, explicit apply, revision
conflict detection and automatic updates in already-open runtime viewers.
Python modules can register custom named actions at startup. Project languages
support translated operator text and a flag selector. A project-wide Python alarm
service monitors tag triggers and retains occurrences, acknowledgement and history.
SQL recipes include a generic editor/viewer, product images, typed parameters,
revision history, recorded approvals and an independent loaded recipe copy.
HMI security supports local accounts and Windows user/group assignments to local
application groups, with protected buttons and numeric value inputs.

Initial controls follow [the HMI style guide](docs/hmi-style-guide.md), based on
the supplied high-performance HMI references and FactoryTalk View ME templates.
The default screen uses a gray header/body/sidebar/footer layout, compact Noto Sans SC
labels, subdued blue live values, flat navy commands and neutral normal states.
Alarm symbols combine priority number, shape and the ME template palette.

Current limits: one screen, a configurable control grid, simulation only, 500 ms polling,
no integrated Python editor or Python hot reload, and no screen-revision history/rollback UI.
There is no PLC adapter yet. Windows/domain password logon still needs validation
with configured accounts; local authorization and synthetic Windows mappings are tested.

## Install

This is contributor setup, not the intended packaged end-user installation.
Prerequisites: Python 3.11+, Node.js 20+/npm for building browser assets, and a
browser. Windows/Python 3.14 is the locally checked environment.

From the checkout:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
npm.cmd ci
npm.cmd run build
```

Assets are bundled locally, with no CDN or cloud editor requirement. The running
server needs Python and a browser; Node is a build/contributor dependency.
Release packaging should eventually hide this setup from HMI developers.
Python dependencies currently use version ranges rather than a deployment lockfile.

## Usage

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

Open [Alarms](http://127.0.0.1:8000/alarms) for outstanding alarms, individual/all
acknowledgement and event history. Acknowledgement never clears the source tag.
Returned but unacknowledged occurrences remain visible. The project database
retains alarm state/history across restarts; simulator tag values themselves reset.
The built-in **Toggle simulated process alarm** action can be assigned to a button
for testing. Polling can miss short pulses. Remote PLC handshakes, audible/silence
behavior and shelving are not implemented. HMI security can require group
permission for acknowledgement; production commissioning remains separate work.

See [language and alarm semantics](docs/languages-and-alarms.md) for trigger,
translation, persistence, quality and retention details and the FactoryTalk ME references.

The default project database is `.local/project.sqlite3`, relative to the working
directory. It retains draft and active screens across restarts. Simulated tag
values reset when Python restarts. To use a separate project database:

```powershell
.\.venv\Scripts\openhmi.exe --project .local/another-project.sqlite3
```

Concurrent editors use revision checks. A stale save/apply is rejected; the
editor retains local changes and asks you to copy them before reloading. Conflict
merging is not implemented. Previous browser-local GrapesJS prototype saves are
left in browser storage and are not automatically imported into this format.

### Login and security groups

Enable HMI login by creating the first local administrator (password is prompted):

```powershell
.\.venv\Scripts\openhmi-security.exe --project .local/project.sqlite3 --user admin
.\.venv\Scripts\openhmi.exe --project .local/project.sqlite3
```

Sign in through the login bar and open **Security**. Create HMI groups, choose
their permissions, and assign local users or Windows users/groups. Windows login
verifies credentials on the Windows server and maps authenticated SIDs to HMI groups.
It uses an explicit credential prompt; automatic browser SSO is not implemented.

Select an **Action button** or **Numeric input** in the designer, choose its
allowed HMI groups, and apply. Unauthorized users see disabled controls. Python
checks the same permissions and active binding on every action or value write.
Project editing, alarm acknowledgement and recipe operations also use HMI permissions.
New projects show **Unsecured simulation** until the first administrator exists.
See [security setup, permissions and Windows behavior](docs/security.md).

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

Next work: [screen/project lifecycle](https://github.com/votecoffee/OpenHMI/issues/1),
[Python IDE and subscriptions](https://github.com/votecoffee/OpenHMI/issues/2),
[a first PLC adapter](https://github.com/votecoffee/OpenHMI/issues/3),
and [equipment controls/operator validation](https://github.com/votecoffee/OpenHMI/issues/4).

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
