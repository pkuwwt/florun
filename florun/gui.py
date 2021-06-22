#!/usr/bin/python
# -*- coding: utf8 -*-

import os
import errno
import sys
import copy
import math
import logging
import tempfile

from PyQt5.QtCore import *
from PyQt5.QtGui import QIcon, QTransform, QDrag, QPainter, QColor, QFont, QPen, QPixmap, QCursor, QPolygonF, QImage, qRgba
from PyQt5.QtWidgets import QDesktopWidget, QApplication, QMainWindow, QDialogButtonBox, \
                         QDialog, QFileDialog, QAction, QStyle, QWidget, QFrame, \
                         QLabel, QTabWidget, QLineEdit, QTextEdit, QPushButton, QToolBox, \
                         QGroupBox, QCheckBox, QComboBox, QSplitter, QMessageBox, \
                         QGridLayout, QVBoxLayout, QHBoxLayout, QFormLayout, \
                         QGraphicsScene, QGraphicsView, QGraphicsItem, \
                         QGraphicsItemGroup, QGraphicsEllipseItem, QGraphicsTextItem, QGraphicsLineItem, \
                         QGraphicsPolygonItem
                         
from PyQt5.QtSvg  import QGraphicsSvgItem

import florun
from florun.flow  import *
from florun.utils import import_plugins, itersubclasses, groupby, empty, traceback2str


logger = logging.getLogger(__name__)


"""
    
   Diagram items
    
"""


class SlotItem(QGraphicsEllipseItem):
    """
    A {SlotItem} is the graphical representation of a {flow.Interface}.
    """
    SIZE = 12
    COLORS = {InterfaceValue  : QColor(255, 255, 64),
              InterfaceStream : QColor(255, 159, 64),
              InterfaceList   : QColor(159, 255, 64)}
    TEXT_LEFT, TEXT_RIGHT, TEXT_BOTTOM, TEXT_TOP = range(4)

    def __init__(self, parent, interface, textposition=None):
        """
        @type parent : L{DiagramItem}
        @type interface : L{flow.Interface}
        @param textpostition : L{SlotItem.TEXT_LEFT}, ... L{SlotItem.TEXT_TOP}
        """
        QGraphicsEllipseItem.__init__(self, parent)
        assert issubclass(parent.__class__, DiagramItem)
        self.parent = parent
        self.connectors = []
        # Underlying object
        self.interface = interface
        self.buildItem()
        self.highlight = False
        self.text.setPlainText(interface.name)
        if textposition is None:
            textposition = SlotItem.TEXT_RIGHT
        self.textposition = textposition

    def buildItem(self):
        self.setToolTip(self.interface.doc)
        color = list(self.COLORS.values())[0]
        for iclass, icolor in self.COLORS.items():
            if issubclass(self.interface.__class__, iclass):
                color = icolor
        self.setBrush(color)
        self.setZValue(self.parent.zValue() + 1)
        self.text = QGraphicsTextItem(self)
        self.text.setParentItem(self)
        f = QFont()
        f.setPointSize(6)
        self.text.setFont(f)

    def setPos(self, pos):
        #QGraphicsEllipseItem.setPos(self, pos)
        self.setRect(pos.x(), pos.y(), self.SIZE, self.SIZE)
        self.text.setPos(pos + self.textOffset())
        self.update()

    @property
    def label(self):
        return self.interface.name

    @property
    def highlight(self):
        return self._highlight

    @highlight.setter
    def highlight(self, state):
        self._highlight = state
        if state:
            self.setPen(QPen(Qt.darkMagenta, 3))
        else:
            if len(self.connectors) == 0:
                self.setPen(QPen(Qt.darkGray, 2))
            else:
                self.setPen(QPen(Qt.darkMagenta, 2))

    def connect(self, connector, start=True):
        if start:
            connector.startItem = self
        else:
            connector.endItem = self
        self.connectors.append(connector)
        self.highlight = False

    def disconnect(self, connector):
        self.connectors.remove(connector)
        self.highlight = False

    def textOffset(self):
        textrect = self.text.boundingRect()
        x = y = 0
        if self.textposition == SlotItem.TEXT_TOP:
            x = x - textrect.width() / 2 + self.SIZE / 2
            y = y - self.SIZE - 2
        elif self.textposition == SlotItem.TEXT_BOTTOM:
            x = x - textrect.width() / 2 + self.SIZE / 2
            y = y + self.SIZE
        elif self.textposition == SlotItem.TEXT_LEFT:
            x = x - textrect.width()
            y = y - textrect.height() / 4
        elif self.textposition == SlotItem.TEXT_RIGHT:
            x = x + self.SIZE
            y = y - textrect.height() / 4
        return QPointF(x, y)

    def __unicode__(self):
        return u"%s:%s (%s)" % (self.parent, self.label, len(self.connectors))


class DiagramConnector(QGraphicsLineItem):
    """
    A {DiagramConnector} is a visual representation of an {flow.Interface}s successor.
    """
    HEAD_SIZE = 10

    def __init__(self, *args):
        QGraphicsLineItem.__init__(self, *args)
        self.startItem = None
        self.endItem   = None

        pen = QPen(Qt.darkMagenta, 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)

        self.setAcceptHoverEvents(True)
        self.setZValue(-1000)
        self.setPen(pen)

        polyhead = QPolygonF([QPointF(-self.HEAD_SIZE / 2, -self.HEAD_SIZE - 3),
                              QPointF( self.HEAD_SIZE / 2, -self.HEAD_SIZE - 3),
                              QPointF(0, -3)])
        self.arrowhead = QGraphicsPolygonItem(polyhead, self)
        self.arrowhead.setPen(pen)
        self.arrowhead.setBrush(Qt.darkMagenta)

    def __unicode__(self):
        return u"%s - %s" % (self.startItem, self.endItem)

    def canConnect(self, endItem):
        """
        Test if startitem and specified endslot are compatible
        @rtype boolean
        """
        return endItem.interface.isCompatible(self.startItem.interface)

    def disconnect(self):
        self.startItem.disconnect(self)
        if self.endItem is not None:
            self.endItem.disconnect(self)

    def moveOrigin(self, pos):
        endpos = self.line().p2()
        self.setLine(QLineF(pos, endpos))

    def moveEnd(self, pos):
        oripos = self.line().p1()
        self.setLine(QLineF(oripos, pos))
        # Rotate arrow head
        self.arrowhead.setPos(pos)
        l = self.line().length() or 1
        # Compute angle of arrow
        angle = math.acos(self.line().dx() / l) - math.pi / 2
        if self.line().dy() < 0:
            angle = math.pi - angle
        # Apply transformation to arrow head
        rotation = QTransform(math.cos(angle), math.sin(angle),
                             -math.sin(angle), math.cos(angle), 0, 0)
        self.arrowhead.setTransform(rotation)

    def updatePosition(self):
        offset = QPointF(SlotItem.SIZE / 2, SlotItem.SIZE / 2)
        oripos = QPointF()
        if self.startItem is not None:
            orirec = self.startItem.sceneBoundingRect()
            oripos = offset + QPointF(orirec.x(), orirec.y())
            self.moveOrigin(oripos)
        if self.endItem is not None:
            endrec = self.endItem.sceneBoundingRect()
            endpos = offset + QPointF(endrec.x(), endrec.y())
            self.moveEnd(endpos)
        else:
            self.moveEnd(oripos)

    def hoverEnterEvent(self, event):
        # Do not consider hovering connector, if over slot.
        hoverSlot = False
        for i in self.scene().items(event.scenePos()):
            if issubclass(i.__class__, SlotItem):
                hoverSlot = True
        if not hoverSlot:
            self.scene().connectorEnterEvent.emit(self)
        QGraphicsLineItem.hoverEnterEvent(self, event)

    def hoverLeaveEvent(self, event):
        self.scene().connectorLeaveEvent.emit(self)
        QGraphicsLineItem.hoverLeaveEvent(self, event)


