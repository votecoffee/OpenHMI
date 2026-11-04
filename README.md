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
Python modules can register custom named actions at startup.

Initial controls follow [the HMI style guide](docs/hmi-style-guide.md), based on
the supplied high-performance HMI references and FactoryTalk View ME templates.
The default screen uses a gray header/body/sidebar/footer layout, compact Arial
labels, subdued blue live values, flat navy commands and neutral normal states.
Alarm symbols combine priority number, shape and the ME template palette.

Current limits: one screen, a configurable control grid, simulation only, 500 ms polling,
no integrated Python editor or Python hot reload, and no history/rollback UI.
There is no PLC adapter or production authentication yet.

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
Boolean alarm tag and a priority. The header summarizes only configured alarm
controls on that screen. Alarm acknowledgement/history are not implemented.
Communication loss or invalid values are displayed explicitly. Existing saved
screens are retained; the expanded five-control example appears in new projects.

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

The server binds to loopback and provides unauthenticated simulation actions.
Real equipment access, operator permissions and commissioning are separate work.
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

Browser checks manage their own in-memory simulation server on port 8765.
No automatic GitHub Actions workflows are configured. Keep machine/customer data
and credentials outside tracked source; `.local/` is ignored for local artifacts.

## License

[MIT](LICENSE), copyright 2026 votecoffee. Puck, React and other dependencies retain
their own licenses; the asset build includes dependency license texts and bundle
notices. No Anvil, Craft.js, FUXA or AdvancedHMI code or assets are vendored.
