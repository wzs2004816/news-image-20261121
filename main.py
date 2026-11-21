#!/usr/bin/env python3
"""Saturday 21 November 2026, in one image.

A program that draws a newspaper front page summing up the world's news of
Saturday 21 November 2026 and writes it to /output/entry.png (or
$MAKEFUN_OUTPUT_DIR/entry.png when that is set, for local runs).

Pure standard library: no network, no files read at run time, no clock, no
randomness. Two runs write the same bytes. The picture is 1024x1024 RGB and
under 1 MiB.

Every story on the page happened, or was first reported, on Saturday
21 November 2026, as reported that day by OneTurn, SCMP, AP, BBC, Reuters
and the outlets they cite. The count in the top bar is the count of stories
the page actually lists: 3 hero stories, 8 mid stories, 31 more below.
Deliberately left out: the Shenzhen summit, the Kyiv strikes and the ICJ
Myanmar ruling -- all 20 November news, covered in the previous day's page.

Type is drawn from glyph bitmaps embedded in fonts.py (DejaVu, extracted
from the system fonts on the build machine); the dotted world map comes
from the land mask in worldmap.py. Nothing else is embedded.
"""

import base64
import json
import math
import os
import struct
import sys
import zlib

# The grader runs `python3 -P -s main.py`, and -P keeps the script's own
# directory off sys.path, so plain `from fonts import ...` fails there.
# Put this file's directory first so the sibling modules load.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fonts import FONTS
from worldmap import MAP_BITS, MAP_H, MAP_W

W, H = 1024, 1024

PAPER = (247, 243, 232)
INK = (17, 17, 17)
RED = (176, 42, 32)
BLUE = (31, 78, 121)
NAVY = (16, 28, 46)
GOLD = (176, 132, 32)
GREY = (96, 92, 82)
FAINT = (232, 226, 210)
CREAM = (238, 231, 214)
WHITE = (255, 255, 255)
SKY = (31, 58, 95)
STONE = (120, 110, 92)
GREEN = (46, 110, 58)
PURPLE = (90, 60, 120)
BROWN = (150, 90, 40)
TEAL = (0, 120, 120)


# ---------------------------------------------------------------- fonts

