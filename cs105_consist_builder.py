"""
CS-105 Consist Builder - a small Swing GUI, run inside JMRI, for building
and viewing native TCS CS-105 consists over LCC/OpenLCB from a computer,
as an alternative to the UWT throttle.

This uses JMRI's bundled org.openlcb.implementations.throttle.TractionThrottle,
the same OpenLCB "Traction Listener Attach" protocol class a UWT throttle
uses to build consists - not JMRI's separate CV19-based "Consist Tool".
Consists built here are the real, native CS-105 kind (the "Runs with X"
relationships visible in the CS-105 Network Tree app), stored on the
command station itself and usable from any throttle afterward.

Node IDs are computed the same way as elsewhere in this project:
  [6, 1, 0, 0, upperAddressByte, lowerAddressByte]
  upper = (192 + (addr >> 8)) if long address else 0
  lower = addr & 0xFF
(matches jmri.jmrix.symbolicprog.TcsUploadAction's node ID scheme, and
confirmed earlier this session against the CS-105's own network tree).

Click the "Instructions" button in the window itself for the full
step-by-step walkthrough (also reproduced below and in README.md).

Locomotives are always picked by typing their DCC address directly - there
is no roster dropdown.

Usage:
  1. Panels > Run Script..., pick this file.
  2. Type the lead locomotive's DCC address, set Long address to match,
     pick an MU switch mode if you want to set it, then click "Assign as
     Lead" (this also shows whatever's already consisted to it, if
     anything).
  3. Type another locomotive's address, set Reverse/F0 as needed, pick an
     MU switch mode if you want to set it, then "Add to Consist". Each
     time a unit is added, its CV19 is also automatically cleared (CV19=0
     sent CV19_REPEAT_COUNT times via Program on Main, to remove any
     leftover Advanced Consist setting), and its horn honks 3 times (0.5s
     each) once that's done. This does NOT happen for the lead itself -
     see "Clear CV19 on Entire Consist" below.
  4. Repeat for more members. "Remove Selected" / "Refresh List" as needed.
  5. "Release Lead" when done - this only releases JMRI's own control
     access, it does NOT break up the consist itself (consists persist
     on the CS-105 independent of any throttle's connection).
  6. "New Consist" clears every address/option field back to blank/default,
     for starting on a fresh consist. It does not release an active
     throttle assignment or touch the consist member list.

Note: assigning a throttle to a locomotive that has never been addressed
before likely auto-creates its CS-105 virtual node as a side effect (this
is presumably how UWT throttles do it too) - so using this tool is also a
way to register new locomotives on the CS-105, one at a time.

"Clear CV19 on Entire Consist" is unrelated to Traction/LCC - it uses
ordinary Program on Main (Ops Mode Programming) to write CV19=0, sent
CV19_REPEAT_COUNT times in a row, on the lead and every attached member
currently shown in the consist list - one engine at a time. Each engine's
horn honks 3 times (0.5s each) once its writes finish, as an audible
confirmation.
This clears any leftover Advanced Consist setting so it doesn't linger
and interfere with CS-105 consisting.

The horn honk sends TractionControlRequestMessage SET_FN messages to the
target directly (see HornHonker) rather than going through
TractionThrottle's VersionedValue-based function API, which did not
reliably produce an outbound message in testing.

The "MU switch" dropdowns (next to "Assign as Lead" and next to "Add to
Consist") are unrelated to CV19 or any DCC CV. Each is an OpenLCB
Configuration Description Information (CDI) variable stored in that
locomotive's own CS-105 LCC virtual node - the same setting shown in
JMRI's "Configure" pane for that node. Choosing anything other than
"(don't change)" fetches that node's CDI, locates the item named "MU
switch" by name (its memory offset isn't known ahead of time - only once
the CDI is fetched), and writes the chosen mode via MuSwitchSetter. Left
on "(don't change)" by default, since it's a per-locomotive
physical-position setting, not something every assign/add should touch.
The lead's MU switch dropdown only fires on "Assign as Lead", never on
"Read Consist" - Read Consist stays a genuinely read-only query.
"""
import jarray
from javax.swing import (JFrame, JPanel, JButton, JLabel, JList,
                          DefaultListModel, JScrollPane, JCheckBox, JTextField,
                          JTextArea, JComboBox, BoxLayout, SwingUtilities,
                          BorderFactory, ListSelectionModel, JOptionPane, Timer)
from java.awt import BorderLayout, FlowLayout, GridLayout, Dimension
from java.awt.event import ActionListener
from java.beans import PropertyChangeListener

from org.openlcb import NodeID, MessageDecoder
from org.openlcb.implementations.throttle import TractionThrottle, RemoteTrainNode
from org.openlcb.messages import TractionControlRequestMessage, TractionControlReplyMessage
from org.openlcb.cdi.impl import ConfigRepresentation
from jmri.jmrix.can import CanSystemConnectionMemo


