# Project languages and alarm monitoring

## Language assets

OpenHMI bundles the supplied `NotoSansSC.ttf` unchanged (SHA-256
`dc71173babc38dfd019912965f2b4b3421fb347ebd854e7b96f64ad63673924a`). Its embedded
name table identifies Noto Sans SC Regular 2.004-H2 and the SIL OFL 1.1. The matching
[upstream OFL](https://github.com/google/fonts/blob/main/ofl/notosanssc/OFL.txt)
is distributed beside it. The supplied 4:3 SVG flags are from flag-icons 7.5.0;
their MIT license is retained. Assets are local and do not require a CDN.

The font's x-height is 543/1000 em versus Arial's 1062/2048 em. Existing HMI
font sizes are multiplied by 0.955 to keep a similar perceived Latin text size;
this is not a guarantee of identical line length. The supplied font contains
the tested English, Spanish, Simplified Chinese and Japanese sample characters.
It does not cover the tested Korean, Arabic or Hebrew samples. Browser/system
fallback is retained for other scripts; target-language coverage needs review.

## Configuration and selection

Use **Languages** in the builder to add a language code, native display name and
an explicit flag. Flags represent the project's chosen association, not a claim
that a language belongs to one country. New projects initially configure English
only. The runtime flag button lists only other configured project languages.
With the flag button focused, press Enter or an arrow key to open the menu.
Use Up/Down or Home/End to move through the flags and Enter to select.
Escape closes the menu and returns focus to the flag button.
Each browser remembers its own selection and falls back to the configured default
if that language is removed.

Translation keys cover screen titles, control labels, units, binary-state text,
alarm messages and operator UI text. Empty entries use the source text; no
translation is generated automatically. Adding a language does not change tag
names, action names, alarm IDs or stored numeric values. Number formatting follows
the selected locale. The engineering editor remains in English.

Trend tools, cursor readouts and saved capture controls use the project
translations. Cursor and capture dates follow the selected locale. The plot
keeps time increasing from left to right, and CSV fields use the export format.

Language and alarm configuration are part of the draft and take effect in runtime
with **Apply live**, alongside the screen. Existing projects receive compatible
defaults when edited; opening them does not overwrite their saved content.

## Alarm model

FactoryTalk ME's [alarm overview](https://www.rockwellautomation.com/en-pl/docs/factorytalk-view/16-00-00/me-help-ditamap/graphic-objects-drawing-elements/the-alarm-setup-editor/about-alarms.html)
separates monitored triggers/messages from alarm graphics, and describes startup
monitoring, retained messages and acknowledgement. Its
[XML reference](https://www.rockwellautomation.com/en-se/docs/factorytalk-view/16-00-00/me-help-ditamap/graphic-objects-drawing-elements/alarm-import-export-wizard/alarm-xml-file-elements.html)
documents value, bit and LSBit triggers. These inform OpenHMI's independently
implemented model, rather than an import-compatibility promise.

Use **Alarm setup** to define project-wide triggers and messages:

* `value`: a tag equals a configured nonzero signed integer. Boolean true matches 1.
* `bit`: one numbered position in a 32-bit word. Position 1 is PLC bit 0;
  position 32 is PLC bit 31. Signed DINT values are interpreted as 32-bit words.
* `lsbit`: only the lowest set bit position in that word matches.

The ME [user guide](https://literature.rockwellautomation.com/idc/groups/literature/documents/um/viewme-um004_-en-e.pdf)
documents this one-based bit-position convention. OpenHMI currently supports
individual 32-bit words, not ME's larger array triggers or arbitrary expressions.

The Python service samples the active configuration every 250 ms while running,
even with no browser open. Screen visibility does not control monitoring. Polling
can miss shorter pulses; this prototype is not a controller-resident event queue.
Actions request an additional sample after completing. Draft changes do not
affect monitoring until applied.

Every false-to-true observation creates an occurrence with its source message,
available translations, priority and UTC timestamps. Repeated true samples do not
create duplicate events. Return-to-normal and acknowledgement are separate:
acknowledgement records operator awareness and never writes or clears a PLC tag.
Returned but unacknowledged occurrences remain visible. A retrigger creates a new
occurrence even if an earlier returned occurrence still awaits acknowledgement.

Missing or invalid trigger data becomes bad quality and does not fabricate a
return-to-normal. Removing/disabling a trigger, or changing its trigger semantics,
retires its current occurrence explicitly; pending acknowledgement is preserved.
History records configuration and quality transitions. Message/priority edits do
not retrigger an unchanged condition; occurrence text remains the original snapshot.
Languages added after an occurrence fall back to its original source message.

The [alarm console](alarm-workflows.md) provides filtered/paged occurrences,
selected/individual/all acknowledgement, captured cause/response guidance,
related-screen links, attributed append-only notes and event CSV export. The header summarizes project-wide outstanding alarms,
including those with no screen graphic. Legacy Boolean alarm controls remain
indicators and do not implicitly register a monitored trigger.

The project SQLite database retains occurrences, acknowledgement and history.
The configured history limit bounds events and completed occurrences; unresolved
occurrences are retained beyond that limit. After restart, the service reconciles
retained state with newly observed values. The simulator's tags reset on restart.

Timed [alarm shelving](alarm-workflows.md#timed-shelving) is available without
changing monitoring or PLC values. Remote PLC acknowledgement handshakes,
audible/silence behavior, controller downloads and multi-process runtime ownership remain unimplemented.
HMI security protects acknowledgement and notes through separate permissions;
real-controller and local/Windows identity commissioning remain separate work.