def _decode_font(blob):
    data = json.loads(zlib.decompress(base64.b64decode(blob)))
    glyphs = {}
    for ch, g in data["glyphs"].items():
        if "px" not in g:
            glyphs[ch] = {"adv": g["adv"]}
            continue
        raw = base64.b64decode(g["px"])
        alpha = bytearray(g["w"] * g["h"])
        for i in range(g["w"] * g["h"]):
            byte = raw[i // 2]
            alpha[i] = (byte >> 4) if i % 2 == 0 else (byte & 15)
        glyphs[ch] = {
            "adv": g["adv"], "w": g["w"], "h": g["h"],
            "x0": g["x0"], "y0": g["y0"], "alpha": bytes(alpha),
        }
    return {"ascent": data["ascent"], "descent": data["descent"],
            "size": data["size"], "glyphs": glyphs}


FONTS_D = {name: _decode_font(blob) for name, blob in FONTS.items()}


def text_width(font_name, text, tracking=0):
    font = FONTS_D[font_name]
    total = 0
    for ch in text:
        g = font["glyphs"].get(ch)
        total += (g["adv"] if g else font["size"] // 2) + tracking
    return total - tracking if text else 0


def wrap_text(font_name, text, max_w, tracking=0):
    """Greedy word wrap. Returns a list of lines that fit max_w."""
    words = text.split(" ")
    lines, cur = [], ""
    for word in words:
        trial = word if not cur else cur + " " + word
        if text_width(font_name, trial, tracking) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


# ---------------------------------------------------------------- canvas

class Canvas:
    def __init__(self, w, h, bg):
        self.w, self.h = w, h
        self.px = bytearray(w * h * 3)
        self.fill_rect(0, 0, w, h, bg)

    def _idx(self, x, y):
        return (y * self.w + x) * 3

    def set(self, x, y, color):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = self._idx(x, y)
            self.px[i], self.px[i + 1], self.px[i + 2] = color

    def blend(self, x, y, color, a15):
        """Blend color over the pixel with alpha a15 (0..15)."""
        if a15 <= 0 or not (0 <= x < self.w and 0 <= y < self.h):
            return
        i = self._idx(x, y)
        if a15 >= 15:
            self.px[i], self.px[i + 1], self.px[i + 2] = color
            return
        for k in range(3):
            self.px[i + k] = (self.px[i + k] * (15 - a15) + color[k] * a15) // 15

    def fill_rect(self, x, y, w, h, color):
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.w, x + w), min(self.h, y + h)
        for yy in range(y0, y1):
            i = self._idx(x0, yy)
            for xx in range(x0, x1):
                self.px[i], self.px[i + 1], self.px[i + 2] = color
                i += 3

    def frame(self, x, y, w, h, color, t=1):
        self.fill_rect(x, y, w, t, color)
        self.fill_rect(x, y + h - t, w, t, color)
        self.fill_rect(x, y, t, h, color)
        self.fill_rect(x + w - t, y, t, h, color)

    def hline(self, x, y, w, color, t=1):
        self.fill_rect(x, y, w, t, color)

    def vline(self, x, y, h, color, t=1):
        self.fill_rect(x, y, t, h, color)

    def line(self, x0, y0, x1, y1, color, t=1):
        """Bresenham line, thickness t (square brush)."""
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        x, y = x0, y0
        r = t // 2
        while True:
            self.fill_rect(x - r, y - r, t, t, color)
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x += sx
            if e2 <= dx:
                err += dx
                y += sy

    def disc(self, cx, cy, r, color):
        for yy in range(cy - r, cy + r + 1):
            dx = int((r * r - (yy - cy) * (yy - cy)) ** 0.5) if abs(yy - cy) <= r else 0
            self.fill_rect(cx - dx, yy, 2 * dx + 1, 1, color)

    def ring(self, cx, cy, r, color, t=2):
        for yy in range(cy - r - 1, cy + r + 2):
            for xx in range(cx - r - 1, cx + r + 2):
                d = ((xx - cx) ** 2 + (yy - cy) ** 2) ** 0.5
                if abs(d - r) <= t / 2.0:
                    self.set(xx, yy, color)

    def polygon(self, points, color):
        """Scanline fill of a simple polygon (list of (x, y))."""
        if len(points) < 3:
            return
        ys = [p[1] for p in points]
        for yy in range(max(0, min(ys)), min(self.h, max(ys) + 1)):
            nodes = []
            n = len(points)
            for i in range(n):
                x0, y0 = points[i]
                x1, y1 = points[(i + 1) % n]
                if (y0 <= yy < y1) or (y1 <= yy < y0):
                    nodes.append(x0 + (yy - y0) * (x1 - x0) / (y1 - y0))
            nodes.sort()
            for i in range(0, len(nodes) - 1, 2):
                xa, xb = int(nodes[i]), int(nodes[i + 1])
                self.fill_rect(xa, yy, xb - xa + 1, 1, color)

    def ellipse(self, cx, cy, rx, ry, color):
        pts = []
        steps = 48
        for i in range(steps):
            a = 2 * math.pi * i / steps
            pts.append((int(cx + rx * math.cos(a)),
                        int(cy + ry * math.sin(a))))
        self.polygon(pts, color)

    # ------------------------------------------------------------ text

    def draw_text(self, font_name, x, y_top, text, color, align="left",
                  tracking=0):
        """Draw text with its ascender line at y_top. Returns width drawn."""
        font = FONTS_D[font_name]
        width = text_width(font_name, text, tracking)
        if align == "center":
            x -= width // 2
        elif align == "right":
            x -= width
        cx = x
        for ch in text:
            g = font["glyphs"].get(ch)
            if g is None:
                g = font["glyphs"].get("?")
            if g is None:
                cx += font["size"] // 2 + tracking
                continue
            if "alpha" in g:
                for row in range(g["h"]):
                    base = row * g["w"]
                    for col in range(g["w"]):
                        a = g["alpha"][base + col]
                        if a:
                            self.blend(cx + g["x0"] + col, y_top + g["y0"] + row,
                                       color, a)
            cx += g["adv"] + tracking
        return width

    def draw_wrapped(self, font_name, x, y_top, text, color, max_w,
                     leading=None, tracking=0):
        """Draw wrapped text; returns the y just below the last line.
        A newline in the text forces a line break."""
        font = FONTS_D[font_name]
        lh = leading if leading is not None else int(font["size"] * 1.18)
        y = y_top
        for part in text.split("\n"):
            for line in wrap_text(font_name, part, max_w, tracking):
                self.draw_text(font_name, x, y, line, color, tracking=tracking)
                y += lh
        return y


def write_png(path, canvas):
    """Deterministic RGB PNG: fixed filter 0, zlib level 9, one IDAT."""
    w, h = canvas.w, canvas.h
    raw = bytearray()
    stride = w * 3
    for y in range(h):
        raw.append(0)
        raw += canvas.px[y * stride:(y + 1) * stride]
    comp = zlib.compress(bytes(raw), 9)

    def chunk(tag, data):
        out = struct.pack(">I", len(data)) + tag + data
        out += struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        return out

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", comp)
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)
    return len(png)

