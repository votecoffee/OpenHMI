# OpenHMI portable Windows preview

This package is an unsigned development preview. It contains the Python runtime,
Python dependencies, browser designer/runtime, Noto font and configured flag
assets. The HMI developer needs Windows x64 and a browser; no Python, Node, npm
or internet connection is needed to run the extracted package.

Current evidence: a Windows x64 / CPython 3.14.3 build and local packaged-process
checks. A clean Windows machine, target account/domain, controller and operator
display still require acceptance. No Windows service is installed by this preview.

## Start and stop

Extract the complete ZIP into a new application folder. Keep `OpenHMI.exe` and
its `_internal` folder together. Open PowerShell in that folder:

```powershell
.\OpenHMI.exe --self-check
.\OpenHMI.exe --open-browser
```

Open <http://127.0.0.1:8000> if the browser does not open. The program runs in the
console; stop it with **Ctrl+C** and wait for application shutdown to complete.
Closing the browser leaves the runtime running. Restart by running the same
command. This preview binds only to the local computer, using one server process.
It does not configure remote HTTP/HTTPS access or automatic startup.

By default, projects are stored in `%LOCALAPPDATA%\OpenHMI\projects`, independently
of the application folder and current working directory. The initial database is
`Default.openhmi.sqlite3`. Use **Projects** in the browser to create/open projects
and export/import complete backups. To use a different library or port:

```powershell
.\OpenHMI.exe --project 'D:\HMI Data\projects\Line1.openhmi.sqlite3' --port 8010 --open-browser
```

One launcher process owns a project-library folder at a time, including project
switching and administrator setup. A second launcher exits with an ownership
message. A stopped or crashed process releases its OS lock automatically; the
remaining `.openhmi-runtime.lock` file does not indicate a running process. This
guard covers this launcher; direct Python API access and old launches cannot be
made safe by a lock they do not use. Keep databases on local storage and do not
run another runtime or security utility against the same library.

## Check the target account before first start

Sign in as the Windows account that will run OpenHMI. Create the intended project
library and log folders if needed, then run the preflight from the extracted folder:

```powershell
$library = 'D:\HMI Data\projects'
New-Item -ItemType Directory -Force -Path $library, (Join-Path $library 'logs')
.\OpenHMI.exe --preflight --project (Join-Path $library 'Line1.openhmi.sqlite3') --port 8010
```

Preflight reports package dependencies and assets, temporary file creation and
cleanup in both folders, write access to any existing project database and active
log file, and whether OpenHMI can bind the selected loopback port at check time.
Use `--log-dir` if you plan to store logs elsewhere. Each check appears in the
JSON output. An unsuccessful check returns exit code 1. Preflight leaves the
project contents intact and starts no HMI server or PLC connection. Target
credentials, HMI group assignments and runtime behavior are verified separately.

## Create a local administrator

Stop the runtime first. The bundled command prompts for the password and its
confirmation; passwords are not supplied as command-line arguments:

```powershell
.\OpenHMI.exe --create-admin admin
```

Use the same `--project` path when running a custom project. Sign in to the HMI
and use **Security** to manage users, local application groups and Windows
account/group mappings. Administrator setup rejects an existing account. The
packaged runtime does not create a default password or bypass existing security.

## Logs, diagnostics and Python customization

The console and `<project library>\logs\runtime.log` receive runtime logs, with
three rotated backups of up to 5 MiB each. `--log-dir` selects another folder.
Logs can contain local file paths, request paths and error details; handle them
with the same care as the project. The protected **Diagnostics** and **Activity**
pages provide the existing cached diagnostics/CSV and operator journal exports.

Trusted Python customization remains available with `--handlers <path>`. Standard
library and bundled dependency imports are available. Arbitrary third-party
Python packages are not installed into a frozen application; use the documented
source/venv installation or build a reviewed package containing those dependencies.
Custom handlers load at startup; integrated Python editing/hot reload is deferred.

## Update, rollback and removal

Use the bundled [package manager](package-management.md) for hash-verified
side-by-side installation, activation and launch. Manual extraction remains
available; neither approach changes existing project data automatically.

1. Stop OpenHMI, retain the old application folder, and export complete backups
   from **Projects** before updating. Back up trusted external handler files too.
2. Extract the new ZIP into a separate folder. Run `--self-check`, then run it
   with the same `--project` path. Replacing binaries does not replace project data.
3. Verify users/groups, images/recipes, alarms/history and project recovery before
   accepting the update. Schema migrations are recorded in the project database.
4. For rollback, restore a pre-update backup into a separate project/library and
   use the retained matching application version. An older executable is not a
   promise of backward database compatibility after a migration.

To remove the preview, stop it and remove only its extracted application folder.
Projects, logs, backups and external handlers are retained outside that folder.
No installer/uninstaller changes the registry, services or startup configuration.

`manifest.json` records build/source identity, dependency versions and SHA-256
file hashes. The ZIP has a `.sha256` sidecar. Hashes check integrity, not publisher
authenticity; code signing and release distribution remain future acceptance work.
Python, font, flag, browser and Python dependency notices accompany the package.

## Contributor build

Use standard CPython 3.14 x64 on Windows and a dedicated environment. Build assets
once with Node 20+/npm, then build the package with the pinned dependency set:

```powershell
python -m venv .local/windows-build-env
.\.local\windows-build-env\Scripts\python.exe -m pip install -r requirements/windows-build.lock
npm.cmd ci
npm.cmd run build
.\.local\windows-build-env\Scripts\python.exe scripts/build-windows.py --output .local/windows-preview
```

The output directory must not already exist; the builder never replaces an old
package. Build work remains in a unique `.local/windows-build-*` directory.
Run the packaged-process drill against the extracted folder:

```powershell
.\.venv\Scripts\python.exe scripts/verify-windows-package.py --package .local/windows-preview/OpenHMI --work '.local/packaged process drill'
```

The drill requires a new work folder and retains its report, logs and synthetic
backup. It verifies manifest hashes, HTTP assets, second-runtime rejection, forced
restart and backup/restore while removing Python/Node from the child process PATH.
The backup drill checks that a locked canvas image and a saved trend CSV survive
restoration.
It kills only the exact subprocess handles it starts. This checks a packaged
process on the build machine, not a clean machine. Test Ctrl+C shutdown separately
in a console, along with the target identity/controller/operator environment.

The lock pins the tested build/runtime versions, not a cross-platform or
byte-identical reproducible-build guarantee. Review/update the lock deliberately.
The build records whether source differs from its commit; distribute only a
reviewed, clean-source build. Build tooling follows the
[PyInstaller one-folder workflow](https://pyinstaller.org/en/stable/usage.html).
