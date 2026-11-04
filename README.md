# OpenHMI

Python HMI runtime with an experimental drag-and-drop web designer, inspired by
AdvancedHMI's communication components and control-address bindings.

## Table of Contents

- [Background](#background)
- [Install](#install)
- [Usage](#usage)
- [Architecture](#architecture)
- [Maintainers](#maintainers)
- [Contributing](#contributing)
- [License](#license)

## Background

OpenHMI aims to combine Python drivers and application logic with familiar HMI
screen design: a toolbox, property inspector, reusable controls and named driver
instances. The selected direction is a Python runtime and browser designer.

The current prototype extends **GrapesJS core**, an open-source visual editor.
It includes numeric-display and indicator controls, an address property,
browser-local screen save/load, a runtime view and a Python simulator.
It has no PLC connection, browser write endpoint, Python code-behind editor,
subscription engine or AdvancedHMI project importer yet.

## Install

Prerequisites: Python 3.11+, Node.js/npm for preparing editor assets, and a browser.
Development has been checked on Windows with Python 3.14; older supported Python
versions have not yet been exercised. Run these commands from the checkout:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
npm.cmd ci
npm.cmd run build
```

The build copies pinned GrapesJS core assets and its license into an ignored
runtime asset folder. There is no CDN dependency at runtime. Node.js is needed
for development/build preparation, not by the running Python server.
The Python dependency ranges are not a reproducible deployment lockfile yet.

## Usage

Start the loopback-only simulation server:

```powershell
.\.venv\Scripts\openhmi.exe
```

Open <http://127.0.0.1:8000>. The screen starts with a numeric display bound to
`TankLevel` and an indicator bound to `MotorRunning`.

1. Drag a control from the HMI controls toolbox onto the canvas.
2. Select it, open Settings (the gear icon), and edit `PLCAddressValue`.
3. Click **Save locally** to save in this browser's local storage. Click
   **Load saved** to restore that screen, including after a page reload.
4. Click **Run screen** to render controls with values from the Python simulator.
   Click **Back to designer** to resume editing.

Runtime uses flow layout and a subset of size/spacing properties. It does not
reproduce arbitrary editor HTML/CSS. Unknown addresses and lost API connectivity
are shown explicitly. Screen saving is browser-local and tied to this origin;
it is not a portable application file or a server-side backup.

The simulator's scalar Python contract is available independently of the UI:

```python
from openhmi.drivers import SimulatorDriver

driver = SimulatorDriver()
print(driver.read("TankLevel"))  # [42.0]
driver.write("TankLevel", [17.5])
```

The development server is an unauthenticated local simulation tool. Production
deployment, real PLC access and operator writes are future implementation work.
Stop the server with Ctrl+C.

## Architecture

See [designer decision and roadmap](docs/architecture.md) for the evaluation of
FUXA, GrapesJS, Eclipse Theia, WinForms/.NET interop and Qt Designer.
See [AdvancedHMI compatibility targets](docs/advancedhmi-compatibility.md) for
source observations, driver mapping and migration boundaries.

We intend similar concepts and driver operations. There is no binary, VB source,
WinForms-control or complete project compatibility claim. AdvancedHMI source,
graphics and DLLs are not included.

## Maintainers

[@votecoffee](https://github.com/votecoffee).

## Contributing

Keep drivers independent of the web editor. Document unsupported addressing,
quality, subscription and write semantics. Use simulated tags for development.

Run local Python and browser checks (browser checks require installed Google Chrome):

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npx.cmd playwright test
```

Browser checks start and stop their own simulation server on port 8765. No
GitHub Actions workflows run automatically. Keep machine/customer data and
credentials outside tracked source; `.local/` is ignored for local artifacts.

## License

[MIT](LICENSE), copyright 2026 votecoffee. GrapesJS core has its own BSD-3-Clause
license, copied with the prepared web assets. Other dependencies retain their
respective licenses. AdvancedHMI is a separate reference project with different
terms; OpenHMI independently implements its code and controls.