class DiagramItem(QGraphicsItemGroup):
    """
    A {DiagramItem} is the graphical representation of a {flow.Node}.
    """
    SVG_SHAPE = ''

    mappings = {}
    
    def __init__(self, *args):
        QGraphicsItemGroup.__init__(self, *args)
        #self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self._shapes = None
        self.text = None
        # Underlying object
        self._node = None
        self.slotitems = []
        #: cf DiagramItem::showSlot() and DiagramScene::itemSelected()
        self.hackselected = False
        self.buildItem()

    def __unicode__(self):
        return u"%s" % self.text.toPlainText()

    @property
    def node(self):
        return self._node

    @node.setter
    def node(self, node):
        self._node = node
        self.addSlots()
        self.showSlots()

    @staticmethod
    def register(nodeclass, diagramitemclass):
        DiagramItem.mappings[nodeclass] = diagramitemclass

    @staticmethod
    def factory(classobj):
        # Find direct match first
        for mainclass, diagramitemcls in DiagramItem.mappings.items():
            if classobj == mainclass:
                return diagramitemcls()
        # Find by inheritance
        for mainclass, diagramitemcls in DiagramItem.mappings.items():
            if issubclass(classobj, mainclass):
                return diagramitemcls()
        raise Exception(_("Unknown node type '%s'") % classobj.__name__)

    @classmethod
    def SVGShape(cls):
        path = os.path.join(florun.icons_dir, cls.SVG_SHAPE)
        if not os.path.exists(path):
            for plugindir in florun.plugins_dirs.split(os.pathsep):
                path = os.path.join(plugindir, cls.SVG_SHAPE)
                if os.path.exists(path):
                    return path 
            logger.warning("SVG missing '%s'" % path)
        return path

    def buildItem(self):
        self.text = QGraphicsTextItem()
        f = QFont()
        f.setBold(True)
        self.text.setFont(f)
        self.text.setZValue(1000)
        self.addToGroup(self.text)
        for s in self.shapes.values():
            self.addToGroup(s)
        self.update()

    @property
    def shapes(self):
        if not self._shapes:
            self._shapes = {}
            for elt in ['start', '']:
                s = QGraphicsSvgItem(self.SVGShape())
                if elt:
                    s.setElementId(elt)
                self._shapes[elt] = s
            self.shapes['start'].setZValue(self.shapes[''].zValue() - 1)
        return self._shapes

    def update(self):
        # Update id
        if self.node is not None:
            self.text.setPlainText(self.node.id)
        # Center text item
        itemrect = self.boundingRect()
        textrect = self.text.boundingRect()
        self.text.setPos(QPointF(itemrect.x() + itemrect.width() / 2 - textrect.width() / 2,
                                -textrect.height() + itemrect.y() + itemrect.height() / 2))
        if textrect.width() > itemrect.width():
            self.text.setTextWidth(itemrect.width())
        # Show slots
        self.showSlots()

    def setStartNode(self, state):
        self.shapes['start'].setVisible(state)

    def itemChange(self, change, value):
        r = QGraphicsItemGroup.itemChange(self, change, value)
        # Selection state
        if change == QGraphicsItem.ItemSelectedChange:
            self.scene().selectedChanged.emit(self)
        # Position
        if change == QGraphicsItem.ItemPositionChange:
            for s in self.slotitems:
                for c in s.connectors:
                    c.updatePosition()
        return r

    def findSlot(self, interface):
        """
        Find the {SlotItem} matching the specified {flow.Interface}.
        @type interface: {flow.Interface}
        @rtype: {SlotItem}
        """
        for s in self.slotitems:
            if s.interface == interface:
                return s
        raise Exception(u"SlotItem with interface %s not found on %s" % (interface, self))

    def addSlots(self):
        # Add them all
        textpositions = {Interface.PARAMETER : SlotItem.TEXT_RIGHT,
                         Interface.INPUT     : SlotItem.TEXT_BOTTOM,
                         Interface.RESULT    : SlotItem.TEXT_LEFT,
                         Interface.OUTPUT    : SlotItem.TEXT_TOP}
        for interface in self.node.interfaces:
            textposition = textpositions.get(interface.type, None)
            slot = SlotItem(self, interface, textposition)
            slot.setVisible(False)
            self.slotitems.append(slot)
            self.addToGroup(slot)

    def showSlots(self):
        for slot in self.slotitems:
            self.showSlot(slot, slot.interface.slot)

    def boundingOffsets(self):
        """
        4-tuple : top, right, bottom, left
        """
        return (0, 0, 0, 0)

    def showSlot(self, slot, state):
        """
        Show/Hide specific slot
        @type state : bool
        """
        # Save selected state, restore after
        self.hackselected = True
        selected = self.isSelected()
        # Show/Hide slot
        slot.setVisible(state)

        # Disconnect all connectors
        if not state:
            for c in slot.connectors:
                self.scene().removeConnector(c, True)

        # Spread on side
        rect = self.boundingRect()

        # List all visible slot on each side
        left   = [s for s in self.slotitems if s.textposition == SlotItem.TEXT_RIGHT  and s.isVisible()]
        right  = [s for s in self.slotitems if s.textposition == SlotItem.TEXT_LEFT   and s.isVisible()]
        top    = [s for s in self.slotitems if s.textposition == SlotItem.TEXT_BOTTOM and s.isVisible()]
        bottom = [s for s in self.slotitems if s.textposition == SlotItem.TEXT_TOP    and s.isVisible()]

        # Find out positions intervals and offsets
        offtop, offright, offbottom, offleft = self.boundingOffsets()
        # slot's textposition allows to know on which side slot appears
        # sidelist    : which list of slots to be handled
        # corner      : which point of reference to spread along side
        # sizex,sizey : which size of refence to spread along side
        if slot.textposition == SlotItem.TEXT_RIGHT:
            sidelist = left
            corner = QPointF(rect.x() + offleft, rect.y())
            sizex, sizey = (0, rect.height())
        elif slot.textposition == SlotItem.TEXT_LEFT:
            sidelist = right
            corner = QPointF(rect.x() + rect.width() + offright, rect.y())
            sizex, sizey = (0, rect.height())
        elif slot.textposition == SlotItem.TEXT_BOTTOM:
            sidelist = top
            corner = QPointF(rect.x(), rect.y() + offtop)
            sizex, sizey = (rect.width(), 0)
        elif slot.textposition == SlotItem.TEXT_TOP:
            sidelist = bottom
            corner = QPointF(rect.x(), rect.y() + rect.height() + offbottom)
            sizex, sizey = (rect.width(), 0)

        intervalx = sizex / (len(sidelist) + 1)
        intervaly = sizey / (len(sidelist) + 1)
        offset = QPointF(-SlotItem.SIZE / 2, -SlotItem.SIZE / 2)

        for j, s in enumerate(sidelist):
            position = corner + offset + QPointF(intervalx * (j + 1), intervaly * (j + 1))
            s.setPos(position)
        # Reset selected state that was lost
        self.setSelected(selected)
        self.hackselected = False


