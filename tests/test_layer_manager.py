"""Headless checks for layer_manager.py.

Run inside 3ds Max through tests/run_tests.ps1 (3dsmaxbatch). Builds a small
scene, opens the panel and drives it the way a user would, writing a report
to %LM_OUT%\\report_<max year>.txt and a screenshot next to it.
"""
import os
import sys
import time
import traceback

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

from pymxs import runtime as rt

SRC = os.environ["LM_SRC"]
OUT = os.environ["LM_OUT"]
YEAR = int(list(rt.maxVersion())[7])
REPORT = os.path.join(OUT, "report_{}.txt".format(YEAR))

failed = []
report = open(REPORT, "w", encoding="utf-8")


def log(*args):
    # Flushed line by line: if Max itself dies, the report shows how far we got.
    report.write(" ".join(str(a) for a in args) + "\n")
    report.flush()
    os.fsync(report.fileno())


def check(name, condition, detail=""):
    if condition:
        log("ok    ", name)
    else:
        failed.append(name)
        log("FAIL  ", name, detail)


def pump(ms=0):
    """Let Qt timers and queued events run."""
    app = QtWidgets.QApplication.instance()
    end = time.time() + ms / 1000.0
    app.processEvents()
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def layer(name):
    return rt.LayerManager.getLayerFromName(name)


def build_scene():
    rt.resetMaxFile(rt.name("noPrompt"))
    manager = rt.LayerManager
    walls = manager.newLayerFromName("Walls")
    furniture = manager.newLayerFromName("Furniture")
    chairs = manager.newLayerFromName("Chairs")
    chairs.setParent(furniture)
    lights = manager.newLayerFromName("Lights")
    manager.newLayerFromName("Empty")

    for i in range(3):
        walls.addNode(rt.Box(name="Wall_{:02d}".format(i + 1), pos=rt.Point3(i * 40, 0, 0)))
    furniture.addNode(rt.Box(name="Table"))
    legs = [rt.Cylinder(name="Chair_leg_{}".format(i)) for i in range(2)]
    seat = rt.Box(name="Chair_seat")
    group = rt.group(legs + [seat], name="Chair_group")
    for node in legs + [seat, group]:
        chairs.addNode(node)
    lights.addNode(rt.Omnilight(name="Key_light"))
    lights.addNode(rt.Freecamera(name="Shot_camera"))
    rt.clearSelection()


