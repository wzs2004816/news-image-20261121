#!/usr/bin/env python3
"""Draw Saturday 21 November 2026 as a one-page newspaper front page.

Pure standard library. No network, no clock, no randomness: the same
command always produces the same bytes. The glyph bitmaps and the world
land mask come from the sibling modules fonts and worldmap.

Layout: a black top bar, a big serif masthead, a UTC timeline strip,
three hero stories with drawn art panels, eight mid stories in two rows,
then a bottom band with a dotted world map, a date-check note and a
31-item "also on Saturday" list, and a sources footer.
"""

import base64
import json
import math
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fonts
import worldmap

WIDTH = 1024
HEIGHT = 1024
LEFT = 26
RIGHT = 998

PAPER = (247, 243, 232)
INK = (17, 17, 17)
GREY = (96, 92, 82)
RED = (176, 42, 32)
GREEN = (46, 110, 58)
BLUE = (31, 78, 121)
GOLD = (176, 132, 32)
PURPLE = (90, 60, 120)
BROWN = (150, 90, 40)
TEAL = (0, 120, 120)
NAVY = (16, 28, 46)
GRID = (40, 52, 74)
STEEL = (90, 120, 160)
BARRED = (200, 60, 44)
LINECOL = (255, 220, 120)
PINKRED = (255, 120, 100)
BEIGE = (226, 214, 188)
DARKBAR = (60, 52, 40)
NIGHT = (14, 14, 24)
SKY = (52, 48, 66)
BLUEGREY = (31, 58, 95)
ORANGE = (255, 150, 40)
MOON = (240, 190, 130)
WINDOW = (255, 220, 160)
WIN2 = (240, 190, 110)
LAND = (150, 140, 115)
WHITE = (255, 255, 255)


