# Screen layout

Every screen starts in the grid layout. Select **Enable freeform layout** in
the designer to convert the selected screen. Existing controls get initial
positions and retain their bindings. The layout is saved with the draft and
takes effect in runtime when you select **Apply live**. Faceplate definitions
have their own grid layout. A faceplate instance can be placed and resized as
one object on a freeform screen.

## Machine graphics and overlays

Set **Canvas width** and **Canvas height** to the target work area. Upload a PNG,
JPEG or WebP using **Background image**. The image is fitted to the exact canvas
rectangle, so use matching proportions for undistorted machine artwork. It is
stored with the project. Images may be up to 8 MiB and 4096 pixels per side.
Complete backups include the image, and applied
revisions retain their image references.

Choose a control in **Control palette** and drag **Add or drag control** to the
canvas. Clicking the button also adds it. Move controls by dragging their
borders or bodies. Select a control to use the corner resize handle or enter
exact **X**, **Y**, **Width** and **Height** values. **Snap to grid** applies to
dragging and resizing. The position fields accept exact pixels. **Zoom** changes
the editing view. The live canvas uses the configured pixel sizes and scrolls
if the viewer is smaller.

Controls may overlap. Use **Objects** to select a control that is covered.
**Bring to front** and **Send to back** change the stacking order. Drag a
selection box from empty canvas to select objects it touches. Hold **Shift**
while dragging to add to the current selection. A group is selected together
and locked backgrounds are skipped. **Escape** cancels the selection drag.
You can also Shift-click individual objects. Align their edges or centers, or space three
or more objects evenly. **Group** makes a selection move together and
**Ungroup** restores individual selection.

Select two or more objects and pick a **Size reference** in **Selection**.
**Match width**, **Match height**, and **Match size** copy the reference
dimensions in one undoable edit. Objects keep their positions. A match that
would extend past the canvas edge is unavailable.

Use **Duplicate selection** or **Ctrl+D** to copy selected canvas objects.
Copies retain their tag bindings and relative positions and receive new IDs.
Duplicating a container also copies its contents. **Copy selection** and
**Paste selection** (Ctrl+C and Ctrl+V) work between freeform screens in the
same project while the designer stays open. A paste is one undoable edit.
With focus on the canvas
or an editor button, use the arrow keys to move the selection by one pixel,
or hold **Shift** to move it by one grid interval.

Use **Undo** and **Redo** in **Canvas tools** to revisit the last 60 edits in
the open freeform editor. With focus on a canvas object or toolbar button,
use **Ctrl+Z**, **Ctrl+Shift+Z** or **Ctrl+Y** (Command also works on macOS).
A drag or resize is one edit. Undo and redo update the draft and take effect
for operators after **Apply live**. Reopening the editor starts a fresh undo
history.

## Locked background objects

Under **Images and shapes**, add an **Image object**, **Rectangle** or **Ellipse**.
Size and position it on the canvas. Select one or more image or shape objects
and choose **Lock as background**. Locked objects sit behind all controls and
containers in both the designer and runtime. They pass clicks and drags
through. To edit one again, choose **Unlock** next to its name in **Objects**.
A screen-wide background image sits below the locked objects.

## Grid and stack containers

Select one or more freeform controls and choose **Pack into grid** or **Pack into
scrollable stack**. The resulting container can be positioned and resized on the
canvas. A grid uses the configured **Grid columns**. A stack places controls in
a single column and scrolls when they exceed the available height. Members
appear in selection order and can be selected in **Objects** to edit their
bindings. **Unpack container** puts its members back on the canvas at their
stored freeform positions.

**Switch to grid layout** removes freeform placement, containers and the
background from the draft screen after confirmation. Previously applied layouts
can be recovered through project revisions.