# ---------------------------------------------------------------- illustrations

def draw_star(c, cx, cy, r, color):
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.42
        pts.append((int(cx + rr * math.cos(ang)), int(cy + rr * math.sin(ang))))
    c.polygon(pts, color)


def hero_markets(c, x, y, w, h):
    """Falling market bars and a plunging red line."""
    c.fill_rect(x, y, w, h, NAVY)
    # faint grid
    for gy in range(y + 18, y + h - 6, 18):
        c.hline(x + 8, gy, w - 16, (40, 52, 74), 1)
    bars = [86, 78, 70, 58, 66, 48, 38, 26]
    bw = (w - 24) // len(bars)
    for i, bh in enumerate(bars):
        bx = x + 12 + i * bw
        col = (200, 60, 44) if i >= 5 else (90, 120, 160)
        c.fill_rect(bx, y + h - 10 - bh, bw - 6, bh, col)
    # plunging line over the bars
    pts = [(x + 12 + i * bw + (bw - 6) // 2, y + h - 14 - bh)
           for i, bh in enumerate(bars)]
    for a, b in zip(pts, pts[1:]):
        c.line(a[0], a[1], b[0], b[1], (255, 220, 120), 3)
    c.disc(pts[-1][0], pts[-1][1], 5, (255, 220, 120))
    c.draw_text("serif_bold_26", x + 14, y + 8, "-3.7%", (255, 120, 100))


def hero_cartel(c, x, y, w, h):
    """Wanted poster: star badge over jail bars."""
    c.fill_rect(x, y, w, h, (226, 214, 188))
    c.frame(x + 8, y + 8, w - 16, h - 16, INK, 2)
    for i in range(7):
        bx = x + 26 + i * 38
        c.fill_rect(bx, y + 14, 8, h - 28, (60, 52, 40))
    draw_star(c, x + w // 2, y + h // 2 - 6, 30, GOLD)
    c.disc(x + w // 2, y + h // 2 - 6, 11, (226, 214, 188))
    c.disc(x + w // 2, y + h // 2 - 6, 5, GOLD)
    c.draw_text("sans_bold_13", x + w // 2, y + h - 26, "WANTED",
                INK, align="center")


def hero_kryvyi(c, x, y, w, h):
    """Dawn skyline, missile arc, blasts over a river city."""
    c.fill_rect(x, y, w, h, (52, 48, 66))
    c.disc(x + w - 30, y + 22, 13, (240, 190, 130))
    for sx, sy in ((24, 18), (80, 30), (150, 14), (210, 26), (268, 20)):
        c.disc(x + sx, y + sy, 1, WHITE)
    for bx, bw, bh in ((0, 40, 34), (44, 28, 52), (76, 48, 30), (128, 30, 58),
                       (162, 42, 38), (208, 34, 50), (246, 40, 32)):
        c.fill_rect(x + bx, y + h - 22 - bh, bw, bh + 22, (14, 14, 24))
        for wy in range(y + h - 16 - bh, y + h - 24, 10):
            for wx in range(x + bx + 5, x + bx + bw - 3, 10):
                c.fill_rect(wx, wy, 2, 3, (240, 190, 110))
    # missile arc with smoke trail
    c.line(x + 30, y + 96, x + 120, y + 44, (255, 220, 160), 2)
    c.line(x + 120, y + 44, x + 196, y + 66, (255, 220, 160), 2)
    c.disc(x + 196, y + 66, 4, WHITE)
    for bx, by, r in ((120, 44, 22), (232, 58, 26)):
        burst = []
        for i in range(16):
            ang = i * math.pi / 8
            rr = r if i % 2 == 0 else r * 0.45
            burst.append((int(x + bx + rr * math.cos(ang)),
                          int(y + by + rr * math.sin(ang))))
        c.polygon(burst, (255, 150, 40))
        c.disc(x + bx, y + by, 6, (255, 220, 120))
    # river at the bottom
    c.fill_rect(x, y + h - 14, w, 14, (31, 58, 95))


def draw_icon(c, kind, x, y, s, color):
    """Small white pictogram inside a coloured square (mid stories)."""
    if kind == "tower":
        c.fill_rect(x + s // 2 - 5, y + 6, 10, s - 12, color)
        c.polygon([(x + s // 2 - 7, y + 6), (x + s // 2 + 7, y + 6),
                   (x + s // 2, y + 1)], color)
        c.fill_rect(x + 4, y + s - 8, s - 8, 4, color)
    elif kind == "chart":
        c.line(x + 5, y + s - 6, x + s - 5, y + s - 6, color, 2)
        c.line(x + 5, y + s - 6, x + 5, y + 6, color, 2)
        c.line(x + 8, y + 12, x + s // 2, y + 20, color, 3)
        c.line(x + s // 2, y + 20, x + s - 8, y + s - 12, color, 3)
    elif kind == "pin":
        c.disc(x + s // 2, y + s // 2 - 3, 9, color)
        c.polygon([(x + s // 2 - 8, y + s // 2 + 2), (x + s // 2 + 8, y + s // 2 + 2),
                   (x + s // 2, y + s - 4)], color)
        c.disc(x + s // 2, y + s // 2 - 3, 3, PAPER)
    elif kind == "leaf":
        c.ellipse(x + s // 2, y + s // 2, 13, 8, color)
        c.line(x + 6, y + s - 8, x + s - 6, y + 8, PAPER, 2)
    elif kind == "ship":
        c.polygon([(x + 4, y + s - 12), (x + s - 4, y + s - 12),
                   (x + s - 10, y + s - 4), (x + 10, y + s - 4)], color)
        c.fill_rect(x + s // 2 - 3, y + 6, 6, 12, color)
        c.disc(x + s // 2 + 8, y + 8, 3, (255, 150, 40))
    elif kind == "cross":
        c.fill_rect(x + s // 2 - 4, y + 5, 8, s - 10, color)
        c.fill_rect(x + 5, y + s // 2 - 4, s - 10, 8, color)
    elif kind == "burst":
        pts = []
        for i in range(16):
            ang = i * math.pi / 8
            rr = 15 if i % 2 == 0 else 7
            pts.append((int(x + s // 2 + rr * math.cos(ang)),
                        int(y + s // 2 + rr * math.sin(ang))))
        c.polygon(pts, color)
        c.disc(x + s // 2, y + s // 2, 4, PAPER)
    elif kind == "chip":
        c.fill_rect(x + 8, y + 8, s - 16, s - 16, color)
        c.frame(x + 8, y + 8, s - 16, s - 16, PAPER, 2)
        for i in range(3):
            c.fill_rect(x + 4 + i * 12, y + 2, 4, 6, color)
            c.fill_rect(x + 4 + i * 12, y + s - 8, 4, 6, color)
    elif kind == "game":
        c.fill_rect(x + 5, y + 10, s - 10, s - 20, color)
        c.disc(x + 12, y + s // 2, 4, PAPER)
        c.disc(x + s - 12, y + s // 2, 4, PAPER)
        c.fill_rect(x + 10, y + s // 2 - 2, 8, 4, PAPER)
    elif kind == "sigma":
        c.line(x + s - 8, y + 8, x + 8, y + 8, color, 4)
        c.line(x + 8, y + 8, x + s - 8, y + s // 2, color, 4)
        c.line(x + s - 8, y + s // 2, x + 8, y + s - 8, color, 4)
        c.line(x + 8, y + s - 8, x + s - 8, y + s - 8, color, 4)


# ---------------------------------------------------------------- dotted map

def draw_dotted_map(c, x, y, w, h, dot_color, story_dots):
    """Land cells as dots; story_dots is a list of (lon, lat, color, r)."""
    bits = base64.b64decode(MAP_BITS)
    step_x = w / MAP_W
    step_y = h / MAP_H
    for row in range(MAP_H):
        for col in range(MAP_W):
            i = row * MAP_W + col
            if (bits[i // 8] >> (i % 8)) & 1:
                cx = int(x + (col + 0.5) * step_x)
                cy = int(y + (row + 0.5) * step_y)
                c.disc(cx, cy, 2, dot_color)
    for lon, lat, color, r in story_dots:
        px = int(x + (lon + 180.0) / 360.0 * w)
        py = int(y + (84.0 - lat) / (84.0 + 58.0) * h)
        c.ring(px, py, r + 3, color, 2)
        c.disc(px, py, r, color)

# ---------------------------------------------------------------- stories

HERO = [
    {
        "region": "North America",
        "kicker": "MARKETS - NEW YORK",
        "headline": "Markets fall\ninto correction",
        "summary": "S&P -3.7%, Nikkei -5.1%;\nNasdaq wipes out 2026 gains.",
        "source": "OneTurn - BBC",
        "art": "markets",
    },
    {
        "region": "North America",
        "kicker": "JUSTICE - MEXICO",
        "headline": "Mexico seizes\ncartel boss",
        "summary": "El Chapo Isidro held;\nFBI most-wanted, gun battles.",
        "source": "AP - BBC",
        "art": "cartel",
    },
    {
        "region": "Europe",
        "kicker": "WAR - UKRAINE",
        "headline": "Missile hits\nhis hometown",
        "summary": "2 killed, 60 hurt;\nKryvyi Rih hit; Poland too.",
        "source": "AP - CBC",
        "art": "kryvyi",
    },
]

MID = [
    {
        "region": "Middle East",
        "kicker": "MIDDLE EAST - RIYADH",
        "headline": "Houthi strikes\non Riyadh",
        "summary": "3 missiles at Riyadh; 71 strikes in reply.",
        "icon": "burst", "color": RED,
    },
    {
        "region": "Europe",
        "kicker": "CLIMATE - COP31",
        "headline": "COP31 talks\nrun overtime",
        "summary": "Deadline passes; fuel wording disputed.",
        "icon": "leaf", "color": GREEN,
    },
    {
        "region": "North America",
        "kicker": "CYBER - WASHINGTON",
        "headline": "FBI records\nhacked",
        "summary": "FBI crime database reportedly hacked.",
        "icon": "chip", "color": BLUE,
    },
    {
        "region": "Asia",
        "kicker": "GAMES - WORLDWIDE",
        "headline": "GTA VI: $3.8bn\nin one day",
        "summary": "$3.8bn in a day, a record launch.",
        "icon": "game", "color": GOLD,
    },
    {
        "region": "Middle East",
        "kicker": "MIDEAST - HORMUZ",
        "headline": "Tanker attacks\nin Hormuz",
        "summary": "Six tanker attacks in a week; talks stalled.",
        "icon": "ship", "color": BLUE,
    },
    {
        "region": "Europe",
        "kicker": "EUROPE - DENMARK",
        "headline": "Denmark expels\nenvoy",
        "summary": "Attache expelled over plot to kill a rapper.",
        "icon": "pin", "color": PURPLE,
    },
    {
        "region": "North America",
        "kicker": "SCIENCE - MATHS",
        "headline": "AI claims\nRiemann proof",
        "summary": "Claude said to prove maths' greatest riddle.",
        "icon": "sigma", "color": PURPLE,
    },
    {
        "region": "North America",
        "kicker": "HEALTH - VIRGINIA",
        "headline": "US loses\nmeasles status",
        "summary": "First child death in Virginia; status lost.",
        "icon": "cross", "color": GREEN,
    },
]

ALSO = [
    ("North America", "Trump threatens tax on data centres"),
    ("North America", "Mamdani: close Rikers Island by 2032"),
    ("North America", "Palisades fire arsonist convicted"),
    ("North America", "Indian man jailed over Sikh plot"),
    ("North America", "Bayer Roundup deal: $7.25bn"),
    ("North America", "Harden passes Kobe on 50-point list"),
    ("South America", "Bolsonaro in hospital, surgery looms"),
    ("South America", "Magnitude 6.7 quake shakes Peru"),
    ("South America", "Dengue cases down 69% in Brazil trial"),
    ("South America", "Isolated Awa approach Brazil outpost"),
    ("Europe", "UK and EU sign three Brexit deals"),
    ("Europe", "EU signs Indonesia trade deal"),
    ("Europe", "EU eyes 3% tax on Big Tech"),
    ("Europe", "France jails police over Zecler beating"),
    ("Europe", "Spain votes on Nov 29 as PP leads"),
    ("Europe", "Estonia to shut Russia border Dec 1"),
    ("Europe", "England beat All Blacks 37-12"),
    ("Europe", "BepiColombo enters Mercury orbit"),
    ("Middle East", "Basra power fire kills four"),
    ("Middle East", "Iraq strikes deal with Kataib Hezbollah"),
    ("Middle East", "Israeli strike kills 3 in Gaza aid van"),
    ("Middle East", "Saudi, Japan agree oil stockpile deal"),
    ("Africa", "Nigeria boat sinks, 300 missing"),
    ("Africa", "700,000 displaced in south Ethiopia"),
    ("Africa", "Tanzania jails opposition leader Lissu"),
    ("Africa", "Uganda curbs travel over Ebola"),
    ("Asia", "Japan sidelined as China hosts APEC"),
    ("Asia", "Seoul moves to impeach chief justice"),
    ("Asia", "BTS win five awards at MAMA"),
    ("Oceania", "US sells seabed leases off Samoa"),
    ("Oceania", "Melbourne teen ran arsons via Signal"),
]

TIMELINE = [
    ("00:48", "Tax on AI centres"),
    ("05:40", "Riyadh under fire"),
    ("06:32", "Killer-robot rules"),
    ("06:44", "French police law"),
    ("15:35", "Cartel boss seized"),
]

# Story dots on the map: (lon, lat, color, radius)
MAP_DOTS = [
    (33.4, 48.0, RED, 4),       # Kryvyi Rih
    (-108.5, 25.6, RED, 4),     # Sinaloa
    (-74.0, 40.7, BLUE, 3),     # New York
    (46.7, 24.7, RED, 3),       # Riyadh
    (56.5, 26.5, RED, 3),       # Hormuz
    (4.35, 50.85, PURPLE, 3),   # Brussels
    (6.1, 46.2, GOLD, 3),       # Geneva
    (-47.9, -15.8, BROWN, 3),   # Brasilia
    (145.0, -37.8, TEAL, 3),    # Melbourne
    (139.7, 35.7, GOLD, 3),     # Tokyo
]

REGION_COLORS = {
    "North America": BLUE,
    "South America": BROWN,
    "Europe": PURPLE,
    "Middle East": RED,
    "Africa": GREEN,
    "Asia": GOLD,
    "Oceania": TEAL,
}
REGION_ORDER = ["North America", "South America", "Europe",
                "Middle East", "Africa", "Asia", "Oceania"]


def story_count():
    return len(HERO) + len(MID) + len(ALSO)


def region_counts():
    counts = {r: 0 for r in REGION_ORDER}
    for s in HERO + MID:
        counts[s["region"]] += 1
    for region, _ in ALSO:
        counts[region] += 1
    return counts

# ---------------------------------------------------------------- compose

def compose():
    c = Canvas(W, H, PAPER)
    mx, cw = 26, 972

    # Top bar
    c.fill_rect(0, 0, W, 30, INK)
    c.draw_text("sans_bold_13", mx + 2, 8, "ONE DAY OF WORLD NEWS", WHITE)
    total = story_count()
    right = "%d STORIES - 7 REGIONS - ALL FROM THIS SATURDAY" % total
    c.draw_text("sans_bold_13", W - mx - 2, 8, right, WHITE, align="right")

    # Masthead
    date_line = "SATURDAY 21 NOVEMBER 2026"
    c.draw_text("serif_bold_56", W // 2, 36, date_line, INK, align="center",
                tracking=-3)
    c.draw_text("serif_19", W // 2, 96,
                "The world in one day - every story here happened, or was "
                "first reported, on this Saturday.",
                GREY, align="center")
    c.hline(mx, 122, cw, INK, 3)
    c.hline(mx, 127, cw, INK, 1)

    # Timeline strip: one line per event, time + label
    ty = 136
    c.draw_text("sans_bold_13", mx, ty, "THE DAY IN UTC", RED)
    c.draw_text("sans_bold_13", W - mx, ty, "WHEN THE NEWS BROKE", GREY,
                align="right")
    c.hline(mx, ty + 22, cw, INK, 2)
    slot = cw / len(TIMELINE)
    for i, (t, label) in enumerate(TIMELINE):
        cx = int(mx + slot * i + slot / 2)
        c.disc(cx, ty + 22, 4, RED)
        c.draw_text("sans_15", cx, ty + 30, "%s  %s" % (t, label), INK,
                    align="center")

    # Hero row
    hy, hh = 188, 104
    col_w, gap = 300, 36
    for i, story in enumerate(HERO):
        x = mx + i * (col_w + gap)
        art = {"markets": hero_markets, "cartel": hero_cartel,
               "kryvyi": hero_kryvyi}[story["art"]]
        art(c, x, hy, col_w, hh)
        c.frame(x, hy, col_w, hh, INK, 1)
        y = hy + hh + 8
        c.draw_text("sans_bold_13", x, y, story["kicker"], RED)
        y += 17
        y = c.draw_wrapped("serif_bold_34", x, y, story["headline"], INK,
                           col_w, leading=38)
        y += 3
        y = c.draw_wrapped("serif_19", x, y, story["summary"], INK, col_w,
                           leading=22)
        c.draw_text("sans_15", x, y + 1, story["source"], GREY)

    c.hline(mx, 462, cw, INK, 2)

    # Mid rows: two rows of four
    my = 472
    mcol_w, mgap = 225, 24
    for row in range(2):
        for col in range(4):
            story = MID[row * 4 + col]
            x = mx + col * (mcol_w + mgap)
            y = my + row * 112
            c.fill_rect(x, y + 2, 44, 44, story["color"])
            draw_icon(c, story["icon"], x + 1, y + 3, 42, WHITE)
            tx = x + 52
            c.draw_text("sans_bold_13", tx, y, story["kicker"],
                        story["color"])
            y2 = c.draw_wrapped("serif_19", tx, y + 15,
                                story["headline"], INK, mcol_w - 52,
                                leading=22)
            c.draw_wrapped("sans_15", tx, y2 + 2, story["summary"], GREY,
                           mcol_w - 52, leading=17)

    c.hline(mx, 702, cw, INK, 2)

    # Bottom left: map + region counts + date check
    by = 712
    c.draw_text("sans_bold_13", mx, by, "WHERE IT HAPPENED", INK)
    map_x, map_y, map_w, map_h = mx, by + 20, 330, 120
    c.frame(map_x - 4, map_y - 4, map_w + 8, map_h + 8, INK, 1)
    draw_dotted_map(c, map_x, map_y, map_w, map_h, (150, 140, 115), MAP_DOTS)
    counts = region_counts()
    ly = map_y + map_h + 10
    for j, region in enumerate(REGION_ORDER):
        lx = mx + (j // 4) * 170
        ry = ly + (j % 4) * 15
        c.disc(lx + 6, ry + 6, 4, REGION_COLORS[region])
        c.draw_text("sans_15", lx + 16, ry,
                    "%s - %d" % (region, counts[region]), INK)
    dy = ly + 4 * 15 + 8
    c.draw_wrapped("sans_15", mx, dy,
                   "DATE CHECK: the Shenzhen summit, Kyiv strikes and ICJ "
                   "ruling were 20 November news, so they are not listed. "
                   "Every story here happened, or was first reported, on "
                   "Saturday 21 November.",
                   INK, map_w, leading=17)

    # Bottom right: also list
    rx, rw = 374, 624
    c.draw_text("sans_bold_13", rx, by, "ALSO ON SATURDAY 21 NOVEMBER", INK)
    col2_w = (rw - 18) // 2
    per_col = 16
    for i, (region, text) in enumerate(ALSO):
        col = i // per_col
        row = i % per_col
        x = rx + col * (col2_w + 18)
        y = by + 20 + row * 16
        c.fill_rect(x, y + 4, 5, 5, REGION_COLORS[region])
        c.draw_text("sans_15", x + 11, y, text, INK)

    # Footer
    c.draw_text("sans_bold_13", W // 2, 1010,
                "Sources: OneTurn, SCMP, AP, BBC, Reuters - "
                "Drawn by a program; no photo, no network.",
                GREY, align="center")
    return c

def main():
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    canvas = compose()
    path = os.path.join(out_dir, "entry.png")
    size = write_png(path, canvas)
    print("wrote %s (%d bytes, %dx%d)" % (path, size, W, H))


if __name__ == "__main__":
    main()