def run():
    import __main__
    build_scene()
    rt.python.ExecuteFile(SRC)
    panel = getattr(__main__, "layer_manager", None)
    check("panel created", panel is not None)
    if panel is None:
        return
    mod_row = __main__.Row
    no_mod = QtCore.Qt.NoModifier
    pump(50)

    def row(name):
        return panel._find_layer_row(name)

    # --- structure ---------------------------------------------------------
    names = [r.layer_name for r in panel._layer_rows()]
    check("all layers listed", sorted(names) == sorted(
        ["0", "Walls", "Furniture", "Chairs", "Lights", "Empty"]), names)
    check("nested layer under its parent", row("Chairs").parent() is row("Furniture"))
    check("nested depth", row("Chairs").depth == 1 and row("Walls").depth == 0)
    check("object counts", row("Walls").count == 3 and row("Chairs").count == 4
          and row("Empty").count == 0, (row("Walls").count, row("Chairs").count))
    check("empty layer not expandable", not row("Empty").expandable)
    check("parent layer expandable", row("Furniture").expandable)
    check("group state on layer", row("Chairs").group == "closed", row("Chairs").group)
    check("no group marker without groups", row("Walls").group is None)
    check("objects are lazy", row("Walls").childCount() == 0)

    # --- expand / object rows ---------------------------------------------
    panel.on_zone_clicked(row("Walls"), "chevron", no_mod)
    kids = [row("Walls").child(i) for i in range(row("Walls").childCount())]
    check("expand creates object rows",
          [k.text(0) for k in kids] == ["Wall_01", "Wall_02", "Wall_03"],
          [k.text(0) for k in kids])
    panel.on_zone_clicked(row("Lights"), "chevron", no_mod)
    icons = {row("Lights").child(i).text(0): row("Lights").child(i).icon
             for i in range(row("Lights").childCount())}
    check("object kind icons", icons == {"Key_light": "light", "Shot_camera": "camera"}, icons)

    # --- object row actions -------------------------------------------------
    wall = row("Walls").child(0)
    panel.tree.setCurrentItem(wall)
    panel.on_item_clicked(wall, 0)
    check("click selects object", rt.selection.count == 1
          and str(rt.selection[0].name) == "Wall_01")
    pump(700)
    check("highlight stays on clicked object", panel.tree.currentItem() is wall)
    panel.on_zone_clicked(wall, "eye", no_mod)
    check("object hide toggle", bool(rt.getNodeByName("Wall_01").isHidden) and not wall.visible)
    panel.on_zone_clicked(wall, "eye", no_mod)
    panel.on_zone_clicked(wall, "freeze", no_mod)
    check("object freeze toggle", bool(rt.getNodeByName("Wall_01").isFrozen) and wall.frozen)
    panel.on_zone_clicked(wall, "freeze", no_mod)
    pump(300)

    # --- layer toggles ------------------------------------------------------
    panel.on_zone_clicked(row("Walls"), "eye", no_mod)
    check("layer hide toggle", not bool(layer("Walls").on) and not row("Walls").visible)
    check("expansion survives refresh", row("Walls").isExpanded()
          and row("Walls").childCount() == 3)
    panel.on_zone_clicked(row("Walls"), "eye", no_mod)
    panel.on_zone_clicked(row("Walls"), "freeze", no_mod)
    check("layer freeze toggle", bool(layer("Walls").isFrozen) and row("Walls").frozen)
    panel.on_zone_clicked(row("Walls"), "freeze", no_mod)

    panel.on_zone_clicked(row("Chairs"), "lock", no_mod)
    check("layer lock opens groups", bool(rt.isOpenGroupHead(rt.getNodeByName("Chair_group")))
          and row("Chairs").group == "open", row("Chairs").group)
    panel.on_zone_clicked(row("Chairs"), "lock", no_mod)
    check("layer lock closes groups", not bool(rt.isOpenGroupHead(rt.getNodeByName("Chair_group"))))

    # --- isolate ------------------------------------------------------------
    panel.isolate_layer("Chairs")
    state = {n: bool(layer(n).on) for n in ("0", "Walls", "Furniture", "Chairs", "Lights")}
    check("isolate keeps layer and its parent", state == {
        "0": False, "Walls": False, "Furniture": True, "Chairs": True, "Lights": False}, state)
    panel.show_all_layers()
    check("show all layers", all(bool(layer(n).on) for n in state))

    # --- selection sync -----------------------------------------------------
    time.sleep(0.6)
    rt.select(rt.getNodeByName("Table"))
    pump(100)
    check("viewport selection highlights its layer",
          panel.current_layer_name() == "Furniture", panel.current_layer_name())

    # --- move selection / select objects -----------------------------------
    panel.tree.setCurrentItem(row("Empty"))
    panel.add_to_layer()
    check("move selection to layer", str(rt.getNodeByName("Table").layer.name) == "Empty"
          and row("Empty").count == 1)
    panel.tree.setCurrentItem(row("Walls"))
    panel.select_layer_objects()
    check("select layer objects", rt.selection.count == 3)
    panel.tree.setCurrentItem(row("Furniture"))
    panel.select_layer_objects()
    check("select objects of an empty layer clears selection", rt.selection.count == 0)

    # --- current layer ------------------------------------------------------
    panel.tree.setCurrentItem(row("Lights"))
    panel.set_current_layer()
    check("set current layer", bool(layer("Lights").current) and row("Lights").current)

    # --- rename -------------------------------------------------------------
    r = row("Empty")
    r.setText(0, "Props")
    pump(400)
    check("rename", layer("Props") is not None and row("Props") is not None
          and row("Empty") is None)
    r = row("Props")
    r.setText(0, "props")
    pump(400)
    check("case-only rename", str(layer("props").name) == "props", str(layer("props").name))
    r = row("props")
    r.setText(0, "Walls")
    pump(400)
    check("rename to an existing name is refused",
          str(layer("props").name) == "props" and row("props").text(0) == "props")
    check("default layer is not editable",
          not bool(row("0").flags() & QtCore.Qt.ItemIsEditable))

    # --- create -------------------------------------------------------------
    before = rt.LayerManager.count
    panel.create_layer()
    pump(50)
    check("create layer", rt.LayerManager.count == before + 1 and row("Layer001") is not None)
    check("new layer opens the rename editor", panel.tree.is_editing())
    editor = panel.tree.findChild(QtWidgets.QLineEdit)
    if editor is not None:
        editor.setText("Doors")
        panel.tree.commitData(editor)
        panel.tree.closeEditor(editor, QtWidgets.QAbstractItemDelegate.NoHint)
    pump(400)
    check("rename through the editor", layer("Doors") is not None and row("Doors") is not None)
    panel.create_layer(parent_name="Doors")
    pump(50)
    editor = panel.tree.findChild(QtWidgets.QLineEdit)
    if editor is not None:
        panel.tree.closeEditor(editor, QtWidgets.QAbstractItemDelegate.RevertModelCache)
    pump(300)
    child = row("Layer001")
    check("create child layer", child is not None and child.parent() is row("Doors"))

    # --- delete -------------------------------------------------------------
    original_question = QtWidgets.QMessageBox.question
    QtWidgets.QMessageBox.question = staticmethod(
        lambda *a, **k: QtWidgets.QMessageBox.Yes)
    try:
        panel.tree.setCurrentItem(row("Furniture"))
        panel.delete_selected_layer()
        check("delete layer with nested layer", layer("Furniture") is None
              and row("Chairs") is not None and row("Chairs").parent() is None)
        panel.tree.setCurrentItem(row("Lights"))        # current layer, has objects
        panel.delete_selected_layer()
        check("delete the current layer with objects", layer("Lights") is None
              and str(rt.getNodeByName("Key_light").layer.name) == "0"
              and bool(layer("0").current))
        panel.tree.setCurrentItem(row("0"))
        panel.delete_selected_layer()
        check("default layer survives delete", layer("0") is not None)
    finally:
        QtWidgets.QMessageBox.question = original_question

    # --- search -------------------------------------------------------------
    panel.search_input.setText("chair")
    pump(500)
    visible = [r.layer_name for r in panel._layer_rows() if not r.isHidden()]
    check("search keeps matching layers only", visible == ["Chairs"], visible)
    found = [row("Chairs").child(i).text(0) for i in range(row("Chairs").childCount())]
    check("search lists matching objects", len(found) == 4, found)
    panel.search_input.setText("wall_02")
    pump(500)
    found = [row("Walls").child(i).text(0) for i in range(row("Walls").childCount())]
    check("search by object name", found == ["Wall_02"] and row("Walls").isExpanded(), found)
    panel.search_input.setText("")
    pump(500)
    check("clearing search restores the list",
          all(not r.isHidden() for r in panel._layer_rows())
          and row("Walls").childCount() == 3)

    # --- scene changes made elsewhere ---------------------------------------
    rt.LayerManager.newLayerFromName("FromScript")
    check("layerCreated callback schedules a refresh", panel._refresh_timer.isActive())
    pump(400)
    check("layer created elsewhere appears", row("FromScript") is not None)
    rt.Sphere(name="Ball")
    pump(400)
    check("node created elsewhere is counted", row("0").count == layer("0").getNumNodes())
    layer("Walls").on = False
    layer("Walls").setName("Outer walls")
    panel._poll()
    check("poll picks up hide + rename done elsewhere",
          row("Outer walls") is not None and not row("Outer walls").visible)
    layer("Outer walls").on = True
    layer("Outer walls").setName("Walls")
    panel._poll()
    if not row("Walls").isExpanded():       # a layer renamed elsewhere collapses
        panel.on_zone_clicked(row("Walls"), "chevron", no_mod)
    rt.getNodeByName("Wall_02").name = "Wall_renamed"
    pump(400)
    names = [row("Walls").child(i).text(0) for i in range(row("Walls").childCount())]
    check("object renamed elsewhere", "Wall_renamed" in names, names)
    rt.getNodeByName("Wall_renamed").name = "Wall_02"
    pump(400)

    # --- groups are hidden / frozen as a whole -------------------------------
    if not row("Chairs").isExpanded():
        panel.on_zone_clicked(row("Chairs"), "chevron", no_mod)

    def chair(name):
        r = row("Chairs")
        for i in range(r.childCount()):
            if r.child(i).text(0) == name:
                return r.child(i)

    family = ["Chair_group", "Chair_seat", "Chair_leg_0", "Chair_leg_1"]
    panel.on_zone_clicked(chair("Chair_group"), "eye", no_mod)
    hidden = [bool(rt.getNodeByName(n).isHidden) for n in family]
    check("hiding a group hides its members", all(hidden), hidden)
    check("member rows follow the group", not chair("Chair_seat").visible
          and not chair("Chair_group").visible)
    panel.on_zone_clicked(chair("Chair_group"), "eye", no_mod)
    hidden = [bool(rt.getNodeByName(n).isHidden) for n in family]
    check("showing a group shows its members", not any(hidden), hidden)
    panel.on_zone_clicked(chair("Chair_group"), "freeze", no_mod)
    frozen = [bool(rt.getNodeByName(n).isFrozen) for n in family]
    check("freezing a group freezes its members", all(frozen), frozen)
    panel.on_zone_clicked(chair("Chair_group"), "freeze", no_mod)
    frozen = [bool(rt.getNodeByName(n).isFrozen) for n in family]
    check("unfreezing a group unfreezes its members", not any(frozen), frozen)
    pump(300)

    # --- scene selection is shown on object rows ------------------------------
    time.sleep(0.6)
    rt.select(rt.getNodeByName("Wall_03"))
    pump(150)
    walls = row("Walls")
    marked = [walls.child(i).text(0) for i in range(walls.childCount())
              if walls.child(i).scene_selected]
    check("selected object is marked in its open layer", marked == ["Wall_03"], marked)
    cur = panel.tree.currentItem()
    check("highlight moves to the selected object's row",
          cur is not None and cur.text(0) == "Wall_03", cur.text(0) if cur else None)
    rt.select(rt.getNodeByName("Chair_group"))     # a closed group: head + members
    pump(150)
    cur = panel.tree.currentItem()
    check("selecting a group highlights the group row",
          cur is not None and cur.text(0) == "Chair_group", cur.text(0) if cur else None)
    check("the group row is marked", chair("Chair_group").scene_selected)
    panel.refresh()
    check("marks survive a refresh", chair("Chair_group").scene_selected)
    rt.clearSelection()
    pump(150)
    check("clearing the selection clears the marks",
          not any(r.scene_selected for r in panel._object_rows()))

    # --- theme --------------------------------------------------------------
    panel._theme_mode = "auto"
    panel.apply_theme()
    check("theme follows Max", (__main__.T["window"] == __main__.DARK["window"])
          == __main__.max_is_dark())
    was_dark = __main__.T["window"] == __main__.DARK["window"]
    panel.toggle_theme()
    check("theme button switches the palette",
          (__main__.T["window"] == __main__.DARK["window"]) != was_dark)
    check("the chosen theme is remembered",
          __main__.load_theme_mode() == ("light" if was_dark else "dark"))
    panel.toggle_theme()
    check("theme button switches back",
          (__main__.T["window"] == __main__.DARK["window"]) == was_dark)
    __main__._settings().remove("theme")

    # --- rounded corners -----------------------------------------------------
    result = __main__.round_window_corners(panel)
    check("Windows accepts the rounded-corner request", result == 0, result)

    # --- screenshot ---------------------------------------------------------
    panel.resize(380, 560)
    pump(100)
    image = QtGui.QImage(panel.size() * 2, QtGui.QImage.Format_ARGB32_Premultiplied)
    image.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(image)
    painter.scale(2, 2)
    try:        # an exception with a live painter takes Max down with it
        panel.render(painter, QtCore.QPoint())
    finally:
        painter.end()
    check("screenshot saved", image.save(os.path.join(OUT, "panel_{}.png".format(YEAR))))

    # --- single instance / close -------------------------------------------
    rt.python.ExecuteFile(SRC)
    pump(200)
    main_window = __main__.qtmax.GetQMaxMainWindow()
    docks = [d for d in main_window.findChildren(QtWidgets.QDockWidget, __main__.OBJECT_NAME)
             if d.isVisible()]
    check("running the script again keeps one panel", len(docks) == 1, len(docks))
    panel = __main__.layer_manager
    panel.close()
    pump(100)
    rt.LayerManager.newLayerFromName("AfterClose")      # must not raise
    pump(300)
    check("closed panel leaves no live bridge", __main__._alive() is None)
    del mod_row


try:
    run()
except Exception:
    failed.append("exception")
    log("EXCEPTION\n" + traceback.format_exc())

log("")
log("python", sys.version.split()[0], "| Max", YEAR)
log("RESULT:", "FAILED ({})".format(len(failed)) if failed else "PASSED")
report.close()