INSTRUCTIONS_TEXT = """HOW TO BUILD A CONSIST

Locomotives are always picked by typing their DCC address - there is no
roster dropdown.

1. Type the lead unit's DCC address into "Lead locomotive DCC address",
   and check/uncheck "Long address" to match. Pick a mode from "MU
   switch" if you want to set the lead's MU switch position too - leave
   it on "(don't change)" to skip that.
2. Click "Assign as Lead". Status will show "Enabled" once JMRI has
   control, and the member list will show a "LEAD: ..." row plus anything
   already consisted to it. If an MU switch mode was picked, it's written
   to the lead's CS-105 virtual node at the same time - "MU switch
   status" shows its progress. (This does NOT happen if you use "Read
   Consist" instead - that stays read-only.)
3. Type the next unit's DCC address into "Add locomotive DCC address"
   (and its Long address checkbox). Check "Reverse" if it runs backwards
   relative to the lead, and "Respond to F0" if you want it to react to
   the lead's headlight function too. Pick a mode from "MU switch" if you
   want to set that unit's MU switch position as it's added - leave it on
   "(don't change)" to skip that.
4. Click "Add to Consist". It appears in the member list once attached.
   Its CV19 is also automatically cleared (CV19=0 sent 3 times via
   Program on Main), and its horn honks 3 times (0.5 seconds each) once
   that finishes - this does NOT happen for the lead itself, only units
   added this way. If an MU switch mode was picked, it's also written to
   that unit's CS-105 virtual node at the same time - "MU switch status"
   shows its progress.
5. Repeat steps 3-4 for any further units.
6. To remove one unit later, select it in the member list and click
   "Remove Selected" (the "LEAD:" row itself can't be removed this way -
   use Release Lead instead if you want to fully let go of the consist).
7. Click "Release Lead" when you're done. This only gives up JMRI's
   control of the lead - the consist itself stays intact on the CS-105 and
   works from any throttle, exactly as if a UWT throttle had built it.

To just check what's already consisted to a locomotive without taking
control of it, use "Read Consist" instead of Assign as Lead in step 2.

Click "New Consist" (top right) at any time to clear all the address and
option fields back to blank/default, ready for building a fresh consist.
This does not release an active lead assignment or clear the member list -
use "Release Lead" for that.

HOW TO CLEAR CV19 ON THE WHOLE CONSIST

If any locomotives still have a CV19 value left over from an old Advanced
Consist setup, clear it on all of them at once - the lead plus every
attached member currently shown in the consist list:

1. Build or read the consist first (Assign as Lead / Add to Consist, or
   Read Consist).
2. Click "Clear CV19 on Entire Consist".
3. Each engine is processed one at a time: CV19=0 is written 3 times in a
   row to it via Program on Main, then its horn honks 3 times (0.5 seconds
   each) as an audible confirmation, before moving on to the next engine.
4. "CV19 status" shows progress throughout, ending with "CV19 cleared on
   all N engine(s) in the consist."

Note: units added via "Add to Consist" already get this same treatment
automatically as they're added - this button is for clearing the lead
too, or for re-running it across the whole consist at once.

SETTING THE MU SWITCH

Both "MU switch" dropdowns - next to "Assign as Lead" and next to "Add
to Consist" - set where that unit's decoder thinks it sits in a consist
or train, the same setting shown in JMRI's "Configure" pane for a
locomotive's LCC node, not a DCC CV. Leave either on "(don't change)" to
skip it. Otherwise pick "Solo Unit", "Coupled at Rear", "Coupled at
Front", or "Middle Unit":

- For the lead, pick a mode before clicking "Assign as Lead" - it's
  written to the lead's own CS-105 virtual node once assigned. Using
  "Read Consist" instead never writes it, since that stays a genuinely
  read-only query.
- For any other unit, pick a mode before clicking "Add to Consist" - it's
  written to that unit's own CS-105 virtual node once added.

"MU switch status" reports progress for both, ending with "MU switch set
to <mode>." Errors are reported there too, e.g. if that node's CDI has no
"MU switch" item at all.
"""


def to_signed_byte(v):
    v = v & 0xFF
    return v - 256 if v > 127 else v


def node_id_for(addr, is_long):
    upper = (192 + (addr >> 8)) if is_long else 0
    lower = addr & 0xFF
    b = jarray.array([6, 1, 0, 0, to_signed_byte(upper), to_signed_byte(lower)], 'b')
    return NodeID(b)


def decode_node_id(node_id):
    c = node_id.getContents()
    upper = c[4] & 0xFF
    lower = c[5] & 0xFF
    is_long = (upper & 0xC0) == 0xC0
    addr = ((upper << 8) & 0x3F00) + lower
    return addr, is_long


def is_plausible_dcc_node(node_id):
    """True if this NodeID decodes to a legal NMRA DCC address (1-127
    short, 1-9999 long). False means it's not a locomotive at all - most
    likely a throttle or other device attached as a listener/controller
    (OpenLCB Traction doesn't structurally distinguish "controlling this
    train" from "consisted to this train")."""
    addr, is_long = decode_node_id(node_id)
    return (1 <= addr <= 9999) if is_long else (1 <= addr <= 127)


class RosterIndex(object):
    """Address -> roster name lookup, used to show a friendly name next to
    each consist member's DCC address. Locomotives are always picked by
    manually typing a DCC address (no roster picker in the UI), but the
    roster is still used here purely for display."""

    def __init__(self):
        roster = jmri.jmrit.roster.Roster.getDefault()
        self.by_addr = {}
        for re in roster.getAllEntries():
            try:
                addr = int(re.getDccAddress())
            except Exception:
                continue
            self.by_addr[(addr, re.isLongAddress())] = re

    def name_for_node(self, node_id):
        addr, is_long = decode_node_id(node_id)
        # A short address must be 1-127 (7-bit NMRA range); anything outside
        # that isn't a real DCC address at all - almost certainly a non-train
        # device (a throttle, the command station, etc.) that happens to
        # also be attached as a listener. Don't pretend we decoded it.
        plausible = (1 <= addr <= 127) if not is_long else (1 <= addr <= 9999)
        if plausible:
            re = self.by_addr.get((addr, is_long))
            if re is not None:
                return "%s (%d%s)" % (re.getId(), addr, "L" if is_long else "S")
            return "addr %d%s (not in roster)" % (addr, "L" if is_long else "S")
        return "non-train device, raw ID %s (look this up in the CS-105 Network Tree)" % \
            node_id.toString()