class DiagramItemProcess(DiagramItem):
    SVG_SHAPE = "item-process.svg"


class DiagramItemInput(DiagramItem):
    SVG_SHAPE = "item-input.svg"

    def boundingOffsets(self):
        return (0, -10, 0, 10)


class DiagramItemOutput(DiagramItem):
    SVG_SHAPE = "item-output.svg"

    def boundingOffsets(self):
        return (0, -10, 0, 10)

"""
    
   Diagram scene
    
"""


class DiagramScene(QGraphicsScene):
    """
    The {DiagramScene} contains all methods to add and remove graphical items.
    Events of user actions are emitted here.
    """
    
    DEFAULT_SIZE = QSizeF(700, 500)

    slotEnterEvent = pyqtSignal(object)
    slotLeaveEvent = pyqtSignal(object)
    connectorEnterEvent = pyqtSignal(object)
    connectorLeaveEvent = pyqtSignal(object)
    selectedChanged = pyqtSignal(object)

    diagramItemSelected = pyqtSignal(object)
    diagramItemCreated = pyqtSignal(object)
    diagramItemRemoved = pyqtSignal(object)
    connectorCreated = pyqtSignal(object)
    connectorRemoved = pyqtSignal(object)
    diagramItemMoved = pyqtSignal(object)
    
    def __init__(self, *args, **kwargs):
        super(DiagramScene, self).__init__(*args, **kwargs)
        self.setSceneRect(QRectF(QPointF(), self.DEFAULT_SIZE))
        self.slotEnterEvent.connect(self._slotEnterEvent)
        self.slotLeaveEvent.connect(self._slotLeaveEvent)
        self.connectorEnterEvent.connect(self._connectorEnterEvent)
        self.connectorLeaveEvent.connect(self._connectorLeaveEvent)
        self.selectedChanged.connect(self.itemSelected)
        self.connector = None
        self.slot = None
        self.connectorHover = None
        self.slotHover = None
        #self.itemSelected = None

    @property
    def window(self):
        return self.parent()

    @property
    def view(self):
        v = self.views()
        if len(v) > 0:
            return v[0]
        return None

    def dragEnterEvent(self, event):
        QGraphicsScene.dragEnterEvent(self, event)
        if event.mimeData().hasFormat('text/plain'):
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        #QGraphicsScene.dragMoveEvent(self, event)
        event.accept()

    def dropEvent(self, event):
        print('dropEvent')
        # Create graphical item from string (classname)
        classname = str(event.mimeData().text())
        classobj = eval(classname)
        node = classobj(flow=self.parent().flow)
        self.addDiagramItem(event.scenePos(), node)

    def _slotEnterEvent(self, slot):
        self.view.setCursor(Qt.CrossCursor)
        slot.highlight = True
        self.slot = slot

    def _slotLeaveEvent(self, slot):
        if self.connector is None:
            self.view.setCursor(Qt.ArrowCursor)
        slot.highlight = False
        self.slot = None

    def _connectorEnterEvent(self, connector):
        self.view.setCursor(MainWindow.ScissorsCursor)
        self.connectorHover = connector

    def _connectorLeaveEvent(self, connector):
        self.view.setCursor(Qt.ArrowCursor)
        self.connectorHover = None

    def addDiagramItem(self, pos, node, emit=True):
        item = DiagramItem.factory(node.__class__)
        item.node = node
        middle = pos - item.sceneBoundingRect().center()
        item.setPos(middle)
        self.addItem(item)
        item.update()
        if emit:
            self.diagramItemCreated.emit(item)
        return item

    def removeDiagramItem(self, item):
        for slot in item.slotitems:
            toremove = copy.copy(slot.connectors)
            for connector in toremove:
                self.removeConnector(connector)
        self.removeItem(item)
        self.diagramItemRemoved.emit(item)

    def addConnector(self, startSlot, endSlot=None, emit=True):
        connector = DiagramConnector()
        self.addItem(connector)
        startSlot.connect(connector, start=True)
        # If endSlot is not given, then the user is now drawing
        if endSlot is not None:
            endSlot.connect(connector, start=False)
            logger.debug("%s %s" % ("Connector added", connector))
            if emit:
                self.connectorCreated.emit(connector)
        connector.updatePosition()
        return connector

    def removeConnector(self, connector, event=False):
        logger.debug("Disconnect {}".format(connector))
        connector.disconnect()
        self.removeItem(connector)
        self._connectorLeaveEvent(connector)
        if event:
            logger.debug("Connector removed : {}".format(connector))
            self.connectorRemoved.emit(connector)

    @property
    def diagramitems(self):
        return [i for i in self.items() if issubclass(i.__class__, DiagramItem)]

    def findDiagramItemByNode(self, node):
        for i in self.diagramitems:
            if i.node == node:
                return i
        raise Exception("%s : %s" % ("DiagramItem not found with node", node))

    def setStartNodes(self, nodes):
        for i in self.diagramitems:
            i.setStartNode(False)
        for n in nodes:
            i = self.findDiagramItemByNode(n)
            i.setStartNode(True)

    def mousePressEvent(self, mouseEvent):
        if self.slot is not None:
            self.connector = self.addConnector(self.slot)
        QGraphicsScene.mousePressEvent(self, mouseEvent)

    def mouseMoveEvent(self, mouseEvent):
        pos = mouseEvent.scenePos()
        # If connector is not None, the user is drawing
        if self.connector is not None:
            self.connector.moveEnd(pos)

        #TODO: refactor this nicely !
        # This is due to this problem : http://ubuntuforums.org/showthread.php?p=9013506
        # Check if mouse left or entered a slot
        hoverslot = None
        for i in self.items(pos):
            if issubclass(i.__class__, SlotItem):
                hoverslot = i
        # Left
        if hoverslot is None and self.slotHover is not None:
            self.slotLeaveEvent.emit(self.slotHover)
        # Entered
        if hoverslot is not None and self.slotHover is None:
            self.slotEnterEvent.emit(hoverslot)
        self.slotHover = hoverslot

        # If not drawing connector, items are movable
        if self.connector is None:
            QGraphicsScene.mouseMoveEvent(self, mouseEvent)

    def mouseReleaseEvent(self, mouseEvent):
        if self.connectorHover is not None:
            # Connector was clicked : remove it
            self.removeConnector(self.connectorHover, True)
        elif self.connector is not None:
            # Create connector
            if self.slot is not None:
                if self.connector.canConnect(self.slot):
                    # Check if connector already exists
                    exists = False
                    for i in [item for item in self.items() if issubclass(item.__class__, DiagramConnector)]:
                        if i.startItem == self.connector.startItem and i.endItem == self.slot:
                            exists = True
                    if not exists:
                        # New connector, remove the one being drawn
                        self.removeConnector(self.connector)
                        # Add the new one with both ends
                        self.addConnector(self.connector.startItem, self.slot)
                    else:
                        self.window.setStatusMessage("Connector already exists")
                        self.removeConnector(self.connector)
                else:
                    # For some reason, start and end slots could not be connected.
                    self.window.setStatusMessage("Incompatible slots")
                    self.removeConnector(self.connector)
            else:
                # Mouse was released outside slot
                self.removeConnector(self.connector)
        # Moved item ?
        pos = mouseEvent.scenePos()
        for i in self.items(pos):
            if issubclass(i.__class__, DiagramItem):
                self.diagramItemMoved.emit(i)
        # Reinitialize situation
        self.connector = None
        self.slot = None
        QGraphicsScene.mouseReleaseEvent(self, mouseEvent)

    def itemSelected(self, item):
        # Due to DiagramItem::showSlot() l.350 auto deselect  !
        # http://www.qtforum.org/article/32164/setvisible-on-a-qgraphicsitemgroup-child-changes-the-group-selected-state.html
        if item.hackselected is False:
            self.diagramItemSelected.emit(item)

