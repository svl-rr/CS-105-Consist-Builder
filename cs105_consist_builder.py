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

Usage:
  1. Panels > Run Script..., pick this file.
  2. Pick a lead locomotive (roster dropdown, or type its DCC address
     directly into the manual field - manual takes priority if filled
     in), click "Assign as Lead" (this also shows whatever's already
     consisted to it, if anything).
  3. Pick another locomotive the same way, set Reverse/F0 as needed,
     "Add to Consist".
  4. Repeat for more members. "Remove Selected" / "Refresh List" as needed.
  5. "Release Lead" when done - this only releases JMRI's own control
     access, it does NOT break up the consist itself (consists persist
     on the CS-105 independent of any throttle's connection).

Note: assigning a throttle to a locomotive that has never been addressed
before likely auto-creates its CS-105 virtual node as a side effect (this
is presumably how UWT throttles do it too) - so using this tool is also a
way to register new locomotives on the CS-105, one at a time.

The "Clear old NCE consist" section is unrelated to Traction/LCC - it
uses ordinary Program on Main (Ops Mode Programming) to write CV19=0 on
a given locomotive, clearing any leftover Decoder Assisted Consist
setting from the old NCE setup so it doesn't linger and interfere. On
success it briefly takes the throttle and honks the horn (F2) 3 times
as an audible confirmation, then releases it again.
"""
import jarray
from javax.swing import (JFrame, JPanel, JButton, JComboBox, JLabel, JList,
                          DefaultListModel, JScrollPane, JCheckBox, JTextField,
                          JTextArea, BoxLayout, SwingUtilities, BorderFactory,
                          ListSelectionModel, JOptionPane, Timer)
from java.awt import BorderLayout, FlowLayout, GridLayout, Dimension
from java.awt.event import ActionListener
from java.beans import PropertyChangeListener

from org.openlcb import NodeID, MessageDecoder
from org.openlcb.implementations.throttle import TractionThrottle, RemoteTrainNode
from org.openlcb.messages import TractionControlRequestMessage, TractionControlReplyMessage
from jmri.jmrix.can import CanSystemConnectionMemo


INSTRUCTIONS_TEXT = """HOW TO BUILD A CONSIST

1. In "Lead locomotive", pick the lead unit from the roster dropdown, or
   type its DCC address into the manual field just below it (check/uncheck
   "Long address" to match) - manual entry wins if it's filled in.
2. Click "Assign as Lead". Status will show "Enabled" once JMRI has
   control, and the member list will show a "LEAD: ..." row plus anything
   already consisted to it.
3. In "Add locomotive", pick (or manually enter) the next unit to attach.
   Check "Reverse" if it runs backwards relative to the lead, and
   "Respond to F0" if you want it to react to the lead's headlight
   function too.
4. Click "Add to Consist". It appears in the member list once attached.
5. Repeat steps 3-4 for any further units.
6. To remove one unit later, select it in the member list and click
   "Remove Selected" (the "LEAD:" row itself can't be removed this way -
   use Release Lead instead if you want to fully let go of the consist).
7. Click "Release Lead" when you're done. This only gives up JMRI's
   control of the lead - the consist itself stays intact on the CS-105 and
   works from any throttle, exactly as if a UWT throttle had built it.

To just check what's already consisted to a locomotive without taking
control of it, use "Read Consist" instead of Assign as Lead in step 2.

HOW TO CLEAR AN OLD NCE CONSIST (CV19)

If a locomotive still has a CV19 value left over from the old NCE setup,
clear it before/while migrating it to CS-105 consisting:

1. Scroll to "Clear old NCE consist".
2. Pick the locomotive from the "Locomotive" dropdown, or type its DCC
   address into the manual field below.
3. Click "Clear CV19", then confirm the dialog (this is a real
   Program-on-Main write to the layout).
4. "CV19 status" will show progress, then "CV19 cleared on ..." once
   done - the locomotive will also honk its horn 3 times as an audible
   confirmation.
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
    """Address/name lookups over the JMRI roster, for combo boxes and
    resolving consist member NodeIDs back to friendly names."""

    def __init__(self):
        roster = jmri.jmrit.roster.Roster.getDefault()
        self.entries = list(roster.getAllEntries())
        self.by_addr = {}
        self.labels = []
        self.label_to_entry = {}
        for re in self.entries:
            try:
                addr = int(re.getDccAddress())
            except Exception:
                continue
            is_long = re.isLongAddress()
            self.by_addr[(addr, is_long)] = re
            label = "%s  (%d%s)" % (re.getId(), addr, "L" if is_long else "S")
            self.labels.append(label)
            self.label_to_entry[label] = re
        self.labels.sort()

    def entry_for_label(self, label):
        return self.label_to_entry.get(label)

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
    """Returns (addr, is_long) if the manual entry field has a valid
    address typed in, else None (meaning: fall back to the roster combo)."""
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


class CvClearListener(jmri.ProgListener):
    """Handles the async reply from a Program-on-Main CV19 write. May be
    called back on a non-EDT thread, so hop to the EDT before touching
    any Swing components."""

    def __init__(self, frame, programmer, label, node_id):
        self.frame = frame
        self.programmer = programmer
        self.label = label
        self.node_id = node_id

    def programmingOpReply(self, value, status):
        SwingUtilities.invokeLater(lambda: self._handle(value, status))

    def _handle(self, value, status):
        if status == jmri.ProgListener.OK:
            self.frame.cvStatusLabel.setText("CV19 cleared on %s - honking horn..." % self.label)
            honker = HornHonker(self.frame.iface, self.node_id, self.label,
                                 self.frame.cvStatusLabel.setText)
            honker.start()
        else:
            self.frame.cvStatusLabel.setText(
                "CV19 write to %s failed (status %d)." % (self.label, status))
        self.frame.clearCvButton.setEnabled(True)
        self.frame._releaseCvProgrammer()


class HornHonker(PropertyChangeListener):
    """Honks the horn (function F2, NCE/most decoders' default horn/whistle
    assignment) 3 times on a locomotive, as a little audible confirmation
    that its CV19 was cleared. Briefly takes controller assignment (the
    only way to send function commands over Traction), then releases it
    again - same as a throttle briefly grabbing a loco to blow the horn.
    Timing uses a non-blocking javax.swing.Timer, never a blocking sleep,
    since this runs on JMRI's GUI thread."""

    HORN_FN = 2
    ON_MS = 400
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

    def _nextStep(self):
        totalSteps = self.HONKS * 2  # on, off, on, off, on, off
        if self.step >= totalSteps:
            self._finish()
            return
        hornOn = (self.step % 2 == 0)
        self.throttle.getFunction(self.HORN_FN).set(hornOn)
        delay = self.ON_MS if hornOn else self.OFF_MS
        self.step += 1
        timer = Timer(delay, _TimerCallback(self._nextStep))
        timer.setRepeats(False)
        timer.start()

    def _finish(self):
        self.throttle.getFunction(self.HORN_FN).set(False)
        self.throttle.removePropertyChangeListener(self)
        self.throttle.release()
        self.status_callback("CV19 cleared on %s (horn honked)." % self.label)


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
        helpPanel.add(JButton("Instructions", actionPerformed=self.onShowInstructions))
        root.add(helpPanel)

        # --- Lead section ---
        leadPanel = JPanel(FlowLayout(FlowLayout.LEFT))
        leadPanel.add(JLabel("Lead locomotive:"))
        self.leadCombo = JComboBox(self.roster.labels)
        leadPanel.add(self.leadCombo)
        self.assignButton = JButton("Assign as Lead", actionPerformed=self.onAssign)
        leadPanel.add(self.assignButton)
        self.readConsistButton = JButton("Read Consist", actionPerformed=self.onReadConsist)
        leadPanel.add(self.readConsistButton)
        root.add(leadPanel)

        leadManualPanel = JPanel(FlowLayout(FlowLayout.LEFT))
        leadManualPanel.add(JLabel("...or enter DCC address manually:"))
        self.leadAddrField = JTextField(6)
        leadManualPanel.add(self.leadAddrField)
        self.leadLongCheck = JCheckBox("Long address", True)
        leadManualPanel.add(self.leadLongCheck)
        root.add(leadManualPanel)

        statusPanel = JPanel(FlowLayout(FlowLayout.LEFT))
        statusPanel.add(JLabel("Status:"))
        self.statusLabel = JLabel("(no lead assigned)")
        statusPanel.add(self.statusLabel)
        root.add(statusPanel)

        root.add(JLabel(" "))

        # --- Add member section ---
        addPanel = JPanel(FlowLayout(FlowLayout.LEFT))
        addPanel.add(JLabel("Add locomotive:"))
        self.addCombo = JComboBox(self.roster.labels)
        addPanel.add(self.addCombo)
        self.reverseCheck = JCheckBox("Reverse")
        addPanel.add(self.reverseCheck)
        self.fn0Check = JCheckBox("Respond to F0")
        addPanel.add(self.fn0Check)
        self.addButton = JButton("Add to Consist", actionPerformed=self.onAdd)
        self.addButton.setEnabled(False)
        addPanel.add(self.addButton)
        root.add(addPanel)

        addManualPanel = JPanel(FlowLayout(FlowLayout.LEFT))
        addManualPanel.add(JLabel("...or enter DCC address manually:"))
        self.addAddrField = JTextField(6)
        addManualPanel.add(self.addAddrField)
        self.addLongCheck = JCheckBox("Long address", True)
        addManualPanel.add(self.addLongCheck)
        root.add(addManualPanel)

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
        root.add(JLabel("Clear old NCE consist (sets CV19 to 0 via Program on Main):"))

        cvPanel = JPanel(FlowLayout(FlowLayout.LEFT))
        cvPanel.add(JLabel("Locomotive:"))
        self.cvCombo = JComboBox(self.roster.labels)
        cvPanel.add(self.cvCombo)
        self.clearCvButton = JButton("Clear CV19", actionPerformed=self.onClearCv19)
        cvPanel.add(self.clearCvButton)
        root.add(cvPanel)

        cvManualPanel = JPanel(FlowLayout(FlowLayout.LEFT))
        cvManualPanel.add(JLabel("...or enter DCC address manually:"))
        self.cvAddrField = JTextField(6)
        cvManualPanel.add(self.cvAddrField)
        self.cvLongCheck = JCheckBox("Long address", True)
        cvManualPanel.add(self.cvLongCheck)
        root.add(cvManualPanel)

        cvStatusPanel = JPanel(FlowLayout(FlowLayout.LEFT))
        cvStatusPanel.add(JLabel("CV19 status:"))
        self.cvStatusLabel = JLabel("(idle)")
        cvStatusPanel.add(self.cvStatusLabel)
        root.add(cvStatusPanel)

        self._consistEntries = []
        self._activeCvProgrammer = None
        self.leadLabel = None

        self.setContentPane(root)
        self.pack()
        self.setLocationRelativeTo(None)

    # --- button handlers ---

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
        if manual is not None:
            addr, is_long = manual
        else:
            label = self.leadCombo.getSelectedItem()
            re = self.roster.entry_for_label(label)
            if re is None:
                return
            addr = int(re.getDccAddress())
            is_long = re.isLongAddress()
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
        if manual is None:
            self.leadLabel = "%s (%s)" % (re.getId(), self.leadLabel)

    def onReadConsist(self, event):
        manual = parse_manual_address(self.leadAddrField, self.leadLongCheck)
        if manual is not None:
            addr, is_long = manual
            label = "addr %d%s" % (addr, "L" if is_long else "S")
        else:
            selLabel = self.leadCombo.getSelectedItem()
            re = self.roster.entry_for_label(selLabel)
            if re is None:
                return
            addr = int(re.getDccAddress())
            is_long = re.isLongAddress()
            label = "%s (%d%s)" % (re.getId(), addr, "L" if is_long else "S")

        nodeID = node_id_for(addr, is_long)

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
        if manual is not None:
            addr, is_long = manual
        else:
            label = self.addCombo.getSelectedItem()
            re = self.roster.entry_for_label(label)
            if re is None:
                return
            addr = int(re.getDccAddress())
            is_long = re.isLongAddress()
        nodeID = node_id_for(addr, is_long)
        flags = 0
        if self.reverseCheck.isSelected():
            flags |= TractionThrottle.CONSIST_FLAG_REVERSE
        if self.fn0Check.isSelected():
            flags |= TractionThrottle.CONSIST_FLAG_FN0
        self.throttle.addToConsist(nodeID, flags)

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
        self.addButton.setEnabled(False)
        self.removeButton.setEnabled(False)
        self.refreshButton.setEnabled(False)
        self.releaseButton.setEnabled(False)

    def onClearCv19(self, event):
        manual = parse_manual_address(self.cvAddrField, self.cvLongCheck)
        if manual is not None:
            addr, is_long = manual
            label = "addr %d%s" % (addr, "L" if is_long else "S")
        else:
            label = self.cvCombo.getSelectedItem()
            re = self.roster.entry_for_label(label)
            if re is None:
                return
            addr = int(re.getDccAddress())
            is_long = re.isLongAddress()

        confirm = JOptionPane.showConfirmDialog(
            self,
            "Set CV19 to 0 on %s (address %d, %s) via Program on Main?\n"
            "This clears any old NCE Decoder Assisted Consist setting." %
            (label, addr, "long" if is_long else "short"),
            "Confirm CV19 clear", JOptionPane.YES_NO_OPTION)
        if confirm != JOptionPane.YES_OPTION:
            return

        apm = jmri.InstanceManager.getNullableDefault(jmri.AddressedProgrammerManager)
        if apm is None:
            self.cvStatusLabel.setText("No addressed (Program on Main) programmer available.")
            return
        programmer = apm.getAddressedProgrammer(is_long, addr)
        if programmer is None:
            self.cvStatusLabel.setText("Could not get a programmer for that address.")
            return

        self._activeCvProgrammer = programmer
        self.clearCvButton.setEnabled(False)
        self.cvStatusLabel.setText("Writing CV19=0 to %s ..." % label)
        nodeID = node_id_for(addr, is_long)
        listener = CvClearListener(self, programmer, label, nodeID)
        try:
            programmer.writeCV("19", 0, listener)
        except jmri.ProgrammerException as ex:
            self.cvStatusLabel.setText("Error: %s" % ex)
            self.clearCvButton.setEnabled(True)
            self._releaseCvProgrammer()

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
