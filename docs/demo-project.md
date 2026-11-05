# OpenHMI demo project

Open **Live screen** to see the process overview, then use the screen navigation
or the buttons on the overview.

1. **Station overview** shows a tank fill and normal band, flow, pump status, a
   UDT-bound pump faceplate, a string display and the loaded recipe image.
2. **Simulator** has bounded numeric and text inputs with touch entry. Edit the
   tank, flow or temperature to change the live charts. Toggle the simulated
   fault, open **Alarms**, and select **Alarm details** for the cause, recovery
   steps and link back to Simulator. Clear the fault in Simulator and acknowledge
   it in Alarms.
3. **Trends** opens with a preloaded simulation capture in the simulation
   project. Hover over the chart for a shared cursor or switch **Trend data** to
   the continuous historian. Use **Run trend** and **Stop trend** to save a new
   capture and export it to CSV.
4. **Recipes** includes an approved profile and a draft trial profile. The
   approved example includes its review history, an image and a loaded copy.
5. Switch between English and Spanish using the flag selector. The demo includes
   sample translations for overview text and alarm guidance.

The generator requires a new directory and creates a standalone SQLite project
and a complete backup ZIP. Open the database with `openhmi --project PATH`, or
import the ZIP from **Projects** in the matching OpenHMI runtime. The demo uses
the default unsecured simulator. There are no bundled login credentials.

## Private PLC preview

For a controller with the four standard scalar demo tags and a demo UDT, use
the generator's optional `--read-only-route`, `--udt-type`, and repeated
`--udt-bit` arguments with the verified controller route, UDT type and visible
Boolean member names. The generator stores the route in the output database and
backup. Keep those files local.

The optional **PLC preview (read-only)** screen binds to `_Demo_DINT`,
`_Demo_REAL`, `_Demo_STRING`, `_Demo_BOOL` and selected Boolean members of
`_Demo_UDT`. The connection starts held. Keep the accompanying `.hold` file
beside the database if opening the SQLite file directly. Review the connection
and tag settings before using **Apply live** to release acquisition. The PLC
screen uses a 2-second update interval and the screen's tag subscription. The
Simulator's inputs and buttons target its own local tags.
