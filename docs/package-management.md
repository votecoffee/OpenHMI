# Managed preview installation and rollback

The Windows preview includes an offline package manager. It installs each version
beside earlier versions, verifies integrity and selects the application used on
the next launch. It does not install a Windows service or restart an operating HMI.
Clean-machine deployment and pilot acceptance remain open.

## Install and select a version

Run these commands from an extracted preview containing `OpenHMI.exe`. Substitute
the exact archive filename you downloaded. Check its expected checksum against
trusted release information before using the sidecar; a checksum supplied beside
an unknown download does not authenticate its publisher.

```powershell
$package = '.\OpenHMI-0.1.0.dev0-windows-x64.zip'
$expected = (Get-Content ($package + '.sha256')).Split()[0]
.\OpenHMI.exe package install $package --sha256 $expected
.\OpenHMI.exe package activate $expected
.\OpenHMI.exe package list
.\OpenHMI.exe package launch --open-browser
```

The package manager's default Windows application root is
`%LOCALAPPDATA%\OpenHMI\application`. Projects remain in
`%LOCALAPPDATA%\OpenHMI\projects`. An installation stores:

* `releases/<first 24 checksum characters>/OpenHMI`: complete application files.
* `installation.json` beside each application: original archive and manifest hashes.
* `active.json` at the application root: selected full archive checksum and prior selection.

The full SHA-256 is always the release identifier. A shortened folder name reduces
path length; the full identity is checked before reusing an existing directory.
Installation does not activate the version automatically. Reinstalling an existing
archive verifies its installed copy and refuses to overwrite changed evidence.

Use a separate local application root when needed; put `--root` before the command:

```powershell
.\OpenHMI.exe package --root 'D:\OpenHMI\application' install $package --sha256 $expected
.\OpenHMI.exe package --root 'D:\OpenHMI\application' activate $expected
.\OpenHMI.exe package --root 'D:\OpenHMI\application' launch --project 'D:\OpenHMI\projects\Line1.openhmi.sqlite3' --port 8010
```

`launch` also accepts `--log-dir`, `--handlers`, `--open-browser` and `--self-check`.
The selected package is verified before execution. Projects and logs explicitly
placed inside the application installation are rejected. The runtime's existing
library lock prevents simultaneous launchers from owning the same project library.

## Update and rollback

1. Export complete backups from **Projects**, retain external handlers and stop
   the runtime with Ctrl+C. Keep the existing application version.
2. Install the new archive using its expected SHA-256. Verify it with
   `package verify <full-checksum>`, then activate and launch it.
3. Check the project, users/groups, recipes/images, alarms/history and required PLC
   behavior before accepting the update. Installed binaries and project data live
   separately; activation changes only the application selection file.
4. To select an older application, use `package list`, then
   `package activate <older-full-checksum>` and launch again. Older versions are
   retained. Re-selecting an application does not reverse database migrations or
   PLC state: restore a compatible pre-update project backup into a separate
   library when rolling back across a schema change.

An already-running application continues using its original version. Selection
changes do not kill it, replay commands, clear project data or silently restart it.
There is no automatic package deletion/uninstall. Stop the runtime before removing
an installation folder deliberately; preserve the separate project/backup folders.

## Verification and failure behavior

The manager requires the expected archive SHA-256, a clean-source package manifest
and an exact file inventory with per-file hashes. It verifies installed metadata,
file inventory and hashes before activation or launch. Corruption, extra payloads,
encrypted entries, archive links, Windows path collisions, traversal and reserved
device names are rejected. Windows path handling follows the
[Microsoft filename rules](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file).
Symbolic links/junctions in installed application paths are rejected too.

Archives are limited to 256 MiB, 5,000 payload files and 1 GiB expanded size.
Installation validates and hashes the captured archive before publishing a new
version directory. Activation writes a flushed temporary selection and atomically
replaces `active.json`. Failed installs and selection failures before the atomic replacement leave the
prior selection intact; a committed selection stays selected. New failed staging/selection files are retained for inspection;
the manager does not recursively delete uncertain paths or overwrite unknown
selection formats. Concurrent package mutations use an OS lock.

Hashes detect integrity changes, not publisher authenticity or malicious packages
whose hashes are already trusted. Filesystem access controls, code signing and the
target installation account remain deployment acceptance work. This is an unsigned
preview, not a signed Windows installer or service deployment.

## Contributor check

The same manager can be exercised without changing the user's application root:

```powershell
.\.venv\Scripts\python.exe -m openhmi.package_manager --root .local/package-drill install $package --sha256 $expected
.\.venv\Scripts\python.exe -m openhmi.package_manager --root .local/package-drill activate $expected
.\.venv\Scripts\python.exe -m openhmi.package_manager --root .local/package-drill launch --self-check
```

Local fixtures cover tampering, path/case collisions, invalid metadata, interrupted
activation, retained previous versions, launch argument boundaries and unchanged
synthetic project bytes. These are software checks; perform the clean-machine,
service, identity, controller and operator-display acceptance gates separately.