def parse_manual_address(text_field, long_checkbox):
    """Returns (addr, is_long) if the field has a valid DCC address typed
    in (1-9999), else None."""
    text = text_field.getText().strip()
    if not text:
        return None
    try:
        addr = int(text)
    except ValueError:
        return None
    if addr < 1 or addr > 9999:
        return None
    return addr, long_checkbox.isSelected()


CV19_REPEAT_COUNT = 3  # CV19=0 is sent this many times in a row per engine


class CvClearListener(jmri.ProgListener):
    """Handles the async reply from one Program-on-Main CV19=0 write, and
    chains up to CV19_REPEAT_COUNT total writes for the same locomotive
    (reusing the same programmer) before honking its horn once and calling
    on_done(). May be called back on a non-EDT thread, so hop to the EDT
    before touching any Swing components."""

    def __init__(self, frame, programmer, label, node_id, writes_remaining, on_done):
        self.frame = frame
        self.programmer = programmer
        self.label = label
        self.node_id = node_id
        self.writes_remaining = writes_remaining
        self.on_done = on_done

    def programmingOpReply(self, value, status):
        SwingUtilities.invokeLater(lambda: self._handle(status))

    def _handle(self, status):
        if status != jmri.ProgListener.OK:
            self.frame.cvStatusLabel.setText(
                "CV19 write to %s failed (status %d)." % (self.label, status))
            self.frame._releaseCvProgrammer()
            self.on_done()
            return

        if self.writes_remaining > 0:
            self.frame.cvStatusLabel.setText(
                "CV19=0 written to %s (%d more write(s))..." %
                (self.label, self.writes_remaining))
            listener = CvClearListener(self.frame, self.programmer, self.label, self.node_id,
                                        self.writes_remaining - 1, self.on_done)
            try:
                self.programmer.writeCV("19", 0, listener)
            except jmri.ProgrammerException as ex:
                self.frame.cvStatusLabel.setText("Error: %s" % ex)
                self.frame._releaseCvProgrammer()
                self.on_done()
            return

        self.frame.cvStatusLabel.setText(
            "CV19 cleared on %s (sent %d times) - honking horn..." %
            (self.label, CV19_REPEAT_COUNT))
        self.frame._releaseCvProgrammer()
        honker = HornHonker(self.frame.iface, self.node_id, self.label,
                             self.frame.cvStatusLabel.setText)
        honker.start()
        self.on_done()


class HornHonker(PropertyChangeListener):
    """Honks the horn (function F2, the standard NMRA/decoder horn-whistle
    assignment) 3 times on a locomotive, each honk held for 0.5 seconds
    (ON_MS), as a little audible confirmation that its CV19 was cleared.
    Briefly takes controller assignment (the
    only way to send function commands over Traction), then releases it
    again - same as a throttle briefly grabbing a loco to blow the horn.
    Timing uses a non-blocking javax.swing.Timer, never a blocking sleep,
    since this runs on JMRI's GUI thread.

    Sends TractionControlRequestMessage.createSetFn(...) directly rather
    than going through TractionThrottle.getFunction(fn).set(...) - the
    VersionedValue wrapper that goes through didn't reliably produce an
    outbound SET_FN message in testing, so this talks to the interface
    directly instead, the same way ConsistReader/addToConsist etc. do."""

    HORN_FN = 2
    ON_MS = 500
    OFF_MS = 250
    HONKS = 3

    def __init__(self, iface, node_id, label, status_callback):
        self.iface = iface
        self.node_id = node_id
        self.label = label
        self.status_callback = status_callback
        self.throttle = None
        self.step = 0

    def start(self):
        self.throttle = TractionThrottle(self.iface)
        self.throttle.addPropertyChangeListener(self)
        node = RemoteTrainNode(self.node_id, self.iface)
        self.throttle.start(node)

    def propertyChange(self, evt):
        SwingUtilities.invokeLater(lambda: self._handle(evt))

    def _handle(self, evt):
        if evt.getPropertyName() == TractionThrottle.UPDATE_PROP_ENABLED:
            if self.throttle.getEnabled():
                self._nextStep()

    def _setHorn(self, on):
        m = TractionControlRequestMessage.createSetFn(
            self.iface.getNodeId(), self.node_id, self.HORN_FN, 1 if on else 0)
        self.iface.getOutputConnection().put(m, self.throttle)

    def _nextStep(self):
        totalSteps = self.HONKS * 2  # on, off, on, off, on, off
        if self.step >= totalSteps:
            self._finish()
            return
        hornOn = (self.step % 2 == 0)
        self._setHorn(hornOn)
        delay = self.ON_MS if hornOn else self.OFF_MS
        self.step += 1
        timer = Timer(delay, _TimerCallback(self._nextStep))
        timer.setRepeats(False)
        timer.start()

    def _finish(self):
        self._setHorn(False)
        self.throttle.removePropertyChangeListener(self)
        self.throttle.release()
        self.status_callback("%s: horn honked %d times." % (self.label, self.HONKS))


