# CS-105 Consist Builder

A small JMRI-hosted GUI for building and viewing native consists on a
[TCS CS-105](https://www.tcsdcc.com/cs-105) command station from a computer,
as an alternative to doing it from a UWT throttle.

It talks to the CS-105 over LCC/OpenLCB using JMRI's bundled
`TractionThrottle` class — the same "Traction Listener Attach" protocol a
UWT throttle uses to build consists. Consists created this way are real,
native CS-105 consists (the same "Runs with X" relationships visible in the
CS-105 Network Tree app), stored on the command station itself and usable
from any throttle afterward. This is deliberately **not** JMRI's separate,
CV19-based "Consist Tool" — that writes a Decoder Assisted Consist to the
locomotive's decoder instead, which is a different (older, more universal
but less capable) kind of consist.

## Requirements

- JMRI (PanelPro or DecoderPro), with an active LCC/OpenLCB connection to
  the CS-105.
- Your locomotives' DCC addresses (there's no roster dropdown — every
  locomotive is picked by typing its address directly).

## Running it

In JMRI: **Panels → Run Script...**, then pick `cs105_consist_builder.py`.
It opens its own window, separate from JMRI's other tools. The
**Instructions** button in the top-right of that window reproduces the
walkthroughs below, so they're on hand without leaving JMRI.

## How to build a consist

1. Type the lead unit's DCC address into **Lead locomotive DCC address**,
   and check/uncheck **Long address** to match.
2. Click **Assign as Lead**. Status will show "Enabled" once JMRI has
   control, and the member list will show a `LEAD: ...` row plus anything
   already consisted to it.
3. Type the next unit's DCC address into **Add locomotive DCC address**
   (and its **Long address** checkbox). Check **Reverse** if it runs
   backwards relative to the lead, and **Respond to F0** if you want it to
   react to the lead's headlight function too.
4. Click **Add to Consist**. It appears in the member list once attached.
   Its CV19 is also automatically cleared (CV19 = 0 sent 3 times via
   Program on Main), and its horn honks 3 times (0.5 seconds each) once
   that's done. This does **not** happen for the lead itself — see "How
   to clear CV19 on the whole consist" below for that.
5. Repeat steps 3–4 for any further units.
6. To remove one unit later, select it in the member list and click
   **Remove Selected** (the `LEAD:` row itself can't be removed this way —
   use Release Lead instead if you want to fully let go of the consist).
7. Click **Release Lead** when you're done. This only gives up JMRI's
   control of the lead — the consist itself stays intact on the CS-105 and
   works from any throttle, exactly as if a UWT throttle had built it.

To just check what's already consisted to a locomotive without taking
control of it, use **Read Consist** instead of Assign as Lead in step 2
(same address field).

Click **New Consist** (top right) at any point to clear every address and
option field back to blank/default, ready for a fresh consist. It does
**not** release an active lead assignment or clear the member list — use
**Release Lead** for that.

## How to clear CV19 on the whole consist

If locomotives still have a CV19 value left over from an old Advanced
Consist setup, clear it on all of them at once — the lead plus every
attached member currently shown in the consist list:

1. Build or read the consist first (Assign as Lead / Add to Consist, or
   Read Consist).
2. Click **Clear CV19 on Entire Consist**.
3. Each engine is processed one at a time: CV19 = 0 is written 3 times in
   a row to it via Program on Main, then its horn honks 3 times (0.5
   seconds each) as an audible confirmation, before moving on to the next
   engine.
4. **CV19 status** shows progress throughout, ending with "CV19 cleared
   on all N engine(s) in the consist."

Units added via "Add to Consist" already get this same treatment
automatically as they're added — this button is for clearing the lead
too, or for re-running it across the whole consist at once.

## Features

### Building a consist

- **New Consist** — clears every address and option entry field back to
  blank/default. Doesn't touch an active throttle assignment or the
  member list.
- **Lead locomotive DCC address** — type the lead unit's address, with a
  **Long address** checkbox next to it.
