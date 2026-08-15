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
It opens its own window, separate from JMRI's other tools.

## Features

- **Assign as Lead** — pick a locomotive (roster dropdown, or type its DCC
  address into the manual field) and take control of it as the consist's
  lead unit. Also shows whatever's already consisted to it, if anything.
- **Read Consist** — a genuinely read-only query: it never sends a
  controller-assign command, so it can't interfere with another throttle
  (a UWT, another JMRI session, etc.) that's already running that
  locomotive. Useful for checking a consist without touching it.
- **Add to Consist / Remove Selected** — add or remove members from the
  currently assigned lead, with **Reverse** and **Respond to F0** flags per
  member.
- **Release Lead** — releases JMRI's own control access. This does **not**
  break up the consist — consists persist on the CS-105 independent of any
  throttle's connection, the same as unplugging a UWT throttle.
- **Clear CV19** — an unrelated convenience feature: writes CV19 = 0 to a
  locomotive via Program on Main, to clear a leftover NCE-style Decoder
  Assisted Consist setting from before a migration to the CS-105.

The consist member list automatically filters out anything that isn't a
real locomotive — OpenLCB Traction doesn't structurally distinguish "a
throttle is controlling this train" from "this train is consisted to that
lead," so both JMRI itself and other throttles/devices can otherwise show
up as phantom "members." Filtering is done by checking that a listener's
node ID decodes to a plausible NMRA DCC address (1-127 short, 1-9999 long).

## Notes

- Assigning a lead locomotive that's never been addressed before on the
  CS-105 likely auto-creates its virtual node as a side effect (the same
  way a UWT throttle would) — so using this tool is also a way to register
  new locomotives on the CS-105, one at a time.
- Node IDs are computed as `[6, 1, 0, 0, upperAddressByte,
  lowerAddressByte]`, matching the scheme used by JMRI's own
  `jmri.jmrit.symbolicprog.TcsUploadAction` (the code behind the
  Programmer's "Export → Roster entry to TCS CS-105" menu item).
- All long-running operations (CDI reads, consist queries, CV
  programming) are handled via callbacks/property-change listeners rather
  than blocking waits, since JMRI runs scripts on its GUI thread — a
  blocking wait there can deadlock the whole application.

## License

MIT — see [LICENSE](LICENSE).