class _TimerCallback(ActionListener):
    """Explicit ActionListener for javax.swing.Timer - Timer's only
    constructor requires the listener as a positional argument, unlike
    JButton etc. where the actionPerformed=... keyword shortcut attaches
    via addActionListener() after construction. Using that shortcut here
    silently produced a Timer with no working listener, so this is
    spelled out explicitly instead."""

    def __init__(self, callback):
        self.callback = callback

    def actionPerformed(self, event):
        self.callback()


MU_SWITCH_UNCHANGED = "(don't change)"
MU_SWITCH_ITEM_NAME = "mu switch"
MU_SWITCH_MODES = [MU_SWITCH_UNCHANGED, "Solo Unit", "Coupled at Rear",
                    "Coupled at Front", "Middle Unit"]
MU_SWITCH_TIMEOUT_MS = 20000  # generous - a CDI fetch reads it in ~64-byte chunks


class _FindItemByName(ConfigRepresentation.Visitor):
    """Collects every CDI entry (leaf or group) whose own item name matches
    target_name (case-insensitive, trimmed) into found_list, in visitation
    order, while still recursing into every group/segment so nothing is
    missed. Matches groups as well as leaves because some CDIs put a
    variable's display name on a wrapping <group> (with the actual integer
    living inside as an unnamed child) rather than on the variable itself
    - the exact CDI authoring for TCS's "MU switch" isn't knowable without
    fetching it live, so both shapes are handled; see
    _resolve_integer_entry."""

    def __init__(self, target_name, found_list):
        self.target_name = target_name.strip().lower()
        self.found_list = found_list

    def _checkName(self, entry):
        item = entry.getCdiItem()
        name = item.getName() if item is not None else None
        if name is not None and name.strip().lower() == self.target_name:
            self.found_list.append(entry)

    def visitLeaf(self, entry):
        self._checkName(entry)

    def visitGroup(self, entry):
        self._checkName(entry)
        self.visitContainer(entry)

    def visitGroupRep(self, entry):
        self._checkName(entry)
        self.visitContainer(entry)

    def visitSegment(self, entry):
        self._checkName(entry)
        self.visitContainer(entry)


def _resolve_integer_entry(entry):
    """If entry is itself an integer/enum leaf (has a usable CdiRep.Map),
    return it. Otherwise, if it's a group/segment container, descend into
    its children and return the first one that is - handles the "name is
    on a wrapping group" CDI shape described on _FindItemByName."""
    try:
        entry.rep.getMap()
        return entry
    except AttributeError:
        pass
    try:
        children = entry.getEntries()
    except AttributeError:
        return None
    for child in children:
        resolved = _resolve_integer_entry(child)
        if resolved is not None:
            return resolved
    return None


class MuSwitchSetter(PropertyChangeListener):
    """Sets the MU switch position on one locomotive - an OpenLCB
    Configuration Description Information (CDI) variable stored in that
    locomotive's own CS-105 LCC virtual node, the same setting shown (and
    normally hand-edited) in JMRI's "Configure" pane for that node. This is
    unrelated to any DCC CV: it fetches the node's CDI over LCC, locates
    the item named "MU switch" by name (see _FindItemByName), translates
    the chosen mode name to that node's own raw enum value via the CDI's
    <map>, and writes it. May be called back on a non-EDT thread, so hops
    to the EDT before touching Swing."""

    def __init__(self, iface, node_id, label, mode_name, status_callback, on_done):
        self.iface = iface
        self.node_id = node_id
        self.label = label
        self.mode_name = mode_name
        self.status_callback = status_callback
        self.on_done = on_done
        self.config = None
        self.entry = None
        self._done = False
        self.timer = Timer(MU_SWITCH_TIMEOUT_MS, _TimerCallback(self._onTimeout))
        self.timer.setRepeats(False)

    def start(self):
        self.status_callback("%s: reading MU switch configuration..." % self.label)
        self.timer.start()
        self.config = ConfigRepresentation(self.iface, self.node_id)
        self.config.addPropertyChangeListener(self)

    def propertyChange(self, evt):
        SwingUtilities.invokeLater(lambda: self._handle(evt))

    def _handle(self, evt):
        if self._done:
            return
        name = evt.getPropertyName()
        if name == ConfigRepresentation.UPDATE_REP:
            self._onRepReady()
        elif name == ConfigRepresentation.UPDATE_WRITE_COMPLETE:
            self._finish(True)

    def _onRepReady(self):
        found = []
        self.config.visit(_FindItemByName(MU_SWITCH_ITEM_NAME, found))
        self.entry = None
        for candidate in found:
            self.entry = _resolve_integer_entry(candidate)
            if self.entry is not None:
                break
        if self.entry is None:
            self.status_callback(
                "%s: no \"MU switch\" item found in this node's CDI - skipped." % self.label)
            self._finish(False)
            return
        cdiMap = self.entry.rep.getMap()
        rawKey = cdiMap.getKey(self.mode_name) if cdiMap is not None else None
        if rawKey is None:
            self.status_callback(
                "%s: MU switch has no option named \"%s\" - skipped." %
                (self.label, self.mode_name))
            self._finish(False)
            return
        self.entry.addPropertyChangeListener(self)
        self.status_callback("%s: writing MU switch = %s..." % (self.label, self.mode_name))
        self.entry.setValue(long(rawKey))

    def _onTimeout(self):
        if self._done:
            return
        self.status_callback("%s: MU switch write timed out (no reply)." % self.label)
        self._finish(False)

    def _finish(self, ok):
        if self._done:
            return
        self._done = True
        self.timer.stop()
        if ok:
            self.status_callback("%s: MU switch set to %s." % (self.label, self.mode_name))
        self.on_done()


