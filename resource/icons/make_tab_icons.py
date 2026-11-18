"""Draws the wintools tab and toolbar icons in the Windows 7 icon style of the
bomdb / allegro_util sets: 3/4 view, top-lit gradients, gloss, dark outline,
soft floor shadow. Each icon has a detailed drawing (256 units, used for
24-256 px) and a hand-simplified 16 px drawing.

    C:\\Python\\313\\python.exe make_tab_icons.py      -> tab_*.ico, act_*.ico next to this file
"""

import importlib.util
import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (QBrush, QColor, QFont, QPainterPath, QPainterPathStroker, QPen,
                         QPolygonF, QTransform)
from PyQt5.QtWidgets import QApplication

HERE = os.path.dirname(os.path.abspath(__file__))

_spec = importlib.util.spec_from_file_location(
    "bomdb_icons",
    r"C:\Dropbox\Common\pcb\Allegro\lib\db\resource\icons\make_tab_icons.py",
)
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)

CHROME = ("#ffffff", "#c9d1da", "#7d8894")


# --- shared helpers --------------------------------------------------------------
def plane(iso, z):
    """Maps (x, y) on the horizontal plane at height z to screen, so flat
    shapes (letters, fans, discs) can be drawn straight onto a top face."""
    s = iso.s
    return QTransform(B.C30 * s, B.VF * s, -B.C30 * s, B.VF * s, iso.cx, iso.cy - z * s)


def side_plane(iso, y):
    """Maps (x, z) on the vertical front-left face at depth y to screen."""
    s = iso.s
    return QTransform(B.C30 * s, B.VF * s, 0, -s, iso.cx - y * B.C30 * s, iso.cy + y * B.VF * s)


def poly_path(pts):
    path = QPainterPath()
    path.addPolygon(QPolygonF(pts))
    path.closeSubpath()
    return path


def text_path(text, family, cx, cy, height):
    f = QFont(family)
    f.setPixelSize(100)
    path = QPainterPath()
    path.addText(0, 0, f, text)
    r = path.boundingRect()
    k = height / r.height()
    t = QTransform()
    t.translate(cx, cy)
    t.scale(k, k)
    t.translate(-r.center().x(), -r.center().y())
    return t.map(path)


def keycap(p, iso, x, y, w, d, h, k, letter=None, family=None, width=1.4):
    """Sculpted key: sloped skirt, top face inset by k."""
    b = [(x, y, 0), (x + w, y, 0), (x + w, y + d, 0), (x, y + d, 0)]
    t = [(x + k, y + k, h), (x + w - k, y + k, h), (x + w - k, y + d - k, h), (x + k, y + d - k, h)]
    lf = [b[3], b[2], t[2], t[3]]
    rf = [b[1], b[2], t[2], t[1]]
    iso.face(lf, iso.fgrad(lf, QColor("#dfe4ea"), QColor("#aab3be")), "#5b6570", width)
    iso.face(rf, iso.fgrad(rf, QColor("#b9c1cb"), QColor("#89939f")), "#5b6570", width)
    iso.face(t, iso.fgrad(t, QColor("#ffffff"), QColor("#d5dbe2")), "#5b6570", width)
    top = poly_path([iso.pt(*q) for q in t])
    if letter:
        glyph = plane(iso, h).map(
            text_path(letter, family, x + w / 2, y + d / 2, (w - 2 * k) * 0.5))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#3a4450"))
        p.drawPath(glyph)
    r = top.boundingRect()
    B.gloss(p, top, QRectF(r.x(), r.y(), r.width(), r.height() * 0.6), 120)


def arc_arrow(cx, cy, r, width, a0, span, head):
    """Thick arc from angle a0 (deg, counter-clockwise) through span, with an
    arrowhead at the far end."""
    rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
    arc = QPainterPath()
    arc.arcMoveTo(rect, a0)
    arc.arcTo(rect, a0, span)
    st = QPainterPathStroker()
    st.setWidth(width)
    st.setCapStyle(Qt.FlatCap)
    body = st.createStroke(arc)
    a = math.radians(a0 + span)
    ex, ey = cx + r * math.cos(a), cy - r * math.sin(a)
    sgn = 1 if span > 0 else -1
    tx, ty = -math.sin(a) * sgn, -math.cos(a) * sgn
    rx, ry = math.cos(a), -math.sin(a)
    tri = poly_path([QPointF(ex + rx * head, ey + ry * head),
                     QPointF(ex + tx * head * 1.15, ey + ty * head * 1.15),
                     QPointF(ex - rx * head, ey - ry * head)])
    return body.united(tri).simplified()