class Canvas:
    """A 1024x1024 RGB raster with a few drawing primitives."""

    def __init__(self, w, h, bg):
        self.w = w
        self.h = h
        self.buf = bytearray(bytes(bg) * (w * h))

    def _pos(self, x, y):
        return (y * self.w + x) * 3

    def blend(self, x, y, rgb, alpha):
        """Blend one pixel over the paper; alpha 0..255."""
        if alpha <= 0 or x < 0 or y < 0 or x >= self.w or y >= self.h:
            return
        i = self._pos(x, y)
        if alpha >= 255:
            self.buf[i] = rgb[0]
            self.buf[i + 1] = rgb[1]
            self.buf[i + 2] = rgb[2]
        else:
            inv = 255 - alpha
            self.buf[i] = (rgb[0] * alpha + self.buf[i] * inv) // 255
            self.buf[i + 1] = (rgb[1] * alpha + self.buf[i + 1] * inv) // 255
            self.buf[i + 2] = (rgb[2] * alpha + self.buf[i + 2] * inv) // 255

    def put(self, x, y, rgb):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = self._pos(x, y)
            self.buf[i] = rgb[0]
            self.buf[i + 1] = rgb[1]
            self.buf[i + 2] = rgb[2]

    def fill(self, x0, y0, x1, y1, rgb):
        """Fill rectangle; x1/y1 exclusive; clipped to the canvas."""
        x0 = max(0, x0)
        y0 = max(0, y0)
        x1 = min(self.w, x1)
        y1 = min(self.h, y1)
        if x0 >= x1 or y0 >= y1:
            return
        row = bytes(rgb) * (x1 - x0)
        for y in range(y0, y1):
            i = self._pos(x0, y)
            self.buf[i:i + len(row)] = row

    def frame(self, x0, y0, x1, y1, rgb, thick=1):
        self.fill(x0, y0, x1, y0 + thick, rgb)
        self.fill(x0, y1 - thick, x1, y1, rgb)
        self.fill(x0, y0, x0 + thick, y1, rgb)
        self.fill(x1 - thick, y0, x1, y1, rgb)

    def disc(self, cx, cy, r, rgb):
        """Filled circle of radius r (floats allowed)."""
        r2 = r * r
        ri = int(math.ceil(r))
        for dy in range(-ri, ri + 1):
            dx = int(math.sqrt(max(0.0, r2 - dy * dy)))
            self.fill(cx - dx, cy + dy, cx + dx + 1, cy + dy + 1, rgb)

    def ring(self, cx, cy, r_out, r_in, rgb):
        """Annulus: r_in <= distance <= r_out."""
        ri = int(math.ceil(r_out))
        for dy in range(-ri, ri + 1):
            for dx in range(-ri, ri + 1):
                d2 = dx * dx + dy * dy
                if r_in * r_in <= d2 <= r_out * r_out:
                    self.put(cx + dx, cy + dy, rgb)

    def ellipse(self, cx, cy, rx, ry, rgb):
        for dy in range(-ry, ry + 1):
            dx = int(rx * math.sqrt(max(0.0, 1.0 - (dy * dy) / float(ry * ry))))
            self.fill(cx - dx, cy + dy, cx + dx + 1, cy + dy + 1, rgb)

    def ellipse_rot(self, cx, cy, rx, ry, angle_deg, rgb):
        """Filled ellipse rotated by angle_deg (clockwise in screen space)."""
        a = math.radians(angle_deg)
        ca, sa = math.cos(a), math.sin(a)
        r = max(rx, ry)
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                u = dx * ca - dy * sa
                v = dx * sa + dy * ca
                if (u * u) / float(rx * rx) + (v * v) / float(ry * ry) <= 1.0:
                    self.put(cx + dx, cy + dy, rgb)

    def thick_line(self, x0, y0, x1, y1, rgb, width):
        """A line of the given width, drawn as stamped discs."""
        dx, dy = x1 - x0, y1 - y0
        steps = max(abs(dx), abs(dy), 1)
        rad = max(1, width // 2)
        for i in range(steps + 1):
            t = i / float(steps)
            x = int(round(x0 + dx * t))
            y = int(round(y0 + dy * t))
            self.disc(x, y, rad, rgb)

    def polyline(self, points, rgb, width):
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            self.thick_line(x0, y0, x1, y1, rgb, width)

    def thick_segment(self, x0, y0, x1, y1, rgb, width):
        """One straight segment of exact perpendicular width, as a quad."""
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length == 0:
            self.disc(x0, y0, width / 2.0, rgb)
            return
        ox = -dy / length * width / 2.0
        oy = dx / length * width / 2.0
        self.polygon([(round(x0 + ox), round(y0 + oy)),
                      (round(x1 + ox), round(y1 + oy)),
                      (round(x1 - ox), round(y1 - oy)),
                      (round(x0 - ox), round(y0 - oy))], rgb)

    def polygon(self, points, rgb):
        """Scanline fill of a simple polygon."""
        if len(points) < 3:
            return
        ys = [p[1] for p in points]
        for y in range(min(ys), max(ys) + 1):
            xs = []
            n = len(points)
            for i in range(n):
                x0, y0 = points[i]
                x1, y1 = points[(i + 1) % n]
                if y0 == y1:
                    continue
                if (y0 <= y < y1) or (y1 <= y < y0):
                    t = (y - y0) / float(y1 - y0)
                    xs.append(x0 + t * (x1 - x0))
            xs.sort()
            for i in range(0, len(xs) - 1, 2):
                self.fill(int(math.ceil(xs[i])), y,
                          int(math.floor(xs[i + 1])) + 1, y + 1, rgb)

    def star(self, cx, cy, r_out, r_in, points, rgb, rotation=-90.0):
        """Star with `points` spikes; rotation in degrees, -90 = up."""
        pts = []
        for i in range(points * 2):
            ang = math.radians(rotation + i * 180.0 / points)
            r = r_out if i % 2 == 0 else r_in
            pts.append((cx + int(round(r * math.cos(ang))),
                        cy + int(round(r * math.sin(ang)))))
        self.polygon(pts, rgb)

    def png(self):
        """Encode the buffer as a PNG (truecolour, no filtering)."""
        raw = bytearray()
        stride = self.w * 3
        for y in range(self.h):
            raw.append(0)
            raw += self.buf[y * stride:(y + 1) * stride]

        def chunk(kind, data):
            return (struct.pack(">I", len(data)) + kind + data +
                    struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

        ihdr = struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
                chunk(b"IDAT", zlib.compress(bytes(raw), 9)) +
                chunk(b"IEND", b""))


# ---------------------------------------------------------------- fonts ---

_FONT_CACHE = {}


def _load_font(name):
    if name in _FONT_CACHE:
        return _FONT_CACHE[name]
    raw = json.loads(zlib.decompress(base64.b64decode(fonts.FONTS[name])))
    glyphs = {}
    for ch, g in raw["glyphs"].items():
        px = base64.b64decode(g["px"]) if "px" in g else b""
        nib = []
        for b in px:
            nib.append(b >> 4)
            nib.append(b & 15)
        glyphs[ch] = {"adv": g["adv"], "w": g.get("w", 0), "h": g.get("h", 0),
                      "x0": g.get("x0", 0), "y0": g.get("y0", 0), "nib": nib}
    font = {"ascent": raw["ascent"], "descent": raw["descent"],
            "glyphs": glyphs}
    _FONT_CACHE[name] = font
    return font


def text_width(font_name, text, tracking=0):
    """Advance width of a string; the middle dot uses the '.' advance."""
    f = _load_font(font_name)
    g = f["glyphs"]
    total = 0
    for ch in text:
        if ch == "\u00b7":
            ch = "."
        gl = g.get(ch)
        if gl is not None:
            total += gl["adv"]
    return total + tracking * max(0, len(text) - 1)


def draw_text(cv, x, baseline, font_name, text, color, tracking=0):
    """Draw text with the pen starting at x; returns the end x."""
    f = _load_font(font_name)
    g = f["glyphs"]
    pen = x
    for ch in text:
        if ch == "\u00b7":
            # Middle dot: a small filled dot floating above the baseline.
            dot = g["."]
            cy = baseline - 6
            cv.disc(pen + dot["adv"] // 2, cy, 2, color)
            pen += dot["adv"] + tracking
            continue
        gl = g.get(ch)
        if gl is None:
            continue
        w, h = gl["w"], gl["h"]
        if w and h:
            nib = gl["nib"]
            top = baseline - f["ascent"] + gl["y0"]
            left = pen + gl["x0"]
            for row in range(h):
                base = row * w
                yy = top + row
                if yy < 0 or yy >= HEIGHT:
                    continue
                for col in range(w):
                    v = nib[base + col]
                    if v:
                        cv.blend(left + col, yy, color, v * 17)
        pen += gl["adv"] + tracking
    return pen


def draw_bold_text(cv, x, baseline, font_name, text, color, tracking=0):
    """Fake bold: draw the text twice, one pixel apart; returns end x."""
    draw_text(cv, x, baseline, font_name, text, color, tracking)
    return draw_text(cv, x + 1, baseline, font_name, text, color, tracking)


def wrap_lines(font_name, text, max_width, tracking=0):
    """Greedy word wrap; returns a list of line strings."""
    lines = []
    current = ""
    for word in text.split(" "):
        trial = word if not current else current + " " + word
        if text_width(font_name, trial, tracking) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


# ----------------------------------------------------------------- map ----

def land_cells():
    """Decode the bit-packed land mask into a set of (col, row).

    Bits are packed LSB-first within each byte: bit i of the stream is
    (byte[i // 8] >> (i % 8)) & 1, where i = row * MAP_W + col.
    """
    raw = base64.b64decode(worldmap.MAP_BITS)
    land = set()
    for row in range(worldmap.MAP_H):
        for col in range(worldmap.MAP_W):
            i = row * worldmap.MAP_W + col
            if (raw[i // 8] >> (i % 8)) & 1:
                land.add((col, row))
    return land


def draw_map(cv, land):
    """Dotted world map in the bottom-left box, with story dots."""
    cv.frame(22, 728, 360, 856, INK, 1)
    cell_w = 332.0 / worldmap.MAP_W
    cell_h = 121.0 / worldmap.MAP_H
    for (col, row) in land:
        x0 = math.floor(25 + col * cell_w)
        x1 = math.ceil(25 + (col + 1) * cell_w)
        y0 = math.floor(732 + row * cell_h)
        y1 = math.ceil(732 + (row + 1) * cell_h)
        cv.fill(x0, y0, x1, y1, LAND)
    dots = [(91, 781, RED, 8), (123, 768, BLUE, 7), (147, 816, BROWN, 7),
            (193, 760, PURPLE, 7), (196, 763, GOLD, 7), (221, 762, RED, 8),
            (232, 781, RED, 8), (244, 781, RED, 8), (319, 772, GOLD, 7),
            (323, 834, TEAL, 7)]
    for (cx, cy, color, r_out) in dots:
        cv.ring(cx, cy, r_out, 4, color)
        cv.disc(cx, cy, 3, color)


# ------------------------------------------------------------ hero art ----

def art_markets(cv, x):
    """Falling bar chart with a yellow trend line and a red -3.7%."""
    cv.fill(x, 188, x + 300, 292, NAVY)
    for gy in (206, 224, 242, 260, 278):
        cv.fill(x + 1, gy, x + 299, gy + 1, GRID)
    tops = [196, 205, 212, 224, 216, 234, 244, 258]
    for i, top in enumerate(tops):
        bx = x + 12 + i * 34
        cv.fill(bx, top, bx + 28, 282, STEEL if i < 5 else BARRED)
    line = [(x + 25, 192), (x + 45, 196), (x + 65, 200), (x + 92, 207),
            (x + 112, 213), (x + 126, 218), (x + 152, 214), (x + 169, 215),
            (x + 184, 223), (x + 199, 231), (x + 214, 235), (x + 232, 240),
            (x + 252, 247)]
    for (x0, y0), (x1, y1) in zip(line, line[1:]):
        cv.thick_segment(x0, y0, x1, y1, LINECOL, 4)
    cv.disc(x + 259, 250, 5, LINECOL)
    draw_text(cv, x + 14, 221, "serif_bold_26", "-3.7%", PINKRED)
    cv.frame(x, 188, x + 300, 292, INK, 1)


def art_wanted(cv, x):
    """Wanted-poster: beige card, mugshot bars, gold star, WANTED."""
    cv.fill(x, 188, x + 300, 292, BEIGE)
    cv.frame(x, 188, x + 300, 292, INK, 1)
    for i in range(7):
        bx = x + 26 + i * 38
        cv.fill(bx, 202, bx + 8, 278, DARKBAR)
    cx, cy = x + 149, 234
    cv.star(cx, cy, 30, 13, 5, GOLD)
    cv.disc(cx, cy, 11, BEIGE)
    cv.disc(cx, cy, 5, GOLD)
    word = "WANTED"
    wx = cx - text_width("sans_bold_13", word) // 2 + 1
    draw_text(cv, wx, 279, "sans_bold_13", word, INK)
    # Inner frame: top and left 2px, bottom and right 1px.
    cv.fill(x + 8, 196, x + 292, 198, INK)
    cv.fill(x + 8, 283, x + 292, 284, INK)
    cv.fill(x + 8, 196, x + 10, 284, INK)
    cv.fill(x + 291, 196, x + 292, 284, INK)


def art_skyline(cv, x):
    """Night skyline, missile arc and two orange bursts over the city."""
    cv.fill(x, 188, x + 300, 292, SKY)
    # Seven dark towers; window grids are 2x3 warm panes, first row at
    # top+6, pitch 10, last row no lower than y=267.
    buildings = [
        (1, 39, 236, [5, 15, 25, 35]),
        (47, 25, 218, [49, 59]),
        (76, 48, 240, [81, 91, 101, 111]),
        (128, 30, 212, [133, 143, 153]),
        (162, 42, 232, [167, 177, 187, 197]),
        (208, 34, 220, [213, 223, 233]),
        (246, 40, 238, [251, 261, 271, 281]),
    ]
    for (bx, bw, top, cols) in buildings:
        cv.fill(x + bx, top, x + bx + bw, 280, NIGHT)
        wy = top + 6
        while wy <= 267:
            for wx in cols:
                cv.fill(x + wx, wy, x + wx + 2, wy + 3, WIN2)
            wy += 10
    cv.fill(x, 280, x + 300, 292, BLUEGREY)
    for (sx, sy) in [(24, 206), (80, 218), (150, 202), (210, 214)]:
        cv.fill(x + sx - 1, sy, x + sx + 2, sy + 1, WHITE)
        cv.fill(x + sx, sy - 1, x + sx + 1, sy + 2, WHITE)
    cv.star(x + 120, 232, 22, 11, 8, ORANGE, rotation=0.0)
    cv.star(x + 232, 246, 26, 13, 8, ORANGE, rotation=0.0)
    cv.thick_segment(x + 40, 277, x + 120, 232, WINDOW, 2)
    cv.thick_segment(x + 120, 232, x + 196, 254, WINDOW, 2)
    cv.disc(x + 120, 232, 6, LINECOL)
    cv.disc(x + 232, 246, 6, LINECOL)
    cv.disc(x + 196, 254, 4, WHITE)
    cv.disc(x + 270, 210, 13, MOON)
    cv.fill(x + 267, 208, x + 270, 209, WHITE)
    cv.fill(x + 268, 207, x + 269, 210, WHITE)
    cv.frame(x, 188, x + 300, 292, INK, 1)


# -------------------------------------------------------------- mid icons --

def draw_icon(cv, ix, iy, kind, bg):
    """A 44x44 coloured square with a white pictogram."""
    cv.fill(ix, iy, ix + 44, iy + 44, bg)
    cx, cy = ix + 22, iy + 22
    if kind == "burst":
        cv.star(cx, cy, 15, 6.5, 12, WHITE)
    elif kind == "leaf":
        cv.ellipse_rot(cx, cy - 1, 13, 6, -17, WHITE)
        cv.thick_line(ix + 10, iy + 27, ix + 34, iy + 17, WHITE, 2)
    elif kind == "chip":
        cv.fill(ix + 11, iy + 11, ix + 33, iy + 33, WHITE)
        for dx in (5, 17, 29):
            cv.fill(ix + dx, iy + 3, ix + dx + 4, iy + 9, WHITE)
            cv.fill(ix + dx, iy + 35, ix + dx + 4, iy + 41, WHITE)
    elif kind == "game":
        cv.fill(ix + 6, iy + 11, ix + 38, iy + 33, WHITE)
        cv.disc(ix + 13, iy + 22, 4, PAPER)
        cv.disc(ix + 31, iy + 22, 4, PAPER)
    elif kind == "ship":
        cv.fill(ix + 19, iy + 7, ix + 25, iy + 19, WHITE)
        cv.disc(ix + 29, iy + 9, 3, ORANGE)
        cv.polygon([(ix + 5, iy + 31), (ix + 42, iy + 31),
                    (ix + 36, iy + 39), (ix + 10, iy + 39)], WHITE)
    elif kind == "pin":
        cv.disc(cx, cy - 4, 10, WHITE)
        cv.polygon([(cx - 9, cy), (cx + 9, cy), (cx, cy + 16)], WHITE)
        cv.disc(cx, cy - 4, 3, bg)
    elif kind == "sigma":
        cv.fill(ix + 7, iy + 7, ix + 37, iy + 11, WHITE)
        cv.fill(ix + 7, iy + 33, ix + 37, iy + 37, WHITE)
        cv.polygon([(ix + 8, iy + 11), (ix + 19, iy + 11),
                    (ix + 37, iy + 22), (ix + 29, iy + 22)], WHITE)
        cv.polygon([(ix + 29, iy + 22), (ix + 37, iy + 22),
                    (ix + 17, iy + 33), (ix + 9, iy + 33)], WHITE)
    elif kind == "cross":
        cv.fill(ix + 18, iy + 6, ix + 26, iy + 38, WHITE)
        cv.fill(ix + 6, iy + 18, ix + 38, iy + 26, WHITE)


# --------------------------------------------------------------- content ----

MASTHEAD = "SATURDAY 21 NOVEMBER 2026"
SUBHEAD = ("The world in one day \u00b7 every story here happened, or was "
           "first reported, on this Saturday.")

TIMELINE = [("00:48", "Tax on AI centres"),
            ("05:40", "Riyadh under fire"),
            ("06:32", "Killer-robot rules"),
            ("06:44", "French police law"),
            ("15:35", "Cartel boss seized")]

HEROES = [
    {"art": "markets", "kicker": "MARKETS - NEW YORK", "color": RED,
     "headline": ["Markets fall", "into correction"],
     "summary": ["S&P -3.7%, Nikkei -5.1%;", "Nasdaq wipes out 2026 gains."],
     "source": "OneTurn - BBC"},
    {"art": "wanted", "kicker": "JUSTICE - MEXICO", "color": RED,
     "headline": ["Mexico seizes", "cartel boss"],
     "summary": ["El Chapo Isidro held;", "FBI most-wanted, gun battles."],
     "source": "AP - BBC"},
    {"art": "skyline", "kicker": "WAR - UKRAINE", "color": RED,
     "headline": ["Missile hits", "his hometown"],
     "summary": ["2 killed, 60 hurt;", "Kryvyi Rih hit; Poland too."],
     "source": "AP - CBC"},
]

MIDS = [
    {"kicker": "MIDDLE EAST - RIYADH", "color": RED, "icon": "burst",
     "headline": ["Houthi strikes", "on Riyadh"],
     "summary": ["3 missiles at Riyadh;", "71 strikes in reply."]},
    {"kicker": "CLIMATE - COP31", "color": GREEN, "icon": "leaf",
     "headline": ["COP31 talks", "run overtime"],
     "summary": ["Deadline passes; fuel", "wording disputed."]},
    {"kicker": "CYBER - WASHINGTON", "color": BLUE, "icon": "chip",
     "headline": ["FBI records", "hacked"],
     "summary": ["FBI crime database", "reportedly hacked."]},
    {"kicker": "GAMES - WORLDWIDE", "color": GOLD, "icon": "game",
     "headline": ["GTA VI: $3.8bn", "in one day"],
     "summary": ["$3.8bn in a day, a", "record launch."]},
    {"kicker": "MIDEAST - HORMUZ", "color": BLUE, "icon": "ship",
     "headline": ["Tanker attacks", "in Hormuz"],
     "summary": ["Six tanker attacks in a", "week; talks stalled."]},
    {"kicker": "EUROPE - DENMARK", "color": PURPLE, "icon": "pin",
     "headline": ["Denmark expels", "envoy"],
     "summary": ["Attache expelled over", "plot to kill a rapper."]},
    {"kicker": "SCIENCE - MATHS", "color": PURPLE, "icon": "sigma",
     "headline": ["AI claims", "Riemann proof"],
     "summary": ["Claude said to prove", "maths' greatest riddle."]},
    {"kicker": "HEALTH - VIRGINIA", "color": GREEN, "icon": "cross",
     "headline": ["US loses", "measles status"],
     "summary": ["First child death in", "Virginia; status lost."]},
]

ALSO_LEFT = [
    ("Trump threatens tax on data centres", BLUE),
    ("Mamdani: close Rikers Island by 2032", BLUE),
    ("Palisades fire arsonist convicted", BLUE),
    ("Indian man jailed over Sikh plot", BLUE),
    ("Bayer Roundup deal: $7.25bn", BLUE),
    ("Harden passes Kobe on 50-point list", BLUE),
    ("Bolsonaro in hospital, surgery looms", BROWN),
    ("Magnitude 6.7 quake shakes Peru", BROWN),
    ("Dengue cases down 69% in Brazil trial", BROWN),
    ("Isolated Awa approach Brazil outpost", BROWN),
    ("UK and EU sign three Brexit deals", PURPLE),
    ("EU signs Indonesia trade deal", PURPLE),
    ("EU eyes 3% tax on Big Tech", PURPLE),
    ("France jails police over Zecler beating", PURPLE),
    ("Spain votes on Nov 29 as PP leads", PURPLE),
    ("Estonia to shut Russia border Dec 1", PURPLE),
]

ALSO_RIGHT = [
    ("England beat All Blacks 37-12", PURPLE),
    ("BepiColombo enters Mercury orbit", PURPLE),
    ("Basra power fire kills four", RED),
    ("Iraq strikes deal with Kataib Hezbollah", RED),
    ("Israeli strike kills 3 in Gaza aid van", RED),
    ("Saudi, Japan agree oil stockpile deal", RED),
    ("Nigeria boat sinks, 300 missing", GREEN),
    ("700,000 displaced in south Ethiopia", GREEN),
    ("Tanzania jails opposition leader Lissu", GREEN),
    ("Uganda curbs travel over Ebola", GREEN),
    ("Japan sidelined as China hosts APEC", GOLD),
    ("Seoul moves to impeach chief justice", GOLD),
    ("BTS win five awards at MAMA", GOLD),
    ("US sells seabed leases off Samoa", TEAL),
    ("Melbourne teen ran arsons via Signal", TEAL),
]

REGION_COUNTS_LEFT = [("North America", 11, BLUE), ("South America", 4, BROWN),
                      ("Europe", 11, PURPLE), ("Middle East", 6, RED)]
REGION_COUNTS_RIGHT = [("Africa", 4, GREEN), ("Asia", 4, GOLD),
                       ("Oceania", 2, TEAL)]

DATE_CHECK_TEXT = ("DATE CHECK: the Shenzhen summit, Kyiv strikes and ICJ "
                   "ruling were 20 November news, so they are not listed. "
                   "Every story here happened, or was first reported, on "
                   "Saturday 21 November.")

FOOTER = ("Sources: OneTurn, SCMP, AP, BBC, Reuters \u00b7 Drawn by a "
          "program; no photo, no network.")


# ---------------------------------------------------------------- layout ---

def draw_top(cv):
    cv.fill(0, 0, WIDTH, 30, INK)
    draw_text(cv, 28, 21, "sans_bold_13", "ONE DAY OF WORLD NEWS", WHITE)
    right = "42 STORIES \u00b7 7 REGIONS \u00b7 ALL FROM THIS SATURDAY"
    draw_text(cv, 996 - text_width("sans_bold_13", right), 21,
              "sans_bold_13", right, WHITE)
    w = text_width("serif_bold_56", MASTHEAD, -3)
    draw_text(cv, (WIDTH - w) // 2, 89, "serif_bold_56", MASTHEAD, INK, -3)
    w = text_width("serif_19", SUBHEAD)
    draw_text(cv, (WIDTH - w) // 2, 114, "serif_19", SUBHEAD, GREY)
    cv.fill(LEFT, 122, RIGHT, 125, INK)
    cv.fill(LEFT, 127, RIGHT, 128, INK)


def draw_timeline(cv):
    draw_text(cv, LEFT, 149, "sans_bold_13", "THE DAY IN UTC", RED)
    label = "WHEN THE NEWS BROKE"
    draw_text(cv, RIGHT - text_width("sans_bold_13", label), 149,
              "sans_bold_13", label, GREY)
    cv.fill(LEFT, 158, RIGHT, 160, INK)
    dots = [123, 317, 512, 706, 900]
    for cx in dots:
        cv.disc(cx, 158, 4, RED)
    for (time, text), dot in zip(TIMELINE, dots):
        total = (text_width("sans_15", time) + 10
                 + text_width("sans_15", text))
        sx = dot - total // 2
        end = draw_text(cv, sx, 180, "sans_15", time, INK)
        draw_text(cv, end + 10, 180, "sans_15", text, INK)


def draw_heroes(cv):
    art_fns = {"markets": art_markets, "wanted": art_wanted,
               "skyline": art_skyline}
    for i, hero in enumerate(HEROES):
        x = LEFT + i * 336
        art_fns[hero["art"]](cv, x)
        draw_text(cv, x, 313, "sans_bold_13", hero["kicker"], hero["color"])
        for j, line in enumerate(hero["headline"]):
            draw_text(cv, x, 349 + j * 38, "serif_bold_34", line, INK)
        for j, line in enumerate(hero["summary"]):
            draw_text(cv, x, 414 + j * 22, "serif_19", line, INK)
        draw_text(cv, x, 455, "sans_15", hero["source"], GREY)


def draw_mids(cv):
    for i, mid in enumerate(MIDS):
        ix = [26, 275, 524, 773][i % 4]
        iy = 474 if i < 4 else 586
        tx = ix + 52
        draw_icon(cv, ix, iy, mid["icon"], mid["color"])
        draw_text(cv, tx, iy + 11, "sans_bold_13", mid["kicker"],
                  mid["color"])
        for j, line in enumerate(mid["headline"]):
            draw_text(cv, tx, iy + 31 + j * 22, "serif_19", line, INK)
        for j, line in enumerate(mid["summary"]):
            draw_text(cv, tx, iy + 73 + j * 17, "sans_15", line, GREY)


def draw_bottom(cv):
    draw_text(cv, LEFT, 725, "sans_bold_13", "WHERE IT HAPPENED", INK)
    draw_text(cv, 374, 725, "sans_bold_13",
              "ALSO ON SATURDAY 21 NOVEMBER", INK)
    draw_map(cv, land_cells())
    for col, counts, dot_x, text_x in (
            (0, REGION_COUNTS_LEFT, 32, 42),
            (1, REGION_COUNTS_RIGHT, 202, 212)):
        for i, (name, n, color) in enumerate(counts):
            baseline = 876 + i * 15
            cv.disc(dot_x, baseline - 8, 4, color)
            draw_text(cv, text_x, baseline, "sans_15",
                      "%s - %d" % (name, n), INK)
    lines = wrap_lines("sans_15", DATE_CHECK_TEXT, 334)
    for i, line in enumerate(lines):
        baseline = 944 + i * 17
        draw_text(cv, LEFT, baseline, "sans_15", line, INK)
    for i, (text, color) in enumerate(ALSO_LEFT):
        baseline = 746 + i * 16
        cv.fill(374, baseline - 10, 379, baseline - 5, color)
        draw_text(cv, 385, baseline, "sans_15", text, INK)
    for i, (text, color) in enumerate(ALSO_RIGHT):
        baseline = 746 + i * 16
        cv.fill(695, baseline - 10, 700, baseline - 5, color)
        draw_text(cv, 706, baseline, "sans_15", text, INK)


def draw_page(cv):
    draw_top(cv)
    draw_timeline(cv)
    draw_heroes(cv)
    cv.fill(LEFT, 462, RIGHT, 464, INK)
    draw_mids(cv)
    cv.fill(LEFT, 702, RIGHT, 704, INK)
    draw_bottom(cv)
    w = text_width("sans_bold_13", FOOTER)
    draw_text(cv, (WIDTH - w + 1) // 2, 1023, "sans_bold_13", FOOTER, GREY)


def main():
    cv = Canvas(WIDTH, HEIGHT, PAPER)
    draw_page(cv)
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "out")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "entry.png")
    data = cv.png()
    with open(path, "wb") as f:
        f.write(data)
    print("wrote %s (%d bytes, 1024x1024)" % (path, len(data)))


if __name__ == "__main__":
    main()
