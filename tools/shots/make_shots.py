"""Renders the README / website screenshots and the demo frames.

Run inside 3ds Max through tools/make_shots.ps1 (3dsmaxbatch). Builds a demo
scene, opens the real panel and saves it at 2x through QWidget.render, so
nothing is captured from the screen. Output goes to %LM_OUT%:

  panel-dark.png, panel-light.png, search-dark.png, search-light.png
  demo/<theme>-NN.png + demo/demo.json   (slides of the website carousel
                                          and their captions)
"""
import json
import os
import time
import traceback

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

from pymxs import runtime as rt

SRC = os.environ["LM_SRC"]
OUT = os.environ["LM_OUT"]
SCALE = 2
SIZE = QtCore.QSize(380, 600)

# layer -> (colour, parent, [(object name, kind), ...])
SCENE = [
    ("Architecture", (120, 144, 156), None, []),
    ("Walls", (176, 190, 197), "Architecture",
     [("Wall_North", "box"), ("Wall_South", "box"), ("Wall_East", "box"), ("Wall_West", "box")]),
    ("Floors", (161, 136, 127), "Architecture", [("Floor_Oak", "box"), ("Ceiling", "box")]),
    ("Windows", (79, 195, 247), "Architecture",
     [("Window_01", "box"), ("Window_02", "box"), ("Window_03", "box")]),
    ("Furniture", (255, 183, 77), None, [("Bookshelf", "box"), ("Sideboard", "box")]),
    ("Seating", (255, 138, 101), "Furniture",
     [("Armchair_01", "group"), ("Armchair_02", "group"), ("Sofa_Main", "box"),
      ("Stool_Bar", "cyl")]),
    ("Tables", (220, 231, 117), "Furniture", [("Table_Coffee", "box"), ("Table_Dining", "box")]),
    ("Lighting", (255, 241, 118), None,
     [("Sun_Key", "light"), ("Lamp_Floor", "light"), ("Lamp_Pendant_01", "light"),
      ("Lamp_Pendant_02", "light")]),
    ("Cameras", (186, 104, 200), None,
     [("Cam_Living_Wide", "camera"), ("Cam_Detail_Sofa", "camera")]),
    ("Decor", (129, 199, 132), None,
     [("Plant_Monstera", "box"), ("Vase_Ceramic", "cyl"), ("Rug_Wool", "box"),
      ("Books_Stack", "box"), ("Lamp_Table", "light")]),
    ("Proxies", (144, 164, 174), None, []),
]


def pump(ms=0):
    app = QtWidgets.QApplication.instance()
    end = time.time() + ms / 1000.0
    app.processEvents()
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def make_node(name, kind):
    if kind == "light":
        return [rt.Omnilight(name=name)]
    if kind == "camera":
        return [rt.Freecamera(name=name)]
    if kind == "cyl":
        return [rt.Cylinder(name=name)]
    if kind == "group":
        parts = [rt.Box(name=name + "_seat"), rt.Box(name=name + "_back")]
        head = rt.group(parts, name=name)
        return parts + [head]
    return [rt.Box(name=name)]


def build_scene():
    rt.resetMaxFile(rt.name("noPrompt"))
    manager = rt.LayerManager
    for name, color, parent, objects in SCENE:
        layer = manager.newLayerFromName(name)
        layer.wireColor = rt.color(*color)
        if parent:
            layer.setParent(manager.getLayerFromName(parent))
        for obj_name, kind in objects:
            for node in make_node(obj_name, kind):
                layer.addNode(node)
    manager.getLayerFromName("Furniture").current = True
    manager.getLayerFromName("Proxies").on = False
    manager.getLayerFromName("Cameras").isFrozen = True
    rt.clearSelection()


def save(panel, name):
    pump(60)
    image = QtGui.QImage(panel.size() * SCALE, QtGui.QImage.Format_ARGB32_Premultiplied)
    image.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(image)
    painter.scale(SCALE, SCALE)
    try:        # an exception with a live painter takes Max down with it
        panel.render(painter, QtCore.QPoint())
    finally:
        painter.end()
    path = os.path.join(OUT, name)
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    image.save(path)


