"""Renders the frames of the promo clip (1080x1350, 30 fps, for X and LinkedIn).

Run inside 3ds Max through tools/make_promo.ps1 (3dsmaxbatch), which then
joins the frames into an mp4 with ffmpeg. The panel in the clip is the real
one: the script drives it step by step on the demo scene and paints every
frame from its current state, adding a pointer, a headline and a backdrop.
Nothing is captured from the screen.
"""
import importlib.util
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
OUT = os.environ["LM_OUT"]                  # folder for frame_00000.png ...
ROOT = os.path.dirname(os.path.dirname(SRC))

W, H, FPS = 1080, 1350, 30
PANEL = QtCore.QSize(380, 600)              # logical size of the panel
ZOOM = 1.6                                  # the panel is painted this much larger
PANEL_W, PANEL_H = int(PANEL.width() * ZOOM), int(PANEL.height() * ZOOM)
PANEL_X, PANEL_Y = (W - PANEL_W) // 2, 300
SITE = "shimodos.github.io/layer-manager-site"

Qt = QtCore.Qt


def load_shots():
    """The demo scene and the Stage helper live in tools/shots/make_shots.py."""
    os.environ["LM_IMPORT_ONLY"] = "1"
    path = os.path.join(ROOT, "tools", "shots", "make_shots.py")
    spec = importlib.util.spec_from_file_location("lm_make_shots", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ease(t):
    return t * t * (3 - 2 * t)


def font(px, weight=None):
    f = QtGui.QFont("Segoe UI")
    f.setPixelSize(px)
    if weight is not None:
        f.setWeight(weight)
    return f


class Film(object):
    """Keeps what the next frame shows and writes frames to disk."""

    def __init__(self, shots, stage, main):
        self.shots = shots
        self.stage = stage
        self.panel = stage.panel
        self.main = main
        self.count = 0
        self.cursor = [PANEL_X + PANEL_W * 0.78, PANEL_Y + PANEL_H * 0.9]
        self.cursor_alpha = 0.0
        self.ripple = None                  # 0..1 while a click ring expands
        self.badge = None                   # key cap shown during a modified click
        self.headline, self.old_headline, self.headline_mix = "", "", 1.0
        self.image = self.grab()
        self.old_image, self.image_mix = None, 1.0
        self.card = 0.0                     # 0..1 fade to the end card

    # -- panel ----------------------------------------------------------------
    def grab(self):
        self.shots.pump(40)
        image = QtGui.QImage(PANEL_W, PANEL_H, QtGui.QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QtGui.QPainter(image)
        painter.scale(ZOOM, ZOOM)
        try:        # an exception with a live painter takes Max down with it
            self.panel.render(painter, QtCore.QPoint())
        finally:
            painter.end()
        return image

    def canvas_point(self, panel_point):
        return [PANEL_X + panel_point[0] * ZOOM, PANEL_Y + panel_point[1] * ZOOM]

    # -- timeline -------------------------------------------------------------
    def emit(self):
        frame = QtGui.QImage(W, H, QtGui.QImage.Format_RGB32)
        painter = QtGui.QPainter(frame)
        try:
            self.paint(painter)
        finally:
            painter.end()
        frame.save(os.path.join(OUT, "frame_{:05d}.png".format(self.count)))
        self.count += 1

    def hold(self, ms):
        for _ in range(max(1, int(round(ms / 1000.0 * FPS)))):
            self.emit()

    def animate(self, ms, apply):
        steps = max(1, int(round(ms / 1000.0 * FPS)))
        for i in range(1, steps + 1):
            apply(i / float(steps))
            self.emit()

    def title(self, text):
        self.old_headline, self.headline = self.headline, text

        def step(t):
            self.headline_mix = ease(t)
        self.animate(500 if self.old_headline else 300, step)

    def move(self, panel_point, ms=650):
        start = list(self.cursor)
        target = self.canvas_point(panel_point)
        alpha = self.cursor_alpha

        def step(t):
            e = ease(t)
            self.cursor = [start[0] + (target[0] - start[0]) * e,
                           start[1] + (target[1] - start[1]) * e]
            self.cursor_alpha = alpha + (1 - alpha) * min(1.0, t * 3)
        self.animate(ms, step)

    def change(self, action, ms=220, settle=300):
        """Run an action on the panel and cross-fade to its new look."""
        old = self.image
        action()
        self.shots.pump(settle)
        self.panel._status_timer.stop()
        self.old_image, self.image = old, self.grab()

        def step(t):
            self.image_mix = t
        self.animate(ms, step)
        self.old_image, self.image_mix = None, 1.0

    def click(self, action, badge=None, settle=300):
        """A click: a ring spreads from the pointer while the panel changes."""
        self.badge = badge
        if badge:
            self.hold(350)                  # let the key cap be read first
        old = self.image
        action()
        self.shots.pump(settle)
        self.old_image, self.image = old, self.grab()

        def step(t):
            self.ripple = t
            self.image_mix = min(1.0, t * 1.6)
        self.animate(300, step)
        self.ripple, self.old_image, self.image_mix = None, None, 1.0
        if badge:
            self.hold(250)
        self.badge = None

    # -- painting -------------------------------------------------------------
    def paint(self, p):
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        p.setRenderHint(QtGui.QPainter.TextAntialiasing, True)

        p.fillRect(0, 0, W, H, QtGui.QColor("#0f1115"))
        for cx, cy, radius, alpha in ((W * 0.85, 250, 700, 70), (W * 0.1, H * 0.8, 620, 38)):
            glow = QtGui.QRadialGradient(cx, cy, radius)
            glow.setColorAt(0, QtGui.QColor(44, 198, 234, alpha))
            glow.setColorAt(1, QtGui.QColor(44, 198, 234, 0))
            p.fillRect(0, 0, W, H, glow)

        if self.card < 1.0:
            p.setOpacity(1.0 - self.card)
            self.paint_scene(p)
        if self.card > 0.0:
            p.setOpacity(self.card)
            self.paint_card(p)
        p.setOpacity(1.0)

    def paint_brand(self, p, y):
        tile = QtCore.QRectF(80, y, 52, 52)
        gradient = QtGui.QLinearGradient(tile.topLeft(), tile.bottomRight())
        gradient.setColorAt(0, QtGui.QColor("#35d0f2"))
        gradient.setColorAt(1, QtGui.QColor("#0b8fb3"))
        p.setPen(Qt.NoPen)
        p.setBrush(gradient)
        p.drawRoundedRect(tile, 12, 12)
        self.main.draw_icon(p, "layers", tile.adjusted(11, 11, -11, -11), "#ffffff", 1.9)
        p.setFont(font(28, QtGui.QFont.DemiBold))
        p.setPen(QtGui.QColor("#ededf0"))
        p.drawText(QtCore.QRectF(148, y, 500, 52), Qt.AlignVCenter | Qt.AlignLeft, "Layer Manager")
        p.setFont(font(24))
        p.setPen(QtGui.QColor("#9aa1ad"))
        p.drawText(QtCore.QRectF(W - 480, y, 400, 52), Qt.AlignVCenter | Qt.AlignRight,
                   "for Autodesk 3ds Max")

    def paint_scene(self, p):
        base = p.opacity()
        self.paint_brand(p, 56)

        # headline: the old one fades up and out, the new one comes in from below
        p.setFont(font(50, QtGui.QFont.DemiBold))
        # (one after the other, so two headlines never overlap)
        mix = self.headline_mix
        out, come = max(0.0, 1 - 2 * mix), max(0.0, 2 * mix - 1)
        for text, alpha, dy in ((self.old_headline, out, -14 * (1 - out)),
                                (self.headline, come, 14 * (1 - come))):
            if not text or alpha <= 0:
                continue
            p.setOpacity(base * alpha)
            p.setPen(QtGui.QColor("#ffffff"))
            p.drawText(QtCore.QRectF(80, 138 + dy, W - 160, 140),
                       Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap, text)
        p.setOpacity(base)

        # the panel: soft shadow, rounded clip, cross-fade between two states
        rect = QtCore.QRectF(PANEL_X, PANEL_Y, PANEL_W, PANEL_H)
        p.setPen(Qt.NoPen)
        for i in range(14):
            grow = (14 - i) * 3.0
            p.setBrush(QtGui.QColor(0, 0, 0, 9))
            p.drawRoundedRect(rect.adjusted(-grow, -grow + 22, grow, grow + 22), 22 + grow, 22 + grow)
        path = QtGui.QPainterPath()
        path.addRoundedRect(rect, 20, 20)
        p.save()
        p.setClipPath(path)
        if self.old_image is not None and self.image_mix < 1.0:
            p.drawImage(rect.topLeft(), self.old_image)
            p.setOpacity(base * self.image_mix)
        p.drawImage(rect.topLeft(), self.image)
        p.restore()
        p.setOpacity(base)
        p.setBrush(Qt.NoBrush)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 46), 2))
        p.drawPath(path)

        # click ring
        cx, cy = self.cursor
        if self.ripple is not None:
            ring = QtGui.QColor("#2cc6ea")
            ring.setAlphaF(max(0.0, 1.0 - self.ripple))
            p.setPen(QtGui.QPen(ring, 5))
            radius = 14 + 44 * ease(self.ripple)
            p.drawEllipse(QtCore.QPointF(cx, cy), radius, radius)

        # pointer
        if self.cursor_alpha > 0:
            p.setOpacity(base * self.cursor_alpha)
            k = 2.1
            arrow = QtGui.QPolygonF([QtCore.QPointF(cx + (x - 4) * k, cy + (y - 2.5) * k)
                                     for x, y in ((4, 2.5), (19.5, 11), (12.7, 12.9), (10.3, 20))])
            p.setPen(Qt.NoPen)
            p.setBrush(QtGui.QColor(0, 0, 0, 70))
            p.drawPolygon(arrow.translated(2, 4))
            p.setPen(QtGui.QPen(QtGui.QColor("#111111"), 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(QtGui.QColor("#ffffff"))
            p.drawPolygon(arrow)
            p.setOpacity(base)

        # key cap next to the pointer for a modified click
        if self.badge:
            cap = QtCore.QRectF(cx - 130, cy + 26, 104, 56)
            p.setPen(QtGui.QPen(QtGui.QColor("#2cc6ea"), 2))
            p.setBrush(QtGui.QColor("#16242b"))
            p.drawRoundedRect(cap, 12, 12)
            p.setFont(font(28, QtGui.QFont.DemiBold))
            p.setPen(QtGui.QColor("#ffffff"))
            p.drawText(cap, Qt.AlignCenter, self.badge)

        p.setFont(font(26))
        p.setPen(QtGui.QColor("#6c727d"))
        p.drawText(QtCore.QRectF(0, H - 72, W, 40), Qt.AlignCenter, SITE)

    def paint_card(self, p):
        tile = QtCore.QRectF(W / 2 - 80, 380, 160, 160)
        gradient = QtGui.QLinearGradient(tile.topLeft(), tile.bottomRight())
        gradient.setColorAt(0, QtGui.QColor("#35d0f2"))
        gradient.setColorAt(1, QtGui.QColor("#0b8fb3"))
        p.setPen(Qt.NoPen)
        p.setBrush(gradient)
        p.drawRoundedRect(tile, 38, 38)
        self.main.draw_icon(p, "layers", tile.adjusted(34, 34, -34, -34), "#ffffff", 1.9)

        p.setPen(QtGui.QColor("#ffffff"))
        p.setFont(font(84, QtGui.QFont.DemiBold))
        p.drawText(QtCore.QRectF(0, 590, W, 120), Qt.AlignCenter, "Layer Manager")
        p.setFont(font(40))
        p.setPen(QtGui.QColor("#c9ced6"))
        p.drawText(QtCore.QRectF(0, 720, W, 60), Qt.AlignCenter, "A layer panel for Autodesk 3ds Max")
        p.setFont(font(32))
        p.setPen(QtGui.QColor("#9aa1ad"))
        p.drawText(QtCore.QRectF(0, 800, W, 50), Qt.AlignCenter, "Free  ·  open source  ·  one Python file")

        pill = QtCore.QRectF(W / 2 - 370, 930, 740, 86)
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor("#2cc6ea"))
        p.drawRoundedRect(pill, 43, 43)
        p.setFont(font(32, QtGui.QFont.DemiBold))
        p.setPen(QtGui.QColor("#04222b"))
        p.drawText(pill, Qt.AlignCenter, SITE)


def run():
    shots = load_shots()
    shots.build_scene()
    rt.python.ExecuteFile(SRC)
    __main__ = sys.modules["adtools_layer_manager"]     # the panel's own module
    stage = shots.Stage(__main__)
    panel = stage.panel
    panel.resize(PANEL)
    stage.set_theme(True)
    stage.reset()

    film = Film(shots, stage, __main__)
    row = stage.row

    def press(target_row, zone):
        return lambda: stage.click(target_row, zone)

    # 1. the list
    film.title("Every layer of your 3ds Max scene on one list")
    film.hold(1000)
    film.move(stage.point(row("Furniture"), "chevron"))
    film.click(press(row("Furniture"), "chevron"))
    film.hold(350)
    film.move(stage.point(row("Seating"), "chevron"), 450)
    film.click(press(row("Seating"), "chevron"))
    film.hold(900)

    # 2. select
    film.title("Click a row to select the object")
    film.move(stage.point(row("Seating", "Sofa_Main"), "name"))
    film.click(press(row("Seating", "Sofa_Main"), "name"))
    film.hold(1200)

    # 3. groups as a whole
    film.title("Hide or freeze a whole group in one click")
    film.move(stage.point(row("Seating", "Armchair_01"), "eye"))
    film.click(press(row("Seating", "Armchair_01"), "eye"))
    film.hold(650)
    film.move(stage.point(row("Seating", "Armchair_02"), "freeze"), 500)
    film.click(press(row("Seating", "Armchair_02"), "freeze"))
    film.hold(1100)

    # 4. isolate
    film.title("Alt+click the eye to isolate a layer")
    film.move(stage.point(row("Furniture"), "eye"))
    film.click(lambda: panel.isolate_layer("Furniture"), badge="Alt")
    film.hold(1400)

    # 5. search
    film.title("Search layers and objects by name")
    film.move(stage.widget_point(panel.search_input))
    film.click(panel.show_all_layers)
    for typed in ("l", "la", "lam", "lamp"):
        film.change(lambda text=typed: panel.search_input.setText(text), ms=100, settle=450)
        film.hold(130)
    film.hold(1300)

    # 6. themes
    film.title("Dark or light, to match your 3ds Max")
    film.change(lambda: panel.search_input.setText(""), settle=500)
    film.move(stage.widget_point(panel.titleBarWidget().theme_button))
    film.click(panel.toggle_theme)
    film.hold(1500)

    # 7. end card
    def to_card(t):
        film.card = ease(t)
    film.animate(450, to_card)
    film.hold(2800)

    panel.close()
    return film.count


status = "ok"
try:
    status = "ok {} frames".format(run())
except Exception:
    status = traceback.format_exc()
with open(os.path.join(OUT, "make_promo.log"), "w") as fh:
    fh.write(status)
