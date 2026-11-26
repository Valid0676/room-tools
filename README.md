# Room tools for the X32 Compact

Two browser tools for setting up a room with a reference mic:

- **Room tuning** (`room-tuning.html`): plays pink noise through the PA, compares what the
  reference mic hears with the noise that was sent, and fits the X32 Main LR EQ to match a target.
- **Feedback finder** (`feedback-finder.html`): finds and logs ringing frequencies while you raise the gain.

## Start

Double-click **RoomTools.exe**. It opens the tools in your browser (use Chrome or Edge as the
default browser). Keep its window open while you work; close it to stop.

First run on a new PC: SmartScreen may say "Windows protected your PC". Click **More info → Run anyway**.
When Windows Firewall asks, allow it on **private networks** so it can reach the desk.

To run from source instead: `python x32_bridge.py`.

## Getting a new build

Every push to `main` builds a fresh exe on GitHub: open the repository's **Actions** tab, pick the
latest "Build RoomTools.exe" run and download **RoomTools-build-N** from Artifacts (a zip with the exe).
For a version to keep, push a tag such as `v1.2`; the exe is then attached to a Release.
The build number shows at the top of the X32 panel ("Bridge running · build N").

The bridge passes messages between the page and the desk (OSC over UDP port 10023), because browsers
can't do that themselves. It only lets through Main LR EQ, Main LR insert and FX-slot settings.
Without the bridge you can still measure and enter the EQ on the desk by hand.

## Room tuning routine

1. **Patch**: noise out of the laptop/interface into one desk channel (EQ and dynamics flat, to Main LR at
   unity). Reference mic into the interface. Connect to the desk with its IP (Setup › Network).
2. **Level**: press Play pink noise and bring the PA up to a normal show level. Set the mic preamp so the
   meter sits near −20 dBFS.
3. **Measure**: with "Bypassed: measure the room", measure 3–5 positions across the audience area
   at ear height. The tool bypasses the Main LR EQ during each measurement and switches it back on after.
4. **Correct**: choose a target (House curve suits most PA work), the bands the tool may use, and the
   max boost. Low/high cut bands already on the desk are left alone. Press **Send EQ to desk**.
5. **Check**: measure again with "As it is now". The purple trace is the room with the EQ applied.
   Use **Undo last send** to put the desk back.

Graphic EQ mode writes a GEQ or TruEQ that is already inserted on Main LR (choose its FX slot).
