# Initial control and screen style

OpenHMI's default operator screen follows high-performance HMI principles with
the structure and visual vocabulary of the supplied FactoryTalk View ME templates.
This is an independently authored web implementation, not an ME display importer
or a claim of ISA certification/native FactoryTalk acceptance.

## Source decisions

| Source and locator | Evidence used | OpenHMI decision |
| --- | --- | --- |
| `proces-wp023_-en-p.pdf`, PDF pp. 18-21 | Neutral backgrounds; restrained live-data color; alarm colors reserved; redundant state encoding | Gray normal screens, blue values, text plus shape for state/alarms |
| Same PDF, pp. 27-30 | Labels and units; limited precision; contextual analog ranges; filled/empty binary symbols | Compact numeric display, labeled binary indicator, analog range control |
| `The-High-Performance-HMI-Handbook-1st-Edition.pdf`, pp. 68, 84-85 | Gray 2D equipment, limited color, no decorative motion, redundant encoding | No card shadows, gradients, green healthy-state badges or decorative animation |
| `pdfcoffee.com_isa-101-pdf-free.pdf`, PDF p. 38 (printed p. 37), clauses 5.2.1.2-5.2.1.4 | Color is not the sole signal; neutral background; consistent placement and density | Explicit alarm labels, distinct priority shapes, compact aligned grouping |
| `FTView_Template/Displays/TPL_Station Overview.xml`, `displaySettings`, `HeaderGroup`, `RightSidebarGroup`, `FooterGroup` | 800x600 screen, #DDDDDD background, Arial, consistent framing | Responsive screen derived from header/body/sidebar/footer proportions |
| `FTView_Template/GlobalObjects/Base.xml`, `HeaderBackground`, `FooterBackground`, `BodyLayoutBoundary` | Header 70px; footer starts at y=525 and is 75px tall; sidebar near x=725 | Persistent title/status area, body workspace, 75px reference side strip and footer |
| `FTView_Template/GlobalObjects/Color Palette.xml`, `DiagnosticPriority1` through `DiagnosticPriority4` | Priority number, shape and fill; P1 red, P2 yellow, P3 orange, P4 pink | Same priority mapping for explicit alarm indications; never infer that all source palettes use this order |
| `FTView_Template/GlobalObjects/Color Palette.xml`, `Pump`, `Tank`, `PrimaryLine`, `NavigationArrow` | Simple gray equipment, range context, dark connector lines | Future equipment controls should share the same restrained 2D vocabulary |

The supplied documents are design references, not operating instructions. Original
PDFs, XML exports, machine references, logos and graphics are not modified or
redistributed. The detailed local source audit remains outside tracked source.

## Default visual language

* Screen background: `#DDDDDD`; grouping and boundaries use nearby gray tones.
* Labels: bundled Noto Sans SC/sans-serif and dark gray, sized to retain the earlier
  Arial x-height. Live numeric values use subdued navy/blue.
  Operator labels describe equipment; raw tag names are engineering details.
* Controls are flat and rectangular. Numeric readouts blend into the display;
  borders identify groups, clickable commands or abnormal/quality conditions.
* Normal ON/OFF states use filled/empty grayscale symbols plus text. ON does not
  mean healthy and OFF does not mean alarm; the configured process meaning matters.
* Command buttons use the template's navy `#002878` with white text. Execution
  feedback says pending/completed/failed. Disabled commands remain visible.
* Color is never the sole indicator. Alarm symbols include priority number and
  state text; a communication/data failure explicitly suppresses a normal reading.
* Keyboard focus remains visible. The XML's disabled focus-highlight option is
  not carried into the browser. Touch targets and text need plant-floor evaluation.

## Initial catalog

| Control | Intended behavior |
| --- | --- |
| Numeric display | Label, live value, engineering units and selected precision; no input-like frame |
| Binary indicator | Stable label, grayscale filled/empty square and configurable ON/OFF text |
| Analog range | Value and units, scale endpoints, normal band and pointer; out-of-scale indication without falsifying the numeric value |
| Tank level indicator | Vertical live fill, engineering units, scale endpoints and normal band |
| State image | Switch between two project images from a Boolean tag, with an optional caption and explicit unavailable-data indication |
| Setpoint comparison | Compare process and setpoint tags, show signed deviation and tolerance, and identify unavailable inputs individually |
| Bitfield display | Read a 32-bit status word as hexadecimal and named on/off bits, with a common quality indication |
| PLC connection status | Show one configured controller's acquisition state and link to affected tags when Diagnostics access is available |
| Tag quality | Show good, stale, unavailable, or disconnected status for one tag, with sample age and an inspectable badge |
| Numeric LED display | Compact seven-segment readout with fixed positions, units, and explicit overflow and quality indications |
| Stack light | Group Boolean signals using configurable active color and polarity, with text and quality on each lamp |
| Radial gauge | Dial with normal band, engineering readout, and a needle that disappears when the value is unavailable |
| Bar graph | Compare up to 12 numeric tags with a shared engineering scale and units. Bars extend from zero when zero is in range, or from the endpoint nearest zero |
| XY chart | Plot up to 8 live numeric tag pairs on independent scales with numbered points and per-axis quality |
| Pie chart | Compare shares of a total across 2 to 8 nonnegative numeric tags with a numbered legend and explicit incomplete-data status |
| Radar chart | Plot 3 to 8 numeric tags around a shared profile, with engineering units and scaling set independently per axis |
| Alarm indicator | Explicit Boolean alarm binding, active/inactive text and numbered priority shape; no implicit alarm from a running/stopped bit |
| Action button | Named Python action, visible disabled state and explicit execution feedback |

These live charts use the screen's normal tag update rate. If a value exceeds
its configured scale, the chart clips the geometry and shows the measured value
and an out-of-scale label. Bad-quality values suppress tank fills and bars. The
radar chart suppresses the polygon when an axis is unavailable and keeps the
individual valid points visible. Radar numbers match the axis labels and engineering ranges below
the chart. Bars compare values in the same units. A Trend shows change over time.

An analog normal band is operator context, not an alarm engine. An excursion
outside the band is labeled as such and does not consume alarm colors. Alarm
priority meanings must be set by the application's alarm philosophy. The initial
alarm indicator has no acknowledgement, shelving, history or safety function.
The screen banner now summarizes project-wide registered alarms through the
[alarm monitoring service](languages-and-alarms.md). Legacy Boolean alarm controls
remain graphics; registering a monitored trigger is a separate project setting.

## Reference conflicts and limits

The template has bright normal-mode/command states. OpenHMI retains its navy
command/navigation language and framing, but follows the HPHMI guidance for
neutral normal state and reserved alarm colors. PlantPAx's example priority colors
also differ from the template; this project deliberately chooses the supplied ME
palette and documents it rather than mixing mappings.

The exported XML includes authoring boundaries with `visible="false"`. Their
geometry is layout evidence, not proof those boundaries are visible in ME.
No customer logo, live login state, real alarms or unsupported navigation is
invented. The reference dimensions guide responsive proportions, not a claim of
pixel-identical native rendering. Readability, grayscale discrimination, alarm
philosophy and display density still need operator review on the target hardware.
