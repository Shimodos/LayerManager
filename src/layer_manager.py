"""
Layer Manager for 3ds Max  (a0.012)

Floating Qt panel to manage scene layers:
  - live tree of all layers (nested layers included) with object counts
  - layers expand to show their objects; clicking an object selects it
    in the scene (objects are tracked by anim handle, not by name)
  - per-row visibility (hide) and freeze toggles, for layers and objects
  - group lock: opens / closes groups (per object, or all groups of a
    layer at once)
  - layer colour swatch (click to change the layer wire colour)
  - search box filtering layers and objects by name
  - select all objects of a layer / move current selection into a layer
  - create (also nested), rename and delete layers, isolate a layer
  - set the current (active) layer
  - follows the 3ds Max UI theme (dark / light)
  - all destructive ops wrapped in a single undo step (Ctrl+Z friendly)

The panel reacts to the scene in real time (layer / node creation, deletion,
renaming, hiding, freezing, file open, scene reset) via 3ds Max callbacks with
a debounce timer. Layer properties have no callback of their own in 3ds Max,
so a cheap poll of the layer list covers changes made in other tools.

Works with PySide2 (3ds Max 2021 - 2024) and PySide6 (3ds Max 2025+).
"""

import os
import time

try:                                      # 3ds Max 2025+
    from PySide6 import QtCore, QtGui, QtWidgets, QtSvg
except ImportError:                         # 3ds Max 2021 - 2024
    from PySide2 import QtCore, QtGui, QtWidgets, QtSvg

import qtmax
import pymxs
from pymxs import runtime as rt

VERSION = "a0.012"
CALLBACK_ID = "layer_manager_callback"
OBJECT_NAME = "ADToolsLayerManager"
DEFAULT_LAYER = "0"                         # built-in layer that can't be renamed/deleted
MAX_OBJECT_ROWS = 2000                      # rows shown per expanded layer
MAX_TRACKED_SELECTION = 3000                # larger selections are not marked row by row
POLL_INTERVAL_MS = 800
ROW_HEIGHT = 26

Qt = QtCore.Qt


# ---------------------------------------------------------------------------
# Themes
# ---------------------------------------------------------------------------
DARK = {
    "window": "#1f2125", "titlebar": "#17181b", "surface": "#262930",
    "hover": "#2f333b", "border": "#363a42", "text": "#e7e9ec",
    "text_dim": "#a3a9b3", "text_faint": "#6c727d", "icon_off": "#4d535d",
    "accent": "#2cc6ea", "accent_hover": "#55d4f2", "accent_pressed": "#1fa7c8",
    "accent_text": "#04222b", "select": "#1d4250", "pill": "#343841",
    "button": "#2d3138", "button_hover": "#383d46", "frozen": "#6cb6ff",
    "warn": "#f5a524", "danger": "#e5484d", "scroll": "#444a54",
}
LIGHT = {
    "window": "#f3f4f6", "titlebar": "#e6e8eb", "surface": "#ffffff",
    "hover": "#eef1f4", "border": "#d8dbe0", "text": "#1d2126",
    "text_dim": "#555c68", "text_faint": "#959ca7", "icon_off": "#c2c7ce",
    "accent": "#0aa3c6", "accent_hover": "#0cb3d9", "accent_pressed": "#0889a6",
    "accent_text": "#ffffff", "select": "#d3f1f8", "pill": "#eaecef",
    "button": "#ffffff", "button_hover": "#eef1f4", "frozen": "#2f7fe0",
    "warn": "#b86e00", "danger": "#d13438", "scroll": "#c5cad1",
}
T = dict(DARK)                              # active theme, see apply_theme()


def max_is_dark():
    """True when the 3ds Max UI uses a dark colour scheme."""
    try:
        c = rt.colorMan.getColor(rt.name("background"))
        return (c.x + c.y + c.z) / 3.0 < 0.5
    except Exception:
        return True


def themed(css):
    """Replace @token@ placeholders with colours of the active theme."""
    for key, value in T.items():
        css = css.replace("@" + key + "@", value)
    return css


STYLESHEET = """
QWidget#root { background-color: @window@; }
QLabel { color: @text@; font: 12px "Segoe UI"; background: transparent; }
QLabel#status { color: @text_faint@; font: 11px "Segoe UI"; }
QLineEdit {
    background-color: @surface@; color: @text@;
    border: 1px solid @border@; border-radius: 7px;
    padding: 5px 8px; min-height: 18px; font: 12px "Segoe UI";
    selection-background-color: @accent@; selection-color: @accent_text@;
}
QLineEdit:hover { border: 1px solid @text_faint@; }
QLineEdit:focus { border: 1px solid @accent@; }
QTreeWidget {
    background-color: @surface@; border: 1px solid @border@;
    border-radius: 8px; padding: 3px; color: @text@;
    font: 12px "Segoe UI"; outline: none;
}
QTreeWidget::item { border: none; }
QTreeWidget QLineEdit {
    border: 1px solid @accent@; border-radius: 4px; padding: 0 4px; min-height: 0;
}
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: @scroll@; border-radius: 3px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: @text_faint@; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QPushButton {
    background-color: @button@; color: @text@;
    border: 1px solid @border@; border-radius: 7px;
    padding: 6px 12px; font: 12px "Segoe UI";
}
QPushButton:hover { background-color: @button_hover@; border: 1px solid @text_faint@; }
QPushButton:pressed { background-color: @hover@; }
QPushButton#accent {
    background-color: @accent@; border: 1px solid @accent@;
    color: @accent_text@; font: 600 12px "Segoe UI";
}
QPushButton#accent:hover { background-color: @accent_hover@; border: 1px solid @accent_hover@; }
QPushButton#accent:pressed { background-color: @accent_pressed@; }
QPushButton#tool { padding: 0; min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; }
"""

MENU_STYLE = """
QMenu {
    background-color: @surface@; color: @text@;
    border: 1px solid @border@; border-radius: 8px;
    padding: 5px; font: 12px "Segoe UI";
}
QMenu::item { padding: 6px 24px 6px 12px; border-radius: 5px; }
QMenu::item:selected { background-color: @select@; color: @text@; }
QMenu::item:disabled { color: @text_faint@; }
QMenu::separator { height: 1px; background: @border@; margin: 5px 6px; }
"""

TITLEBAR_STYLE = """
QWidget#titlebar { background-color: @titlebar@; }
QLabel#title { color: @text@; font: 600 12px "Segoe UI"; background: transparent; }
QLabel#version { color: @text_faint@; font: 11px "Segoe UI"; background: transparent; }
QPushButton { border: none; background: transparent; border-radius: 5px; }
QPushButton:hover { background-color: @hover@; }
QPushButton#close:hover { background-color: @danger@; }
"""


# ---------------------------------------------------------------------------
# Vector icons (24x24 stroke icons, drawn with QtSvg so they stay sharp)
# ---------------------------------------------------------------------------
ICONS = {
    "eye": '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/>'
           '<circle cx="12" cy="12" r="3"/>',
    "eye_off": '<path d="M3 3l18 18"/>'
               '<path d="M10.6 5.1c.5-.1.9-.1 1.4-.1 6.4 0 10 7 10 7s-1.1 2.2-3.2 4.1"/>'
               '<path d="M6.6 6.6C3.6 8.5 2 12 2 12s3.6 7 10 7c1.7 0 3.200-.5 4.500-1.200"/>'
               '<path d="M9.900 9.900a3 3 0 0 0 4.200 4.200"/>',
    "snow": '<path d="M12 2v20M3.300 7l17.400 10M20.700 7L3.300 17"/>'
            '<path d="M9.500 3.500L12 6l2.500-2.500M9.500 20.500L12 18l2.500 2.500"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/>'
            '<path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "unlock": '<rect x="5" y="11" width="14" height="10" rx="2"/>'
              '<path d="M8 11V7a4 4 0 0 1 7.600-1.700"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "refresh": '<path d="M20 11a8 8 0 0 0-14.300-4.300L4 8.500"/><path d="M4 4v4.500h4.500"/>'
               '<path d="M4 13a8 8 0 0 0 14.300 4.300L20 15.500"/><path d="M20 20v-4.500h-4.500"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.500-3.500"/>',
    "chev_right": '<path d="M9 6l6 6-6 6"/>',
    "chev_down": '<path d="M6 9l6 6 6-6"/>',
    "expand": '<path d="M7 15l5 5 5-5M7 9l5-5 5 5"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2'
           'M4.900 4.900l1.400 1.400M17.700 17.700l1.400 1.400M19.100 4.900l-1.400 1.400'
           'M6.300 17.700l-1.400 1.400"/>',
    "moon": '<path d="M21 12.800A9 9 0 1 1 11.200 3a7 7 0 0 0 9.800 9.800z"/>',
    "layers": '<path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M3 12l9 5 9-5"/>'
              '<path d="M3 16l9 5 9-5"/>',
    "cursor": '<path d="M5 3l14 7-6 2-2 6L5 3z"/>',
    "move_in": '<path d="M4 12h11M11 7l5 5-5 5"/><path d="M20 4v16"/>',
    # object kinds
    "geometry": '<path d="M21 8l-9-5-9 5v8l9 5 9-5V8z"/><path d="M3 8l9 5 9-5M12 13v8"/>',
    "group": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5'
             'a2 2 0 0 1-2-2V7z"/>',
    "light": '<circle cx="12" cy="12" r="4"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3'
             'M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/>',
    "camera": '<rect x="2" y="7" width="13" height="10" rx="2"/><path d="M15 11l7-4v10l-7-4"/>',
    "shape": '<path d="M3 17c3-12 6-12 9-5s6 7 9-5"/>',
    "helper": '<path d="M12 3v18M3 12h18"/><circle cx="12" cy="12" r="4"/>',
}
SVG_TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="{color}" stroke-width="{width}" stroke-linecap="round" '
    'stroke-linejoin="round">{body}</svg>'
)
_renderers = {}