"""

   Library of Nodes

"""


class NodeLibrary(QToolBox):
    """
    The {NodeLibrary} contains different sets of {LibraryItem}s.
    The {QtGui.QToolBox} allows to have collapsable widgets.
    """
    MAX_PER_LINE = 2

    def __init__(self, *args):
        QToolBox.__init__(self, *args)
        self.loadSets()

    def loadSets(self):
        DiagramItem.register(ProcessNode, DiagramItemProcess)
        DiagramItem.register(InputNode, DiagramItemInput)
        DiagramItem.register(OutputNode, DiagramItemOutput)
        
        import_plugins(florun.plugins_dirs, globals())

        libs = groupby([c for c in itersubclasses(Node) if c.label != ''], 'category')
        _key = lambda x: x.label
        # Add sets according to groups
        for itemgroup in libs:
            set = []
            for classobj in sorted(itemgroup, key=_key):
                item = DiagramItem.factory(classobj)
                logger.debug(u"Adding %s/%s in nodes library" % (type(item).__name__, classobj.fullname()))
                item = LibraryItem(classobj.fullname(), classobj.label, item.SVGShape())
                set.append(item)
            self.addSet(set, itemgroup[0].category)

    def addSet(self, widgets, label):
        """
        @type widgets : list of {LibraryItem}
        @param label  : the name of the set of items
        @type label   : string
        """
        layout = QGridLayout()
        layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        for i, widget in enumerate(widgets):
            layout.addWidget(widget, int(i / self.MAX_PER_LINE), i % self.MAX_PER_LINE)
        list = QWidget()
        list.setLayout(layout)
        self.addItem(list, label)


class LibraryItem(QFrame):

    def __init__(self, id, label, iconfile):
        QFrame.__init__(self)
        self.id = id
        # An Icon and a label below
        icon = QLabel()
        icon.setPixmap(QPixmap(iconfile).scaledToWidth(50))
        layout = QGridLayout()
        layout.addWidget(icon, 0, 0, Qt.AlignHCenter)
        title = QLabel(label)
        font = title.font()
        font.setPixelSize(10)
        title.setFont(font)
        layout.addWidget(title, 1, 0, Qt.AlignTop | Qt.AlignHCenter)
        self.setLayout(layout)
        self.setMaximumSize(80, 80)
        self._window = None

    @property
    def window(self):
        if self._window is None:
            widget = self.parent()
            while widget is not None and not issubclass(widget.__class__, MainWindow):
                widget = widget.parent()
            self._window = widget
        return self._window

    """
    Drag and drop management
    """

    def enterEvent(self, event):
        self.setFrameStyle(QFrame.Panel | QFrame.Sunken)
        self.setCursor(Qt.OpenHandCursor)
        # Show description in status bar
        self.window.setStatusMessage(eval(self.id).description)

    def leaveEvent(self, event):
        self.setFrameStyle(QFrame.NoFrame)
        self.setCursor(Qt.ArrowCursor)

    def mousePressEvent(self, mouseEvent):
        self.setCursor(Qt.ClosedHandCursor)

    def mouseReleaseEvent(self, mouseEvent):
        self.setCursor(Qt.OpenHandCursor)

    def mouseMoveEvent(self, event):
        # Drag-n-Drop on left clic :
        if event.buttons() != Qt.LeftButton:
            return
        # Store the classname of the node in the D-n-D
        mimeData = QMimeData()
        mimeData.setText(self.id)
        # Initialize Drag-and-drop action
        drag = QDrag(self)
        drag.setMimeData(mimeData)
        drag.setHotSpot(event.pos() - self.rect().topLeft())

        dropAction = drag.exec_(Qt.MoveAction)
        if dropAction == Qt.MoveAction:
            self.close()

"""
    
    Parameters Editor
    
"""


class ParameterField(QWidget):
    """
    A form widget for the {ParameterEditor}.
    It will reflect its associated L{flow.Interface}.
    """

    def __init__(self, interface, *args):
        """
        @type interface : L{flow.Interface}
        """
        QWidget.__init__(self, *args)
        self.interface = interface

        self.label = interface.name

        self.edit     = QLineEdit(self)
        self.checkbox = QCheckBox('slot', self)
        self.checkbox.setToolTip('Use slot input')

        layout = QHBoxLayout()
        layout.addWidget(self.edit)
        layout.addWidget(self.checkbox)
        self.setLayout(layout)
        self.setToolTip(interface.doc)
        # Show slot as it should be
        self.setSlot(self.interface.slot)

    def setSlot(self, slotstate):
        """
        Show slot checkbox as specified by slotstate
        """
        self.checkbox.setCheckState(Qt.Checked if slotstate else Qt.Unchecked)
        self.edit.setEnabled(not slotstate)
        value = ''
        if self.interface.value is not None and not slotstate:
            value = self.interface.value
        self.edit.setText(value)

    @property
    def checked(self):
        return self.checkbox.checkState() == Qt.Checked