class Stage(object):
    """Drives the panel and records the demo steps."""

    def __init__(self, main):
        self.main = main
        self.panel = main.layer_manager
        self.steps = []

    def set_theme(self, dark):
        self.panel._theme_mode = "dark" if dark else "light"
        self.panel.apply_theme()

    def row(self, layer_name, obj=None):
        row = self.panel._find_layer_row(layer_name)
        if obj is None:
            return row
        for i in range(row.childCount()):
            if row.child(i).text(0) == obj:
                return row.child(i)
        raise KeyError(obj)

    def point(self, row, zone):
        """Centre of a row zone in panel coordinates."""
        tree = self.panel.tree
        rect = tree.visualItemRect(row)
        zones = tree.delegate.zones(rect, row)
        if zone == "name":
            p = QtCore.QPoint(zones["name"].left() + 28, rect.center().y())
        else:
            p = zones[zone].center()
        p = tree.viewport().mapTo(self.panel, p)
        return [p.x(), p.y()]

    def widget_point(self, widget):
        p = widget.mapTo(self.panel, widget.rect().center())
        return [p.x(), p.y()]

    def reset(self):
        panel = self.panel
        panel.search_input.setText("")
        panel._filter = ""
        panel._expanded.clear()
        build_scene()
        panel.refresh()
        panel.tree.setCurrentItem(None)
        panel._status_timer.stop()
        panel._show_summary()
        pump(450)       # lets the search box finish fading its clear button out

    def click(self, row, zone):
        modifiers = QtCore.Qt.NoModifier
        if zone == "name":
            self.panel.tree.setCurrentItem(row)
            self.panel.on_item_clicked(row, 0)
        else:
            self.panel.on_zone_clicked(row, zone, modifiers)
        pump(250)


def demo(stage, theme):
    """The scripted tour. Every step: pointer target, caption, resulting frame."""
    panel = stage.panel
    stage.reset()
    frames = []

    def quiet():
        panel._status_timer.stop()
        panel._show_summary()

    def frame(caption):
        name = "demo/{}-{:02d}.png".format(theme, len(frames))
        save(panel, name)
        frames.append({"image": os.path.basename(name), "caption": caption})

    # Each slide shows a different state, so no two look alike.
    frame("Every layer of the scene, nested layers included")

    stage.click(stage.row("Furniture"), "chevron")
    stage.click(stage.row("Seating"), "chevron")
    stage.click(stage.row("Seating", "Armchair_02"), "lock")
    stage.click(stage.row("Seating", "Sofa_Main"), "name")
    quiet()
    frame("Open a layer and click an object to select it")

    stage.reset()
    stage.click(stage.row("Architecture"), "chevron")
    panel.isolate_layer("Architecture")
    pump(250)
    panel.tree.setCurrentItem(stage.row("Architecture"))
    quiet()
    frame("Alt+click the eye to isolate a layer")

    stage.reset()
    panel.search_input.setText("lamp")
    pump(600)
    quiet()
    frame("Search finds layers and objects by name")

    stage.reset()
    stage.click(stage.row("Lighting"), "chevron")
    stage.click(stage.row("Lighting"), "freeze")
    stage.click(stage.row("Decor"), "eye")
    row = stage.row("Decor")
    panel.tree.setCurrentItem(row)
    panel.tree.editItem(row, 0)
    pump(250)
    editor = panel.tree.findChild(QtWidgets.QLineEdit)
    if editor is not None:
        editor.setText("Decor and plants")
        editor.end(False)
    quiet()
    frame("Hide, freeze and rename right in the list")
    if editor is not None:
        panel.tree.closeEditor(editor, QtWidgets.QAbstractItemDelegate.RevertModelCache)
    pump(100)
    return frames