def svg_renderer(name, color, width=2.0):
    key = (name, color, width)
    renderer = _renderers.get(key)
    if renderer is None:
        data = SVG_TEMPLATE.format(color=color, width=width, body=ICONS[name])
        renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(data.encode("utf-8")))
        _renderers[key] = renderer
    return renderer


def draw_icon(painter, name, rect, color, width=2.0):
    svg_renderer(name, color, width).render(painter, QtCore.QRectF(rect))


def make_icon(name, color, size=16):
    """QIcon for buttons; rendered oversized so it stays crisp on HiDPI."""
    scale = 4
    pixmap = QtGui.QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    svg_renderer(name, color).render(
        painter, QtCore.QRectF(0, 0, size * scale, size * scale))
    painter.end()
    return QtGui.QIcon(pixmap)


def run_menu(menu, pos):
    """QMenu.exec was renamed between PySide2 and PySide6."""
    runner = getattr(menu, "exec", None) or getattr(menu, "exec_")
    return runner(pos)


# ---------------------------------------------------------------------------
# MAXScript helpers: whole-scene scans run natively instead of node by node
# ---------------------------------------------------------------------------
rt.execute(
    "fn lm_group_heads = (for o in objects where isGroupHead o collect o)\n"
    "fn lm_find_nodes pat = (for o in objects where matchPattern o.name pattern:pat collect o)"
)


def node_from_handle(handle):
    node = rt.GetAnimByHandle(handle) if handle else None
    if node is None or not rt.isValidNode(node):
        return None
    return node


def group_family(node):
    """The node itself; for a group head also every member, nested groups
    included. Hiding or freezing only the head leaves the group on screen,
    because the head is just the dummy that holds the members."""
    nodes = [node]
    if rt.isGroupHead(node):
        stack = list(node.children)
        while stack:
            child = stack.pop()
            if rt.isGroupMember(child):
                nodes.append(child)
                stack.extend(list(child.children))
    return nodes


def node_kind(node):
    """Icon name for an object row."""
    try:
        if rt.isGroupHead(node):
            return "group"
        cls = rt.superClassOf(node)
        if cls == rt.light:
            return "light"
        if cls == rt.camera:
            return "camera"
        if cls == rt.shape:
            return "shape"
        if cls == rt.helper:
            return "helper"
    except Exception:
        pass
    return "geometry"


# ---------------------------------------------------------------------------
# Tree rows
# ---------------------------------------------------------------------------
class Row(QtWidgets.QTreeWidgetItem):
    """One tree row: a layer, an object, or the 'N more' note."""
    LAYER, OBJECT, MORE = 0, 1, 2

    def __init__(self, kind):
        super(Row, self).__init__()
        self.kind = kind
        self.index_text = ""
        self.layer_name = None      # layers: own name; objects: owning layer
        self.handle = None          # objects: anim handle of the scene node
        self.depth = 0
        self.visible = True
        self.frozen = False
        self.current = False
        self.color = None           # layers: QColor of the layer wire colour
        self.count = 0              # layers: number of objects
        self.child_layers = 0
        self.populated = False      # layers: object rows have been created
        self.group = None           # None | "open" | "closed"
        self.icon = "geometry"
        self.scene_selected = False # objects: selected in the scene right now

    @property
    def expandable(self):
        return self.kind == Row.LAYER and (self.count > 0 or self.child_layers > 0)


ACTION_ZONES = ("chevron", "color", "eye", "freeze", "lock")