class ParametersEditor(QWidget):

    diagramItemChanged = pyqtSignal(object)

    def __init__(self, parent, scene, *args):
        QWidget.__init__(self, *args)
        self.parent = parent
        self.scene = scene

        # Actions
        self.btnDelete = QPushButton("Delete")
        self.btnDelete.setIcon(self.parent.loadIcon('edit-delete'))
        self.btnCancel = QPushButton("Undo")
        self.btnCancel.setIcon(self.parent.loadIcon('edit-undo'))
        self.btnSave = QPushButton("Apply")
        self.btnSave.setIcon(self.parent.loadIcon('dialog-apply'))
        # slots
        self.btnDelete.clicked.connect(self.delete)
        self.btnCancel.clicked.connect(self.cancel)
        self.btnSave.clicked.connect(self.save)

        # Buttons
        buttonslayout = QHBoxLayout()
        buttonslayout.addWidget(self.btnDelete)
        buttonslayout.addWidget(self.btnCancel)
        buttonslayout.addWidget(self.btnSave)
        buttonswidget = QWidget()
        buttonswidget.setLayout(buttonslayout)

        # Parameters Layout
        self.paramlayout = QVBoxLayout()
        parameterbox = QGroupBox()
        parameterbox.setTitle("Parameters")
        parameterbox.setLayout(self.paramlayout)

        # Information Layout
        self.lbldescription = QLabel()
        self.lbldescription.setWordWrap(True)

        infolayout = QVBoxLayout()
        infolayout.addWidget(self.lbldescription)
        self.informationbox = QGroupBox()
        self.informationbox.setLayout(infolayout)

        mainlayout = QVBoxLayout()
        mainlayout.addWidget(self.informationbox)
        mainlayout.addWidget(parameterbox)
        mainlayout.addStretch()
        mainlayout.addWidget(buttonswidget)

        self.setLayout(mainlayout)

        # Form item
        self.formwidget = None
        self.formlayout = None
        """@type item : {DiagramItem}"""
        self.item       = None
        self.nodeId     = None
        self.extrafields = {}
        self.changed    = False

        # Init form with default fields
        self.clear()

    def enable(self):
        state = self.item is not None
        self.nodeId.setEnabled(state)
        for w in self.extrafields.values():
            w.setEnabled(state)
        self.btnDelete.setEnabled(state)
        self.btnCancel.setEnabled(state and self.changed)
        self.btnSave.setEnabled(state and self.changed)

    def clear(self):
        # If item fields were changed ?
        if self.item is not None:
            if self.changed:
                answer = MainWindow.messageYesNo("Apply fields ?",
                                                 "Some node properties have been modified.",
                                                 "Do you want to apply changes?")
                if answer == QMessageBox.Yes:
                    self.save()
                # Clear loaded item, Update it on scene
                self.item.update()

        # Now clear the panel, and reinitialize widgets
        if self.formwidget is not None:
            self.paramlayout.removeWidget(self.formwidget)
            self.formwidget.setParent(None)

        # Common fields
        self.lbldescription.setText('')
        self.informationbox.setTitle("Node")

        self.nodeId = QLineEdit('', self)
        self.formlayout = QFormLayout()
        self.formlayout.addRow("Id", self.nodeId)

        self.formwidget = QWidget()
        self.formwidget.setLayout(self.formlayout)
        self.paramlayout.insertWidget(0, self.formwidget)

        self.item = None
        self.changed = False
        self.extrafields = {}

        # Enable widgets
        self.enable()

    def delete(self):
        self.scene.removeDiagramItem(self.item)
        self.clear()

    def cancel(self):
        self.changed = False
        self.load(self.item)

    def load(self, item):
        self.clear()
        self.item = item

        self.informationbox.setTitle(item.node.category + " : " + item.node.label)
        self.lbldescription.setText(item.node.description)

        self.nodeId.setText(item.node.id)
        # For each node interface, add a widget
        for interface in item.node.interfaces:
            if interface.isValue() and interface.isInput():
                w = ParameterField(interface)
                # Trick to have tooltip on form row
                qlabel = QLabel(w.label)
                qlabel.setToolTip(w.interface.doc)
                self.formlayout.addRow(qlabel, w)
                # Connect checkbox event
                w.checkbox.stateChanged.connect(self.showSlot)
                w.edit.textChanged.connect(self.entriesChanged)
                w.edit.returnPressed.connect(self.save)
                # Keep track of associations for saving
                self.extrafields[interface.name] = w
        self.nodeId.textChanged.connect(self.entriesChanged)
        self.nodeId.returnPressed.connect(self.save)
        self.enable()

    def save(self):
        userentries = {}
        userentries['id'] = (self.nodeId.text(), None)
        for name, w in self.extrafields.items():
            userentries[name] = (str(w.edit.text()), w.checked)
        # Save Interface values (from GUI to flow)
        self.item.node.applyAttributes(userentries)
        self.changed = False
        # Update item on scene
        self.item.update()
        self.enable()
        self.diagramItemChanged.emit(self.item)

    def showSlot(self, state):
        for w in self.extrafields.values():
            w.setSlot(w.checked)
            # Show/Hide slot on item
            slot = self.item.findSlot(w.interface)
            self.item.showSlot(slot, w.checked)
            # State changed ?
            if w.interface.slot != w.checked:
                self.changed = True
                self.enable()

    def entriesChanged(self):
        self.changed = True
        self.enable()


class FlowConsole(QWidget):

    def __init__(self, *args):
        QWidget.__init__(self, *args)
        self.process = None

        self.cbloglevel = QComboBox()
        self.cbloglevel.insertItem(0, "Errors only",    logging.ERROR)
        self.cbloglevel.insertItem(1, "Warnings",       logging.WARNING)
        self.cbloglevel.insertItem(2, "Information",    logging.INFO)
        self.cbloglevel.insertItem(3, "Debug messages", logging.DEBUG)
        self.cbloglevel.setCurrentIndex(2)

        self.lblloglevel = QLabel("Output")
        self.lblloglevel.setBuddy(self.cbloglevel)

        hlbox = QHBoxLayout()
        hlbox.addWidget(self.lblloglevel)
        hlbox.addWidget(self.cbloglevel)
        hlbox.addStretch()
        hbox = QWidget()
        hbox.setLayout(hlbox)

        self.console = QTextEdit()
        self.console.setAcceptRichText(False)

        self.mainlayout = QVBoxLayout()
        self.mainlayout.addWidget(hbox)
        self.mainlayout.addWidget(self.console)
        self.setLayout(self.mainlayout)

    #@property
    def loglevel(self):
        idx = self.cbloglevel.currentIndex()
        integer = self.cbloglevel.itemData(idx)
        return integer

    def enable(self):
        self.cbloglevel.setEnabled(self.process is None)

    def attachProcess(self, process):
        self.process = process
        self.console.clear()
        self.enable()

    def detachProcess(self):
        self.process = None
        self.enable()

    def clear(self):
        self.console.setText('')

    def updateConsole(self):
        if self.process is not None:
            stdout = self.process.readAllStandardOutput().trimmed()
            if stdout:
                stdout = stdout.replace(b"<",  b"&lt;")
                stdout = stdout.replace(b">",  b"&gt;")
                stdout = stdout.replace(b"\n", b"<br/>")
                self.console.append("<span style=\"color: black\">" + bytes(stdout).decode('utf-8') + "</span>")
            stderr = self.process.readAllStandardError().trimmed()
            if stderr:
                stderr = stderr.replace(b"<", b"&lt;")
                stderr = stderr.replace(b">", b"&gt;")
                stderr = stderr.replace(b"\n", b"<br/>")
                self.console.append("<span style=\"color: red\">" + bytes(stderr).decode('utf-8') + "</span>")