class ConsistReader(MessageDecoder):
    """Read-only consist query for a train node - does NOT send
    AssignController, so it never takes control away from whatever
    throttle (a UWT, another JMRI session, etc.) may already be running
    that locomotive. Calls on_complete(entries) when done, where entries
    is a list of (NodeID, flags) tuples, or on_timeout() if nothing came
    back within TIMEOUT_MS."""

    TIMEOUT_MS = 8000

    def __init__(self, iface, target_node_id, on_complete, on_timeout):
        self.iface = iface
        self.target = target_node_id
        self.on_complete = on_complete
        self.on_timeout = on_timeout
        self.entries = None
        self._done = False
        self.timer = Timer(self.TIMEOUT_MS, _TimerCallback(self._onTimeout))
        self.timer.setRepeats(False)

    def start(self):
        self.iface.registerMessageListener(self)
        self.timer.start()
        m = TractionControlRequestMessage.createConsistLengthQuery(
            self.iface.getNodeId(), self.target)
        self.iface.getOutputConnection().put(m, self)

    def _onTimeout(self):
        if self._done:
            return
        self._finish(None)

    def _finish(self, result):
        if self._done:
            return
        self._done = True
        self.timer.stop()
        self.iface.unRegisterMessageListener(self)
        if result is None:
            SwingUtilities.invokeLater(lambda: self.on_timeout())
        else:
            SwingUtilities.invokeLater(lambda: self.on_complete(result))

    def handleTractionControlReply(self, msg, sender):
        if self._done:
            return
        if not msg.getSourceNodeID().equals(self.target):
            return
        if not msg.getDestNodeID().equals(self.iface.getNodeId()):
            return
        if msg.getCmd() != TractionControlReplyMessage.CMD_CONSIST:
            return
        if msg.getSubCmd() != TractionControlReplyMessage.SUBCMD_CONSIST_QUERY:
            return
        length = msg.getConsistLength()
        if self.entries is None:
            self.entries = [None] * length
            if length == 0:
                self._finish(self.entries)
                return
            for i in range(length):
                q = TractionControlRequestMessage.createConsistIndexQuery(
                    self.iface.getNodeId(), self.target, i)
                self.iface.getOutputConnection().put(q, self)
        index = msg.getConsistIndex()
        if index is not None and index >= 0 and index < len(self.entries):
            n = msg.getConsistQueryNodeID()
            f = msg.getConsistQueryFlags()
            self.entries[index] = (n, f)
            if all(e is not None for e in self.entries):
                self._finish(self.entries)


class _Entry(object):
    """Mimics org.openlcb...TractionThrottle$ConsistEntry's shape (.node,
    .flags) so the read-only "Read Consist" path can share the same list
    rendering code as the live, assigned-throttle path."""

    def __init__(self, node, flags):
        self.node = node
        self.flags = flags


