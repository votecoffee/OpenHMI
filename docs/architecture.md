# Live HMI builder architecture

Decision date: 2026-11-04. Status: working local simulation prototype.

OpenHMI is a live HMI builder for automation developers. A basic application
must be possible without code: drop controls, select tags, configure formatting
and built-in actions, and apply the screen to a running viewer. Python is the
customization language. HTML, CSS, JavaScript, React and npm must not appear in
the HMI developer workflow. These remain implementation tools for OpenHMI contributors.

AdvancedHMI compatibility is no longer a requirement. The earlier
[compatibility investigation](advancedhmi-compatibility.md) is historical context.
FUXA is a feature/interaction reference only; it is not a dependency, integration
candidate or mandatory comparison gate.

## Editor assessment

| Reference | Useful capability | Decision |
| --- | --- | --- |
| [Anvil](https://anvil.works/docs/client/quickstart.html) | Visual forms, property editing and Python event handlers | Model the development experience; do not assume its visual editor is part of the open-source runtime |
| [Puck](https://puckeditor.com/docs/getting-started) | Ready editor interface, registered React controls, fields and a matching runtime renderer | Selected next prototype base; hide React and editor serialization behind OpenHMI |
| [Craft.js](https://craft.js.org/docs/overview/) | Building blocks for highly customized drag/drop React editors | Keep as an alternative if spatial editing or custom interaction exceeds Puck's fit; more editor UI must be authored |
| [GrapesJS core](https://github.com/GrapesJS/grapesjs) | General HTML/template editing | Retire the first prototype; its web styling concepts and separate runtime renderer do not match the new workflow |
| [FUXA](https://github.com/frangoteam/FUXA) | HMI control, alarm, trend and engineering interaction examples | Ideas only; no adoption or integration |

Puck and Craft.js both publish MIT licenses. Puck's
[component configuration](https://puckeditor.com/docs/api-reference/configuration/component-config)
allows an HMI-specific property inspector. Its
[Render component](https://puckeditor.com/docs/api-reference/components/render)
lets editing and runtime use the same control implementations. Puck does not
provide Python execution, PLC drivers or persistence; OpenHMI supplies those.
Craft.js's documentation explicitly describes editor building blocks rather than
a complete tailored editor. This comparison is based on primary documentation;
Craft.js and Anvil have not been prototyped locally.

Anvil's [open-source runtime](https://github.com/anvil-works/anvil-runtime)
can host apps independently, while its README identifies the visual builder as
the cloud editor. Anvil's
[deployment environments](https://anvil.works/docs/deployment)
associate an application version with a deployment. We borrow the distinction
between editing a draft and applying a version, not an undocumented promise of
arbitrary hot code replacement.

## Live development contract

1. The editor displays current simulated tag values while controls and properties
   are edited. Interacting with an editor control selects/configures it; it does
   not invoke an equipment command.
2. Draft changes autosave on the Python server. Runtime viewers continue to use
   the active screen until the developer applies the draft.
3. Applying a validated screen changes the active revision. Existing viewers
   receive it without a manual page refresh or a Python process restart.
4. Draft saves and apply operations include the expected revision. Conflicting
   writers receive a conflict rather than silently replacing another draft.
5. Tag state and driver ownership belong to Python and survive screen-only changes.
   Editing a binding does not recreate the driver or replay an action.
6. Python customization uses named application actions. The browser chooses a
   registered action; it does not submit Python source for execution.

The first implementation is a local, single-screen simulation prototype.
Screen/tag delivery may use bounded polling initially. Production permissions,
audit, rollback UI, multiple users, subscriptions and commissioning behavior need
separate acceptance. Live Python code replacement is a future feature with a
module lifecycle; initially custom handlers are loaded at startup.

## Project and runtime ownership

```text
HMI editor -> validated OpenHMI draft -> active screen revision -> runtime viewers
      |                                      |
      +-- shared control catalog ------------+
                                             |
                                  Python tags and named actions
                                             |
                                   independent driver adapters
```

Persist an OpenHMI schema with typed control properties, tag references and named
actions, not raw HTML/CSS or Puck internals. An adapter translates between that
schema and the editor. Use identical controls for editor previews and viewers.
The initial layout is a configurable control grid in a gray ME-derived screen
frame; [the HMI style guide](hmi-style-guide.md) records its source decisions.
Free placement, reusable
faceplates, multiple screens and richer graphics remain future work.

## Priorities

* No-code: tag browser, numeric display, indicator, action button, format/units,
  analog ranges, explicit alarm indicators, screen navigation and reusable equipment controls.
* Python customization: local handler modules first; later an integrated editor,
  event templates, diagnostics, dependency management and deliberate reload.
* Live engineering: autosaved drafts, apply without viewer reload, revision conflict
  feedback, later history/rollback and collaborative editing.
* Industrial runtime: quality/timestamps, subscriptions, reconnect, typed writes,
  richer alarm workflows/trends, access control and a separately accepted first protocol adapter.
* Installation: contributors may need Node; released end-user builds should ship
  assets and present project/open/run controls without web tooling.

Track the next work in [project/editor lifecycle](https://github.com/votecoffee/OpenHMI/issues/1),
[Python customization and subscriptions](https://github.com/votecoffee/OpenHMI/issues/2),
and [first PLC adapter](https://github.com/votecoffee/OpenHMI/issues/3).

## Current validation

Local Python tests cover rejected bindings/schema data, draft/apply separation,
stale revision rejection, persistence across server restarts, built-in actions
and loading/invoking a custom Python action. Browser checks exercise actual
drag/drop, property editing, autosave/reload, apply to an already-open viewer,
live tag updates after a Python action, disconnected values and stale-editor
conflicts. Editor preview actions stay disabled. These are simulation checks,
not PLC, production deployment or arbitrary Python hot-reload acceptance.

Project-wide [languages and alarm monitoring](languages-and-alarms.md) are now
implemented separately from screen controls. The Python lifespan owns the alarm
sampling task; SQLite retains alarm occurrences and events. Runtime graphics
consume its status without driving the monitor. Draft language/alarm settings
share the screen's validation, revision checks and Apply live boundary.

[SQL recipes](recipes.md) use a separate revision and review lifecycle. Python
owns immutable content revisions, approval identity, field-change audit, images
and operation policy in SQLite. Loading takes a separate snapshot of the content
and its production-approval Boolean. Library changes do not alter the simulator's
loaded copy. Test recipes may be loaded; the eventual controller owns run/reject
decisions. Recipe accounts protect those operations only; application-wide
authentication and a real controller transfer handshake remain future work.