"""
    
    Main Window
    
"""


class MainWindow(QMainWindow):
    """
    @type ScissorsCursor : {QCursor}
    """
    ScissorsCursor = None

    def __init__(self, filename=None, *args):
        QMainWindow.__init__(self, *args)
        MainWindow.ScissorsCursor = QCursor(self.loadIcon('cursor-scissors').pixmap(QSize(24, 24)))
        self.apptitle = florun.__title__
        # Main attributes
        self.basedir = florun.base_dir
        self.asked = False
        self.tmpfile = None
        self.flow = None
        self.buildActions()
        self.buildWidgets()
        # Load preferences
        self.loadPreferences()
        # Init
        if filename is not None:
            self.loadFlow(filename)
        else:
            self.newFlow()
        self.updateTitle()

    def buildWidgets(self):
        # Main widgets
        self.statusBar()
        self.buildMenuToolbar()
        """
        Diagram Panel
        """
        # Scene
        self.scene = DiagramScene(self)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)
        # Node library
        self.nodelibrary = NodeLibrary()
        # Parameters Panel
        self.parameters = ParametersEditor(self, self.scene)
        # Put it all together
        diagrampanel = QSplitter()
        diagrampanel.addWidget(self.nodelibrary)
        diagrampanel.addWidget(self.view)
        diagrampanel.addWidget(self.parameters)
        diagrampanel.setSizes([180, 400, 150])
        diagrampanel.setStretchFactor(0, 0)
        diagrampanel.setStretchFactor(1, 1)
        diagrampanel.setStretchFactor(2, 0)

        """
        Console Panel
        """
        self.console = FlowConsole(self)

        # Build tabs
        self.maintabs = QTabWidget()
        self.maintabs.addTab(diagrampanel, "Scheme")
        self.maintabs.addTab(self.console, "Console")
        self.setCentralWidget(self.maintabs)

        # Connect events
        self.scene.diagramItemSelected.connect(self._diagramItemSelected)
        self.scene.diagramItemCreated.connect(self._diagramItemCreated)
        self.scene.diagramItemRemoved.connect(self._diagramItemRemoved)
        self.scene.connectorCreated.connect(self._connectorCreated)
        self.scene.connectorRemoved.connect(self._connectorRemoved)
        self.scene.diagramItemMoved.connect(self._diagramItemMoved)

        self.parameters.diagramItemChanged.connect(self._diagramItemChanged)

    def loadPreferences(self):
        # Center of the screen by default
        self.setGeometry(100, 100, 800, 500)
        self.center()
        # Reload settings if exist
        settings = QSettings(florun.__title__)
        def settings_to_bytes(name):
            v = settings.value(name)
            if isinstance(v, QByteArray):
                return v
            if v is None:
                return QByteArray()
            return v.toByteArray()
        self.restoreGeometry(settings_to_bytes("mainwindow/geometry"))
        self.restoreState(settings_to_bytes("mainwindow/windowState"))

    def savePreferences(self):
        settings = QSettings(florun.__title__)
        settings.beginGroup("mainwindow")
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())
        settings.endGroup()

    @property
    def filename(self):
        return self.flow.filename or "Untitled"

    def updateTitle(self):
        filename = self.filename
        if self.flow.modified:
            filename = "*"+filename
        self.setWindowTitle("%s - %s" % (filename, self.apptitle))

    def setStatusMessage(self, txt, timeout=6000):
        self.statusBar().showMessage(txt, timeout)

    def loadIcon(self, iconid):
        """
        @param iconid : Freedesktop identifier from http://standards.freedesktop.org/icon-naming-spec/icon-naming-spec-latest.html
        @type iconid : str
        @rtype: L{QtGui.QIcon}
        """
        # Try Themed Icons (Qt >= 4.6)
        try:
            if QIcon.hasThemeIcon(iconid):
                return QIcon.fromTheme(iconid)
        except AttributeError as e:
            pass

        # Else
        # Try in Qt default icons
        lookup = {'edit-delete':      QStyle.SP_TrashIcon,
                  'edit-undo':        QStyle.SP_DialogCancelButton,
                  'dialog-apply':     QStyle.SP_DialogOkButton,
                  #'document-new':    QStyle.SP_DialogResetButton,
                  'document-open':    QStyle.SP_DialogOpenButton,
                  'document-save':    QStyle.SP_DialogSaveButton,
                  'application-exit': QStyle.SP_DialogCloseButton}
        qticonid = lookup.get(iconid)
        if qticonid is not None:
            style = self.style()
            return style.standardIcon(qticonid)

        # Else
        # Guess path of icon
        for base in [florun.icons_dir, '/usr/share/icons/']:
            find = QProcess()
            find.start('find %s -name "%s*"' % (base, iconid))
            if find.waitForFinished():
                list = find.readAllStandardOutput().split("\n")
                if len(list) > 0:
                    path = bytes(list[0]).decode('utf-8')
                    if path != '':
                        logger.debug("Load icon file from '%s'" % path)
                        return QIcon(QPixmap(path))
        return QIcon(QPixmap())

    def buildActions(self):
        self.new = QAction(self.loadIcon('document-new'), 'New', self)
        self.new.setShortcut('Ctrl+N')
        self.new.setStatusTip('New flow')
        self.new.triggered.connect(self.newFlow)

        self.open = QAction(self.loadIcon('document-open'), 'Open', self)
        self.open.setShortcut('Ctrl+O')
        self.open.setStatusTip('Open flow')
        self.open.triggered.connect(self.loadFlow)

        self.save = QAction(self.loadIcon('document-save'), 'Save', self)
        self.save.setShortcut('Ctrl+S')
        self.save.setStatusTip('Save flow')
        self.save.triggered.connect(self.saveFlow)

        self.export = QAction(self.loadIcon('image-x-generic'), 'Export', self)
        self.export.setShortcut('Ctrl+Shift+S')
        self.export.setStatusTip('Export flow to image')
        self.export.triggered.connect(self.exportFlow)

        self.exit = QAction(self.loadIcon('application-exit'), 'Exit', self)
        self.exit.setShortcut('Ctrl+Q')
        self.exit.setStatusTip('Exit application')
        self.exit. triggered.connect(self.close)

        self.start = QAction(self.loadIcon('media-playback-start'), 'Start', self)
        self.start.setShortcut('Ctrl+R')
        self.start.setStatusTip('Start flow')
        self.start.triggered.connect(self.startFlow)

        self.stop = QAction(self.loadIcon('media-playback-stop'), 'Stop', self)
        self.stop.setShortcut('Ctrl+S')
        self.stop.setStatusTip('Stop running flow')
        self.stop.triggered.connect(self.stopFlow)
        self.stop.setEnabled(False)

    def updateSavedState(self):
        self.updateTitle()
        self.save.setEnabled(self.flow.modified)
        self.asked = False

    def adjustView(self):
        self.view.setSceneRect(self.scene.itemsBoundingRect())

    def center(self):
        screen = QDesktopWidget().screenGeometry()
        size =  self.geometry()
        self.move((screen.width()-size.width())/2, (screen.height()-size.height())/2)

    def buildMenuToolbar(self):
        """
        Wait for more families of actions to install menubar
        menubar = self.menuBar()
        file = menubar.addMenu('&Flow')
        file.addAction(self.new)
        file.addAction(self.open)
        file.addAction(self.save)
        file.addAction(self.exit)
        """
        toolbar = self.addToolBar('Main')
        toolbar.addAction(self.new)
        toolbar.addAction(self.open)
        toolbar.addAction(self.save)
        toolbar.addAction(self.export)

        toolbar.addSeparator()
        toolbar.addAction(self.start)
        toolbar.addAction(self.stop)

        toolbar.addSeparator()
        toolbar.addAction(self.exit)

    def FlowCLIArguments(self, argsnames):
        """
        Build a dialog to allow entering CLI args
        required to start flow.
        @type argsnames : list of string
        """
        dialog = QDialog()
        dialog.setWindowTitle("Enter command-line arguments")
        # Form widget
        form = {}
        formlayout = QFormLayout()
        for argname in argsnames:
            edit = QLineEdit()
            form[argname] = edit
            formlayout.addRow(argname, edit)
        formwidget = QWidget()
        formwidget.setLayout(formlayout)
        # Ok / Cancel
        box = QDialogButtonBox()
        box.addButton(QDialogButtonBox.Ok)
        box.addButton(QDialogButtonBox.Cancel)
        box.accepted.connect(dialog.accept)
        box.rejected.connect(dialog.reject)
        vlayout = QVBoxLayout()
        vlayout.addWidget(formwidget)
        vlayout.addWidget(box)
        # Show dialog
        dialog.setLayout(vlayout)
        answer = dialog.exec_()
        userentries = {}
        for name, edit in form.items():
            txt = edit.text()
            if not empty(txt):
                userentries[name] = txt
        return answer, userentries

    @classmethod
    def messageException(cls, excType, excValue, tracebackobj):
        errmsg = u"%s: %s" % (str(excType), str(excValue))
        tbinfo = traceback2str(tracebackobj)

        logger.debug(errmsg + "\n" + tbinfo)

        if excType is KeyboardInterrupt:
            sys.exit(errno.EINTR)

        errorbox = QMessageBox()
        errorbox.setWindowTitle(_(u"Internal Error"))
        errorbox.setIcon(QMessageBox.Critical)
        errorbox.setText(_(u"An unhandled exception occurred."))
        errorbox.setInformativeText(errmsg)
        errorbox.setDetailedText(tbinfo)
        errorbox.exec_()

    @classmethod
    def messageCancelSaveDiscard(cls, title, mainText, infoText):
        msgBox = QMessageBox()
        msgBox.setWindowTitle(title)
        msgBox.setIcon(QMessageBox.Question)
        msgBox.setText(mainText)
        msgBox.setInformativeText(infoText)
        msgBox.setStandardButtons(QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        msgBox.setDefaultButton(QMessageBox.Save)
        return msgBox.exec_()

    @classmethod
    def messageYesNo(cls, title, mainText, infoText):
        msgBox = QMessageBox()
        msgBox.setWindowTitle(title)
        msgBox.setIcon(QMessageBox.Question)
        msgBox.setText(mainText)
        msgBox.setInformativeText(infoText)
        msgBox.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msgBox.setDefaultButton(QMessageBox.Yes)
        return msgBox.exec_()

    @classmethod
    def messageCancelYesNo(cls, title, mainText, infoText):
        msgBox = QMessageBox()
        msgBox.setWindowTitle(title)
        msgBox.setIcon(QMessageBox.Question)
        msgBox.setText(mainText)
        msgBox.setInformativeText(infoText)
        msgBox.setStandardButtons(QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
        msgBox.setDefaultButton(QMessageBox.Yes)
        return msgBox.exec_()

    """
    
    Scene events
    
    """

    def _diagramItemSelected(self, item):
        if not item.isSelected():
            self.parameters.load(item)
        else:
            self.parameters.clear()

    def _diagramItemMoved(self, item):
        # Set graphical properties (positions, etc)
        pos = item.scenePos()
        if item.node.applyPosition(pos.x(), pos.y()):
            logger.debug("Main window: diagram item moved : {}".format(item))
        self.updateSavedState()

    def _diagramItemChanged(self, item):
        """
        Emitted by {ParameterEditor}
        """
        logger.debug("Main window: diagram item changed : {}".format(item))
        self.updateSavedState()

    def _diagramItemCreated(self, item):
        logger.debug("Main window: diagram item created : %s" % item)
        self.flow.addNode(item.node)
        self.updateSavedState()

    def _diagramItemRemoved(self, item):
        logger.debug("Main window: diagram item removed : {}".format(item))
        self.flow.removeNode(item.node)
        self.updateSavedState()

    def _connectorCreated(self, connector):
        logger.debug("Main window: diagram connector created : {}".format(connector))
        start = connector.startItem.interface
        end = connector.endItem.interface
        self.flow.addConnector(start, end)
        # Update start nodes states
        self.scene.setStartNodes(self.flow.startNodes)
        self.updateSavedState()

    def _connectorRemoved(self, connector):
        logger.debug("Main window: diagram connector removed : {}".format(connector))
        assert connector.startItem is not None
        assert connector.endItem is not None
        start = connector.startItem.interface
        end = connector.endItem.interface
        self.flow.removeConnector(start, end)
        # Update start nodes states
        self.scene.setStartNodes(self.flow.startNodes)
        self.updateSavedState()

    """
    
    Main events
    
    """

    def closeEvent(self, event):
        """
        Close the window.
        """
        # Ask to save if flow was modified
        if self.flow.modified:
            answer = self.messageCancelSaveDiscard(u"Save flow ?",
                                                   "The flow has been modified.",
                                                   "Do you want to save your changes?")
            if answer == QMessageBox.Save:
                if not self.saveFlow():
                    event.ignore() # Was not saved, don't close
                    return
            if answer == QMessageBox.Cancel:
                event.ignore() # Don't close
                return
        # Really quit
        self.savePreferences()
        event.accept()

    def newFlow(self):
        """
        Start a new flow
        """
        # Ask to save if flow was modified
        if self.flow is not None:
            if self.flow.modified:
                answer = self.messageCancelYesNo("Save flow ?",
                                                 "The flow has been modified.",
                                                 "Do you want to save your changes?")
                if answer == QMessageBox.Yes:
                    if not self.saveFlow():
                        return # Was not saved, don't clear.
                if answer == QMessageBox.Cancel:
                    return # Don't clear
        self.flow = Flow()
        self.scene.clear()
        self.parameters.clear()
        self.console.clear()
        self.updateSavedState()

    def loadFlow(self, filename=None):
        """
        Load a flow from a file.
        """
        if not filename:
            # Ask to save if flow was modified
            if self.flow is not None:
                if self.flow.modified:
                    answer = self.messageCancelYesNo("Save flow ?",
                                                     "The flow has been modified.",
                                                     "Do you want to save your changes?")
                    if answer == QMessageBox.Yes:
                        if not self.saveFlow():
                            return # Was not saved, don't open.
                    if answer == QMessageBox.Cancel:
                        return # Don't open
            # Ask the user
            filename, _ = QFileDialog.getOpenFileName(self, 'Open file', self.basedir)
            print(filename)
            if filename == '': # User clicked cancel
                return

        print(filename)
        logger.debug("Load file '%s'..." % filename)
        self.basedir = os.path.dirname(filename)
        self.flow = Flow.load(filename)
        self.scene.clear()
        self.parameters.clear()
        self.console.clear()
        # Switch to console tab
        self.maintabs.setCurrentIndex(0)

        # Add graphical items
        for i, n in enumerate(self.flow.nodes):
            posx = n.graphicalprops.get('x', 50 * i)
            posy = n.graphicalprops.get('y', 50 * i)
            pos = QPointF(posx, posy)
            diagramitem = self.scene.addDiagramItem(pos=pos, node=n, emit=False)
        # Add connectors
        for n in self.flow.nodes:
            for interface in n.interfaces:
                startitem = self.scene.findDiagramItemByNode(n)
                startslot = startitem.findSlot(interface)
                for successor in interface.successors:
                    enditem = self.scene.findDiagramItemByNode(successor.node)
                    endslot = enditem.findSlot(successor)
                    self.scene.addConnector(startslot, endslot, emit=False)
        # Adjust view
        self.adjustView()
        # Update save buttons
        self.updateSavedState()

    def saveFlow(self, flow=None):
        """
        Save a flow to a file
        """
        if not flow:
            flow = self.flow
        # Ask the user if never saved
        if flow.filename is None:
            ask, _ = QFileDialog.getSaveFileName(self, 'Save file', self.basedir)
            if not ask: # User clicked cancel
                return False
            flow.filename = ask
        logger.debug(u"Save file '%s'..." % flow.filename)
        flow.save()
        self.updateSavedState()
        return True

    def exportFlow(self):
        """
        Export the flow to an image
        """
        PADDING = 15
        # Ask filename to user
        filename, _ = QFileDialog.getSaveFileName(self, 'Export image', self.basedir)
        if not filename:  # User clicked cancel
            return False
        logger.debug(u"Export flow to image '%s'..." % filename)
        # Compute scene rect
        sourceRect = self.scene.itemsBoundingRect()
        sourceRect.adjust(-PADDING, -PADDING, PADDING, PADDING)
        targetRect = QRectF(QPointF(), sourceRect.size())
        # Initialize painting
        image = QImage(targetRect.size().toSize(), QImage.Format_ARGB32_Premultiplied)
        image.fill(qRgba(0, 0, 0, 0))  # fill whole image + padding
        painter = QPainter(image)
        # TODO
        #painter.initFrom(self.view)
        painter.setBackgroundMode(Qt.TransparentMode)
        # Draw scene content
        self.scene.clearSelection()
        self.scene.render(painter, target=targetRect, source=QRectF(sourceRect.toRect()))
        # Draw flow filename in upper left corner
        painter.drawText(QRectF(1, 1, targetRect.size().width(), PADDING), self.filename)
        image.save(filename)
        painter.end()

    def startFlow(self):
        """
        Run current flow
        """
        flow = self.flow
        if flow.modified and not self.asked:
            answer = MainWindow.messageCancelYesNo("Save flow before execution ?",
                                                   "The flow has been modified.",
                                                   "Do you want to save your changes?")
            if answer == QMessageBox.Yes:
                self.saveFlow(flow)
            elif answer == QMessageBox.Cancel:
                logger.debug("Flow start canceled by user.")
                return
            else:
                self.asked = True  # Only ask once.
        # If no explicit save, use temp file
        self.tmpfile = tempfile.NamedTemporaryFile('w')
        if self.asked:
            flow = flow.clone()
            flow.filename = self.tmpfile.name
            flow.save()

        # Switch to console tab
        self.maintabs.setCurrentIndex(1)

        if len(flow.nodes) == 0:
            return  # why ?

        # Ask for args if any
        userargs = {}
        cliargs  = [n.name.value for n in flow.CLIParameterNodes() \
                                    if  len(n.name.predecessors) == 0 \
                                    and n.name.value is not None]
        if len(cliargs) > 0:
            logger.debug("CLI args required : {}".format(', '.join(cliargs)))
            answer, userargs = self.FlowCLIArguments(cliargs)
            if answer == QDialog.Rejected:
                logger.debug("Flow start canceled by user.")
                self.tmpfile.close()  # Delete temp file since unnecessary
                return

        self.setStatusMessage("Flow is now running.", 0)  # no timeout
        # Disable widgets
        self.start.setEnabled(False)
        self.stop.setEnabled(True)
        # Lock edition
        self.scene.view.setEnabled(False)
        self.parameters.setEnabled(False)
        self.nodelibrary.setEnabled(False)

        # Create process
        self.process = QProcess()
        self.console.attachProcess(self.process)
        self.process.readyReadStandardOutput.connect(self.console.updateConsole)
        self.process.readyReadStandardError.connect(self.console.updateConsole)
        # TODO: (int, QProcess::ExitStatus)
        self.process.finished.connect(self.onFinishedFlow)

        # Run command
        cmd = florun.build_exec_cmd(flow, self.console.loglevel(), userargs)
        logger.debug("Start command '{}'".format(cmd))
        self.process.start(cmd)
        # check if command-line error...
        if not self.process.waitForStarted():
            raise Exception("Could not execute flow : {} : {}".format(cmd, self.process.error()))

    def stopFlow(self):
        """
        Stop current flow
        """
        # Interrupt running thread
        self.process.kill()

    def onFinishedFlow(self, exitCode, exitStatus):
        """
        @type exitCode : int
        @type exitStatus : L{QProcess.ExitStatus}
        """
        if exitStatus == QProcess.NormalExit:
            msg = "Flow execution finished ({})".format(exitCode)
        else:
            msg = "Flow execution interrupted by user."
        logger.debug(msg)
        self.setStatusMessage(msg)
        self.tmpfile.close()  # Delete flow temp file
        # Reinitialize GUI
        self.console.detachProcess()
        self.process = None
        self.start.setEnabled(True)
        self.stop.setEnabled(False)
        # Unlock edition
        self.scene.view.setEnabled(True)
        self.parameters.setEnabled(True)
        self.nodelibrary.setEnabled(True)


def main(args, filename=None):
    app = QApplication(args)
    # Internationalization : Install file according to current locale
    translator = QTranslator()
    locale = QLocale.system().name()
    if translator.load(os.path.join(florun.locale_dir, '%s' % locale, "gui")):
        app.installTranslator(translator)
    else:
        logger.warning("Could not install translator for locale '%s'" % locale)
    # Build window
    mainWindow = MainWindow(filename)
    mainWindow.show()
    # Replace system exception hook with GUI
    sys.excepthook = mainWindow.messageException
    # Qt Main loop
    return app.exec_()

if __name__ == "__main__":
    main(sys.argv)