class ConsistBuilderFrame(JFrame, PropertyChangeListener):

    def __init__(self, olcb_iface):
        JFrame.__init__(self, "CS-105 Consist Builder")
        self.iface = olcb_iface
        self.roster = RosterIndex()
        self.throttle = None

        self.setDefaultCloseOperation(JFrame.DISPOSE_ON_CLOSE)
        root = JPanel()
        root.setLayout(BoxLayout(root, BoxLayout.Y_AXIS))
        root.setBorder(BorderFactory.createEmptyBorder(10, 10, 10, 10))

        helpPanel = JPanel(FlowLayout(FlowLayout.RIGHT))
        helpPanel.add(JButton("New Consist", actionPerformed=self.onNewConsist))
        helpPanel.add(JButton("Instructions", actionPerformed=self.onShowInstructions))
        root.add(helpPanel)

        # --- Lead section ---
        leadPanel = JPanel(FlowLayout(FlowLayout.LEFT))
        leadPanel.add(JLabel("Lead locomotive DCC address:"))
        self.leadAddrField = JTextField(6)
        leadPanel.add(self.leadAddrField)
        self.leadLongCheck = JCheckBox("Long address", True)
        leadPanel.add(self.leadLongCheck)
        leadPanel.add(JLabel("MU switch:"))
        # Only acted on by onAssign - onReadConsist leaves it alone, since
        # Read Consist is meant to stay read-only.
        self.leadMuSwitchCombo = JComboBox(MU_SWITCH_MODES)
        leadPanel.add(self.leadMuSwitchCombo)
        self.assignButton = JButton("Assign as Lead", actionPerformed=self.onAssign)
        leadPanel.add(self.assignButton)
        self.readConsistButton = JButton("Read Consist", actionPerformed=self.onReadConsist)
        leadPanel.add(self.readConsistButton)
        root.add(leadPanel)

        statusPanel = JPanel(FlowLayout(FlowLayout.LEFT))
        statusPanel.add(JLabel("Status:"))
        self.statusLabel = JLabel("(no lead assigned)")
        statusPanel.add(self.statusLabel)
        root.add(statusPanel)

        root.add(JLabel(" "))

        # --- Add member section ---
        addPanel = JPanel(FlowLayout(FlowLayout.LEFT))
        addPanel.add(JLabel("Add locomotive DCC address:"))
        self.addAddrField = JTextField(6)
        addPanel.add(self.addAddrField)
        self.addLongCheck = JCheckBox("Long address", True)
        addPanel.add(self.addLongCheck)
        self.reverseCheck = JCheckBox("Reverse")
        addPanel.add(self.reverseCheck)
        self.fn0Check = JCheckBox("Respond to F0")
        addPanel.add(self.fn0Check)
        addPanel.add(JLabel("MU switch:"))
        self.muSwitchCombo = JComboBox(MU_SWITCH_MODES)
        addPanel.add(self.muSwitchCombo)
        self.addButton = JButton("Add to Consist", actionPerformed=self.onAdd)
        self.addButton.setEnabled(False)
        addPanel.add(self.addButton)
        root.add(addPanel)

        muStatusPanel = JPanel(FlowLayout(FlowLayout.LEFT))
        muStatusPanel.add(JLabel("MU switch status:"))
        self.muSwitchStatusLabel = JLabel("(idle)")
        muStatusPanel.add(self.muSwitchStatusLabel)
        root.add(muStatusPanel)

        # --- Consist member list ---
        root.add(JLabel("Current consist members:"))
        self.listModel = DefaultListModel()
        self.memberList = JList(self.listModel)
        self.memberList.setSelectionMode(ListSelectionModel.SINGLE_SELECTION)
        scroll = JScrollPane(self.memberList)
        scroll.setPreferredSize(Dimension(420, 140))
        root.add(scroll)

        btnPanel = JPanel(FlowLayout(FlowLayout.LEFT))
        self.removeButton = JButton("Remove Selected", actionPerformed=self.onRemove)
        self.removeButton.setEnabled(False)
        btnPanel.add(self.removeButton)
        self.refreshButton = JButton("Refresh List", actionPerformed=self.onRefresh)
        self.refreshButton.setEnabled(False)
        btnPanel.add(self.refreshButton)
        self.releaseButton = JButton("Release Lead", actionPerformed=self.onRelease)
        self.releaseButton.setEnabled(False)
        btnPanel.add(self.releaseButton)
        root.add(btnPanel)

        root.add(JLabel(" "))
        root.add(JLabel("Clear old Advanced Consist: writes CV19=0 (x%d) on the lead and every"
                         " attached member above, via Program on Main:" % CV19_REPEAT_COUNT))

        cvPanel = JPanel(FlowLayout(FlowLayout.LEFT))
        self.clearCvButton = JButton("Clear CV19 on Entire Consist", actionPerformed=self.onClearCv19)
        cvPanel.add(self.clearCvButton)
        root.add(cvPanel)

        cvStatusPanel = JPanel(FlowLayout(FlowLayout.LEFT))
        cvStatusPanel.add(JLabel("CV19 status:"))
        self.cvStatusLabel = JLabel("(idle)")
        cvStatusPanel.add(self.cvStatusLabel)
        root.add(cvStatusPanel)

        self._consistEntries = []
        self._activeCvProgrammer = None
        self.leadLabel = None
        self.leadNodeID = None

        self.setContentPane(root)
        self.pack()
        self.setLocationRelativeTo(None)

    # --- button handlers ---

    def onNewConsist(self, event):
        """Clears all address/option entry fields back to their defaults.
        Does not touch an active throttle assignment or the current
        consist member list - use Release Lead for that."""
        self.leadAddrField.setText("")
        self.leadLongCheck.setSelected(True)
        self.leadMuSwitchCombo.setSelectedItem(MU_SWITCH_UNCHANGED)
        self.addAddrField.setText("")
        self.addLongCheck.setSelected(True)
        self.reverseCheck.setSelected(False)
        self.fn0Check.setSelected(False)
        self.muSwitchCombo.setSelectedItem(MU_SWITCH_UNCHANGED)

    def onShowInstructions(self, event):
        textArea = JTextArea(INSTRUCTIONS_TEXT)
        textArea.setEditable(False)
        textArea.setLineWrap(False)
        textArea.setFont(JLabel().getFont())
        scroll = JScrollPane(textArea)
        scroll.setPreferredSize(Dimension(560, 420))
        JOptionPane.showMessageDialog(
            self, scroll, "CS-105 Consist Builder - Instructions",
            JOptionPane.PLAIN_MESSAGE)

    def onAssign(self, event):
        manual = parse_manual_address(self.leadAddrField, self.leadLongCheck)
        if manual is None:
            self.statusLabel.setText("Enter a valid DCC address (1-9999) first.")
            return
        addr, is_long = manual
        nodeID = node_id_for(addr, is_long)

        if self.throttle is not None:
            self.throttle.removePropertyChangeListener(self)
            self.throttle.release()

        self.throttle = TractionThrottle(self.iface)
        self.throttle.addPropertyChangeListener(self)
        self.statusLabel.setText("Assigning...")
        node = RemoteTrainNode(nodeID, self.iface)
        self.throttle.start(node)
        self.leadLabel = "%d%s" % (addr, "L" if is_long else "S")
        self.leadNodeID = nodeID

        # Set the lead's MU switch too, if one was picked. This is a
        # separate CDI write over LCC, independent of (and not gated on)
        # the throttle assignment above - unlike onAdd there's no button
        # to re-disable/re-enable around it, so on_done is a no-op.
        muMode = self.leadMuSwitchCombo.getSelectedItem()
        if muMode != MU_SWITCH_UNCHANGED:
            setter = MuSwitchSetter(self.iface, nodeID, self.leadLabel, muMode,
                                     self.muSwitchStatusLabel.setText, lambda: None)
            setter.start()

    def onReadConsist(self, event):
        manual = parse_manual_address(self.leadAddrField, self.leadLongCheck)
        if manual is None:
            self.statusLabel.setText("Enter a valid DCC address (1-9999) first.")
            return
        addr, is_long = manual
        label = "addr %d%s" % (addr, "L" if is_long else "S")
        nodeID = node_id_for(addr, is_long)

        # Deliberately ignores self.leadMuSwitchCombo - Read Consist never
        # writes anything, so a mode picked there has no effect here (only
        # Assign as Lead acts on it).
        #
        # A read-only display shouldn't coexist with a stale active/editable
        # session pointed at a different (or the same) lead - drop it first.
        if self.throttle is not None:
            self.throttle.removePropertyChangeListener(self)
            self.throttle.release()
            self.throttle = None
            self.addButton.setEnabled(False)
            self.removeButton.setEnabled(False)
            self.refreshButton.setEnabled(False)
            self.releaseButton.setEnabled(False)

        self.readConsistButton.setEnabled(False)
        self.statusLabel.setText("Reading consist for %s (read-only, not taking control)..." % label)

        def onComplete(entries):
            self.readConsistButton.setEnabled(True)
            self.leadLabel = label + "  [read-only - Assign as Lead to edit]"
            self.leadNodeID = nodeID
            realEntries = [(n, f) for n, f in entries if is_plausible_dcc_node(n)]
            self._consistEntries = [_Entry(n, f) for n, f in realEntries]
            self._renderConsistList()
            self.statusLabel.setText(
                "Read %d consist member(s) for %s." % (len(realEntries), label))

        def onTimeout():
            self.readConsistButton.setEnabled(True)
            self.statusLabel.setText(
                "No reply from %s (no node on the CS-105 for that address?)." % label)

        reader = ConsistReader(self.iface, nodeID, onComplete, onTimeout)
        reader.start()

    def onAdd(self, event):
        if self.throttle is None or not self.throttle.getEnabled():
            return
        manual = parse_manual_address(self.addAddrField, self.addLongCheck)
        if manual is None:
            self.statusLabel.setText("Enter a valid DCC address (1-9999) to add first.")
            return
        addr, is_long = manual
        label = "addr %d%s" % (addr, "L" if is_long else "S")
        nodeID = node_id_for(addr, is_long)
        flags = 0
        if self.reverseCheck.isSelected():
            flags |= TractionThrottle.CONSIST_FLAG_REVERSE
        if self.fn0Check.isSelected():
            flags |= TractionThrottle.CONSIST_FLAG_FN0
        self.throttle.addToConsist(nodeID, flags)

        muMode = self.muSwitchCombo.getSelectedItem()
        if muMode == MU_SWITCH_UNCHANGED:
            muMode = None

        # Clear any leftover Advanced Consist CV19 setting on the newly
        # added unit too (honking its horn once done as confirmation), and
        # set its MU switch if one was chosen. Both run independently, so
        # the Add button stays disabled until whichever of them is running
        # has finished.
        self.addButton.setEnabled(False)
        pending = [2 if muMode is not None else 1]

        def onPartDone():
            pending[0] -= 1
            if pending[0] == 0:
                self.addButton.setEnabled(True)

        self._clearCv19(addr, is_long, label, nodeID, onPartDone)
        if muMode is not None:
            setter = MuSwitchSetter(self.iface, nodeID, label, muMode,
                                     self.muSwitchStatusLabel.setText, onPartDone)
            setter.start()

    def onRemove(self, event):
        idx = self.memberList.getSelectedIndex()
        # Row 0 is the LEAD display row (informational only, not removable
        # this way - release the lead via "Release Lead" instead).
        realIdx = idx - 1
        if realIdx < 0 or realIdx >= len(self._consistEntries):
            return
        entry = self._consistEntries[realIdx]
        if entry is None:
            return
        self.throttle.removeFromConsist(entry.node)

    def onRefresh(self, event):
        if self.throttle is not None:
            self.throttle.queryConsist()

    def onRelease(self, event):
        if self.throttle is not None:
            self.throttle.release()
            self.throttle.removePropertyChangeListener(self)
            self.throttle = None
        self.statusLabel.setText("(no lead assigned)")
        self.listModel.clear()
        self._consistEntries = []
        self.leadLabel = None
        self.leadNodeID = None
        self.addButton.setEnabled(False)
        self.removeButton.setEnabled(False)
        self.refreshButton.setEnabled(False)
        self.releaseButton.setEnabled(False)

    def onClearCv19(self, event):
        """Clears CV19 (sent CV19_REPEAT_COUNT times each) on every engine
        currently in the consist - the lead plus all attached members -
        one engine at a time, honking each one's horn as it finishes."""
        targets = self._gatherConsistTargets()
        if not targets:
            self.cvStatusLabel.setText(
                "No consist assigned - use Assign as Lead or Read Consist first.")
            return
        self.clearCvButton.setEnabled(False)
        self._clearCv19Queue(targets, 0)

    def _gatherConsistTargets(self):
        """Returns [(addr, is_long, label, node_id), ...] for the lead (if
        assigned) plus every real member currently shown in the consist
        list."""
        targets = []
        if self.leadNodeID is not None:
            addr, is_long = decode_node_id(self.leadNodeID)
            targets.append((addr, is_long, self.leadLabel or "LEAD", self.leadNodeID))
        for entry in self._consistEntries:
            if entry is None:
                continue
            addr, is_long = decode_node_id(entry.node)
            targets.append((addr, is_long, self.roster.name_for_node(entry.node), entry.node))
        return targets

    def _clearCv19Queue(self, targets, index):
        if index >= len(targets):
            self.cvStatusLabel.setText(
                "CV19 cleared on all %d engine(s) in the consist." % len(targets))
            self.clearCvButton.setEnabled(True)
            return
        addr, is_long, label, node_id = targets[index]
        self.cvStatusLabel.setText(
            "Clearing CV19 on engine %d of %d (%s)..." % (index + 1, len(targets), label))
        self._clearCv19(addr, is_long, label, node_id,
                         lambda: self._clearCv19Queue(targets, index + 1))

    def _clearCv19(self, addr, is_long, label, node_id, on_done):
        """Writes CV19=0 via Program on Main for the given locomotive
        CV19_REPEAT_COUNT times in a row, then honks its horn on success.
        Shared by "Clear CV19" (applied to every engine in the consist)
        and the automatic clear that happens when adding a locomotive to a
        consist. on_done() is always called exactly once, regardless of
        success/failure, so callers can chain to the next engine or
        re-enable whatever button they disabled while this was in flight."""
        apm = jmri.InstanceManager.getNullableDefault(jmri.AddressedProgrammerManager)
        if apm is None:
            self.cvStatusLabel.setText("No addressed (Program on Main) programmer available.")
            on_done()
            return
        programmer = apm.getAddressedProgrammer(is_long, addr)
        if programmer is None:
            self.cvStatusLabel.setText("Could not get a programmer for that address.")
            on_done()
            return

        self._activeCvProgrammer = programmer
        self.cvStatusLabel.setText(
            "Writing CV19=0 to %s (1 of %d)..." % (label, CV19_REPEAT_COUNT))
        listener = CvClearListener(self, programmer, label, node_id,
                                    CV19_REPEAT_COUNT - 1, on_done)
        try:
            programmer.writeCV("19", 0, listener)
        except jmri.ProgrammerException as ex:
            self.cvStatusLabel.setText("Error: %s" % ex)
            self._releaseCvProgrammer()
            on_done()

    def _releaseCvProgrammer(self):
        if self._activeCvProgrammer is not None:
            apm = jmri.InstanceManager.getNullableDefault(jmri.AddressedProgrammerManager)
            if apm is not None:
                apm.releaseAddressedProgrammer(self._activeCvProgrammer)
            self._activeCvProgrammer = None

    # --- property change from TractionThrottle (may arrive off the EDT) ---

    def propertyChange(self, evt):
        SwingUtilities.invokeLater(lambda: self._handlePropertyChange(evt))

    def _handlePropertyChange(self, evt):
        name = evt.getPropertyName()
        if name == TractionThrottle.UPDATE_PROP_STATUS:
            self.statusLabel.setText(str(self.throttle.getStatus()))
        elif name == TractionThrottle.UPDATE_PROP_ENABLED:
            enabled = self.throttle.getEnabled()
            self.addButton.setEnabled(enabled)
            self.refreshButton.setEnabled(enabled)
            self.releaseButton.setEnabled(enabled)
            if enabled:
                self.throttle.queryConsist()
        elif name == TractionThrottle.UPDATE_PROP_CONSISTLIST:
            myNodeId = self.iface.getNodeId()
            allEntries = list(self.throttle.getConsistList())
            # Filter out JMRI's own controller node (attached as a listener
            # on assign to take control) and any other non-train device
            # (e.g. a physical throttle that has this loco selected) - only
            # real, plausible-DCC-address locomotives are shown.
            self._consistEntries = [e for e in allEntries
                                     if e is None or (not e.node.equals(myNodeId)
                                                       and is_plausible_dcc_node(e.node))]
            self._renderConsistList()
            self.removeButton.setEnabled(len(self._consistEntries) > 0)

    def _renderConsistList(self):
        self.listModel.clear()
        self.listModel.addElement("LEAD: %s" % (self.leadLabel or "?"))
        for entry in self._consistEntries:
            if entry is None:
                self.listModel.addElement("(loading...)")
            else:
                flagbits = []
                if entry.flags & TractionThrottle.CONSIST_FLAG_REVERSE:
                    flagbits.append("reverse")
                if entry.flags & TractionThrottle.CONSIST_FLAG_FN0:
                    flagbits.append("F0")
                flagtext = (" [" + ", ".join(flagbits) + "]") if flagbits else ""
                self.listModel.addElement(self.roster.name_for_node(entry.node) + flagtext)


cscm = jmri.InstanceManager.getNullableDefault(CanSystemConnectionMemo)
if cscm is None:
    print("No CAN/LCC connection found - is the CS-105 connected?")
else:
    olcbIface = cscm.get(org.openlcb.OlcbInterface)
    frame = ConsistBuilderFrame(olcbIface)
    frame.setVisible(True)