def brand(main):
    """icon-256.png and og.png (1200x630 social card) for the website."""
    def tile(painter, rect):
        gradient = QtGui.QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0, QtGui.QColor("#35d0f2"))
        gradient.setColorAt(1, QtGui.QColor("#0b8fb3"))
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(gradient)
        radius = rect.width() * 0.23
        painter.drawRoundedRect(rect, radius, radius)
        inset = rect.width() * 0.2
        main.draw_icon(painter, "layers", rect.adjusted(inset, inset, -inset, -inset),
                       "#ffffff", 1.9)

    icon = QtGui.QImage(256, 256, QtGui.QImage.Format_ARGB32_Premultiplied)
    icon.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(icon)
    try:
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        tile(painter, QtCore.QRectF(8, 8, 240, 240))
    finally:
        painter.end()
    icon.save(os.path.join(OUT, "icon-256.png"))

    card = QtGui.QImage(1200, 630, QtGui.QImage.Format_RGB32)
    card.fill(QtGui.QColor("#0f1115"))
    shot = QtGui.QImage(os.path.join(OUT, "panel-dark.png"))
    painter = QtGui.QPainter(card)
    try:
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        glow = QtGui.QRadialGradient(950, 260, 520)
        glow.setColorAt(0, QtGui.QColor(44, 198, 234, 70))
        glow.setColorAt(1, QtGui.QColor(44, 198, 234, 0))
        painter.fillRect(card.rect(), glow)

        target = QtCore.QRectF(760, 70, 380, 600)
        path = QtGui.QPainterPath()
        path.addRoundedRect(target, 14, 14)
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 40), 2))
        painter.drawPath(path)
        painter.setClipPath(path)
        painter.drawImage(target, shot)
        painter.setClipping(False)

        tile(painter, QtCore.QRectF(80, 96, 72, 72))
        font = QtGui.QFont("Segoe UI")
        font.setPixelSize(30)
        font.setWeight(QtGui.QFont.DemiBold)
        painter.setFont(font)
        painter.setPen(QtGui.QColor("#ededf0"))
        painter.drawText(QtCore.QRectF(172, 96, 500, 72),
                         QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, "Layer Manager")
        font.setPixelSize(64)
        painter.setFont(font)
        painter.drawText(QtCore.QRectF(80, 220, 640, 240),
                         QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft | QtCore.Qt.TextWordWrap,
                         "Scene layers,\none click away.")
        font.setPixelSize(27)
        font.setWeight(QtGui.QFont.Normal)
        painter.setFont(font)
        painter.setPen(QtGui.QColor("#9aa1ad"))
        painter.drawText(QtCore.QRectF(80, 430, 620, 120),
                         QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft | QtCore.Qt.TextWordWrap,
                         "A free, open-source layer panel for Autodesk 3ds Max.")
    finally:
        painter.end()
    card.save(os.path.join(OUT, "og.png"))


def run():
    import __main__
    build_scene()
    rt.python.ExecuteFile(SRC)
    stage = Stage(__main__)
    panel = stage.panel
    panel.resize(SIZE)
    pump(100)

    manifest = {"width": SIZE.width(), "height": SIZE.height(), "themes": {}}
    for theme, dark in (("dark", True), ("light", False)):
        stage.set_theme(dark)

        # hero shot: a lived-in state
        stage.reset()
        stage.click(stage.row("Furniture"), "chevron")
        stage.click(stage.row("Seating"), "chevron")
        stage.click(stage.row("Seating", "Armchair_02"), "lock")
        stage.click(stage.row("Seating", "Stool_Bar"), "eye")
        stage.click(stage.row("Seating", "Sofa_Main"), "name")
        panel._status_timer.stop()
        panel._show_summary()
        save(panel, "panel-{}.png".format(theme))

        # search shot
        stage.reset()
        panel.search_input.setText("lamp")
        pump(500)
        panel._status_timer.stop()
        panel._show_summary()
        save(panel, "search-{}.png".format(theme))

        manifest["themes"][theme] = demo(stage, theme)

    with open(os.path.join(OUT, "demo", "demo.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)
    panel.close()
    brand(__main__)


status = "ok"
try:
    run()
except Exception:
    status = traceback.format_exc()
with open(os.path.join(OUT, "make_shots.log"), "w") as fh:
    fh.write(status)