- **Assign as Lead** — takes control of that locomotive as the consist's
  lead unit, and shows whatever's already consisted to it, if anything.
- **Read Consist** — a genuinely read-only query on the same address
  field: it never sends a controller-assign command, so it can't
  interfere with another throttle (a UWT, another JMRI session, etc.)
  that's already running that engine. Populates the same member list as
  Assign as Lead, marked read-only; click Assign as Lead afterward if you
  then want to edit what you saw.
- **Add locomotive DCC address** — same address + Long address entry,
  plus **Reverse** and **Respond to F0** flags, to attach another unit to
  the currently assigned lead via **Add to Consist**. Each added unit
  automatically has its CV19 cleared (3 writes) and its horn honked 3
  times (0.5 seconds each) as confirmation — see "Clearing CV19" below.
  This auto-clear only applies to units added this way, not to the lead
  itself.
- **Current consist members** — live list of attached units. The lead
  itself is shown as a non-removable `LEAD: ...` row at the top; real
  members follow.
- **Remove Selected** — detach the selected (non-lead) member.
- **Refresh List** — re-query the current consist from the CS-105.
- **Release Lead** — releases JMRI's own control access. This does
  **not** break up the consist — consists persist on the CS-105
  independent of any throttle's connection, the same as unplugging a UWT
  throttle.

The member list automatically filters out anything that isn't a real
locomotive. OpenLCB Traction doesn't structurally distinguish "a throttle
is controlling this train" from "this train is consisted to that lead," so
both JMRI itself (which attaches as a listener when it takes control) and
other throttles/devices (e.g. a UWT that currently has the loco selected)
would otherwise show up as phantom "members." Filtering works by checking
that a listener's node ID decodes to a plausible NMRA DCC address (1-127
short, 1-9999 long) — anything else is assumed to be a non-train device
and hidden.

### Clearing CV19

- **Clear CV19 on Entire Consist** — applies to the lead plus every
  attached member currently shown in the consist member list, one engine
  at a time: for each, CV19 = 0 is written **3 times in a row** via
  Program on Main (`CV19_REPEAT_COUNT` in the script), then its horn
  honks 3 times (0.5 seconds each, `ON_MS` in the script) as
  confirmation, before moving to the next engine. No
  address entry needed — it operates on whatever consist is currently
  built/loaded. Clears any leftover Advanced Consist setting from before
  a migration to the CS-105.
- This same clear-and-honk logic (3 writes + 3 honks) also runs
  **automatically** on each locomotive as it's added via "Add to
  Consist" — the button above is for the lead (which isn't auto-cleared)
  or for re-running it across the whole consist at once.
- The horn honk sends `SET_FN` Traction messages to the target directly,
  rather than going through `TractionThrottle`'s `VersionedValue`-based
  function API, which didn't reliably produce an outbound message.

## Notes

- Assigning a lead locomotive that's never been addressed before on the
  CS-105 likely auto-creates its virtual node as a side effect (the same
  way a UWT throttle would) — so using this tool is also a way to register
  new locomotives on the CS-105, one at a time.
- Node IDs are computed as `[6, 1, 0, 0, upperAddressByte,
  lowerAddressByte]`, matching the scheme used by JMRI's own
  `jmri.jmrit.symbolicprog.TcsUploadAction` (the code behind the
  Programmer's "Export → Roster entry to TCS CS-105" menu item).
- All long-running or timed operations (CDI reads, consist queries, CV
  programming, the horn-honk sequence) are handled via callbacks,
  property-change listeners, and non-blocking `javax.swing.Timer`s rather
  than blocking waits or sleeps, since JMRI runs scripts on its GUI
  thread — a blocking wait there can deadlock the whole application.
- `javax.swing.Timer`'s only constructor requires its `ActionListener` as
  a positional argument. The Jython keyword shortcut that works for
  things like `JButton(text, actionPerformed=callable)` doesn't reliably
  wire up for `Timer`, and silently produces a timer that never fires —
  this script constructs an explicit `ActionListener` instead.

## License

MIT — see [LICENSE](LICENSE).
