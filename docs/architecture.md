# Architecture and designer decision

Decision date: 2026-11-04. Status: initial prototype direction.

OpenHMI will use CPython for drivers and application logic, and a browser for
designing and running screens. The web designer necessarily uses JavaScript;
Python remains the runtime and future application event-handler language.

## Desktop options

Python can call .NET through [Python.NET](https://pythonnet.github.io/pythonnet/python.html)
or [IronPython](https://ironpython.net/documentation/dotnet/dotnet.html).
That is runtime interoperation, not a Python WinForms designer integration.
[Visual Studio's Python tooling](https://learn.microsoft.com/en-us/visualstudio/python/overview-of-python-tools-for-visual-studio)
documents Python editing, projects and debugging; its
[WinForms designer workflow](https://learn.microsoft.com/en-us/visualstudio/designers/walkthrough-windows-forms-designer)
uses .NET form projects. We found no documented current native Python WinForms
designer workflow. This is a documentation-based assessment, not a local VS test.

A C# WinForms class library with a Python host could retain drag-and-drop .NET
controls, but would require a separate bridge for events, UI-thread dispatch,
packaging and debugging. It remains technically plausible, not prototyped here.
The project owner chose a Python runtime with a web designer instead.

[Qt Designer / PySide6](https://doc.qt.io/qtforpython-6/tutorials/basictutorial/uifiles.html)
is another viable native Python visual-design path, using .ui files. It would
use Qt controls rather than WinForms controls and does not meet the selected web direction.

## Existing editor candidates

| Candidate | What it provides | Work needed for OpenHMI | Assessment |
| --- | --- | --- | --- |
| [FUXA](https://github.com/frangoteam/FUXA) | MIT HMI/SCADA web editor and runtime; Angular/SVG frontend, Node.js backend | Prove editor/backend separation or bridge to Python; map tags, subscriptions, scripts and deployment | Strongest HMI-specific alternative; evaluate before a large designer investment |
| [GrapesJS core](https://github.com/GrapesJS/grapesjs) | BSD-3-Clause embeddable component, block, property and layout editor | Supply industrial controls, bindings, runtime renderer, screen format and Python event bridge | Selected for a bounded first prototype |
| [Eclipse Theia](https://theia-ide.org/docs/composing_applications/) | Extensible browser/desktop IDE platform with code-editor integration | Add a screen designer and HMI project tools; maintain its separate backend | Potential later IDE host; does not supply an HMI canvas by itself |

These are source/documentation assessments. FUXA and Theia have not been built
or benchmarked locally. GrapesJS **core** is distinct from the commercial
[Studio SDK](https://github.com/GrapesJS/studio); OpenHMI uses core only.
No FUXA, Theia or AdvancedHMI code or assets are vendored.

GrapesJS's [custom components](https://grapesjs.com/docs/modules/Components.html)
and [project storage](https://grapesjs.com/docs/modules/Storage.html) are the
extension points for the first designer experiment. Node/npm prepares editor
assets; the running prototype should need only Python and a browser.

## Target structure

```text
Browser designer -> versioned project -> validated runtime screen
                                            |
Browser runtime <- tag values/quality <- Python binding/subscription service
                                            |
                                     Python driver adapters -> PLC
Browser actions -> named Python handlers -> authorized driver writes
```

Screens should have names, control instances, geometry, properties and explicit
bindings. Driver instances are shared by controls through a ComComponent-style
reference; addresses stay separate from labels and display formatting. A control
catalog should drive both the toolbox and runtime rendering. A future project
contains screens, connections, reusable controls and Python handler modules.

The first prototype is simulation-only. Its editor format is experimental, with
browser-local save/load, and its runtime values are polled. It must not be
mistaken for the final portable project format or subscription transport.

## Acceptance gates

1. Drag a numeric display and indicator onto a screen, edit their addresses,
   save/reload, and view simulated values in runtime mode.
2. Prove an editor-independent versioned project format, validation and migrations;
   compare the same screen round trip with FUXA before committing to a larger editor.
3. Add Python application handlers, driver subscription lifecycle, quality,
   timestamps, stale/disconnected rendering and deterministic cancellation tests.
4. Add one independently implemented protocol adapter with simulator tests and
   explicit hardware read/write acceptance; select PLC family before this step.
5. Add write controls with permissions, typed validation, audit and failure feedback.
   Keep designer preview disconnected from physical equipment.

Deployment authentication, multiuser editing, historian/alarms, reusable faceplates,
debugging and signed application packaging are subsequent product work.