class RowDelegate(QtWidgets.QStyledItemDelegate):
    """Paints rows by hand: number, chevron, swatch / kind icon, name, count
    badge and the hide / freeze / group toggles."""

    def __init__(self, tree):
        super(RowDelegate, self).__init__(tree)
        self.tree = tree

    def sizeHint(self, option, index):
        return QtCore.QSize(120, ROW_HEIGHT)

    def zones(self, rect, row):
        """Rectangles of the clickable / painted parts of a row."""
        top, h = rect.top(), rect.height()
        right = rect.right() - 5
        z = {}
        for key in ("lock", "freeze", "eye"):
            z[key] = QtCore.QRect(right - 22, top, 22, h)
            right -= 22
        left = rect.left() + 4
        z["index"] = QtCore.QRect(left, top, 22, h)
        left += 26 + row.depth * 14
        z["chevron"] = QtCore.QRect(left, top, 16, h)
        left += 17
        z["color"] = QtCore.QRect(left, top, 16, h)
        left += 21
        z["name"] = QtCore.QRect(left, top, max(10, right - left - 4), h)
        return z

    def zone_at(self, rect, row, pos):
        if row.kind == Row.MORE:
            return "name"
        z = self.zones(rect, row)
        if row.expandable and z["chevron"].contains(pos):
            return "chevron"
        if row.kind == Row.LAYER and z["color"].contains(pos):
            return "color"
        if z["eye"].contains(pos):
            return "eye"
        if z["freeze"].contains(pos):
            return "freeze"
        if row.group and z["lock"].contains(pos):
            return "lock"
        return "name"

    def tooltip(self, row, zone):
        if zone == "eye":
            return "Visible - click to hide" if row.visible else "Hidden - click to show"
        if zone == "freeze":
            return "Frozen - click to unfreeze" if row.frozen else "Click to freeze"
        if zone == "color":
            return "Layer colour - click to change"
        if zone == "lock":
            if row.kind == Row.LAYER:
                return "Click to {} all groups in this layer".format(
                    "close" if row.group == "open" else "open")
            return ("Open group - click to close" if row.group == "open"
                    else "Closed group - click to open")
        if row.kind == Row.LAYER and row.current:
            return "{} (current layer)".format(row.layer_name)
        return ""

    def helpEvent(self, event, view, option, index):
        if event.type() == QtCore.QEvent.ToolTip:
            row = self.tree.itemFromIndex(index)
            if row is not None:
                text = self.tooltip(row, self.zone_at(option.rect, row, event.pos()))
                if text:
                    QtWidgets.QToolTip.showText(event.globalPos(), text, view)
                    return True
            QtWidgets.QToolTip.hideText()
            return True
        return super(RowDelegate, self).helpEvent(event, view, option, index)

    def paint(self, painter, option, index):
        row = self.tree.itemFromIndex(index)
        if row is None:
            return
        rect = option.rect
        selected = bool(option.state & QtWidgets.QStyle.State_Selected)
        hover = bool(option.state & QtWidgets.QStyle.State_MouseOver)

        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        body = QtCore.QRectF(rect.adjusted(1, 1, -1, -1))
        if selected or row.scene_selected:
            # Filled: the highlighted row and every object selected in the scene.
            painter.setPen(Qt.NoPen)
            painter.setBrush(QtGui.QColor(T["select"]))
            painter.drawRoundedRect(body, 5, 5)
        if selected:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QtGui.QColor(T["accent"]))
            painter.drawRoundedRect(
                QtCore.QRectF(body.left(), body.top() + 5, 3, body.height() - 10), 1.5, 1.5)
        elif hover:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QtGui.QColor(T["hover"]))
            painter.drawRoundedRect(body, 5, 5)

        font = QtGui.QFont(option.font)
        small = QtGui.QFont(font)
        small.setPixelSize(10)
        z = self.zones(rect, row)
        cy = rect.center().y()

        if row.kind == Row.MORE:
            painter.setFont(font)
            painter.setPen(QtGui.QColor(T["text_faint"]))
            painter.drawText(z["name"], Qt.AlignLeft | Qt.AlignVCenter, row.text(0))
            painter.restore()
            return

        # row number
        painter.setFont(small)
        painter.setPen(QtGui.QColor(T["text_faint"]))
        painter.drawText(z["index"], Qt.AlignRight | Qt.AlignVCenter, row.index_text)

        # expand chevron
        if row.expandable:
            c = z["chevron"]
            draw_icon(painter, "chev_down" if row.isExpanded() else "chev_right",
                      QtCore.QRect(c.left() + 2, cy - 5, 12, 12), T["text_dim"], 2.4)

        # layer colour swatch / object kind icon
        s = z["color"]
        if row.kind == Row.LAYER:
            painter.setPen(Qt.NoPen)
            painter.setBrush(row.color or QtGui.QColor(T["text_faint"]))
            painter.drawRoundedRect(QtCore.QRectF(s.left() + 2, cy - 5, 11, 11), 3, 3)
        else:
            draw_icon(painter, row.icon, QtCore.QRect(s.left() + 1, cy - 6, 13, 13),
                      T["text_faint"] if row.visible else T["icon_off"])

        # toggles on the right
        def toggle(zone, name, color):
            r = z[zone]
            draw_icon(painter, name,
                      QtCore.QRect(r.center().x() - 6, cy - 6, 14, 14), color)

        toggle("eye", "eye" if row.visible else "eye_off",
               T["text_dim"] if row.visible else T["icon_off"])
        toggle("freeze", "snow", T["frozen"] if row.frozen else T["icon_off"])
        if row.group:
            toggle("lock", "unlock" if row.group == "open" else "lock",
                   T["warn"] if row.group == "open" else T["text_dim"])

        # name, 'current' marker and count badge share the middle
        name_rect = QtCore.QRect(z["name"])
        painter.setFont(small)
        small_fm = painter.fontMetrics()

        if row.kind == Row.LAYER:
            text = str(row.count)
            w = small_fm.horizontalAdvance(text) + 12
            badge = QtCore.QRectF(name_rect.right() - w, cy - 7.5, w, 16)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QtGui.QColor(T["pill"]))
            painter.drawRoundedRect(badge, 8, 8)
            painter.setPen(QtGui.QColor(T["text_dim"] if row.count else T["text_faint"]))
            painter.drawText(badge, Qt.AlignCenter, text)
            name_rect.setRight(int(badge.left()) - 6)

        name_font = QtGui.QFont(font)
        name_font.setBold(row.kind == Row.LAYER and row.current)
        painter.setFont(name_font)
        fm = painter.fontMetrics()
        marker_w = 0
        if row.kind == Row.LAYER and row.current:
            marker_w = small_fm.horizontalAdvance("current") + 12 + 6
        text = fm.elidedText(row.text(0), Qt.ElideRight,
                             max(10, name_rect.width() - marker_w))
        if not row.visible:
            color = T["text_faint"]
        elif row.kind == Row.LAYER:
            color = T["text"]
        else:
            color = T["text_dim"]
        painter.setPen(QtGui.QColor(color))
        painter.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter, text)

        if marker_w:
            x = name_rect.left() + fm.horizontalAdvance(text) + 6
            pill = QtCore.QRectF(x, cy - 7.5, marker_w - 6, 16)
            accent = QtGui.QColor(T["accent"])
            fill = QtGui.QColor(accent)
            fill.setAlpha(46)
            painter.setPen(Qt.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(pill, 8, 8)
            painter.setFont(small)
            painter.setPen(accent)
            painter.drawText(pill, Qt.AlignCenter, "current")

        painter.restore()

    # -- in-place rename editor -------------------------------------------
    def createEditor(self, parent, option, index):
        editor = super(RowDelegate, self).createEditor(parent, option, index)
        if editor is not None:
            # Otherwise typed letters fire 3ds Max keyboard shortcuts.
            qtmax.DisableMaxAcceleratorsOnFocus(editor, True)
        return editor

    def updateEditorGeometry(self, editor, option, index):
        row = self.tree.itemFromIndex(index)
        if row is None:
            editor.setGeometry(option.rect)
            return
        r = self.zones(option.rect, row)["name"]
        editor.setGeometry(r.adjusted(-5, 2, 0, -2))


class LayerTree(QtWidgets.QTreeWidget):
    """Single-column tree; clicks on the toggle zones are reported through
    zoneClicked instead of changing the highlighted row."""
    zoneClicked = QtCore.Signal(object, str, object)
    keyAction = QtCore.Signal(str)

    def __init__(self, parent=None):
        super(LayerTree, self).__init__(parent)
        self.delegate = RowDelegate(self)
        self.setItemDelegate(self.delegate)
        self.setColumnCount(1)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setUniformRowHeights(True)
        self.setExpandsOnDoubleClick(False)
        self.setMouseTracking(True)
        self.viewport().setAttribute(Qt.WA_Hover, True)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self._pressed = None

    def is_editing(self):
        return self.state() == QtWidgets.QAbstractItemView.EditingState

    def _zone(self, pos):
        row = self.itemAt(pos)
        if row is None:
            return None, None
        return row, self.delegate.zone_at(self.visualItemRect(row), row, pos)

    def mousePressEvent(self, event):
        self._pressed = None
        if event.button() == Qt.LeftButton:
            row, zone = self._zone(event.pos())
            if zone in ACTION_ZONES:
                self._pressed = (row, zone)
                event.accept()
                return
        super(LayerTree, self).mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        row, zone = self._zone(event.pos())
        if zone in ACTION_ZONES:            # fast repeated toggles
            self.mousePressEvent(event)
            return
        super(LayerTree, self).mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        if self._pressed is not None:
            row, zone = self._pressed
            self._pressed = None
            now_row, now_zone = self._zone(event.pos())
            if now_row is row and now_zone == zone:
                self.zoneClicked.emit(row, zone, event.modifiers())
            event.accept()
            return
        super(LayerTree, self).mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if not self.is_editing():
            key = event.key()
            if key == Qt.Key_F2:
                self.keyAction.emit("rename")
                return
            if key == Qt.Key_Right:
                self.keyAction.emit("expand")
                return
            if key == Qt.Key_Left:
                self.keyAction.emit("collapse")
                return
        super(LayerTree, self).keyPressEvent(event)


# ---------------------------------------------------------------------------
# Custom title bar
# ---------------------------------------------------------------------------
class CustomDockWidgetTitleBar(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super(CustomDockWidgetTitleBar, self).__init__(parent)
        self.setObjectName("titlebar")
        self.setFixedHeight(32)
        self.setAutoFillBackground(True)
        # A plain QWidget subclass ignores stylesheet backgrounds without this.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._collapsed = False

        self.logo = QtWidgets.QLabel()
        self.logo.setFixedSize(16, 16)
        self.logo.setScaledContents(True)

        self.titleLabel = QtWidgets.QLabel("Layer Manager")
        self.titleLabel.setObjectName("title")
        self.versionLabel = QtWidgets.QLabel(VERSION)
        self.versionLabel.setObjectName("version")

        self.theme_button = QtWidgets.QPushButton()
        self.theme_button.setCursor(Qt.PointingHandCursor)
        self.theme_button.setFixedSize(26, 24)
        self.theme_button.setIconSize(QtCore.QSize(14, 14))
        self.theme_button.clicked.connect(self.parentWidget().toggle_theme)

        self.minimize_button = QtWidgets.QPushButton()
        self.minimize_button.setCursor(Qt.PointingHandCursor)
        self.minimize_button.setFixedSize(26, 24)
        self.minimize_button.setIconSize(QtCore.QSize(14, 14))
        self.minimize_button.clicked.connect(self.parentWidget().toggle_collapsed)

        self.close_button = QtWidgets.QPushButton()
        self.close_button.setObjectName("close")
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.setToolTip("Close")
        self.close_button.setFixedSize(26, 24)
        self.close_button.setIconSize(QtCore.QSize(14, 14))
        self.close_button.clicked.connect(self.parentWidget().close)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 4, 0)
        layout.setSpacing(6)
        layout.addWidget(self.logo)
        layout.addWidget(self.titleLabel)
        layout.addWidget(self.versionLabel)
        layout.addStretch()
        layout.addWidget(self.theme_button)
        layout.addWidget(self.minimize_button)
        layout.addWidget(self.close_button)

        self.apply_theme()

    def apply_theme(self):
        self.setStyleSheet(themed(TITLEBAR_STYLE))
        self.logo.setPixmap(make_icon("layers", T["accent"]).pixmap(64, 64))
        self.close_button.setIcon(make_icon("close", T["text_dim"]))
        # The button shows the theme a click switches to.
        dark = T["window"] == DARK["window"]
        self.theme_button.setIcon(make_icon("sun" if dark else "moon", T["text_dim"]))
        self.theme_button.setToolTip(
            "Switch to the light theme" if dark else "Switch to the dark theme")
        self.set_collapsed(self._collapsed)

    def set_collapsed(self, collapsed):
        """Flip the minimize glyph between roll-up and roll-down."""
        self._collapsed = collapsed
        self.minimize_button.setIcon(
            make_icon("plus" if collapsed else "minus", T["text_dim"]))
        self.minimize_button.setToolTip("Expand panel" if collapsed else "Collapse panel")


# ---------------------------------------------------------------------------
# Main dock widget
# ---------------------------------------------------------------------------
class LayerManagerDockWidget(QtWidgets.QDockWidget):
    def __init__(self, parent=None):
        super(LayerManagerDockWidget, self).__init__(parent)
        self.setWindowFlags(Qt.Tool)
        self.setWindowTitle("Layer Manager {}".format(VERSION))
        self.setAttribute(Qt.WA_DeleteOnClose)

        self._populating = False
        self._filter = ""
        self._expanded = set()              # layer names the user expanded
        self._signature = None              # last seen layer state, see _poll
        # Timestamp of the last object click inside the panel; selection-sync
        # is suppressed for a short window after it (see update_layer_selection).
        self._panel_select_time = 0.0
        self._selected_handles = set()      # anim handles selected in the scene
        # "auto" follows the 3ds Max colour scheme; the title bar button
        # switches to an explicit "dark" / "light" and that choice is kept.
        self._theme_mode = load_theme_mode()

        # Roll-up state (Qt::Tool windows have no real minimize -- see toggle_collapsed)
        self._collapsed = False
        self._expanded_size = QtCore.QSize(380, 560)
        self._expanded_pos = None
        self._saved_min_height = 0
        self._saved_max_height = 16777215

        # Debounce timer: coalesces bursts of scene callbacks into one refresh.
        self._refresh_timer = QtCore.QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(150)
        self._refresh_timer.timeout.connect(self._refresh_from_timer)

        # Search box debounce.
        self._filter_timer = QtCore.QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(200)
        self._filter_timer.timeout.connect(self._apply_filter)

        # 3ds Max has no callback for layer property changes (hide, freeze,
        # rename, current layer, colour), so compare a cheap snapshot instead.
        self._poll_timer = QtCore.QTimer(self)
        self._poll_timer.setInterval(POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll)

        # Status messages fade back to the summary line.
        self._status_timer = QtCore.QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(5000)
        self._status_timer.timeout.connect(self._show_summary)

        self.initUI()
        self.setTitleBarWidget(CustomDockWidgetTitleBar(self))
        self.apply_theme()
        self.create_connections()
        self.refresh()
        self._sync_scene_selection()
        self._poll_timer.start()

    # -- UI -----------------------------------------------------------------
    def initUI(self):
        root = QtWidgets.QWidget()
        root.setObjectName("root")
        self._root = root

        main_layout = QtWidgets.QVBoxLayout(root)
        main_layout.setContentsMargins(10, 10, 10, 8)
        main_layout.setSpacing(8)

        # --- Search + tools row ---
        top_row = QtWidgets.QHBoxLayout()
        top_row.setSpacing(6)

        self.search_input = QtWidgets.QLineEdit(self)
        self.search_input.setPlaceholderText("Search layers and objects")
        self.search_input.setClearButtonEnabled(True)
        # Otherwise typed letters fire 3ds Max keyboard shortcuts.
        qtmax.DisableMaxAcceleratorsOnFocus(self.search_input, True)
        self.search_input.textChanged.connect(lambda _text: self._filter_timer.start())
        # QAction lives in QtWidgets (PySide2) or QtGui (PySide6). It is created
        # here with a parent: the one returned by addAction(icon, position)
        # loses its C++ object under PySide2.
        action_class = getattr(QtGui, "QAction", None) or QtWidgets.QAction
        self._search_action = action_class(self.search_input)
        self.search_input.addAction(
            self._search_action, QtWidgets.QLineEdit.LeadingPosition)
        top_row.addWidget(self.search_input, 1)

        self.new_btn = self._tool_button("New layer", self.create_layer)
        self.expand_btn = self._tool_button("Expand / collapse all layers",
                                            self.toggle_expand_all)
        self.refresh_btn = self._tool_button("Refresh", self.refresh)
        for btn in (self.new_btn, self.expand_btn, self.refresh_btn):
            top_row.addWidget(btn)
        main_layout.addLayout(top_row)

        # --- Layer tree ---
        self.tree = LayerTree(self)
        self.tree.itemClicked.connect(self.on_item_clicked)
        self.tree.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.tree.itemChanged.connect(self.on_item_changed)
        self.tree.zoneClicked.connect(self.on_zone_clicked)
        self.tree.keyAction.connect(self.on_key_action)
        self.tree.customContextMenuRequested.connect(self.open_context_menu)
        main_layout.addWidget(self.tree, 1)

        # --- Action row ---
        action_row = QtWidgets.QHBoxLayout()
        action_row.setSpacing(6)

        self.select_btn = QtWidgets.QPushButton("Select Objects")
        self.select_btn.setCursor(Qt.PointingHandCursor)
        self.select_btn.setToolTip("Select all objects in the highlighted layer")
        self.select_btn.clicked.connect(self.select_layer_objects)
        action_row.addWidget(self.select_btn, 1)

        self.move_btn = QtWidgets.QPushButton("Move Selection Here")
        self.move_btn.setObjectName("accent")
        self.move_btn.setCursor(Qt.PointingHandCursor)
        self.move_btn.setToolTip("Move the current scene selection into the highlighted layer")
        self.move_btn.clicked.connect(self.add_to_layer)
        action_row.addWidget(self.move_btn, 1)
        main_layout.addLayout(action_row)

        # --- Status ---
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setObjectName("status")
        main_layout.addWidget(self.status_label)

        self.setWidget(root)
        self.setMinimumSize(300, 320)
        self.resize(380, 560)

        focus_search = QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+F"), self) \
            if hasattr(QtWidgets, "QShortcut") else QtGui.QShortcut(
                QtGui.QKeySequence("Ctrl+F"), self)
        focus_search.setContext(Qt.WidgetWithChildrenShortcut)
        focus_search.activated.connect(self.search_input.setFocus)
        self._focus_search = focus_search

    def _tool_button(self, tooltip, slot):
        btn = QtWidgets.QPushButton()
        btn.setObjectName("tool")
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setIconSize(QtCore.QSize(16, 16))
        btn.clicked.connect(slot)
        return btn

    def apply_theme(self):
        """Pick the palette (the user's choice, else the one matching the
        3ds Max UI) and restyle everything."""
        if self._theme_mode in ("dark", "light"):
            dark = self._theme_mode == "dark"
        else:
            dark = max_is_dark()
        T.clear()
        T.update(DARK if dark else LIGHT)
        self.setStyleSheet(themed("QDockWidget { background-color: @window@; }"))
        self._root.setStyleSheet(themed(STYLESHEET))
        self._search_action.setIcon(make_icon("search", T["text_faint"]))
        self.new_btn.setIcon(make_icon("plus", T["text"]))
        self.expand_btn.setIcon(make_icon("expand", T["text"]))
        self.refresh_btn.setIcon(make_icon("refresh", T["text"]))
        self.select_btn.setIcon(make_icon("cursor", T["text"]))
        self.move_btn.setIcon(make_icon("move_in", T["accent_text"]))
        title_bar = self.titleBarWidget()
        if title_bar is not None:
            title_bar.apply_theme()
        self.tree.viewport().update()

    def toggle_theme(self):
        """Title bar button: switch between the dark and the light palette."""
        dark_now = T["window"] == DARK["window"]
        self._theme_mode = "light" if dark_now else "dark"
        save_theme_mode(self._theme_mode)
        self.apply_theme()

    def showEvent(self, event):
        super(LayerManagerDockWidget, self).showEvent(event)
        round_window_corners(self)

    def toggle_collapsed(self):
        """Roll the panel up into its title bar and back.

        A floating QDockWidget is a Qt::Tool window, which has no real minimize
        button, so collapsing to the title bar is the workable equivalent.
        """
        body = self.widget()
        if body is None:
            return
        title_bar = self.titleBarWidget()
        bar_height = title_bar.height() if title_bar is not None else 32

        if self._collapsed:
            body.show()
            self.setMinimumHeight(self._saved_min_height)
            self.setMaximumHeight(self._saved_max_height)
            self.resize(self._expanded_size)
            if self._expanded_pos is not None:
                self.move(self._expanded_pos)
            self._collapsed = False
            self.request_refresh()
        else:
            self._expanded_size = self.size()
            self._expanded_pos = self.pos()
            self._saved_min_height = self.minimumHeight()
            self._saved_max_height = self.maximumHeight()
            body.hide()
            # Fixing both bounds forces the window to shrink to the bar itself.
            self.setMinimumHeight(bar_height)
            self.setMaximumHeight(bar_height)
            self.resize(self.width(), bar_height)
            self._snap_to_main_bottom()
            self._collapsed = True

        if title_bar is not None:
            title_bar.set_collapsed(self._collapsed)

    def _snap_to_main_bottom(self):
        """Park the collapsed bar on the bottom edge of the Max main window.

        Both windows are top level, so frameGeometry is in desktop coordinates
        and already includes the native frame.
        """
        main_win = self.parentWidget()
        if main_win is None:
            return
        area = main_win.frameGeometry()
        frame = self.frameGeometry()

        y = area.bottom() - frame.height() + 1
        # Keep the bar inside the main window horizontally.
        right_limit = max(area.left(), area.right() - frame.width() + 1)
        x = min(max(self.x(), area.left()), right_limit)
        self.move(x, y)

    # -- Max callbacks ------------------------------------------------------
    def create_connections(self):
        """Register Max callbacks so the panel tracks the scene live."""
        # Callbacks run their script in __main__; publish the bridges there so
        # they resolve no matter how this file was loaded.
        import __main__
        __main__.layer_manager_on_selection_changed = layer_manager_on_selection_changed
        __main__.layer_manager_request_refresh = layer_manager_request_refresh
        __main__.layer_manager_theme_changed = layer_manager_theme_changed

        rt.callbacks.removeScripts(id=rt.name(CALLBACK_ID))

        refresh = "layer_manager_request_refresh()"
        events = {
            "selectionSetChanged": "layer_manager_on_selection_changed()",
            "colorChanged":        "layer_manager_theme_changed()",
        }
        for event in ("layerCreated", "layerDeleted", "layerParentChanged",
                      "nodeCreated", "nodePostDelete", "nodeLayerChanged",
                      "nodeRenamed", "nodeHide", "nodeUnhide", "nodeFreeze",
                      "nodeUnfreeze", "filePostOpen", "filePostMerge",
                      "postImport", "systemPostNew", "systemPostReset",
                      "sceneUndo", "sceneRedo"):
            events[event] = refresh
        for event, fn in events.items():
            try:
                rt.callbacks.addScript(
                    rt.name(event),
                    'python.execute "{}"'.format(fn),
                    id=rt.name(CALLBACK_ID),
                )
            except Exception as e:
                print("Layer Manager: skipped callback '{}' ({})".format(event, e))

    def request_refresh(self):
        """Called from Max callbacks; debounced to avoid refresh storms."""
        self._refresh_timer.start()

    def _busy(self):
        """True while a rebuild would pull the rug from under the user."""
        return self.tree.is_editing() or self.tree._pressed is not None

    def _refresh_from_timer(self):
        if self._collapsed:
            return                          # refreshed again on expand
        if self._busy():
            self._refresh_timer.start()
            return
        self.refresh()

    def _poll(self):
        if self._collapsed or not self.isVisible() or self._busy():
            return
        try:
            signature = self._scan_layers()[1]
        except Exception:
            return
        if signature != self._signature:
            self.refresh()

    # -- Data / rendering ---------------------------------------------------
    def _scan_layers(self):
        """Read every layer once -> ([info dict, ...], comparable signature)."""
        infos, signature = [], []
        manager = rt.LayerManager
        for i in range(manager.count):
            layer = manager.getLayer(i)
            parent = layer.getParent()
            color = layer.wireColor
            info = {
                "layer": layer,
                "name": str(layer.name),
                "parent": str(parent.name) if parent is not None else None,
                "visible": bool(layer.on),
                "frozen": bool(layer.isFrozen),
                "current": bool(layer.current),
                "count": int(layer.getNumNodes()),
                "color": (int(color.r), int(color.g), int(color.b)),
            }
            infos.append(info)
            signature.append((info["name"], info["parent"], info["visible"],
                              info["frozen"], info["current"], info["count"],
                              info["color"]))
        return infos, signature

    def _group_states(self):
        """{layer name: 'open' | 'closed'} for layers that contain groups."""
        states = {}
        for head in rt.lm_group_heads():
            try:
                name = str(head.layer.name)
                is_open = bool(rt.isOpenGroupHead(head))
            except Exception:
                continue
            if is_open or name not in states:
                states[name] = "open" if is_open else "closed"
        return states

    def _layer_nodes(self, layer):
        ok, nodes = layer.nodes(pymxs.byref(None))
        return list(nodes) if ok and nodes is not None else []

    def _layer_rows(self):
        """All layer rows, depth first."""
        out = []

        def walk(item):
            for i in range(item.childCount()):
                child = item.child(i)
                if child.kind == Row.LAYER:
                    out.append(child)
                    walk(child)
        walk(self.tree.invisibleRootItem())
        return out

    def _find_layer_row(self, layer_name):
        if layer_name is None:
            return None
        target = str(layer_name).lower()    # layer names are case-insensitive
        for row in self._layer_rows():
            if row.layer_name.lower() == target:
                return row
        return None

    def _current_key(self):
        row = self.tree.currentItem()
        if row is None:
            return None
        if row.kind == Row.OBJECT:
            return ("object", row.handle, row.layer_name)
        return ("layer", row.layer_name, row.layer_name)

    def refresh(self):
        """Rebuild the tree, keeping highlight, expansion and scroll position."""
        tree = self.tree
        if tree is None:
            return
        self._refresh_timer.stop()

        current = self._current_key()
        scroll = tree.verticalScrollBar().value()
        infos, self._signature = self._scan_layers()
        groups = self._group_states()

        # Search: which objects match, grouped by layer.
        matches = None
        needle = self._filter
        if needle:
            matches = {}
            for node in rt.lm_find_nodes("*" + needle + "*"):
                try:
                    matches.setdefault(str(node.layer.name), []).append(node)
                except Exception:
                    continue

        self._populating = True
        tree.setUpdatesEnabled(False)
        tree.clear()

        rows = {}
        for info in infos:
            row = Row(Row.LAYER)
            row.layer_name = info["name"]
            row.setText(0, info["name"])
            flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
            if info["name"] != DEFAULT_LAYER:
                flags |= Qt.ItemIsEditable
            row.setFlags(flags)
            row.visible = info["visible"]
            row.frozen = info["frozen"]
            row.current = info["current"]
            row.count = info["count"]
            row.color = QtGui.QColor(*info["color"])
            row.group = groups.get(info["name"])
            rows[info["name"]] = row

        for info in infos:                  # parents can come after children
            row = rows[info["name"]]
            parent = rows.get(info["parent"]) if info["parent"] else None
            if parent is not None and parent is not row:
                parent.addChild(row)
                parent.child_layers += 1
            else:
                tree.addTopLevelItem(row)

        def number(item, depth):
            n = 0
            for i in range(item.childCount()):
                child = item.child(i)
                n += 1
                child.index_text = str(n)
                child.depth = depth
                number(child, depth + 1)
        number(tree.invisibleRootItem(), 0)

        if matches is None:
            known = set(rows)
            self._expanded &= known         # forget layers that are gone
            for name in self._expanded:
                self._populate_objects(rows[name])
                rows[name].setExpanded(True)
        else:
            self._apply_matches(rows, matches, needle.lower())

        self._populating = False
        tree.setUpdatesEnabled(True)

        self._restore_current(current)
        tree.verticalScrollBar().setValue(scroll)
        self._mark_selected_rows()
        self._summary = self._make_summary(infos, matches)
        if not self._status_timer.isActive():
            self._show_summary()

    def _apply_matches(self, rows, matches, needle):
        """Search mode: show matching layers and the objects that match."""
        def visit(row):
            shown = needle in row.layer_name.lower()
            nodes = matches.get(row.layer_name)
            for i in range(row.childCount()):
                child = row.child(i)
                if child.kind == Row.LAYER and visit(child):
                    shown = True
            if nodes:
                self._populate_objects(row, nodes)
                row.populated = False       # partial list: reload on demand
                shown = True
            if nodes or any(not row.child(i).isHidden()
                            for i in range(row.childCount())):
                row.setExpanded(True)
            row.setHidden(not shown)
            return shown

        for i in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(i))

    def _populate_objects(self, row, nodes=None):
        """(Re)create the object rows of a layer row."""
        for i in reversed(range(row.childCount())):
            if row.child(i).kind != Row.LAYER:
                row.removeChild(row.child(i))

        if nodes is None:
            layer = rt.LayerManager.getLayerFromName(row.layer_name)
            nodes = self._layer_nodes(layer) if layer else []
        nodes = sorted(nodes, key=lambda n: str(n.name).lower())

        was_populating = self._populating
        self._populating = True
        for idx, node in enumerate(nodes[:MAX_OBJECT_ROWS], 1):
            child = Row(Row.OBJECT)
            child.index_text = str(idx)
            child.depth = row.depth + 1
            child.layer_name = row.layer_name
            child.handle = int(rt.GetHandleByAnim(node))
            child.setText(0, str(node.name))
            child.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            child.scene_selected = child.handle in self._selected_handles
            row.addChild(child)
            self._read_object_state(child, node)
        if len(nodes) > MAX_OBJECT_ROWS:
            more = Row(Row.MORE)
            more.depth = row.depth + 1
            more.layer_name = row.layer_name
            more.setText(0, "{} more - use search to find them".format(
                len(nodes) - MAX_OBJECT_ROWS))
            more.setFlags(Qt.ItemIsEnabled)
            row.addChild(more)
        self._populating = was_populating
        row.populated = True

    def _read_object_state(self, row, node):
        row.visible = not bool(node.isHidden)
        row.frozen = bool(node.isFrozen)
        row.icon = node_kind(node)
        if rt.isGroupHead(node):
            row.group = "open" if bool(rt.isOpenGroupHead(node)) else "closed"
        else:
            row.group = None

    def _restore_current(self, key):
        if key is None:
            return
        kind, ident, layer_name = key
        target = None
        layer_row = self._find_layer_row(layer_name)
        if kind == "object" and layer_row is not None:
            for i in range(layer_row.childCount()):
                child = layer_row.child(i)
                if child.kind == Row.OBJECT and child.handle == ident:
                    target = child
                    break
        if target is None:
            target = layer_row
        if target is not None and not target.isHidden():
            self.tree.blockSignals(True)
            self.tree.setCurrentItem(target)
            self.tree.blockSignals(False)

    def _make_summary(self, infos, matches):
        total = sum(info["count"] for info in infos)
        if matches is not None:
            found = sum(len(v) for v in matches.values())
            return "{} object(s) match \"{}\"".format(found, self._filter)
        return "{} layer(s), {} object(s)".format(len(infos), total)

    def _show_summary(self):
        self.status_label.setStyleSheet("")
        self.status_label.setText(getattr(self, "_summary", ""))

    def _apply_filter(self):
        self._filter = self.search_input.text().strip()
        self.refresh()

    def select_layer_row(self, layer_name):
        """Highlight the tree row for a layer by name (no signals)."""
        row = self._find_layer_row(layer_name)
        if row is None or row.isHidden():
            return
        self.tree.blockSignals(True)
        self.tree.setCurrentItem(row)
        self.tree.scrollToItem(row, QtWidgets.QAbstractItemView.EnsureVisible)
        self.tree.blockSignals(False)

    def current_layer_name(self):
        """Name of the highlighted layer (or the layer of the highlighted
        object row), or None."""
        row = self.tree.currentItem() if self.tree else None
        return row.layer_name if row is not None else None

    def _object_rows(self):
        """Every object row currently in the tree."""
        out = []
        for layer_row in self._layer_rows():
            for i in range(layer_row.childCount()):
                child = layer_row.child(i)
                if child.kind == Row.OBJECT:
                    out.append(child)
        return out

    def _sync_scene_selection(self):
        """Remember which nodes are selected in the scene and mark their rows."""
        handles = set()
        sel = rt.selection
        if 0 < sel.count <= MAX_TRACKED_SELECTION:
            try:
                handles = {int(rt.GetHandleByAnim(n)) for n in sel}
            except Exception:
                handles = set()
        self._selected_handles = handles
        self._mark_selected_rows()

    def _mark_selected_rows(self):
        handles = self._selected_handles
        for row in self._object_rows():
            row.scene_selected = row.handle in handles
        self.tree.viewport().update()

    def _primary_selected(self, sel):
        """The node whose row gets the highlight: a selected closed group is
        its head plus all members, and the head is the row that stands for it."""
        try:
            for i in range(min(sel.count, 200)):
                node = sel[i]
                if rt.isGroupHead(node) and not rt.isGroupMember(node):
                    return node
        except Exception:
            pass
        return sel[0]

    def update_layer_selection(self):
        """Follow the scene selection.

        Rows of selected objects are marked in every open layer. The highlight
        moves to the selected object's row when its layer is open, otherwise to
        the layer row. The only exception is a short window right after an
        object was clicked inside the panel: Max fires selectionSetChanged
        several times for that one select(), and without the window the last
        fire would steal the highlight from the clicked object row.
        """
        if self._collapsed:
            return
        self._sync_scene_selection()
        if self._busy():
            return
        sel = rt.selection
        if sel.count == 0:
            return
        if time.time() - self._panel_select_time < 0.5:
            cur = self.tree.currentItem()
            if (cur is not None and cur.kind == Row.OBJECT
                    and cur.handle in self._selected_handles):
                return
        try:
            node = self._primary_selected(sel)
            layer_row = self._find_layer_row(node.layer.name)
            if layer_row is not None and layer_row.isExpanded():
                handle = int(rt.GetHandleByAnim(node))
                for i in range(layer_row.childCount()):
                    child = layer_row.child(i)
                    if (child.kind == Row.OBJECT and child.handle == handle
                            and not child.isHidden()):
                        self.tree.blockSignals(True)
                        self.tree.setCurrentItem(child)
                        self.tree.scrollToItem(
                            child, QtWidgets.QAbstractItemView.EnsureVisible)
                        self.tree.blockSignals(False)
                        return
            self.select_layer_row(node.layer.name)
        except Exception:
            pass

    # -- Row interactions ---------------------------------------------------
    def on_item_clicked(self, row, column):
        if row.kind == Row.OBJECT:
            add = bool(QtWidgets.QApplication.keyboardModifiers() & Qt.ControlModifier)
            self._select_object_row(row, add)

    def on_zone_clicked(self, row, zone, modifiers):
        if zone == "chevron":
            self._toggle_expand(row)
        elif row.kind == Row.OBJECT:
            self._object_cell_clicked(row, zone)
        elif row.kind == Row.LAYER:
            self._layer_cell_clicked(row, zone, modifiers)

    def on_key_action(self, action):
        row = self.tree.currentItem()
        if row is None or row.kind != Row.LAYER:
            return
        if action == "rename":
            self._begin_rename(row)
        elif action == "expand" and row.expandable and not row.isExpanded():
            self._toggle_expand(row)
        elif action == "collapse" and row.isExpanded():
            self._toggle_expand(row)

    def _toggle_expand(self, row):
        if row.kind != Row.LAYER:
            return
        if row.isExpanded():
            row.setExpanded(False)
            self._expanded.discard(row.layer_name)
        else:
            if not row.populated:
                self._populate_objects(row)
            row.setExpanded(True)
            if not self._filter:
                self._expanded.add(row.layer_name)
        self.tree.viewport().update()

    def toggle_expand_all(self):
        rows = [r for r in self._layer_rows() if r.expandable and not r.isHidden()]
        collapse = any(r.isExpanded() for r in rows)
        for row in rows:
            if row.isExpanded() == collapse:
                self._toggle_expand(row)

    def _layer_cell_clicked(self, row, zone, modifiers):
        name = row.layer_name
        layer = rt.LayerManager.getLayerFromName(name)
        if not layer:
            self.request_refresh()
            return
        if zone == "eye":
            if modifiers & Qt.AltModifier:
                self.isolate_layer(name)
            else:
                self._set_layer_visible(layer, not bool(layer.on))
                self.refresh()
        elif zone == "freeze":
            self._set_layer_frozen(layer, not bool(layer.isFrozen))
            self.refresh()
        elif zone == "lock":
            self._toggle_layer_groups(name)
        elif zone == "color":
            self._pick_layer_color(name)

    def _object_cell_clicked(self, row, zone):
        """Toggle hide / freeze / group open state for a single object row."""
        node = node_from_handle(row.handle)
        if node is None:
            self.set_status("Object no longer exists.", warn=True)
            self.request_refresh()
            return
        family = [node]
        what = "Group" if rt.isGroupHead(node) else "Object"
        if zone == "eye":
            family = group_family(node)     # a group is hidden as a whole
            hide = not bool(node.isHidden)
            with pymxs.undo(True, "Hide / unhide object"):
                for n in family:
                    n.isHidden = hide
            self.set_status("{} '{}' {}".format(
                what, node.name, "hidden" if hide else "shown"))
        elif zone == "freeze":
            family = group_family(node)     # ... and frozen as a whole
            freeze = not bool(node.isFrozen)
            with pymxs.undo(True, "Freeze / unfreeze object"):
                for n in family:
                    n.isFrozen = freeze
            self.set_status("{} '{}' {}".format(
                what, node.name, "frozen" if freeze else "unfrozen"))
        elif zone == "lock":
            if not rt.isGroupHead(node):
                return
            with pymxs.undo(True, "Open / close group"):
                rt.setGroupOpen(node, not bool(rt.isOpenGroupHead(node)))
            self.set_status("Group '{}' {}".format(
                node.name, "opened" if rt.isOpenGroupHead(node) else "closed"))
        self._redraw()
        self._read_object_state(row, node)
        if len(family) > 1:
            # Group members have rows of their own; they changed too.
            members = {int(rt.GetHandleByAnim(n)): n for n in family}
            for other in self._object_rows():
                if other is not row and other.handle in members:
                    self._read_object_state(other, members[other.handle])
        if zone == "lock":
            # The layer lock shows the aggregate state -- keep it in sync.
            parent = row.parent()
            if parent is not None:
                parent.group = self._group_states().get(parent.layer_name)
        self.tree.viewport().update()

    def _layer_group_heads(self, layer_name):
        """All group-head nodes that live on the given layer."""
        heads = []
        for n in rt.lm_group_heads():
            try:
                if str(n.layer.name) == layer_name:
                    heads.append(n)
            except Exception:
                continue
        return heads

    def _toggle_layer_groups(self, layer_name):
        """One click drives all groups of a layer to a common state:
        close all if any is open, otherwise open all."""
        heads = self._layer_group_heads(layer_name)
        if not heads:
            self.set_status("Layer '{}' has no groups.".format(layer_name))
            return
        any_open = any(bool(rt.isOpenGroupHead(h)) for h in heads)
        with pymxs.undo(True, "Toggle groups"):
            for h in heads:
                rt.setGroupOpen(h, not any_open)
        self._redraw()
        self.refresh()
        self.set_status("{} group(s) in '{}' {}".format(
            len(heads), layer_name, "closed" if any_open else "opened"))

    def _pick_layer_color(self, layer_name):
        layer = rt.LayerManager.getLayerFromName(layer_name)
        if not layer:
            return
        c = layer.wireColor
        color = QtWidgets.QColorDialog.getColor(
            QtGui.QColor(int(c.r), int(c.g), int(c.b)), self,
            "Layer colour - {}".format(layer_name))
        if not color.isValid():
            return
        with pymxs.undo(True, "Layer colour"):
            layer.wireColor = rt.color(color.red(), color.green(), color.blue())
        self._redraw()
        self.refresh()
        self.set_status("Colour of '{}' changed".format(layer_name))

    def on_item_double_clicked(self, row, column):
        if row.kind == Row.LAYER:
            self._begin_rename(row)

    def _begin_rename(self, row):
        if row.layer_name == DEFAULT_LAYER:
            self.set_status("The default layer '0' cannot be renamed.", warn=True)
            return
        self.tree.editItem(row, 0)

    def on_item_changed(self, row, column):
        """Commit an in-place rename."""
        if self._populating or row.kind != Row.LAYER:
            return
        old = row.layer_name
        new = row.text(0).strip()
        if not new or new == old or old == DEFAULT_LAYER:
            self._revert_name(row, old)
            return
        existing = rt.LayerManager.getLayerFromName(new)
        # Lookup is case-insensitive: 'walls' -> 'Walls' finds the layer itself.
        if existing and new.lower() != old.lower():
            self.set_status("Layer '{}' already exists.".format(new), warn=True)
            self._revert_name(row, old)
            return
        layer = rt.LayerManager.getLayerFromName(old)
        if layer and new.lower() == old.lower():
            # 3ds Max ignores a rename that only changes letter case, so go
            # through a temporary name.
            layer.setName(self._unique_layer_name())
        if layer and layer.setName(new):
            if old in self._expanded:
                self._expanded.discard(old)
                self._expanded.add(new)
            row.layer_name = new
            self.set_status("Renamed '{}' -> '{}'".format(old, new))
            # The editor is still committing: rebuild once it has finished.
            self.request_refresh()
        else:
            self.set_status("Could not rename layer '{}'.".format(old), warn=True)
            self._revert_name(row, old)

    def _revert_name(self, row, name):
        self._populating = True
        row.setText(0, name)
        self._populating = False

    def _select_object_row(self, row, add=False):
        """Select in the scene the node an object row represents."""
        node = node_from_handle(row.handle)
        if node is None:
            self.set_status("Object no longer exists.", warn=True)
            self.request_refresh()
            return
        self._panel_select_time = time.time()
        if add:
            rt.selectMore(node)
        else:
            rt.select(node)
        self._redraw()
        self.set_status("Selected '{}'".format(node.name))

    def _move_object_to_layer(self, handle, layer_name):
        """Move a single object (by anim handle) into another layer."""
        node = node_from_handle(handle)
        if node is None:
            self.set_status("Object no longer exists.", warn=True)
            self.request_refresh()
            return
        layer = rt.LayerManager.getLayerFromName(layer_name)
        if not layer:
            self.set_status("Layer '{}' does not exist.".format(layer_name), warn=True)
            return
        with pymxs.undo(True, "Move to layer"):
            layer.addnode(node)
        self.refresh()
        self.select_layer_row(layer_name)
        self.set_status("Moved '{}' to '{}'".format(node.name, layer_name))

    # -- Context menu -------------------------------------------------------
    def open_context_menu(self, pos):
        row = self.tree.itemAt(pos)
        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet(themed(MENU_STYLE))
        where = self.tree.viewport().mapToGlobal(pos)

        if row is not None and row.kind == Row.MORE:
            return

        if row is not None and row.kind == Row.OBJECT:
            handle = row.handle
            own_layer = row.layer_name
            menu.addAction("Select Object", lambda: self._select_object_row(row))
            move_menu = menu.addMenu("Move to Layer")
            move_menu.setStyleSheet(themed(MENU_STYLE))
            for i in range(rt.LayerManager.count):
                target = str(rt.LayerManager.getLayer(i).name)
                action = move_menu.addAction(
                    target,
                    lambda h=handle, ln=target: self._move_object_to_layer(h, ln))
                if target == own_layer:
                    action.setEnabled(False)
            run_menu(menu, where)
            return

        if row is not None:
            self.tree.setCurrentItem(row)
            name = row.layer_name
            is_default = (name == DEFAULT_LAYER)

            menu.addAction("Select Objects", self.select_layer_objects)
            menu.addAction("Move Selection Here", self.add_to_layer)
            current_action = menu.addAction("Set as Current Layer", self.set_current_layer)
            current_action.setEnabled(not row.current)
            menu.addSeparator()
            menu.addAction("Hide Layer" if row.visible else "Show Layer",
                           self._toggle_visibility)
            menu.addAction("Unfreeze Layer" if row.frozen else "Freeze Layer",
                           self._toggle_freeze)
            menu.addAction("Isolate Layer", lambda: self.isolate_layer(name))
            menu.addAction("Show All Layers", self.show_all_layers)
            menu.addSeparator()
            menu.addAction("New Child Layer", lambda: self.create_layer(parent_name=name))
            if row.parent() is not None:
                menu.addAction("Move to Top Level", lambda: self._unparent_layer(name))
            rename_action = menu.addAction("Rename", lambda: self._begin_rename(row))
            delete_action = menu.addAction("Delete Layer", self.delete_selected_layer)
            if is_default:
                rename_action.setEnabled(False)
                delete_action.setEnabled(False)
        else:
            menu.addAction("New Layer", self.create_layer)
            menu.addAction("Show All Layers", self.show_all_layers)

        run_menu(menu, where)

    # -- Layer state helpers ------------------------------------------------
    def _set_layer_visible(self, layer, visible):
        with pymxs.undo(True, "Hide / show layer"):
            layer.on = visible
        self._redraw()
        self.set_status("Layer '{}' {}".format(layer.name, "shown" if visible else "hidden"))

    def _set_layer_frozen(self, layer, frozen):
        with pymxs.undo(True, "Freeze / unfreeze layer"):
            layer.isFrozen = frozen
        self._redraw()
        self.set_status("Layer '{}' {}".format(layer.name, "frozen" if frozen else "unfrozen"))

    def _toggle_visibility(self):
        name = self.current_layer_name()
        layer = rt.LayerManager.getLayerFromName(name) if name else None
        if layer:
            self._set_layer_visible(layer, not bool(layer.on))
            self.refresh()

    def _toggle_freeze(self):
        name = self.current_layer_name()
        layer = rt.LayerManager.getLayerFromName(name) if name else None
        if layer:
            self._set_layer_frozen(layer, not bool(layer.isFrozen))
            self.refresh()

    def isolate_layer(self, layer_name):
        """Show one layer (with its parents and children) and hide the rest."""
        target = rt.LayerManager.getLayerFromName(layer_name)
        if not target:
            return
        keep = set()
        layer = target
        while layer is not None:            # the layer and its ancestors
            keep.add(str(layer.name).lower())
            layer = layer.getParent()

        def add_children(parent):
            for i in range(1, parent.getNumChildren() + 1):
                child = parent.getChild(i)
                keep.add(str(child.name).lower())
                add_children(child)
        add_children(target)

        manager = rt.LayerManager
        with pymxs.undo(True, "Isolate layer"):
            for i in range(manager.count):
                layer = manager.getLayer(i)
                layer.on = str(layer.name).lower() in keep
        self._redraw()
        self.refresh()
        self.set_status("Isolated layer '{}'".format(layer_name))

    def show_all_layers(self):
        manager = rt.LayerManager
        with pymxs.undo(True, "Show all layers"):
            for i in range(manager.count):
                manager.getLayer(i).on = True
        self._redraw()
        self.refresh()
        self.set_status("All layers shown")

    def _unparent_layer(self, layer_name):
        layer = rt.LayerManager.getLayerFromName(layer_name)
        if not layer:
            return
        with pymxs.undo(True, "Move layer to top level"):
            layer.setParent(rt.undefined)
        self.refresh()
        self.select_layer_row(layer_name)
        self.set_status("Layer '{}' moved to the top level".format(layer_name))

    def _redraw(self):
        try:
            rt.redrawViews()
        except Exception:
            pass

    # -- Actions ------------------------------------------------------------
    def _unique_layer_name(self):
        n = 1
        while True:
            name = "Layer{:03d}".format(n)
            if not rt.LayerManager.getLayerFromName(name):
                return name
            n += 1

    def create_layer(self, checked=False, parent_name=None):
        """Create a layer with a free name and start renaming it in place."""
        layer_name = self._unique_layer_name()
        with pymxs.undo(True, "Create layer"):
            layer = rt.LayerManager.newLayerFromName(layer_name)
            if layer and parent_name:
                parent = rt.LayerManager.getLayerFromName(parent_name)
                if parent:
                    layer.setParent(parent)
        if not layer:
            self.set_status("Could not create a layer.", warn=True)
            return

        if self._filter:                    # the new row must not be filtered out
            self.search_input.blockSignals(True)
            self.search_input.clear()
            self.search_input.blockSignals(False)
            self._filter = ""
        if parent_name:
            self._expanded.add(parent_name)
        self.refresh()
        self.select_layer_row(layer_name)
        self.set_status("Created layer '{}'".format(layer_name))
        row = self._find_layer_row(layer_name)
        if row is not None:
            self.tree.setFocus()
            self.tree.editItem(row, 0)

    def add_to_layer(self):
        sel = rt.selection
        if sel.count == 0:
            self.set_status("No objects selected.", warn=True)
            return
        layer_name = self.current_layer_name()
        if not layer_name:
            self.set_status("Highlight a layer in the list first.", warn=True)
            return
        layer = rt.LayerManager.getLayerFromName(layer_name)
        if not layer:
            self.set_status("Layer '{}' does not exist.".format(layer_name), warn=True)
            return

        moved = 0
        with pymxs.undo(True, "Move to layer"):
            for obj in list(sel):
                layer.addnode(obj)
                if obj.layer == layer:
                    moved += 1
        self.refresh()
        self.select_layer_row(layer_name)
        self.set_status("Moved {} object(s) to '{}'".format(moved, layer_name))

    def select_layer_objects(self):
        layer_name = self.current_layer_name()
        if not layer_name:
            self.set_status("Highlight a layer in the list first.", warn=True)
            return
        layer = rt.LayerManager.getLayerFromName(layer_name)
        if not layer:
            self.set_status("Layer '{}' does not exist.".format(layer_name), warn=True)
            return
        objects = self._layer_nodes(layer)
        self._panel_select_time = time.time()
        if objects:
            rt.select(objects)
        else:
            rt.clearSelection()
        self._redraw()
        self.set_status("Selected {} object(s) in '{}'".format(len(objects), layer_name))

    def set_current_layer(self):
        layer_name = self.current_layer_name()
        layer = rt.LayerManager.getLayerFromName(layer_name) if layer_name else None
        if not layer:
            self.set_status("Highlight a layer in the list first.", warn=True)
            return
        layer.current = True
        self.refresh()
        self.select_layer_row(layer_name)
        self.set_status("Current layer: '{}'".format(layer_name))

    def delete_selected_layer(self):
        layer_name = self.current_layer_name()
        if not layer_name:
            self.set_status("Highlight a layer in the list first.", warn=True)
            return
        if layer_name == DEFAULT_LAYER:
            self.set_status("The default layer '0' cannot be deleted.", warn=True)
            return
        layer = rt.LayerManager.getLayerFromName(layer_name)
        if not layer:
            self.request_refresh()
            return

        nodes = self._layer_nodes(layer)
        children = [layer.getChild(i) for i in range(1, layer.getNumChildren() + 1)]
        details = []
        if nodes:
            details.append("{} object(s) will be moved to layer '{}'.".format(
                len(nodes), DEFAULT_LAYER))
        if children:
            details.append("{} nested layer(s) will move one level up.".format(
                len(children)))
        reply = QtWidgets.QMessageBox.question(
            self, "Delete layer",
            "Delete layer '{}'?\n{}".format(layer_name, "\n".join(details)).strip(),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return

        with pymxs.undo(True, "Delete layer"):
            default_layer = rt.LayerManager.getLayer(0)
            if bool(layer.current):         # can't delete the current layer
                default_layer.current = True
            grandparent = layer.getParent()
            for child in children:          # a layer with children can't be deleted
                child.setParent(grandparent if grandparent is not None else rt.undefined)
            for obj in nodes:
                default_layer.addnode(obj)
            deleted = rt.LayerManager.deleteLayerByName(layer_name)

        self._expanded.discard(layer_name)
        self.refresh()
        if deleted:
            self.set_status("Deleted layer '{}'".format(layer_name))
        else:
            self.set_status("Could not delete layer '{}'.".format(layer_name), warn=True)

    # -- Helpers ------------------------------------------------------------
    def set_status(self, text, warn=False):
        """Show a message in the status line; it falls back to the summary."""
        label = getattr(self, "status_label", None)
        if label is None:
            return
        label.setStyleSheet("color: {};".format(T["warn"]) if warn else
                            "color: {};".format(T["text_dim"]))
        label.setText(text)
        self._status_timer.start()

    def closeEvent(self, event):
        for timer in (self._poll_timer, self._refresh_timer,
                      self._filter_timer, self._status_timer):
            timer.stop()
        rt.callbacks.removeScripts(id=rt.name(CALLBACK_ID))
        save_geometry(self)
        super(LayerManagerDockWidget, self).closeEvent(event)


# ---------------------------------------------------------------------------
# Settings kept between sessions: window position and the chosen theme
# ---------------------------------------------------------------------------
def _settings():
    # LAYER_MANAGER_SETTINGS lets the tests use a store of their own instead
    # of overwriting the user's.
    return QtCore.QSettings(
        "AD Tools", os.environ.get("LAYER_MANAGER_SETTINGS", "LayerManager"))


def load_theme_mode():
    try:
        mode = _settings().value("theme")
    except Exception:
        mode = None
    return mode if mode in ("dark", "light") else "auto"


def save_theme_mode(mode):
    try:
        _settings().setValue("theme", mode)
    except Exception as e:
        print("Layer Manager: could not save the theme ({})".format(e))


def round_window_corners(widget):
    """Ask Windows 11 to round the corners of the floating panel.

    A floating dock with a custom title bar is a frameless window, and DWM
    rounds only natively framed ones unless told otherwise
    (DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWCP_ROUND = 2). Returns the
    HRESULT, or None when the call is unavailable; older Windows just refuses.
    """
    try:
        import ctypes
        preference = ctypes.c_int(2)
        return ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(int(widget.window().winId())), 33,
            ctypes.byref(preference), ctypes.sizeof(preference))
    except Exception:
        return None


