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
- A JMRI roster with your locomotives' DCC addresses (used to populate the
  dropdown pickers; not required if you only use the manual address fields).

## Running it

In JMRI: **Panels → Run Script...**, then pick `cs105_consist_builder.py`.
It opens its own window, separate from JMRI's other tools. The
**Instructions** button in the top-right of that window reproduces the
walkthroughs below, so they're on hand without leaving JMRI.

## How to build a consist

1. In **Lead locomotive**, pick the lead unit from the roster dropdown, or
   type its DCC address into the manual field just below (and check/uncheck
   **Long address** to match) — manual entry wins if it's filled in.
2. Click **Assign as Lead**. Status will show "Enabled" once JMRI has
   control, and the member list will show a `LEAD: ...` row plus anything
   already consisted to it.
3. In **Add locomotive**, pick (or manually enter) the next unit to attach.
   Check **Reverse** if it runs backwards relative to the lead, and
   **Respond to F0** if you want it to react to the lead's headlight
   function too.
4. Click **Add to Consist**. It appears in the member list once attached.
5. Repeat steps 3–4 for any further units.
6. To remove one unit later, select it in the member list and click
   **Remove Selected** (the `LEAD:` row itself can't be removed this way —
   use Release Lead instead if you want to fully let go of the consist).
7. Click **Release Lead** when you're done. This only gives up JMRI's
   control of the lead — the consist itself stays intact on the CS-105 and
   works from any throttle, exactly as if a UWT throttle had built it.

To just check what's already consisted to a locomotive without taking
control of it, use **Read Consist** instead of Assign as Lead in step 2.

## How to clear an old NCE consist (CV19)

If a locomotive still has a CV19 value left over from the old NCE setup,
clear it before/while migrating it to CS-105 consisting:

1. Scroll to **Clear old NCE consist**.
2. Pick the locomotive from the **Locomotive** dropdown, or type its DCC
   address into the manual field below.
3. Click **Clear CV19**, then confirm the dialog (this is a real
   Program-on-Main write to the layout).
4. **CV19 status** will show progress, then "CV19 cleared on ..." once
   done — the locomotive will also honk its horn 3 times as an audible
   confirmation.

## Features

### Building a consist

- **Lead locomotive** — pick from the roster dropdown, or type a DCC
  address directly into the manual field below it (manual takes priority
  when filled in; leave it blank to use the dropdown).
- **Assign as Lead** — takes control of the picked locomotive as the
  consist's lead unit, and shows whatever's already consisted to it, if
  anything.
- **Read Consist** — a genuinely read-only query on the Lead
  locomotive/address: it never sends a controller-assign command, so it
  can't interfere with another throttle (a UWT, another JMRI session,
  etc.) that's already running that engine. Populates the same member
  list as Assign as Lead, marked read-only; click Assign as Lead
  afterward if you then want to edit what you saw.
- **Add locomotive** / **Add to Consist** — same roster-or-manual address
  picker, plus **Reverse** and **Respond to F0** flags, to attach another
  unit to the currently assigned lead.
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

### Clearing old NCE consists

- **Clear old NCE consist** — pick a locomotive (roster or manual address)
  and click **Clear CV19** to write CV19 = 0 via Program on Main, clearing
  any leftover NCE-style Decoder Assisted Consist setting from before a
  migration to the CS-105. Asks for confirmation first, since it's a real
  write to the layout.
- On success, it briefly takes the throttle and honks the horn (function
  F2, the standard horn/whistle assignment) 3 times as an audible "done"
  confirmation, then releases control again.

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