def cycle_arrows(p, cx, cy, r, width, stops, outline, halo=0.0, pen=1.5):
    paths = [arc_arrow(cx, cy, r, width, 105, 145, width * 0.95),
             arc_arrow(cx, cy, r, width, 285, 145, width * 0.95)]
    if halo:
        p.setPen(QPen(QColor(255, 255, 255, 235), halo, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        for path in paths:
            p.drawPath(path)
    p.setPen(QPen(QColor(outline), pen, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(B.vgrad(cy - r - width, cy + r + width, *stops))
    for path in paths:
        p.drawPath(path)
    if halo:
        clip = paths[0].united(paths[1])
        B.gloss(p, clip, QRectF(cx - r - width, cy - r - width, 2 * (r + width), r + width), 130)


BLUE = ((0, "#8cc8ff"), (0.5, "#2a7fe0"), (1, "#0f4fb0"))
GREEN = ((0, "#a6f07a"), (0.5, "#3fb53a"), (1, "#1c7a1f"))
RED = ((0, "#ff6a55"), (0.5, "#e02a1a"), (1, "#a8140b"))


def round_badge(p, cx, cy, r, stops, outline, pen=2.0):
    path = QPainterPath()
    path.addEllipse(QPointF(cx, cy), r, r)
    p.setPen(QPen(QColor(255, 255, 255, 235), pen * 3))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    p.setPen(QPen(QColor(outline), pen))
    p.setBrush(B.vgrad(cy - r, cy + r, *stops))
    p.drawPath(path)
    return path


def block_arrow(x0, x1, cy, t, head, head_len):
    """Arrow pointing from x0 to x1 (either direction)."""
    sgn = 1 if x1 > x0 else -1
    xh = x1 - sgn * head_len
    return poly_path([QPointF(x0, cy - t), QPointF(xh, cy - t), QPointF(xh, cy - head),
                      QPointF(x1, cy), QPointF(xh, cy + head), QPointF(xh, cy + t),
                      QPointF(x0, cy + t)])


def draw_block_arrow(p, path, stops, outline, halo, pen):
    r = path.boundingRect()
    p.setPen(QPen(QColor("#ffffff"), halo, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    p.setPen(QPen(QColor(outline), pen, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(B.vgrad(r.top(), r.bottom(), *stops))
    p.drawPath(path)
    B.gloss(p, path, QRectF(r.x(), r.y(), r.width(), r.height() * 0.5), 150)


def folder_back(x, y, w, h, tab_w, tab_h):
    path = QPainterPath()
    path.moveTo(x, y + tab_h)
    path.lineTo(x, y + 4)
    path.quadTo(x, y, x + 4, y)
    path.lineTo(x + tab_w, y)
    path.lineTo(x + tab_w + tab_h, y + tab_h)
    path.lineTo(x + w, y + tab_h)
    path.lineTo(x + w, y + h)
    path.lineTo(x, y + h)
    path.closeSubpath()
    return path


def manila(p, x, y, w, h, tab_w, tab_h, pen=1.5, gloss=True):
    back = folder_back(x, y, w, h, tab_w, tab_h)
    p.setPen(QPen(QColor("#8a6414"), pen))
    p.setBrush(B.vgrad(y, y + h, (0, "#f2cf6a"), (1, "#c9952a")))
    p.drawPath(back)
    front = QPainterPath()
    front.addRect(QRectF(x, y + tab_h * 1.9, w, h - tab_h * 1.9))
    p.setBrush(B.vgrad(y + tab_h * 1.9, y + h, (0, "#fff0b8"), (0.5, "#f8d879"), (1, "#e2ae3e")))
    p.drawPath(front)
    if gloss:
        B.gloss(p, front, QRectF(x, y + tab_h * 1.9, w, (h - tab_h * 1.9) * 0.5), 120)


def xml_page(p, x, y, w, h, fold, pen=1.5):
    page = B._page(p, x, y, w, h, fold, "#ffffff", "#e4e8ec", "#8a929b")
    p.setPen(QPen(QColor("#8a929b"), pen))
    p.setBrush(B.vgrad(y, y + fold, (0, "#f7f9fb"), (1, "#c3c9d0")))
    p.drawPolygon(QPolygonF([QPointF(x + w - fold, y), QPointF(x + w - fold, y + fold),
                             QPointF(x + w, y + fold)]))
    cy = y + h * 0.36
    s = w * 0.13
    p.setPen(QPen(QColor("#2a4d8f"), w * 0.06, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    cx = x + w * 0.5
    p.drawPolyline(QPolygonF([QPointF(cx - s * 1.2, cy - s), QPointF(cx - s * 2.2, cy),
                              QPointF(cx - s * 1.2, cy + s)]))
    p.drawPolyline(QPolygonF([QPointF(cx + s * 1.2, cy - s), QPointF(cx + s * 2.2, cy),
                              QPointF(cx + s * 1.2, cy + s)]))
    p.drawLine(QPointF(cx + s * 0.45, cy - s * 1.15), QPointF(cx - s * 0.45, cy + s * 1.15))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#9aa3ad"))
    for i, ln in enumerate((0.62, 0.72, 0.5)):
        p.drawRect(QRectF(x + w * 0.14, y + h * (0.6 + i * 0.1), w * ln, h * 0.028))
    B.gloss(p, page, QRectF(x, y, w, h * 0.5), 60)


# --- Initial Config: glossy monitor with a green check badge ------------------------
def initcfg(size):
    img, p = B.canvas(size)
    B.floor_shadow(p, 120, 228, 112, 16, 85)
    base = QPainterPath()
    base.addRoundedRect(QRectF(64, 200, 108, 18), 9, 9)
    p.setPen(QPen(QColor("#4a525c"), 1.8))
    p.setBrush(B.vgrad(200, 218, (0, "#f2f4f7"), (1, "#7d8894")))
    p.drawPath(base)
    neck = poly_path([QPointF(104, 168), QPointF(132, 168), QPointF(140, 204),
                      QPointF(96, 204)])
    p.setBrush(B.lgrad(QPointF(96, 0), QPointF(140, 0),
                       (0, "#8f9aa7"), (0.5, "#f2f4f7"), (1, "#7d8894")))
    p.drawPath(neck)
    bezel = QPainterPath()
    bezel.addRoundedRect(QRectF(14, 22, 208, 150), 12, 12)
    p.setPen(QPen(QColor("#3d444c"), 2.0))
    p.setBrush(B.vgrad(22, 172, (0, "#f2f4f7"), (0.5, "#b9c1cb"), (1, "#7d8894")))
    p.drawPath(bezel)
    B.gloss(p, bezel, QRectF(14, 22, 208, 60), 130)
    scr = QRectF(26, 34, 184, 114)
    screen = QPainterPath()
    screen.addRect(scr)
    p.setPen(QPen(QColor("#000000"), 1.5))
    p.setBrush(B.vgrad(34, 148, (0, "#2f66b8"), (0.55, "#123a78"), (1, "#071a3a")))
    p.drawPath(screen)
    bar = QRectF(26, 126, 184, 22)
    p.setPen(Qt.NoPen)
    p.setBrush(B.vgrad(126, 148, (0, "#2b2f36"), (1, "#101216")))
    p.drawRect(bar)
    p.setBrush(B.vgrad(130, 144, (0, "#8cc8ff"), (1, "#0f4fb0")))
    p.drawEllipse(QPointF(42, 137), 7, 7)
    p.setBrush(QColor("#9aa5b1"))
    for x in (60, 80, 100):
        p.drawRoundedRect(QRectF(x, 131, 14, 12), 3, 3)
    p.setPen(QPen(QColor("#6b7580"), 1.2))
    p.setBrush(B.vgrad(44, 66, (0, "#ffffff"), (1, "#c3cbd4")))
    p.drawRoundedRect(QRectF(38, 44, 18, 22), 3, 3)
    B.gloss(p, screen, QRectF(26, 34, 184, 56), 90)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#7be07b"))
    p.drawEllipse(QPointF(118, 160), 3, 3)
    badge = round_badge(p, 192, 184, 46, GREEN, "#0f4f12", 2.2)
    B.gloss(p, badge, QRectF(146, 138, 92, 46), 130)
    p.setPen(QPen(QColor("#ffffff"), 15, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    p.drawPolyline(QPolygonF([QPointF(171, 185), QPointF(186, 200), QPointF(215, 167)]))
    p.end()
    return img


def initcfg_16():
    img, p = B.canvas(16, 16)
    p.setPen(QPen(QColor("#3d444c"), 0.8))
    p.setBrush(B.vgrad(1, 11, (0, "#e9edf1"), (1, "#8d97a3")))
    p.drawRoundedRect(QRectF(0.5, 1.5, 13.5, 9.5), 1.5, 1.5)
    p.setPen(Qt.NoPen)
    p.setBrush(B.vgrad(2.7, 9.7, (0, "#3a78d0"), (1, "#0a1f45")))
    p.drawRect(QRectF(1.7, 2.7, 11.1, 7))
    p.setBrush(QColor("#1a1d22"))
    p.drawRect(QRectF(1.7, 8.5, 11.1, 1.2))
    p.setBrush(QColor("#9aa5b1"))
    p.drawRect(QRectF(5.6, 11, 3.4, 1.6))
    p.drawRoundedRect(QRectF(3.4, 12.4, 7.8, 1.5), 0.7, 0.7)
    p.setPen(QPen(QColor("#0f4f12"), 0.6))
    p.setBrush(B.vgrad(7.4, 16, *GREEN))
    p.drawEllipse(QPointF(11.8, 11.8), 4.0, 4.0)
    p.setPen(QPen(QColor("#ffffff"), 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    p.drawPolyline(QPolygonF([QPointF(9.7, 12), QPointF(11.2, 13.5), QPointF(14, 10)]))
    p.end()
    return img


# --- Repeat rate: keycap with repeat arrows -----------------------------------------
def repeat(size, family):
    img, p = B.canvas(size)
    B.floor_shadow(p, 112, 196, 104, 26, 80)
    iso = B.Iso(p, 110, 42, 16.5)
    keycap(p, iso, 0, 0, 7, 7, 2.3, 0.95, "A", family, 1.6)
    cycle_arrows(p, 192, 190, 40, 20, BLUE, "#0b3f86", halo=8, pen=2)
    p.end()
    return img


def repeat_16():
    img, p = B.canvas(16, 16)
    p.setPen(QPen(QColor("#5b6570"), 0.8))
    p.setBrush(B.vgrad(1, 12, (0, "#c3cad3"), (1, "#8d97a3")))
    p.drawRoundedRect(QRectF(0.5, 1.5, 11, 10.5), 2, 2)
    p.setBrush(B.vgrad(1, 9, (0, "#ffffff"), (1, "#d5dbe2")))
    p.drawRoundedRect(QRectF(2, 2, 8, 7.5), 1.5, 1.5)
    cycle_arrows(p, 11.5, 11.5, 3.2, 2.3, BLUE, "#0b3f86", pen=0.6)
    p.end()
    return img


# --- Key diagnostics: keycap in front of a scope trace ----------------------------------
def _scope(p, x, y, w, h, pen, trace_w, grid=True):
    bez = QPainterPath()
    bez.addRoundedRect(QRectF(x, y, w, h), h * 0.09, h * 0.09)
    p.setPen(QPen(QColor("#3d444c"), pen))
    p.setBrush(B.vgrad(y, y + h, (0, "#f2f4f7"), (0.5, "#b9c1cb"), (1, "#7d8894")))
    p.drawPath(bez)
    m = h * 0.09
    scr = QRectF(x + m, y + m, w - 2 * m, h - 2 * m)
    p.setPen(QPen(QColor("#000000"), pen * 0.7))
    p.setBrush(B.vgrad(scr.top(), scr.bottom(), (0, "#0f2a18"), (1, "#03100a")))
    p.drawRect(scr)
    if grid:
        p.setPen(QPen(QColor(80, 200, 120, 60), pen * 0.6))
        for i in range(1, 4):
            p.drawLine(QPointF(scr.left() + scr.width() * i / 4, scr.top()),
                       QPointF(scr.left() + scr.width() * i / 4, scr.bottom()))
            p.drawLine(QPointF(scr.left(), scr.top() + scr.height() * i / 4),
                       QPointF(scr.right(), scr.top() + scr.height() * i / 4))
    lo, hi = scr.bottom() - scr.height() * 0.22, scr.top() + scr.height() * 0.22
    xs = [0.0, 0.14, 0.3, 0.44, 0.5, 0.62, 0.8, 0.9, 1.0]
    pts = []
    level = lo
    for i, f in enumerate(xs):
        px = scr.left() + scr.width() * f
        pts.append(QPointF(px, level))
        if i < len(xs) - 1:
            level = hi if level == lo else lo
            pts.append(QPointF(px, level))
    p.setPen(QPen(QColor("#6dff8a"), trace_w, Qt.SolidLine, Qt.SquareCap, Qt.MiterJoin))
    p.setBrush(Qt.NoBrush)
    p.drawPolyline(QPolygonF(pts))
    glass = QPainterPath()
    glass.addRect(scr)
    B.gloss(p, glass, QRectF(scr.x(), scr.y(), scr.width(), scr.height() * 0.45), 55)


def keydiag(size, family):
    img, p = B.canvas(size)
    B.floor_shadow(p, 130, 224, 112, 22, 85)
    _scope(p, 92, 14, 156, 120, 2.0, 5.0)
    iso = B.Iso(p, 86, 120, 13.0)
    keycap(p, iso, 0, 0, 7, 7, 2.2, 0.9, "K", family, 1.5)
    p.end()
    return img


def keydiag_16():
    img, p = B.canvas(16, 16)
    _scope(p, 5, 0.5, 10.5, 9, 0.6, 0.9, grid=False)
    p.setPen(QPen(QColor("#5b6570"), 0.7))
    p.setBrush(B.vgrad(7, 15.5, (0, "#c3cad3"), (1, "#8d97a3")))
    p.drawRoundedRect(QRectF(0.5, 7, 8.5, 8.5), 1.5, 1.5)
    p.setBrush(B.vgrad(7, 13, (0, "#ffffff"), (1, "#d5dbe2")))
    p.drawRoundedRect(QRectF(1.6, 7.6, 6.3, 5.6), 1.2, 1.2)
    p.end()
    return img


# --- System: tweak checklist window (lime on / pink off) with a gear -----------------
LIME, PINK = "#c8f0aa", "#ffcdd5"


def system(size):
    img, p = B.canvas(size)
    B.floor_shadow(p, 128, 226, 112, 18, 85)
    x, y, w, h = 14, 22, 206, 186
    frame = QPainterPath()
    frame.addRoundedRect(QRectF(x, y, w, h), 9, 9)
    p.setPen(QPen(QColor("#1f3c66"), 2.0))
    p.setBrush(B.vgrad(y, y + 34, (0, "#8fc1f2"), (0.5, "#3d7fcc"), (1, "#25609f")))
    p.drawPath(frame)
    B.gloss(p, frame, QRectF(x, y, w, 18), 140)
    body = QRectF(x + 8, y + 32, w - 16, h - 40)
    p.setPen(QPen(QColor("#6f7a86"), 1.2))
    p.setBrush(B.vgrad(body.top(), body.bottom(), (0, "#ffffff"), (1, "#e6eaee")))
    p.drawRect(body)
    for i, on in enumerate((True, False, True, True)):
        ry = body.top() + 10 + i * 35
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(LIME if on else PINK))
        p.drawRect(QRectF(body.left() + 6, ry, body.width() - 12, 28))
        box = QRectF(body.left() + 12, ry + 4, 20, 20)
        p.setPen(QPen(QColor("#5f6a76"), 1.4))
        p.setBrush(QColor("#ffffff"))
        p.drawRect(box)
        if on:
            p.setPen(QPen(QColor("#1f7a2c"), 4.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPolyline(QPolygonF([QPointF(box.left() + 3.5, box.top() + 10),
                                      QPointF(box.left() + 8.5, box.top() + 15.5),
                                      QPointF(box.left() + 17, box.top() + 4)]))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#7d8894"))
        p.drawRect(QRectF(box.right() + 10, ry + 11, 96 - (i % 2) * 26, 6))
    B._gear(p, 200, 198, 50, 40, 10, 12, math.radians(8), CHROME, "#6b7580", "#3d444c", 9)
    p.end()
    return img


def system_16():
    img, p = B.canvas(16, 16)
    p.setPen(QPen(QColor("#1f3c66"), 0.8))
    p.setBrush(B.vgrad(0.5, 4, (0, "#8fc1f2"), (1, "#25609f")))
    p.drawRect(QRectF(0.5, 0.5, 15, 15))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#ffffff"))
    p.drawRect(QRectF(1.5, 3.5, 13, 11))
    for i, on in enumerate((True, False, True)):
        ry = 4.5 + i * 3.3
        p.setBrush(QColor("#9fdc78" if on else "#ffadba"))
        p.drawRect(QRectF(2, ry, 12, 2.6))
        p.setBrush(QColor("#1f7a2c" if on else "#ffffff"))
        p.setPen(QPen(QColor("#5f6a76"), 0.5))
        p.drawRect(QRectF(2.6, ry + 0.4, 1.8, 1.8))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#6f7a86"))
        p.drawRect(QRectF(5.4, ry + 0.9, 7 - (i % 2) * 2, 0.9))
    p.end()
    return img


# --- GPU: graphics card with twin fans, bracket and gold fingers ---------------------
def _fan(p, iso, z, cx, cy, r, blades=9):
    t = plane(iso, z)
    ring = QPainterPath()
    ring.addEllipse(QPointF(cx, cy), r, r)
    p.setPen(QPen(QColor("#0b0c0e"), 1.2))
    p.setBrush(QColor("#101215"))
    p.drawPath(t.map(ring))
    for k in range(blades):
        a = 2 * math.pi * k / blades
        blade = QPainterPath()
        blade.moveTo(cx + math.cos(a) * r * 0.28, cy + math.sin(a) * r * 0.28)
        blade.quadTo(cx + math.cos(a + 0.55) * r * 0.75, cy + math.sin(a + 0.55) * r * 0.75,
                     cx + math.cos(a + 0.35) * r * 0.93, cy + math.sin(a + 0.35) * r * 0.93)
        blade.quadTo(cx + math.cos(a + 0.05) * r * 0.62, cy + math.sin(a + 0.05) * r * 0.62,
                     cx + math.cos(a - 0.25) * r * 0.28, cy + math.sin(a - 0.25) * r * 0.28)
        blade.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#3a4049") if k % 2 else QColor("#2c3138"))
        p.drawPath(t.map(blade))
    hub = QPainterPath()
    hub.addEllipse(QPointF(cx, cy), r * 0.3, r * 0.3)
    hp = t.map(hub)
    hr = hp.boundingRect()
    p.setPen(QPen(QColor("#3d444c"), 1.0))
    p.setBrush(B.lgrad(hr.topLeft(), hr.bottomRight(), (0, "#e9edf1"), (1, "#6b7580")))
    p.drawPath(hp)


def gpu(size):
    img, p = B.canvas(size)
    B.floor_shadow(p, 140, 212, 116, 24, 85)
    iso = B.Iso(p, 92, 58, 19.0)
    W, D, T = 9.0, 4.6, 0.3
    # bracket stands at the back-left end
    iso.box(-0.35, -0.25, 0, 0.35, D + 0.5, 2.3, "#f2f4f7", "#c3cbd4", "#9aa5b1", "#4a525c",
            "#ffffff", 1.2)
    iso.box(0, 0, 0, W, D, T, "#1f6b35", "#b89a52", "#9c8244", "#123f20", "#3f9a5a", 1.3)
    for i in range(14):
        x0 = 3.2 + i * 0.36
        f = [(x0, D - 0.55, T + 0.01), (x0 + 0.22, D - 0.55, T + 0.01),
             (x0 + 0.22, D - 0.05, T + 0.01), (x0, D - 0.05, T + 0.01)]
        iso.face(f, iso.fgrad(f, QColor("#ffe07a"), QColor("#b8860b")))
    SH = 1.25
    iso.box(0.25, 0.15, T, W - 0.4, D - 0.85, SH, "#3a3f47", "#23272d", "#181b20", "#07080a",
            "#6b7380", 1.4)
    # silver accent strip along the shroud's front edge
    z = T + SH + 0.01
    strip = [(0.45, D - 1.05, z), (W - 0.35, D - 1.05, z), (W - 0.35, D - 0.85, z),
             (0.45, D - 0.85, z)]
    iso.face(strip, QBrush(QColor("#c9d1da")))
    fy = 0.15 + (D - 0.85) / 2 - 0.1
    _fan(p, iso, z, 2.55, fy, 1.6)
    _fan(p, iso, z, 6.45, fy, 1.6)
    top = poly_path([iso.pt(0.25, 0.15, z), iso.pt(W - 0.15, 0.15, z),
                     iso.pt(W - 0.15, D - 0.7, z), iso.pt(0.25, D - 0.7, z)])
    r = top.boundingRect()
    B.gloss(p, top, QRectF(r.x(), r.y(), r.width(), r.height() * 0.5), 70)
    p.end()
    return img


def gpu_16():
    img, p = B.canvas(16, 16)
    p.setPen(QPen(QColor("#4a525c"), 0.6))
    p.setBrush(B.vgrad(2, 14, (0, "#ffffff"), (1, "#9aa5b1")))
    p.drawRect(QRectF(0.5, 2, 1.6, 12.5))
    p.setPen(QPen(QColor("#123f20"), 0.6))
    p.setBrush(QColor("#1f6b35"))
    p.drawRect(QRectF(2, 10.5, 13.5, 2))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#f0c040"))
    p.drawRect(QRectF(6, 12.5, 6.5, 1.8))
    p.setPen(QPen(QColor("#07080a"), 0.7))
    p.setBrush(B.vgrad(3, 11, (0, "#5a616c"), (1, "#1e2228")))
    p.drawRoundedRect(QRectF(2.3, 3.2, 13.2, 7.6), 1.2, 1.2)
    for cx in (5.6, 12.1):
        p.setPen(QPen(QColor("#9aa5b1"), 0.6))
        p.setBrush(QColor("#101215"))
        p.drawEllipse(QPointF(cx, 7), 2.8, 2.8)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#c9d1da"))
        p.drawEllipse(QPointF(cx, 7), 0.9, 0.9)
    p.end()
    return img


# --- Files: wastebasket full of paper -------------------------------------------------
def _basket(p, cx, top, bot, rt, rb, ry, pen, ribs, papers):
    inner = QPainterPath()
    inner.addEllipse(QPointF(cx, top), rt, ry)
    p.setPen(QPen(QColor("#44576b"), pen))
    p.setBrush(B.vgrad(top - ry, top + ry, (0, "#3c4d60"), (1, "#8aa0b6")))
    p.drawPath(inner)
    papers()
    body = QPainterPath()
    body.moveTo(cx - rt, top)
    body.lineTo(cx - rb, bot)
    body.arcTo(QRectF(cx - rb, bot - ry * 0.75, 2 * rb, ry * 1.5), 180, 180)
    body.lineTo(cx + rt, top)
    body.arcTo(QRectF(cx - rt, top - ry, 2 * rt, 2 * ry), 0, -180)
    body.closeSubpath()
    p.setPen(QPen(QColor("#44576b"), pen))
    p.setBrush(B.lgrad(QPointF(cx - rt, 0), QPointF(cx + rt, 0),
                       (0, QColor(120, 145, 172, 235)), (0.35, QColor(222, 234, 246, 235)),
                       (0.7, QColor(160, 184, 208, 235)), (1, QColor(92, 116, 142, 240))))
    p.drawPath(body)
    p.save()
    p.setClipPath(body)
    p.setPen(QPen(QColor(255, 255, 255, 110), pen * 1.4))
    for i in range(1, ribs):
        f = i / ribs
        a = math.pi * (1 - f)
        xt = cx + math.cos(a) * rt
        xb = cx + math.cos(a) * rb
        yt = top + math.sin(a) * ry
        yb = bot + math.sin(a) * ry * 0.75
        p.drawLine(QPointF(xt, yt), QPointF(xb, yb))
    p.restore()
    B.gloss(p, body, QRectF(cx - rt, top, rt, bot - top), 90)
    rim = QPainterPath()
    rim.addEllipse(QPointF(cx, top), rt, ry)
    p.setPen(QPen(QColor("#dbe6f1"), pen * 2.2))
    p.setBrush(Qt.NoBrush)
    p.drawPath(rim)
    p.setPen(QPen(QColor("#44576b"), pen))
    p.drawPath(rim)


def files(size):
    img, p = B.canvas(size)
    B.floor_shadow(p, 128, 234, 96, 14, 90)

    def papers():
        for pts, rot in (([(62, 58), (112, 20), (150, 44), (122, 84)], 0),
                         ([(118, 70), (150, 14), (198, 30), (184, 82)], 0),
                         ([(80, 76), (96, 40), (140, 58), (130, 86)], 0)):
            path = poly_path([QPointF(*q) for q in pts])
            p.setPen(QPen(QColor("#8a929b"), 1.5))
            p.setBrush(B.vgrad(10, 90, (0, "#ffffff"), (1, "#d7dce2")))
            p.drawPath(path)
            p.setPen(QPen(QColor("#b0b8c0"), 1.2))
            a, b = pts[0], pts[1]
            for k in (0.3, 0.55):
                p.drawLine(QPointF(a[0] + (pts[3][0] - a[0]) * k + 8, a[1] + (pts[3][1] - a[1]) * k),
                           QPointF(b[0] + (pts[2][0] - b[0]) * k - 6, b[1] + (pts[2][1] - b[1]) * k))

    _basket(p, 128, 76, 222, 88, 62, 24, 1.8, 12, papers)
    p.end()
    return img


def files_16():
    img, p = B.canvas(16, 16)
    p.setPen(QPen(QColor("#8a929b"), 0.5))
    p.setBrush(QColor("#ffffff"))
    p.drawPolygon(QPolygonF([QPointF(3.6, 4.6), QPointF(6.2, 0.6), QPointF(9.4, 2.2),
                             QPointF(8, 5.4)]))
    p.drawPolygon(QPolygonF([QPointF(7.8, 5), QPointF(10, 0.9), QPointF(13.2, 2.4),
                             QPointF(12.2, 5.4)]))
    body = poly_path([QPointF(1.6, 5), QPointF(14.4, 5), QPointF(12.6, 15.4), QPointF(3.4, 15.4)])
    p.setPen(QPen(QColor("#2f4256"), 0.8))
    p.setBrush(B.lgrad(QPointF(1.6, 0), QPointF(14.4, 0), (0, "#6d86a0"), (0.4, "#c9d8e8"),
                       (1, "#48607a")))
    p.drawPath(body)
    p.setPen(QPen(QColor(47, 66, 86, 150), 0.7))
    for x0, x1 in ((5, 5.9), (8, 8), (11, 10.1)):
        p.drawLine(QPointF(x0, 6.4), QPointF(x1, 14.6))
    p.setPen(QPen(QColor("#2f4256"), 0.8))
    p.setBrush(QColor("#dbe6f1"))
    p.drawRoundedRect(QRectF(1, 4.2, 14, 1.8), 0.9, 0.9)
    p.end()
    return img


# --- Registry: regedit cube cluster ------------------------------------------------------
CUBE = ("#8cc8ff", "#2f74d0", "#1c4f9c", "#0c2f66", "#d4ebff")


def _cube(iso, x, y, z, c, width):
    iso.box(x, y, z, c, c, c, *CUBE, width)


def registry(size):
    img, p = B.canvas(size)
    B.floor_shadow(p, 128, 222, 104, 20, 85)
    iso = B.Iso(p, 128, 96, 15.5)
    c, g = 3.1, 0.35
    _cube(iso, 0, 0, 0, c, 1.4)
    _cube(iso, c + g, 0, 0, c, 1.4)
    _cube(iso, 0, c + g, 0, c, 1.4)
    _cube(iso, 0, 0, c + g * 0.5, c, 1.4)
    p.end()
    return img


def registry_16():
    img, p = B.canvas(16, 16)
    iso = B.Iso(p, 8, 8.1, 1.0)
    c, g = 4.0, 0.3
    for x, y, z in ((0, 0, 0), (c + g, 0, 0), (0, c + g, 0), (0, 0, c + g * 0.5)):
        iso.box(x, y, z, c, c, c, *CUBE, 0.5)
    p.end()
    return img


# --- Orphan paths: registry cube and a broken chain link --------------------------------
def _link(cx, cy, length, girth, thick, angle):
    outer = QPainterPath()
    outer.addRoundedRect(QRectF(-length / 2, -girth / 2, length, girth), girth / 2, girth / 2)
    inner = QPainterPath()
    il, ig = length - 2 * thick, girth - 2 * thick
    inner.addRoundedRect(QRectF(-il / 2, -ig / 2, il, ig), ig / 2, ig / 2)
    t = QTransform()
    t.translate(cx, cy)
    t.rotate(angle)
    return t.map(outer.subtracted(inner))


def _draw_link(p, path, pen):
    r = path.boundingRect()
    p.setPen(QPen(QColor("#3d444c"), pen))
    p.setBrush(B.lgrad(r.topLeft(), r.bottomRight(), (0, "#ffffff"), (0.35, "#c3cbd4"),
                       (0.55, "#e9edf1"), (1, "#6b7580")))
    p.drawPath(path)
    B.gloss(p, path, QRectF(r.x(), r.y(), r.width(), r.height() * 0.5), 110)


def _sparks(p, cx, cy, n, r0, r1, width):
    p.setPen(QPen(QColor("#e02a1a"), width, Qt.SolidLine, Qt.RoundCap))
    for k in range(n):
        a = math.radians(135 + (k - (n - 1) / 2) * 38)
        for sgn in (1, -1):
            p.drawLine(QPointF(cx + sgn * math.cos(a) * r0, cy - sgn * math.sin(a) * r0),
                       QPointF(cx + sgn * math.cos(a) * r1, cy - sgn * math.sin(a) * r1))


def orphan(size):
    img, p = B.canvas(size)
    B.floor_shadow(p, 128, 230, 108, 16, 80)
    _draw_link(p, _link(80, 176, 118, 66, 21, -45), 1.8)
    _draw_link(p, _link(176, 80, 118, 66, 21, -45), 1.8)
    _sparks(p, 128, 128, 3, 14, 36, 6.0)
    p.end()
    return img


def orphan_16():
    img, p = B.canvas(16, 16)
    for cx, cy in ((4.3, 11.7), (11.7, 4.3)):
        path = _link(cx, cy, 8.2, 5.2, 1.8, -45)
        p.setPen(QPen(QColor("#1e2227"), 0.7))
        p.setBrush(B.lgrad(QPointF(cx - 4, cy - 4), QPointF(cx + 4, cy + 4),
                           (0, "#dfe4ea"), (1, "#3d444c")))
        p.drawPath(path)
    p.setPen(QPen(QColor("#ff2010"), 1.5, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(5.9, 5.9), QPointF(7.0, 7.0))
    p.drawLine(QPointF(9.0, 9.0), QPointF(10.1, 10.1))
    p.end()
    return img


# --- Uninstall: software box with a red minus badge ----------------------------------
def software_box(p, iso, W, D, H, width, tape=True):
    iso.box(0, 0, 0, W, D, H, "#eef4fb", "#5e95d6", "#3a6fb2", "#1b3f73", "#ffffff", width)
    t = side_plane(iso, D)
    disc = QPainterPath()
    disc.addEllipse(QPointF(W * 0.5, H * 0.5), 1.8, 1.8)
    hole = QPainterPath()
    hole.addEllipse(QPointF(W * 0.5, H * 0.5), 0.4, 0.4)
    dp = t.map(disc.subtracted(hole))
    r = dp.boundingRect()
    p.setPen(QPen(QColor("#6b7580"), 1.2))
    p.setBrush(B.lgrad(r.topLeft(), r.bottomRight(), (0, "#ffffff"), (0.3, "#d8e8ff"),
                       (0.5, "#ffe6f6"), (0.7, "#e0fff0"), (1, "#aab4c0")))
    p.drawPath(dp)
    if tape:
        face = [(W * 0.42, 0, H + 0.01), (W * 0.58, 0, H + 0.01), (W * 0.58, D, H + 0.01),
                (W * 0.42, D, H + 0.01)]
        iso.face(face, QBrush(QColor(90, 150, 220, 170)))
    front = poly_path([iso.pt(0, D, 0), iso.pt(W, D, 0), iso.pt(W, D, H), iso.pt(0, D, H)])
    fr = front.boundingRect()
    B.gloss(p, front, QRectF(fr.x(), fr.y(), fr.width(), fr.height() * 0.5), 70)


def uninstall(size):
    img, p = B.canvas(size)
    B.floor_shadow(p, 120, 216, 108, 22, 80)
    software_box(p, B.Iso(p, 108, 96, 17.0), 6.4, 4.4, 5.2, 1.6)
    badge = round_badge(p, 196, 190, 46, RED, "#7a0e08", 2.2)
    B.gloss(p, badge, QRectF(150, 144, 92, 46), 130)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#ffffff"))
    p.drawRoundedRect(QRectF(170, 182, 52, 16), 3, 3)
    p.end()
    return img


def uninstall_16():
    img, p = B.canvas(16, 16)
    iso = B.Iso(p, 4.6, 5.4, 0.95)
    iso.box(0, 0, 0, 6.2, 4.4, 5.0, "#eef4fb", "#5e95d6", "#3a6fb2", "#1b3f73", "#ffffff", 0.6)
    p.setPen(QPen(QColor("#7a0e08"), 0.6))
    p.setBrush(B.vgrad(8, 16, *RED))
    p.drawEllipse(QPointF(11.8, 11.8), 3.8, 3.8)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#ffffff"))
    p.drawRect(QRectF(9.6, 11.1, 4.4, 1.5))
    p.end()
    return img


# --- Environment: a list page (one PATH entry per line) with a blue % badge ---------
def envedit(size, family):
    img, p = B.canvas(size)
    B.floor_shadow(p, 112, 228, 96, 16, 80)
    x, y, w, h, fold = 36, 14, 150, 200, 34
    page = B._page(p, x, y, w, h, fold, "#ffffff", "#e4e8ec", "#8a929b")
    p.setPen(QPen(QColor("#8a929b"), 1.5))
    p.setBrush(B.vgrad(y, y + fold, (0, "#f7f9fb"), (1, "#c3c9d0")))
    p.drawPolygon(QPolygonF([QPointF(x + w - fold, y), QPointF(x + w - fold, y + fold),
                             QPointF(x + w, y + fold)]))
    p.setPen(Qt.NoPen)
    for i, (ln, col) in enumerate(((0.55, "#2a4d8f"), (0.7, "#2a4d8f"), (0.62, "#b00000"),
                                   (0.48, "#2a4d8f"), (0.66, "#2a4d8f"))):
        yy = y + 52 + i * 26
        p.setBrush(QColor("#9aa3ad"))
        p.drawEllipse(QPointF(x + 22, yy + 4), 4.5, 4.5)
        p.setBrush(QColor(col))
        p.drawRect(QRectF(x + 34, yy, w * ln, 8))
    B.gloss(p, page, QRectF(x, y, w, h * 0.5), 60)
    badge = round_badge(p, 192, 186, 48, BLUE, "#0b3a80", 2.2)
    B.gloss(p, badge, QRectF(144, 138, 96, 48), 130)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#ffffff"))
    p.drawPath(text_path("%", family, 192, 188, 50))
    p.end()
    return img


def envedit_16():
    img, p = B.canvas(16, 16)
    p.setPen(QPen(QColor("#8a929b"), 0.7))
    p.setBrush(QColor("#ffffff"))
    p.drawRect(QRectF(1.5, 0.5, 9.5, 13))
    p.setPen(Qt.NoPen)
    for i, col in enumerate(("#2a4d8f", "#2a4d8f", "#b00000", "#2a4d8f")):
        p.setBrush(QColor(col))
        p.drawRect(QRectF(3, 2.5 + i * 2.5, 6 if i != 1 else 4.5, 1.2))
    p.setPen(QPen(QColor("#0b3a80"), 0.6))
    p.setBrush(B.vgrad(8, 16, *BLUE))
    p.drawEllipse(QPointF(11.8, 11.8), 3.9, 3.9)
    p.setPen(QPen(QColor("#ffffff"), 1.0, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(13.3, 9.9), QPointF(10.3, 13.7))
    p.setBrush(QColor("#ffffff"))
    p.setPen(Qt.NoPen)
    p.drawEllipse(QPointF(10.4, 10.4), 0.85, 0.85)
    p.drawEllipse(QPointF(13.2, 13.2), 0.85, 0.85)
    p.end()
    return img


# --- Startup: software box with a green play badge ------------------------------------
def play_triangle(cx, cy, r):
    return poly_path([QPointF(cx - r * 0.5, cy - r * 0.866), QPointF(cx + r, cy),
                      QPointF(cx - r * 0.5, cy + r * 0.866)])


def startup(size):
    img, p = B.canvas(size)
    B.floor_shadow(p, 120, 216, 108, 22, 80)
    software_box(p, B.Iso(p, 108, 96, 17.0), 6.4, 4.4, 5.2, 1.6)
    badge = round_badge(p, 196, 190, 46, GREEN, "#1a5a14", 2.2)
    B.gloss(p, badge, QRectF(150, 144, 92, 46), 130)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#ffffff"))
    p.drawPath(play_triangle(201, 190, 24))
    p.end()
    return img


def startup_16():
    img, p = B.canvas(16, 16)
    iso = B.Iso(p, 4.6, 5.4, 0.95)
    iso.box(0, 0, 0, 6.2, 4.4, 5.0, "#eef4fb", "#5e95d6", "#3a6fb2", "#1b3f73", "#ffffff", 0.6)
    p.setPen(QPen(QColor("#1a5a14"), 0.6))
    p.setBrush(B.vgrad(8, 16, *GREEN))
    p.drawEllipse(QPointF(11.8, 11.8), 3.8, 3.8)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#ffffff"))
    p.drawPath(play_triangle(12.2, 11.8, 2.3))
    p.end()
    return img


# --- Installer: software box with a glossy green down arrow --------------------------
def down_arrow(cx, y0, y1, t, head, head_len):
    yh = y1 - head_len
    return poly_path([QPointF(cx - t, y0), QPointF(cx + t, y0), QPointF(cx + t, yh),
                      QPointF(cx + head, yh), QPointF(cx, y1), QPointF(cx - head, yh),
                      QPointF(cx - t, yh)])


def installer(size):
    img, p = B.canvas(size)
    B.floor_shadow(p, 124, 226, 104, 18, 80)
    software_box(p, B.Iso(p, 112, 118, 14.5), 6.2, 4.4, 4.2, 1.6, tape=False)
    draw_block_arrow(p, down_arrow(124, 6, 116, 22, 50, 52), GREEN, "#1a5a14", 9.0, 2.2)
    p.end()
    return img


def installer_16():
    img, p = B.canvas(16, 16)
    B.Iso(p, 6.3, 7.4, 1.1).box(0, 0, 0, 6.2, 4.4, 4.2, "#eef4fb", "#5e95d6", "#3a6fb2",
                                "#1b3f73", "#ffffff", 0.6)
    p.setPen(QPen(QColor("#1a5a14"), 0.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(B.vgrad(0, 9, *GREEN))
    p.drawPath(down_arrow(8.2, 0.5, 9.2, 1.7, 4.0, 4.0))
    p.end()
    return img


# --- Context Menu: classic popup menu, one row highlighted, with a mouse pointer ------------
ARROW = ((0, 0), (0, 29), (8, 22), (14, 36), (21, 33), (15, 20), (26, 20))
MENU_ICONS = (("#aad6ff", "#2a7fe0"), ("#b9f59a", "#3fb53a"), ("#ffffff", "#9aa5b1"),
              ("#ffd88a", "#e08a1a"), ("#ffb0a2", "#e02a1a"))


def pointer(p, x, y, k, pen, shadow):
    pts = [QPointF(x + a * k, y + b * k) for a, b in ARROW]
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0, 80))
    p.drawPolygon(QPolygonF([q + QPointF(shadow, shadow) for q in pts]))
    p.setPen(QPen(QColor("#15181c"), pen, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(B.vgrad(y, y + 36 * k, (0, "#ffffff"), (1, "#c3cbd4")))
    p.drawPolygon(QPolygonF(pts))


def ctxmenu(size):
    img, p = B.canvas(size)
    B.floor_shadow(p, 118, 238, 100, 12, 80)
    x, y, w, h = 20, 14, 166, 214
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0, 55))
    p.drawRect(QRectF(x + 7, y + 7, w, h))
    panel = QPainterPath()
    panel.addRect(QRectF(x, y, w, h))
    p.setPen(QPen(QColor("#6b7580"), 2.0))
    p.setBrush(B.vgrad(y, y + h, (0, "#ffffff"), (1, "#eef1f5")))
    p.drawPath(panel)
    p.setPen(Qt.NoPen)
    p.setBrush(B.vgrad(y, y + h, (0, "#f4f6f9"), (1, "#e1e6ec")))
    p.drawRect(QRectF(x + 1, y + 1, 40, h - 2))
    p.setPen(QPen(QColor("#c9d1da"), 1.5))
    p.drawLine(QPointF(x + 41, y + 1), QPointF(x + 41, y + h - 1))
    for i, (top, ln) in enumerate(zip((26, 60, 94, 142, 176), (96, 72, 104, 84, 62))):
        lit = i == 2
        if lit:
            row = QPainterPath()
            row.addRoundedRect(QRectF(x + 4, top, w - 8, 30), 4, 4)
            p.setPen(QPen(QColor("#1f5fb0"), 1.6))
            p.setBrush(B.vgrad(top, top + 30, (0, "#b6dcff"), (0.5, "#4a96ea"), (1, "#1f66c4")))
            p.drawPath(row)
            B.gloss(p, row, QRectF(x + 4, top, w - 8, 15), 120)
        c0, c1 = MENU_ICONS[i]
        p.setPen(QPen(QColor("#4a525c"), 1.3))
        p.setBrush(B.vgrad(top + 6, top + 24, (0, c0), (1, c1)))
        p.drawRoundedRect(QRectF(x + 11, top + 6, 18, 18), 3, 3)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ffffff" if lit else "#7d8894"))
        p.drawRoundedRect(QRectF(x + 52, top + 11, ln, 8), 4, 4)
    p.setPen(QPen(QColor("#b9c1cb"), 2.0))
    p.drawLine(QPointF(x + 48, y + 120), QPointF(x + w - 8, y + 120))
    p.setPen(QPen(QColor("#ffffff"), 1.5))
    p.drawLine(QPointF(x + 48, y + 122), QPointF(x + w - 8, y + 122))
    pointer(p, 128, 112, 2.8, 2.4, 5)
    p.end()
    return img


def ctxmenu_16():
    img, p = B.canvas(16, 16)
    p.setPen(QPen(QColor("#5b6570"), 0.8))
    p.setBrush(B.vgrad(0.5, 15, (0, "#ffffff"), (1, "#e3e8ee")))
    p.drawRect(QRectF(0.5, 0.5, 11.5, 14.5))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#e1e6ec"))
    p.drawRect(QRectF(1, 1, 3.2, 13.5))
    for i, (top, ln) in enumerate(zip((1.4, 4.0, 6.6, 11.0), (5.5, 4.2, 5.8, 4.6))):
        lit = i == 2
        if lit:
            p.setPen(QPen(QColor("#1f5fb0"), 0.6))
            p.setBrush(B.vgrad(top, top + 2.6, (0, "#8cc8ff"), (1, "#2a6fd0")))
            p.drawRect(QRectF(1, top, 10.6, 2.6))
        c0, c1 = MENU_ICONS[i if i < 3 else 3]
        p.setPen(QPen(QColor("#4a525c"), 0.5))
        p.setBrush(B.vgrad(top + 0.5, top + 2.1, (0, c0), (1, c1)))
        p.drawRect(QRectF(1.7, top + 0.5, 1.6, 1.6))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ffffff" if lit else "#7d8894"))
        p.drawRect(QRectF(5.0, top + 0.7, ln, 1.2))
    p.setPen(QPen(QColor("#b9c1cb"), 0.7))
    p.drawLine(QPointF(4.8, 9.9), QPointF(11, 9.9))
    pointer(p, 8.6, 6.0, 0.27, 0.6, 0.5)
    p.end()
    return img


# --- Empty folders: open manila folder with nothing inside -----------------------------
def empty(size):
    img, p = B.canvas(size)
    B.floor_shadow(p, 128, 228, 112, 18, 85)
    x, y, w, h = 18, 34, 208, 184
    back = folder_back(x, y, w, h, 76, 20)
    p.setPen(QPen(QColor("#8a6414"), 1.8))
    p.setBrush(B.vgrad(y, y + h, (0, "#e8bf55"), (1, "#b8841f")))
    p.drawPath(back)
    inner = QRectF(x + 10, y + 30, w - 20, h - 40)
    p.setPen(Qt.NoPen)
    p.setBrush(B.vgrad(inner.top(), inner.bottom(), (0, "#a9761a"), (1, "#d9a83c")))
    p.drawRect(inner)
    front = poly_path([QPointF(x + 30, y + 88), QPointF(x + w + 20, y + 88),
                       QPointF(x + w, y + h), QPointF(x, y + h)])
    p.setPen(QPen(QColor("#8a6414"), 1.8))
    p.setBrush(B.vgrad(y + 88, y + h, (0, "#fff2c0"), (0.5, "#f8d879"), (1, "#e2ae3e")))
    p.drawPath(front)
    B.gloss(p, front, QRectF(x, y + 88, w + 20, (h - 88) * 0.5), 130)
    p.end()
    return img


def empty_16():
    img, p = B.canvas(16, 16)
    p.setPen(QPen(QColor("#8a6414"), 0.7))
    p.setBrush(B.vgrad(2, 15, (0, "#e8bf55"), (1, "#b8841f")))
    p.drawPath(folder_back(0.5, 2, 14, 12.5, 5, 1.6))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#a9761a"))
    p.drawRect(QRectF(1.4, 4.4, 12.2, 3.2))
    p.setPen(QPen(QColor("#8a6414"), 0.7))
    p.setBrush(B.vgrad(7, 15, (0, "#fff2c0"), (1, "#e8b448")))
    p.drawPolygon(QPolygonF([QPointF(2.5, 7.5), QPointF(15.5, 7.5), QPointF(14.5, 14.5),
                             QPointF(0.5, 14.5)]))
    p.end()
    return img


# --- Largest files: page with descending size bars -------------------------------------
def largest(size):
    img, p = B.canvas(size)
    B.floor_shadow(p, 130, 238, 100, 14, 90)
    x, y, w, h, fold = 34, 14, 180, 222, 36
    page = B._page(p, x, y, w, h, fold, "#ffffff", "#e4e8ec", "#8a929b")
    p.setBrush(B.vgrad(y, y + fold, (0, "#f7f9fb"), (1, "#c3c9d0")))
    p.drawPolygon(QPolygonF([QPointF(x + w - fold, y), QPointF(x + w - fold, y + fold),
                             QPointF(x + w, y + fold)]))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#2a4d8f"))
    p.drawRect(QRectF(x + 16, y + 18, 80, 10))
    for i, ln in enumerate((150, 118, 88, 62, 40)):
        by = y + 50 + i * 33
        bar = QPainterPath()
        bar.addRect(QRectF(x + 14, by, ln, 22))
        p.setPen(QPen(QColor("#7a2a0e" if i == 0 else "#0b3f86"), 1.2))
        p.setBrush(B.vgrad(by, by + 22, *(((0, "#ffb070"), (0.5, "#f06a28"), (1, "#b83a0c"))
                                          if i == 0 else BLUE)))
        p.drawPath(bar)
        B.gloss(p, bar, QRectF(x + 14, by, ln, 11), 130)
    B.gloss(p, page, QRectF(x, y, w, h * 0.4), 50)
    p.end()
    return img


def largest_16():
    img, p = B.canvas(16, 16)
    path = QPainterPath()
    path.moveTo(1.5, 0.5)
    path.lineTo(11, 0.5)
    path.lineTo(14.5, 4)
    path.lineTo(14.5, 15.5)
    path.lineTo(1.5, 15.5)
    path.closeSubpath()
    p.setPen(QPen(QColor("#7d858e"), 1.0))
    p.setBrush(B.vgrad(0, 16, (0, "#ffffff"), (1, "#dde2e7")))
    p.drawPath(path)
    p.setPen(Qt.NoPen)
    for i, (ln, c) in enumerate(((11, "#e0561c"), (8, "#2a7fe0"), (5, "#2a7fe0"))):
        p.setBrush(QColor(c))
        p.drawRect(QRectF(2.5, 4.5 + i * 3.6, ln, 2.4))
    p.end()
    return img


# --- Temperatures: glass thermometer on a scale plate -----------------------------------
def temps(size):
    img, p = B.canvas(size)
    B.floor_shadow(p, 128, 240, 72, 12, 90)
    plate = QPainterPath()
    plate.addRoundedRect(QRectF(66, 8, 124, 200), 18, 18)
    p.setPen(QPen(QColor("#6f7a86"), 1.8))
    p.setBrush(B.vgrad(8, 208, (0, "#ffffff"), (1, "#d5dbe2")))
    p.drawPath(plate)
    B.gloss(p, plate, QRectF(66, 8, 124, 90), 90)
    p.setPen(QPen(QColor("#5f6a76"), 3.0))
    for i in range(9):
        y = 30 + i * 18
        p.drawLine(QPointF(152, y), QPointF(152 + (24 if i % 2 == 0 else 13), y))
    tube = QPainterPath()
    tube.addRoundedRect(QRectF(108, 16, 40, 190), 20, 20)
    p.setPen(Qt.NoPen)
    p.setBrush(B.lgrad(QPointF(108, 0), QPointF(148, 0), (0, QColor(225, 235, 245, 230)),
                       (0.5, QColor(255, 255, 255, 240)), (1, QColor(190, 202, 215, 230))))
    p.drawPath(tube)
    p.setBrush(B.lgrad(QPointF(118, 0), QPointF(138, 0), (0, "#b8140b"), (0.4, "#ff6a55"),
                       (1, "#a8140b")))
    p.drawRect(QRectF(118, 84, 20, 124))
    p.setPen(QPen(QColor("#4a525c"), 2.0))
    p.setBrush(Qt.NoBrush)
    p.drawPath(tube)
    bulb = QPainterPath()
    bulb.addEllipse(QPointF(128, 206), 36, 36)
    p.setPen(QPen(QColor("#7a0e08"), 2.2))
    p.setBrush(B.lgrad(QPointF(92, 170), QPointF(164, 242), (0, "#ff9a8a"), (0.45, "#e02a1a"),
                       (1, "#8a1006")))
    p.drawPath(bulb)
    B.gloss(p, bulb, QRectF(92, 170, 72, 34), 150)
    shine = QPainterPath()
    shine.addRoundedRect(QRectF(114, 26, 7, 150), 3.5, 3.5)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 170))
    p.drawPath(shine)
    p.end()
    return img


def temps_16():
    img, p = B.canvas(16, 16)
    p.setPen(QPen(QColor("#5f6a76"), 0.8))
    for i, y in enumerate((2.0, 4.0, 6.0, 8.0)):
        p.drawLine(QPointF(10.6, y), QPointF(12.8 if i % 2 == 0 else 11.8, y))
    p.setPen(QPen(QColor("#4a525c"), 0.8))
    p.setBrush(QColor("#ffffff"))
    p.drawRoundedRect(QRectF(6, 0.5, 4, 12), 2, 2)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#e02a1a"))
    p.drawRect(QRectF(7.1, 4, 1.8, 8))
    p.setPen(QPen(QColor("#7a0e08"), 0.7))
    p.setBrush(B.vgrad(9, 16, (0, "#ff6a55"), (1, "#a8140b")))
    p.drawEllipse(QPointF(8, 12.3), 3.2, 3.2)
    p.end()
    return img


# --- Toolbar: refresh, find, import, export, restart Explorer ---------------------------
def refresh(size):
    img, p = B.canvas(size)
    cycle_arrows(p, 128, 128, 80, 38, GREEN, "#1a5a14", halo=9, pen=2.2)
    p.end()
    return img


def refresh_16():
    img, p = B.canvas(16, 16)
    cycle_arrows(p, 8, 8, 5.2, 2.5, GREEN, "#1a5a14", pen=0.6)
    p.end()
    return img


def _magnifier(p, cx, cy, r, ring, hlen, hw, pen):
    p.save()
    p.translate(cx, cy)
    p.rotate(45)
    handle = QPainterPath()
    handle.addRoundedRect(QRectF(r + ring * 0.2, -hw / 2, hlen, hw), hw * 0.4, hw * 0.4)
    p.setPen(QPen(QColor("#111111"), pen))
    p.setBrush(B.vgrad(-hw / 2, hw / 2, (0, "#6b6f76"), (0.4, "#2c2f33"), (1, "#0d0e10")))
    p.drawPath(handle)
    p.setBrush(B.vgrad(-hw / 2, hw / 2, (0, "#ffffff"), (0.5, "#9aa5b1"), (1, "#4a525c")))
    p.drawRect(QRectF(r + ring * 0.2, -hw * 0.6, hlen * 0.22, hw * 1.2))
    p.restore()
    lens = QPainterPath()
    lens.addEllipse(QPointF(cx, cy), r, r)
    p.setPen(Qt.NoPen)
    p.setBrush(B.lgrad(QPointF(cx - r, cy - r), QPointF(cx + r, cy + r),
                       (0, QColor(210, 235, 255, 200)), (1, QColor(120, 175, 230, 200))))
    p.drawPath(lens)
    B.gloss(p, lens, QRectF(cx - r, cy - r, 2 * r, r), 170)
    outer = QPainterPath()
    outer.addEllipse(QPointF(cx, cy), r + ring / 2, r + ring / 2)
    inner = QPainterPath()
    inner.addEllipse(QPointF(cx, cy), r - ring / 2, r - ring / 2)
    p.setPen(QPen(QColor("#3d444c"), pen))
    p.setBrush(B.lgrad(QPointF(cx - r, cy - r), QPointF(cx + r, cy + r),
                       (0, "#ffffff"), (0.45, "#b9c1cb"), (0.6, "#e9edf1"), (1, "#5a6270")))
    p.drawPath(outer.subtracted(inner))


def find(size):
    img, p = B.canvas(size)
    B.floor_shadow(p, 150, 236, 90, 12, 80)
    _magnifier(p, 100, 100, 66, 22, 104, 32, 2.0)
    p.end()
    return img


def find_16():
    img, p = B.canvas(16, 16)
    _magnifier(p, 6.2, 6.2, 4.2, 1.8, 6.4, 2.8, 0.6)
    p.end()
    return img


def import_(size):
    img, p = B.canvas(size)
    B.floor_shadow(p, 150, 236, 100, 14, 90)
    xml_page(p, 84, 20, 150, 204, 34)
    draw_block_arrow(p, block_arrow(8, 164, 150, 24, 48, 52), BLUE, "#0b3f86", 6.0, 2.0)
    p.end()
    return img


def export(size):
    img, p = B.canvas(size)
    B.floor_shadow(p, 110, 236, 100, 14, 90)
    xml_page(p, 20, 20, 150, 204, 34)
    draw_block_arrow(p, block_arrow(92, 250, 150, 24, 48, 52), GREEN, "#1a5a14", 6.0, 2.0)
    p.end()
    return img


def _page16(p, x):
    path = QPainterPath()
    path.moveTo(x, 0.5)
    path.lineTo(x + 7, 0.5)
    path.lineTo(x + 10, 3.5)
    path.lineTo(x + 10, 15.5)
    path.lineTo(x, 15.5)
    path.closeSubpath()
    p.setPen(QPen(QColor("#7d858e"), 1.0))
    p.setBrush(B.vgrad(0, 16, (0, "#ffffff"), (1, "#dde2e7")))
    p.drawPath(path)
    p.setPen(QPen(QColor("#2a4d8f"), 1.0))
    p.setBrush(Qt.NoBrush)
    p.drawPolyline(QPolygonF([QPointF(x + 3.5, 3), QPointF(x + 2, 4.5), QPointF(x + 3.5, 6)]))
    p.drawPolyline(QPolygonF([QPointF(x + 6.5, 3), QPointF(x + 8, 4.5), QPointF(x + 6.5, 6)]))


def import_16():
    img, p = B.canvas(16, 16)
    _page16(p, 5.5)
    p.setPen(QPen(QColor("#0b3f86"), 0.7))
    p.setBrush(B.vgrad(6, 15, *BLUE))
    p.drawPath(block_arrow(0.5, 11, 10.5, 1.8, 4, 4.2))
    p.end()
    return img


def export_16():
    img, p = B.canvas(16, 16)
    _page16(p, 0.5)
    p.setPen(QPen(QColor("#1a5a14"), 0.7))
    p.setBrush(B.vgrad(6, 15, *GREEN))
    p.drawPath(block_arrow(5, 15.5, 10.5, 1.8, 4, 4.2))
    p.end()
    return img


def explorer(size):
    img, p = B.canvas(size)
    B.floor_shadow(p, 120, 226, 110, 18, 85)
    manila(p, 10, 26, 200, 180, 70, 20, 1.8)
    cycle_arrows(p, 186, 178, 44, 22, GREEN, "#1a5a14", halo=9, pen=2.0)
    p.end()
    return img


def explorer_16():
    img, p = B.canvas(16, 16)
    manila(p, 0.5, 1.5, 13, 11.5, 5, 1.6, 0.7, gloss=False)
    cycle_arrows(p, 11.4, 11.4, 3.2, 1.7, GREEN, "#1a5a14", pen=0.6)
    p.end()
    return img


def all_icons():
    fam = B.bold_family()
    return {
        "tab_initcfg": B.build(initcfg, initcfg_16),
        "tab_installer": B.build(installer, installer_16),
        "tab_repeat": B.build(lambda s: repeat(s, fam), repeat_16),
        "tab_keydiag": B.build(lambda s: keydiag(s, fam), keydiag_16),
        "tab_system": B.build(system, system_16),
        "tab_gpu": B.build(gpu, gpu_16),
        "tab_temps": B.build(temps, temps_16),
        "tab_files": B.build(files, files_16),
        "tab_registry": B.build(registry, registry_16),
        "tab_orphans": B.build(orphan, orphan_16),
        "tab_uninstall": B.build(uninstall, uninstall_16),
        "tab_startup": B.build(startup, startup_16),
        "tab_envedit": B.build(lambda s: envedit(s, fam), envedit_16),
        "tab_ctxmenu": B.build(ctxmenu, ctxmenu_16),
        "tab_empty": B.build(empty, empty_16),
        "tab_largest": B.build(largest, largest_16),
        "act_refresh": B.build(refresh, refresh_16),
        "act_find": B.build(find, find_16),
        "act_import": B.build(import_, import_16),
        "act_export": B.build(export, export_16),
        "act_explorer": B.build(explorer, explorer_16),
    }


if __name__ == "__main__":
    app = QApplication(sys.argv)
    out = sys.argv[1] if len(sys.argv) > 1 else HERE
    for name, frames in all_icons().items():
        path = os.path.join(out, f"{name}.ico")
        B.save_ico(path, frames)
        print("wrote", path)