def save_geometry(widget):
    try:
        collapsed = widget._collapsed
        size = widget._expanded_size if collapsed else widget.size()
        pos = widget._expanded_pos if collapsed and widget._expanded_pos else widget.pos()
        settings = _settings()
        settings.setValue("size", size)
        settings.setValue("pos", pos)
    except Exception as e:
        print("Layer Manager: could not save window position ({})".format(e))


def restore_geometry(widget):
    try:
        settings = _settings()
        size = settings.value("size")
        pos = settings.value("pos")
        if isinstance(size, QtCore.QSize) and size.isValid():
            widget.resize(size)
        if isinstance(pos, QtCore.QPoint):
            target = QtCore.QRect(pos, widget.size())
            for screen in QtGui.QGuiApplication.screens():
                if screen.availableGeometry().intersects(target):
                    widget.move(pos)
                    break
    except Exception as e:
        print("Layer Manager: could not restore window position ({})".format(e))


# ---------------------------------------------------------------------------
# Module-level bridges for Max callbacks (callbacks can only call globals)
# ---------------------------------------------------------------------------
layer_manager = None


def _alive():
    """The panel, or None when it was never opened or is already closed."""
    panel = layer_manager
    if panel is None:
        return None
    try:
        panel.isVisible()                   # raises once the C++ widget is gone
    except RuntimeError:
        return None
    return panel


def layer_manager_on_selection_changed():
    panel = _alive()
    if panel is not None:
        panel.update_layer_selection()


def layer_manager_request_refresh():
    panel = _alive()
    if panel is not None:
        panel.request_refresh()


def layer_manager_theme_changed():
    panel = _alive()
    if panel is not None:
        panel.apply_theme()


def main():
    global layer_manager
    try:
        main_window = qtmax.GetQMaxMainWindow()
        # Running the script again re-creates the module globals, so look the
        # previous panel up in Qt instead of trusting a Python variable.
        for old in main_window.findChildren(QtWidgets.QDockWidget, OBJECT_NAME):
            try:
                old.close()
            except Exception:
                pass

        layer_manager = LayerManagerDockWidget(parent=main_window)
        layer_manager.setObjectName(OBJECT_NAME)
        layer_manager.setFloating(True)
        restore_geometry(layer_manager)
        layer_manager.show()
        print("Layer Manager {} loaded".format(VERSION))
    except Exception:
        import traceback
        print("Layer Manager failed to start:\n{}".format(traceback.format_exc()))


if __name__ == '__main__':
    main()
