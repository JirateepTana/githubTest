"""Builds the Siam Sunset Cruise motor yacht for siam-sunset-river.html.

    blender --background --factory-startup --python build_boat.py -- [preview=<dir>] [views=a,b] [nobake]

Writes boat.json (a glTF with its data inlined, because artifacts don't serve .glb; one mesh:
UV0 for the page's textures, UV1 for the AO map) and boat-ao.jpg (ambient occlusion baked into UV1)
next to this script. With preview=<dir> it renders Cycles stills of the yacht into <dir> instead.

Yacht space in Blender: bow +Y, up +Z, waterline Z=0, metres. The glTF export turns this into the
page's three.js boat space (bow -Z, up +Y). Material names are the contract with the page, which
swaps each one for its own live material (palette colours, night glow).
"""
import base64
import bisect
import json
import os
import random
import struct
import sys
from math import cos, pi, radians, sin, sqrt

import bmesh
import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OPT = dict(a.split("=", 1) if "=" in a else (a, "1") for a in ARGS)

# name: (sRGB hex, metallic, roughness, emission strength) -- only used for previews and as
# fallbacks; the page replaces every one of these by name.
MATS = {
    "Hull": ("#f3f2ee", 0.0, 0.18, 0),
    "Super": ("#f3f2ee", 0.0, 0.22, 0),
    "Boot": ("#1d2740", 0.0, 0.3, 0),
    "Accent": ("#e2a93b", 0.6, 0.3, 0),
    "Deck": ("#9a6a45", 0.0, 0.7, 0),
    "Glass": ("#151b22", 0.2, 0.05, 0),
    "Frame": ("#16191c", 0.5, 0.35, 0),
    "Port": ("#151b22", 0.3, 0.06, 0),
    "Steel": ("#d8d8d6", 0.9, 0.18, 0),
    "GlassRail": ("#cfe9ff", 0.0, 0.05, 0),
    "Cushion": ("#ece6da", 0.0, 0.85, 0),
    "Table": ("#fbf7ee", 0.0, 0.75, 0),
    "Chair": ("#3b2b20", 0.0, 0.6, 0),
    "Rubber": ("#1b1b1d", 0.0, 0.8, 0),
    "Water": ("#3fb6c9", 0.0, 0.05, 0),
    "Skin": ("#b98466", 0.0, 0.6, 0),
    "Gold": ("#e2b04a", 0.9, 0.25, 0),
    "LED": ("#ffd9a0", 0.0, 1.0, 3),
    "Bulb": ("#ffd88a", 0.0, 1.0, 4),
    "NavRed": ("#ff3b30", 0.0, 1.0, 4),
    "NavGreen": ("#2bd96b", 0.0, 1.0, 4),
    "NavWhite": ("#ffffff", 0.0, 1.0, 4),
}
NAMES = list(MATS)
NO_AO = {"Glass", "Port", "GlassRail", "Water", "LED", "Bulb", "NavRed", "NavGreen", "NavWhite"}  # glass and lights
RNG = random.Random(7)

bm = bmesh.new()
UV = bm.loops.layers.uv.new("UVMap")


def ss(a, b, x):
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def V3(p):
    return Vector(p) if len(p) == 3 else Vector((p[0], p[1], 0.0))


# ---------------------------------------------------------------- mesh primitives
def face(vs, mat, uvs=None, smooth=False):
    o, n = vs[0].co, Vector()
    for i in range(1, len(vs) - 1):
        n += (vs[i].co - o).cross(vs[i + 1].co - o)
    if n.length < 1e-9:  # collapsed (rows meeting at the stem, bulwarks fading out): leave it out
        return None
    try:
        f = bm.faces.new(vs)
    except ValueError:  # the face already exists
        return None
    f.material_index = NAMES.index(mat)
    f.smooth = smooth
    if uvs:
        for loop, uv in zip(f.loops, uvs):
            loop[UV].uv = uv
    return f


def poly(pts, mat, uvs=None, smooth=False, facing=None):
    """Polygon from points; with `facing` the winding is flipped so the normal agrees with it."""
    pts = [Vector(p) for p in pts]
    if facing is not None:
        n = Vector()
        for i in range(len(pts)):  # Newell normal
            a, b = pts[i], pts[(i + 1) % len(pts)]
            n += Vector(((a.y - b.y) * (a.z + b.z), (a.z - b.z) * (a.x + b.x), (a.x - b.x) * (a.y + b.y)))
        if n.dot(Vector(facing)) < 0:
            pts.reverse()
            uvs = uvs[::-1] if uvs else uvs
    return face([bm.verts.new(p) for p in pts], mat, uvs, smooth)


def quads(V, mat, smooth=True, close=False, wrap=False, uvs=None, skip=None):
    """Quads between consecutive rows of verts (normal = row direction x column direction).
    mat: a name or fn(row, col). Repeated verts (poles) collapse to triangles.
    skip(verts) -> True leaves that quad out."""
    nr, nc = len(V), len(V[0])
    for i in range(nr if wrap else nr - 1):
        i2 = (i + 1) % nr
        for j in range(nc if close else nc - 1):
            j2 = (j + 1) % nc
            vs = [V[i][j], V[i][j2], V[i2][j2], V[i2][j]]
            if skip and skip(vs):
                continue
            uv = [uvs[i][j], uvs[i][j2], uvs[i2][j2], uvs[i2][j]] if uvs else [None] * 4
            kv, ku = [], []
            for v, u in zip(vs, uv):
                if not (kv and v is kv[-1]):
                    kv.append(v)
                    ku.append(u)
            if len(kv) > 1 and kv[0] is kv[-1]:
                kv.pop()
                ku.pop()
            if len(kv) >= 3:
                face(kv, mat(i, j) if callable(mat) else mat, ku if uvs else None, smooth)


def grid(rows, mat, **kw):
    V = [[bm.verts.new(p) for p in r] for r in rows]
    quads(V, mat, **kw)
    return V


HEX_FACES = {
    "-z": ((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)),
    "+z": ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)),
    "-y": ((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)),
    "+y": ((0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)),
    "-x": ((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)),
    "+x": ((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)),
}


def hexa(corner, mat, uv=None):
    """Six-sided block from corner(i, j, k) -> point; mirrored frames are flipped back to outward.
    mat: a name or {face key: name} with "*" as the default."""
    o = corner(0, 0, 0)
    det = (corner(1, 0, 0) - o).cross(corner(0, 1, 0) - o).dot(corner(0, 0, 1) - o)
    c = corner if det > 0 else (lambda i, j, k: corner(i, 1 - j, k))
    for key, idx in HEX_FACES.items():
        m = mat.get(key, mat.get("*")) if isinstance(mat, dict) else mat
        pts = [c(*t) for t in idx]
        face([bm.verts.new(p) for p in pts], m, [uv(p) for p in pts] if uv else None)


def box(c, size, mat, rot=None, uv=None):
    c, h, R = Vector(c), Vector(size) / 2, rot or Matrix.Identity(3)
    hexa(lambda i, j, k: c + R @ Vector(((2 * i - 1) * h.x, (2 * j - 1) * h.y, (2 * k - 1) * h.z)), mat, uv)


def perp(t):
    a = Vector((0, 0, 1)) if abs(t.z) < 0.9 else Vector((1, 0, 0))
    return a.cross(t).normalized()


def tube(pts, r, mat, seg=8, close=False, caps=True, smooth=True, taper=None):
    """Round tube along a polyline; taper(t in 0..1) scales the radius."""
    pts = [Vector(p) for p in pts]
    n = len(pts)
    tans = []
    for i in range(n):
        d = (pts[(i + 1) % n] - pts[i - 1]) if close else (pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)])
        tans.append(d.normalized())
    U, rows = perp(tans[0]), []
    for i in range(n):
        t = tans[i]
        U = (U - t * U.dot(t)).normalized()  # parallel transport keeps the rings from twisting
        W = t.cross(U)
        rr = r * (taper(i / (n - 1)) if taper else 1.0)
        rows.append([pts[i] + (U * cos(2 * pi * k / seg) + W * sin(2 * pi * k / seg)) * rr for k in range(seg)])
    grid(rows, mat, smooth=smooth, close=True, wrap=close)
    if caps and not close:
        poly(rows[0][::-1], mat)
        poly(rows[-1], mat)


def cyl(p0, p1, r, mat, seg=12, **kw):
    tube([p0, p1], r, mat, seg, **kw)


def lathe(prof, c, mat, seg=16, smooth=True, rot=None):
    """Revolve [(r, z)] (listed bottom to top) about the local vertical axis through c.
    mat: a name or fn(segment index)."""
    c, R, V = Vector(c), rot or Matrix.Identity(3), []
    for r, z in prof:
        if r < 1e-6:
            V.append([bm.verts.new(c + R @ Vector((0, 0, z)))] * seg)
        else:
            V.append([bm.verts.new(c + R @ Vector((r * cos(2 * pi * k / seg), r * sin(2 * pi * k / seg), z)))
                      for k in range(seg)])
    quads(V, (lambda i, j: mat(i)) if callable(mat) else mat, smooth=smooth, close=True)


def sphere(c, r, mat, seg=12, rings=8):
    lathe([(r * sin(pi * k / rings), -r * cos(pi * k / rings)) for k in range(rings + 1)], c, mat, seg)


def ring(c, r, minor, mat, axis="y", seg=20, mseg=8):
    """Torus lying across `axis` (its hole looks along that axis)."""
    c = Vector(c)
    if axis == "x":
        pts = [c + Vector((0, r * cos(2 * pi * k / seg), r * sin(2 * pi * k / seg))) for k in range(seg)]
    elif axis == "y":
        pts = [c + Vector((r * cos(2 * pi * k / seg), 0, r * sin(2 * pi * k / seg))) for k in range(seg)]
    else:
        pts = [c + Vector((r * cos(2 * pi * k / seg), r * sin(2 * pi * k / seg), 0)) for k in range(seg)]
    tube(pts, minor, mat, mseg, close=True)


# ---------------------------------------------------------------- outlines on the decks
class Path:
    """Closed outline, counter-clockwise seen from above, with outward horizontal normals.
    Points on walls are addressed by (s = distance along the outline, z, n = offset outwards)."""

    def __init__(self, pts, nrm=None):
        self.p = [V3(p) for p in pts]
        if nrm is None:  # from the neighbours: the tangent turned a quarter clockwise
            nrm = []
            for i in range(len(self.p)):
                d = self.p[(i + 1) % len(self.p)] - self.p[i - 1]
                nrm.append((d.y, -d.x, 0.0))
        self.n = [V3(n).normalized() for n in nrm]
        self.s = [0.0]
        for i in range(1, len(self.p) + 1):
            self.s.append(self.s[-1] + (self.p[i % len(self.p)] - self.p[i - 1]).length)
        self.L = self.s[-1]

    def locate(self, s):
        s %= self.L
        i = min(bisect.bisect_right(self.s, s) - 1, len(self.p) - 1)
        return i, (i + 1) % len(self.p), (s - self.s[i]) / max(1e-9, self.s[i + 1] - self.s[i])

    def Wi(self, j, z, n=0.0):
        p, nn = self.p[j], self.n[j]
        return Vector((p.x + nn.x * n, p.y + nn.y * n, z))

    def W(self, s, z, n=0.0):
        i, j, t = self.locate(s)
        p, nn = self.p[i].lerp(self.p[j], t), self.n[i].lerp(self.n[j], t).normalized()
        return Vector((p.x + nn.x * n, p.y + nn.y * n, z))

    def s_near(self, q):
        q, best = V3(q), (1e9, 0.0)
        for i in range(len(self.p)):
            a, b = self.p[i], self.p[(i + 1) % len(self.p)]
            ab = b - a
            t = max(0.0, min(1.0, (q - a).dot(ab) / max(1e-12, ab.length_squared)))
            d = (a + ab * t - q).length
            if d < best[0]:
                best = (d, self.s[i] + t * ab.length)
        return best[1]

    def offset(self, o):
        """The outline moved out by o metres, or by o(normal) where it varies round the outline."""
        f = o if callable(o) else (lambda n: o)
        return Path([p + n * f(n) for p, n in zip(self.p, self.n)], self.n)

    def contains(self, q, margin=0.0):
        """Inside this convex outline, with `margin` to spare outwards (negative: that far inside)."""
        return all((V3(q) - p).dot(n) < margin for p, n in zip(self.p, self.n))


def house_path(hw, y_aft, y_fs, lf, rc, step=0.8, m=40):
    """Deckhouse outline: straight sides, an elliptical front from y_fs reaching lf further forward,
    a flat aft end with rounded corners of radius rc."""
    P, N = [], []

    def add(x, y, nx, ny):
        P.append((x, y))
        N.append((nx, ny))

    ys = y_aft + rc
    n = max(1, round((y_fs - ys) / step))
    for k in range(n):
        add(hw, ys + (y_fs - ys) * k / n, 1, 0)
    for k in range(m):
        a = pi * k / m
        add(hw * cos(a), y_fs + lf * sin(a), lf * cos(a), hw * sin(a))
    for k in range(n):
        add(-hw, y_fs - (y_fs - ys) * k / n, -1, 0)
    for k in range(6):
        a = pi + pi / 2 * k / 6
        add(-hw + rc + rc * cos(a), ys + rc * sin(a), cos(a), sin(a))
    na = max(1, round(2 * (hw - rc) / step))
    for k in range(na):
        add(-hw + rc + 2 * (hw - rc) * k / na, y_aft, 0, -1)
    for k in range(6):
        a = 1.5 * pi + pi / 2 * k / 6
        add(hw - rc + rc * cos(a), ys + rc * sin(a), cos(a), sin(a))
    return Path(P, N)


def rect_path(x0, x1, y0, y1, r, step=0.6):
    """Rounded rectangle, counter-clockwise from above."""
    P = []
    for cx, cy, a0 in ((x1 - r, y0 + r, -pi / 2), (x1 - r, y1 - r, 0.0), (x0 + r, y1 - r, pi / 2), (x0 + r, y0 + r, pi)):
        P += [(cx + r * cos(a0 + pi / 2 * k / 6), cy + r * sin(a0 + pi / 2 * k / 6)) for k in range(7)]
    return Path(P)


def fill(path, z, mat, down=False, uv=None):
    """Fan-fill a convex outline at height z, facing up (or down)."""
    pts = [path.Wi(j, z) for j in range(len(path.p))]
    c = sum(pts, Vector()) / len(pts)
    cv, vs = bm.verts.new(c), [bm.verts.new(p) for p in pts]
    for j in range(len(vs)):
        tri = [cv, vs[j], vs[(j + 1) % len(vs)]]
        if down:
            tri = [tri[0], tri[2], tri[1]]
        face(tri, mat, [uv(v.co) for v in tri] if uv else None)


def ring_fill(outer, inner, z, mat, uv=None, down=False):
    """Flat ring between two outlines facing up (or down): a deck round a deckhouse, a soffit under an overhang."""
    loops = []
    for path in (outer, inner):
        vs = [bm.verts.new(path.Wi(j, z)) for j in range(len(path.p))]
        loops += [bm.edges.new((vs[j], vs[(j + 1) % len(vs)])) for j in range(len(vs))]
    res = bmesh.ops.triangle_fill(bm, use_beauty=True, use_dissolve=False, edges=loops, normal=Vector((0, 0, 1)))
    for f in res["geom"]:
        if isinstance(f, bmesh.types.BMFace):
            f.normal_update()
            if (f.normal.z < 0) != down:
                f.normal_flip()
            f.material_index = NAMES.index(mat)
            if uv:
                for loop in f.loops:
                    loop[UV].uv = uv(loop.vert.co)


def deck_uv(p):
    return (p.x / 4.0, p.y / 4.0)


# ---------------------------------------------------------------- deckhouse walls and glazing
class Wall:
    """Deckhouse side from z0 to z1 leaning in by lean(normal) at the top: tumblehome on the sides,
    a raked windscreen where the outline faces forward."""

    def __init__(self, path, z0, z1, lean):
        self.P, self.z0, self.z1 = path, z0, z1
        self.lean = [lean(n) for n in path.n]

    def lean_at(self, s):
        i, j, t = self.P.locate(s)
        return self.lean[i] + (self.lean[j] - self.lean[i]) * t

    def pt(self, s, z, off=0.0):
        return self.P.W(s, z, off - self.lean_at(s) * (z - self.z0) / (self.z1 - self.z0))

    def top(self):
        """The wall's top edge as an outline (where the soffit above meets it)."""
        return Path([self.P.Wi(j, self.z1, -self.lean[j]) for j in range(len(self.P.p))], self.P.n)

    def build(self, mat="Super"):
        """In six rows: where the lean changes along the outline a single quad would twist out through the glass."""
        P = self.P
        grid([[P.Wi(j, self.z0 + (self.z1 - self.z0) * t, -self.lean[j] * t) for j in range(len(P.p))]
              for t in (k / 6 for k in range(7))], mat, close=True)

    def ribbon(self, pts, w, mat, off=0.024):
        """A flat strip w wide along a polyline in (s, z), standing off the wall: glazing bars, frit."""
        a, b = Vector(pts[0]), Vector(pts[1])
        d = (b - a).normalized()
        m = Vector((-d.y, d.x)) * (w / 2)
        n = max(1, round((b - a).length / 0.12))  # short steps, so the strip hugs a curved wall
        line = [a.lerp(b, k / n) for k in range(n + 1)]
        grid([[self.pt(q.x - m.x, q.y - m.y, off) for q in line], [self.pt(q.x + m.x, q.y + m.y, off) for q in line]],
             mat, smooth=False)

    def band(self, s0, s1, z0, z1, r0=0.0, r1=0.0, panel=1.8, glass="Glass", frame="Frame"):
        """Tinted glazing between s0 and s1 along the bottom edge; at the top the ends shift by r0 and r1
        (raked ends). Cut into panes about `panel` wide with black bars; every pane shows one of the
        page's four rooms through its UVs."""
        L = s1 - s0
        n = max(1, round(abs(L) / panel))
        bot = [s0 + L * k / n for k in range(n + 1)]
        top = [s0 + r0 + (L + r1 - r0) * k / n for k in range(n + 1)]
        for k in range(n):
            var, rows, uvs = RNG.randrange(4), [], []
            cols = max(4, round(abs(bot[k + 1] - bot[k]) / 0.15))  # short steps, so the glass hugs a curved wall
            for tz in (0.0, 0.5, 1.0):
                row, urow = [], []
                for c in range(cols + 1):
                    tc = c / cols
                    a = bot[k] + (bot[k + 1] - bot[k]) * tc
                    b = top[k] + (top[k + 1] - top[k]) * tc
                    row.append(self.pt(a + (b - a) * tz, z0 + (z1 - z0) * tz, 0.015))
                    urow.append(((var + tc) / 4, tz))
                rows.append(row)
                uvs.append(urow)
            grid(rows, glass, smooth=False, uvs=uvs)
        for k in range(n + 1):
            self.ribbon([(bot[k], z0), (top[k], z1)], 0.05 if 0 < k < n else 0.08, frame)
        for k in range(n):
            self.ribbon([(bot[k], z0), (bot[k + 1], z0)], 0.08, frame)
            self.ribbon([(top[k], z1), (top[k + 1], z1)], 0.08, frame)


def slab(edge, z_lo, z_hi, below=None, above=None, top="Deck"):
    """Deck slab whose edge follows the outline `edge`: rounded fascia with an LED strip under its lip,
    the soffit back to the top of the deckhouse below (or all the way across), and the deck on top
    (round the deckhouse standing on it, if there is one)."""
    h = z_hi - z_lo
    prof = [(-0.09, z_lo), (-0.03, z_lo), (0.0, z_lo), (0.04, z_lo + 0.15 * h), (0.06, z_lo + 0.5 * h),
            (0.04, z_lo + 0.85 * h), (0.0, z_hi)]
    grid([[edge.Wi(j, z, n) for j in range(len(edge.p))] for n, z in prof], lambda i, j: "LED" if i == 0 else "Super",
         close=True)
    lip = edge.offset(-0.09)
    if below:
        ring_fill(lip, below, z_lo, "Super", down=True)
    else:
        fill(lip, z_lo, "Super", down=True)
    if above:
        ring_fill(edge, above, z_hi, top, deck_uv)
    else:
        fill(edge, z_hi, top, uv=deck_uv)
    return edge


def solid_bulwark(path, z, h=1.05, t=0.16):
    """Solid white bulwark flush with a deck's fascia, teak capping on top: the curved walls of a superyacht's aft decks."""
    out = [path.Wi(j, z) for j in range(len(path.p))]
    inn = [path.Wi(j, z, -t) for j in range(len(path.p))]
    up = Vector((0, 0, h))
    grid([out, [p + up for p in out]], "Super", close=True)  # outside face
    grid([[p + up for p in inn], inn], "Super", close=True)  # inside face, looking inboard
    grid([[p + up for p in out], [p + up for p in inn]], "Deck", close=True, smooth=False,
         uvs=[[deck_uv(p) for p in out], [deck_uv(p) for p in inn]])


def long_table(x, y0, y1, z, seats):
    """Teak dining table running fore and aft, chairs down both sides."""
    L, ym = y1 - y0, (y0 + y1) / 2
    box((x, ym, z + 0.74), (1.0, L, 0.05), "Deck", uv=deck_uv)
    for dx in (-0.4, 0.4):
        for yy in (y0 + 0.2, y1 - 0.2):
            box((x + dx, yy, z + 0.36), (0.06, 0.06, 0.72), "Chair")
    for k in range(seats):
        yy = y0 + L * (k + 0.5) / seats
        chair(x + 0.85, yy, z, 0.0)
        chair(x - 0.85, yy, z, pi)
        lathe([(0, 0.765), (0.04, 0.765), (0.04, 0.79), (0.03, 0.8), (0.035, 0.86), (0.025, 0.9), (0, 0.905)],
              (x, yy, z), lambda i: "Gold" if i < 3 else "Bulb", 8)


def jet_ski(x, y, a):
    """A jet ski floating at the waterline, bow pointing along a (radians about Z)."""
    R, c = Matrix.Rotation(a, 3, "Z"), Vector((x, y, 0.0))

    def corner(i, j, k):  # hull block narrowing to a pointed bow, deeper at the back
        w = (0.6, 0.12)[j] * (1.0 if k else 0.7)
        return c + R @ Vector(((2 * i - 1) * w, (-1.4, 1.5)[j], (-0.15, 0.45)[k]))

    hexa(corner, {"+z": "Super", "*": "Super"})
    box(c + R @ Vector((0, -0.4, 0.62)), (0.45, 1.3, 0.3), "Boot", R)
    box(c + R @ Vector((0, 0.55, 0.62)), (0.8, 0.5, 0.35), "Accent", R)
    cyl(c + R @ Vector((-0.35, 0.65, 0.85)), c + R @ Vector((0.35, 0.65, 0.85)), 0.025, "Rubber", 6)


def sofa(x, y, z, w, d, a):
    """Lounge sofa, w long, facing direction a (radians about Z)."""
    R, c = Matrix.Rotation(a, 3, "Z"), Vector((x, y, z))
    box(c + R @ Vector((0, 0, 0.2)), (w, d, 0.4), "Super", R)
    box(c + R @ Vector((0, 0.05, 0.48)), (w - 0.08, d - 0.18, 0.16), "Cushion", R)
    box(c + R @ Vector((0, -d / 2 + 0.12, 0.72)), (w - 0.08, 0.2, 0.5), "Cushion", R)


TORSO = [(0, 0), (0.17, 0), (0.19, 0.25), (0.21, 0.5), (0.16, 0.62), (0.06, 0.66), (0, 0.66)]


def person(x, y, z, a, cloth, seated=False):
    """A guest facing local -x (towards the table, for a chair turned by a)."""
    R, c = Matrix.Rotation(a, 3, "Z"), Vector((x, y, z))

    def L(p):
        return c + R @ Vector(p)

    if seated:
        box(L((-0.2, 0, 0.56)), (0.46, 0.34, 0.15), "Boot", R)
        box(L((-0.42, 0, 0.27)), (0.13, 0.3, 0.52), "Boot", R)
        hip, head = 0.55, 1.36
        for s in (1, -1):
            tube([L((0.03, s * 0.22, 1.08)), L((-0.05, s * 0.24, 0.86)), L((-0.38, s * 0.2, 0.82))], 0.045, cloth, 6)
    else:
        for s in (1, -1):
            cyl(L((0, s * 0.1, 0)), L((0, s * 0.1, 0.88)), 0.075, "Boot", 6)
            cyl(L((0, s * 0.23, 1.4)), L((0, s * 0.27, 0.95)), 0.05, cloth, 6)
        hip, head = 0.85, 1.66
    lathe(TORSO, L((0.03 if seated else 0, 0, hip)), cloth, 10)
    cyl(L((0, 0, hip + 0.64)), L((0, 0, head - 0.08)), 0.05, "Skin", 6)
    sphere(L((0, 0, head)), 0.11, "Skin", 10, 6)
    sphere(L((0.02, 0, head + 0.03)), 0.105, "Rubber", 10, 6)  # hair, a little behind the face


def guests(chairs, share=0.7):
    """Seat guests on some of the given (x, y, z, a) chairs."""
    for x, y, z, a in chairs:
        if RNG.random() < share:
            person(x, y, z, a, RNG.choice(("Cushion", "Table", "Boot", "Chair", "Rubber", "Accent")), seated=True)


def string_lights(p0, p1, sag=0.35, step=0.5):
    """Festoon of bulbs hanging between two points."""
    p0, p1 = Vector(p0), Vector(p1)
    n = max(2, int((p1 - p0).length / step))
    pts = [p0.lerp(p1, t / n) - Vector((0, 0, sag * 4 * (t / n) * (1 - t / n))) for t in range(n + 1)]
    tube(pts, 0.008, "Rubber", 4, caps=False)
    for p in pts[1:-1]:
        sphere(p - Vector((0, 0, 0.06)), 0.045, "Bulb", 6, 4)


def helicopter(c, a):
    """A light twin helicopter parked on its skids at c, nose along a (radians about Z)."""
    c, R = Vector(c), Matrix.Rotation(a, 3, "Z")

    def L(p):
        return c + R @ Vector(p)

    prof = [(0, 0), (0.55, 0.05), (0.95, 0.6), (1.1, 1.6), (1.12, 3.2), (1.08, 4.2), (0.95, 5.0), (0.7, 5.8),
            (0.4, 6.3), (0, 6.6)]
    lathe(prof, L((0, -2.6, 1.55)), lambda i: "Port" if i >= 5 else ("Boot" if i == 1 else "Super"), 20,
          rot=R @ Matrix.Rotation(-pi / 2, 3, "X"))
    box(L((0, 1.1, 1.35)), (2.26, 2.2, 0.08), "Boot", R)  # livery stripe round the cabin
    tube([L((0, -2.4, 1.9)), L((0, -5.0, 2.1)), L((0, -7.6, 2.35))], 0.34, "Super", 12, taper=lambda t: 1 - 0.55 * t)
    box(L((0, -7.55, 2.95)), (0.1, 0.9, 1.4), "Super", R @ Matrix.Rotation(radians(-18), 3, "X"))
    box(L((0, -6.6, 2.3)), (1.9, 0.4, 0.06), "Super", R)
    for k in range(2):
        box(L((0.12, -7.8, 3.2)), (0.04, 0.14, 1.5), "Rubber", R @ Matrix.Rotation(k * pi / 2, 3, "X"))
    box(L((0, -0.8, 2.85)), (1.1, 2.8, 0.6), "Super", R)  # engine cowling
    cyl(L((0, 0, 3.1)), L((0, 0, 3.6)), 0.12, "Steel", 8)
    cyl(L((0, 0, 3.55)), L((0, 0, 3.72)), 0.3, "Rubber", 12)
    for k in range(4):
        ang = radians(20) + k * pi / 2
        box(L((2.9 * cos(ang), 2.9 * sin(ang), 3.65)), (5.4, 0.32, 0.05), "Rubber", R @ Matrix.Rotation(ang, 3, "Z"))
    for s in (1, -1):
        tube([L((s * 1.05, -2.4, 0.1)), L((s * 1.05, 2.6, 0.1)), L((s * 1.05, 3.1, 0.35))], 0.06, "Steel", 6)
        for yy in (-1.3, 1.6):
            cyl(L((s * 1.05, yy, 0.1)), L((s * 0.7, yy, 0.75)), 0.05, "Steel", 6)


def tender(x, y, a):
    """Limousine tender afloat beside the yacht, bow along a."""
    R, c = Matrix.Rotation(a, 3, "Z"), Vector((x, y, 0.0))

    def corner(i, j, k):
        w = (1.35, 0.2)[j] * (1.0 if k else 0.72)
        return c + R @ Vector(((2 * i - 1) * w, (-4.4, 4.6)[j], (-0.3, 0.95)[k]))

    hexa(corner, {"+z": "Deck", "*": "Super"}, uv=deck_uv)
    box(c + R @ Vector((0, 0.6, 1.3)), (2.0, 3.4, 0.7), "Super", R)
    box(c + R @ Vector((0, 0.6, 1.36)), (2.04, 3.0, 0.4), "Port", R)
    box(c + R @ Vector((0, -2.9, 1.1)), (1.9, 1.6, 0.3), "Cushion", R)


def balustrade(path, z, h=1.0, inset=0.08, gap=None):
    """Glass balustrade with a stainless top rail along an outline (gap(point) -> True leaves an opening)."""
    B = path.offset(-inset)
    pts = [B.Wi(j, z) for j in range(len(B.p))]
    runs = split_runs(pts, gap) if gap else [pts + pts[:1]]
    for run in runs:
        grid([[p + Vector((0, 0, 0.1)) for p in run], [p + Vector((0, 0, h - 0.06)) for p in run]], "GlassRail",
             smooth=False)
        tube([p + Vector((0, 0, h)) for p in run], 0.03, "Steel", 8)
        for p in run[::4] + [run[-1]]:
            cyl(p, p + Vector((0, 0, h)), 0.022, "Steel", 6, caps=False)


def split_runs(pts, gap):
    """Open runs of a closed loop with the points where gap(p) is true removed."""
    if not any(gap(p) for p in pts):
        return [pts + pts[:1]]
    k = next(i for i, p in enumerate(pts) if gap(p))
    pts = pts[k:] + pts[:k]
    runs, cur = [], []
    for p in pts:
        if gap(p):
            if len(cur) > 1:
                runs.append(cur)
            cur = []
        else:
            cur.append(p)
    if len(cur) > 1:
        runs.append(cur)
    return runs


# ---------------------------------------------------------------- hull (a 98 m mega yacht, after the Gemini concept picture)
Y0, Y1 = -47.0, 51.0  # transom, stem head
ZK = -0.6  # lowest waterline (enough for the yacht's bobbing)
ZS_STEM = 8.6  # stem head height
Y_CHINE = 47.0  # where the chine runs into the stem
YS = [Y0 + (Y1 - Y0) * (1 - (1 - i / 130) ** 1.5) for i in range(131)]  # stations, denser at the bow
NV = (0.0, 0.33, 0.66, 1.0)  # keel to chine (V bottom)
NU = (0.12, 0.26, 0.42, 0.58, 0.74, 0.88, 1.0)  # chine to sheer (flaring topsides)
CHINE = len(NV) - 1
BH = 1.0  # bulwark height round the main deck


def stem_z(y):  # raked stem, curving into the forefoot below the water
    return ZK + (ZS_STEM - ZK) * max(0.0, (y - 44.0) / (Y1 - 44.0)) ** 1.15


def stem_y(z):
    return 44.0 + (Y1 - 44.0) * max(0.0, (z - ZK) / (ZS_STEM - ZK)) ** (1 / 1.15)


def half_breadth(y):
    if y <= 0.0:
        return 8.0 - 0.6 * (1 - ss(Y0, -10.0, y))
    return 8.0 * sqrt(max(0.0, 1 - (y / Y1) ** 1.9))


def sheer(y):  # bulwark top: sweeps up to the bow, fades down to deck level at the open transom
    return 5.4 + 3.2 * ss(-10.0, Y1, y) ** 1.7 - BH * (1 - ss(Y0, Y0 + 6.0, y))


def deck_z(y):
    return sheer(y) - BH * ss(Y0, Y0 + 6.0, y)


def section(y):
    """Starboard section from the keel (or the stem, where the bow rakes) up to the sheer, as (x, z)."""
    zs, bs = sheer(y), half_breadth(y)
    zb = max(ZK, stem_z(y))
    if y < Y_CHINE:
        zc = 0.15 + (stem_z(Y_CHINE) - 0.15) * ss(-6.0, Y_CHINE, y) ** 1.4
        bc = bs * (0.96 - 0.2 * ss(0.0, Y_CHINE, y)) * (1 - ss(30.0, Y_CHINE, y) ** 1.3)
        zc = max(zc, zb)
    else:
        zc, bc = zb, 0.0
    pts = [(bc * f ** 0.9, zb + (zc - zb) * f) for f in NV]
    pts += [(bc + (bs - bc) * f ** 1.6, zc + (zs - zc) * f) for f in NU]
    return pts


def hull_x(y, z):
    return hull_pt(y, z)[0]


def hull_pt(y, z, off=0.0):
    """Starboard hull surface at height z on station y, pushed off it by `off` along the section's normal
    (on the sloping V near the bow a sideways offset alone would sink into it). Returns (x, z)."""
    pts = section(y)
    for (x0, z0), (x1, z1) in zip(pts, pts[1:]):
        if z0 <= z <= z1 and z1 > z0:
            n = Vector((z1 - z0, -(x1 - x0))).normalized()
            return x0 + (x1 - x0) * (z - z0) / (z1 - z0) + n.x * off, z + n.y * off
    x0, z0 = pts[-1] if z >= pts[-1][1] else pts[0]
    return x0 + off, z0


def hull():
    for side in (1.0, -1.0):
        ys = YS if side > 0 else YS[::-1]
        cols = [[(side * x, y, z) for x, z in section(y)] for y in ys]
        V = grid([list(r) for r in zip(*cols)], "Hull")
        for j in range(len(ys) - 1):  # the chine is a crease, not a curve
            e = bm.edges.get((V[CHINE][j], V[CHINE][j + 1]))
            if e:
                e.smooth = False
    sec = section(Y0)
    poly([(-x, Y0, z) for x, z in sec] + [(x, Y0, z) for x, z in sec[::-1]], "Hull", facing=(0, -1, 0))  # transom


def hull_strip(zlo, zhi, mat, y_from=Y0, off=0.03, rows=3, n=260):
    """A band painted on the hull between zlo(y) and zhi(y) on both sides (navy lower hull, pinstripes)."""
    for side in (1.0, -1.0):
        grid_rows = []
        for r in range(rows):
            t = r / (rows - 1)
            row = []
            for k in range(n + 1):
                u = k / n
                yy = y_from
                for _ in range(3):  # where this row meets the stem depends on its height there
                    z = zlo(yy) + (zhi(yy) - zlo(yy)) * t
                    yy = y_from + (min(Y1, stem_y(z)) - 0.04 - y_from) * u
                z = zlo(yy) + (zhi(yy) - zlo(yy)) * t
                x, zz = hull_pt(yy, z, off + 0.12 * ss(28.0, Y1, yy))  # the bow curves hard: stand further off
                row.append(Vector((side * x, yy, zz)))
            grid_rows.append(row)
        if side < 0:
            grid_rows = [r[::-1] for r in grid_rows]
        grid(grid_rows, mat, smooth=True)
    if y_from <= Y0:  # carry it across the transom
        z0, z1 = zlo(Y0), zhi(Y0)
        poly([(-hull_x(Y0, z0), Y0 - off, z0), (hull_x(Y0, z0), Y0 - off, z0), (hull_x(Y0, z1), Y0 - off, z1),
              (-hull_x(Y0, z1), Y0 - off, z1)], mat, facing=(0, -1, 0))


def hull_window(side, y0, y1, zc, h, mat="Port", off=0.012):
    """Flush tinted window on the hull side with round ends (a stadium), following the hull's curve."""
    r = h / 2
    n = max(6, round((y1 - y0) / 0.15))
    ys = [y0 + (y1 - y0) * k / n for k in range(n + 1)]

    def half(y):
        e = min(y - y0, y1 - y, r)
        return sqrt(max(0.0, r * r - (r - e) ** 2))

    rows = []
    for t in (-1.0, -0.7, 0.0, 0.7, 1.0):
        rows.append([Vector((side * hull_pt(y, zc + t * half(y), off)[0], y, zc + t * half(y))) for y in ys])
    if side < 0:
        rows = [r[::-1] for r in rows]
    grid(rows, mat, smooth=False)


def bulwarks():
    """Teak cap and the inside face of the bulwarks; stainless rub rails outside."""
    for side in (1.0, -1.0):
        ys = [y for y in YS if y < Y1 - 0.5]
        inner, cap_out, cap_in = [], [], []
        for y in ys:
            zs, zd = sheer(y), deck_z(y)
            cap_out.append(Vector((side * hull_x(y, zs), y, zs)))
            cap_in.append(Vector((side * max(0.0, hull_x(y, zs) - 0.2), y, zs)))
            inner.append([Vector((side * max(0.0, hull_x(y, z) - 0.2), y, z)) for z in (zd, (zd + zs) / 2, zs)])
        rows = [list(r) for r in zip(*inner)]  # bottom to top
        if side > 0:
            rows = [r[::-1] for r in rows]  # inside face looks inboard
        grid(rows, "Super")
        cap = [cap_out, cap_in]  # outside edge to inside edge: faces up when the stations run forward on starboard
        grid(cap if side > 0 else [r[::-1] for r in cap], "Deck", smooth=False)
    for side in (1, -1):
        tube([(side * (hull_x(y, sheer(y)) + 0.04), y, sheer(y) - 0.12) for y in YS[:-1]], 0.05, "Steel", 6)


def main_deck(house):
    rows = []
    for y in YS:
        if y > Y1 - 0.8:
            break
        zd = deck_z(y)
        b = max(0.0, hull_x(y, zd) - 0.2)
        rows.append([Vector((-b + 2 * b * k / 12, y, zd)) for k in range(13)])

    def under_house(vs):
        return all(house.contains(v.co, -0.15) for v in vs)

    grid(rows, "Deck", uvs=[[deck_uv(v) for v in r] for r in rows], skip=under_house)


# ---------------------------------------------------------------- furniture and fittings
def chair(x, y, z, a):
    R, c = Matrix.Rotation(a, 3, "Z"), Vector((x, y, z))
    for loc, size, mat in (((0, 0, 0.45), (0.46, 0.46, 0.05), "Chair"),
                           ((0, 0, 0.49), (0.42, 0.42, 0.04), "Cushion"),
                           ((0.21, 0, 0.75), (0.05, 0.46, 0.56), "Chair")):
        box(c + R @ Vector(loc), size, mat, R)
    for lx in (-0.19, 0.19):
        for ly in (-0.19, 0.19):
            box(c + R @ Vector((lx, ly, 0.21)), (0.04, 0.04, 0.42), "Chair", R)


def table_set(x, y, z, chairs=4):
    lathe([(0, 0), (0.66, 0), (0.64, 0.24), (0.615, 0.6), (0.605, 0.72), (0.6, 0.76), (0, 0.765)], (x, y, z), "Table", 20)
    lathe([(0, 0.765), (0.045, 0.765), (0.045, 0.79), (0.03, 0.8), (0.04, 0.86), (0.03, 0.9), (0, 0.905)],
          (x, y, z), lambda i: "Gold" if i < 3 else "Bulb", 8)
    for k in range(chairs):
        a = pi / 4 + 2 * pi * k / chairs
        chair(x + 0.95 * cos(a), y + 0.95 * sin(a), z, a)


def sunpad(x, y, z, w, l):
    box((x, y, z + 0.1), (w, l, 0.2), "Super")
    box((x, y, z + 0.27), (w - 0.06, l - 0.06, 0.16), "Cushion")


def bollard(x, y, z):
    box((x, y, z + 0.03), (0.8, 0.32, 0.06), "Steel")
    for dx in (-0.22, 0.22):
        lathe([(0, 0), (0.12, 0), (0.12, 0.34), (0.15, 0.37), (0.15, 0.42), (0, 0.43)], (x + dx, y, z + 0.06), "Steel", 10)


def name_plate(y=-41.0, z=3.9, size=0.75):
    """The yacht's name in gold on both sides of the hull, aft."""
    font = None
    try:
        font = bpy.data.fonts.load("C:/Windows/Fonts/georgiab.ttf")
    except Exception:
        pass
    cu = bpy.data.curves.new("name", "FONT")
    cu.body, cu.size, cu.extrude, cu.resolution_u = "SIAM SUNSET", size, 0.015, 2
    cu.align_x, cu.align_y = "CENTER", "CENTER"
    if font:
        cu.font = font
    ob = bpy.data.objects.new("name", cu)
    bpy.context.scene.collection.objects.link(ob)
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    yaw = (hull_x(y + 2.0, z) - hull_x(y - 2.0, z)) / 4.0  # the hull widens forward here: turn the lettering with it
    for side in (1, -1):  # text x runs aft-to-fore on starboard, fore-to-aft on port, so it reads left to right
        R = Matrix(((0, 0, 1), (1, 0, 0), (0, 1, 0))) if side > 0 else Matrix(((0, 0, -1), (-1, 0, 0), (0, 1, 0)))
        R = Matrix.Rotation(-side * yaw, 3, "Z") @ R
        at = Vector((side * (hull_x(y, z) + 0.03), y, z))
        for p in me.polygons:
            face([bm.verts.new(at + R @ me.vertices[i].co) for i in p.vertices], "Gold")
    bpy.data.objects.remove(ob)
    bpy.data.curves.remove(cu)
    bpy.data.meshes.remove(me)


# ---------------------------------------------------------------- the yacht: five deckhouses stepping back, each under its own deck
D1, D2, D3, D4, D5 = 4.4, 7.7, 11.0, 14.3, 17.4  # main, upper, bridge, owner's and sun deck floors
HOUSES = (  # (outline: half width, aft end, start of the round front, its reach, corner), side lean, front rake
    ((6.6, -36.0, 20.0, 10.0, 1.5), 0.25, 1.2),
    ((6.2, -30.0, 18.0, 9.5, 1.5), 0.25, 1.6),
    ((5.6, -20.0, 16.0, 8.0, 1.2), 0.3, 2.2),
    ((4.8, -10.0, 10.0, 5.5, 1.0), 0.3, 1.8),
)
DECKS = (  # deck over each house: (outline), with wide round-cornered overhangs aft for shade
    (7.4, -42.0, 20.0, 11.5, 3.5),
    (7.0, -36.0, 18.0, 10.5, 3.0),
    (6.4, -27.0, 16.0, 8.6, 2.8),
    (5.6, -16.0, 10.0, 6.0, 2.4),
)
HARDTOP = (4.0, -9.5, 3.5, 3.0, 1.0)
STAFF = Vector((0.0, Y0 + 0.3, D1 + 2.6))  # ensign staff top on the transom (the page hangs the flag there)


def tumble(side_lean, front_lean):
    return lambda n: side_lean + front_lean * max(0.0, n.y) ** 2


def build():
    hull()
    hull_strip(lambda y: -0.1, lambda y: 2.3, "Boot")  # navy lower hull
    hull_strip(lambda y: 2.42, lambda y: 2.5, "Accent")
    hull_strip(lambda y: sheer(y) - 0.42, lambda y: sheer(y) - 0.34, "Accent", y_from=Y0 + 6.1)
    for side in (1, -1):  # guest cabins along the hull, portholes forward, anchor pockets
        for yc in (-36.0, -25.0, -14.0, -3.0, 8.0):  # guest cabins: three big windows each, not a ferry's row
            for k in range(3):
                hull_window(side, yc + 3.0 * k, yc + 3.0 * k + 2.6, 3.2, 0.85)
        for k in range(6):
            y = 24.0 + 2.2 * k
            hull_window(side, y, y + 0.5, 3.5 + 0.12 * k, 0.5)
        hull_window(side, 45.6, 47.6, 6.9, 0.9, "Rubber", off=0.02)
        ax = side * (hull_x(46.6, 6.8) + 0.12)
        box((ax, 46.6, 6.9), (0.14, 0.2, 0.8), "Steel")
        box((ax, 46.6, 6.5), (0.18, 0.9, 0.2), "Steel")
    name_plate()
    bulwarks()

    # deckhouses with tinted glazing all round, aft doors, and the decks over them
    floors = (D1, D2, D3, D4, D5)
    walls = []
    for k, (h, lean, rake) in enumerate(HOUSES):
        P = house_path(*h, step=1.2, m=56)
        W = Wall(P, floors[k], floors[k + 1] - 0.3, tumble(lean, rake))
        W.build()
        hw, y_aft = h[0], h[1]
        W.band(P.s_near((hw, y_aft + 1.6)), P.s_near((-hw, y_aft + 1.6)), floors[k] + 0.6, floors[k] + 2.55,
               r0=1.6, r1=-1.6, panel=2.6)
        W.band(P.s_near((-(hw - 1.6), y_aft)), P.s_near((hw - 1.6, y_aft)), floors[k] + 0.05, floors[k] + 2.65, panel=1.6)
        walls.append((P, W))
    main_deck(walls[0][0])
    for k, e in enumerate(DECKS):
        E = house_path(*e, step=1.2, m=60)
        above = walls[k + 1][0] if k + 1 < len(walls) else None
        slab(E, floors[k + 1] - 0.45, floors[k + 1], below=walls[k][1].top(), above=above)
        if k < 2:  # lower decks: solid curved bulwarks; the upper ones keep light glass rails
            solid_bulwark(E, floors[k + 1])
        else:
            balustrade(E, floors[k + 1])

    # hardtop on the sun deck on a swept radar arch, the mast with domes and radar
    zt = D5 + 2.7
    slab(house_path(*HARDTOP), zt, zt + 0.25, top="Super")
    for s in (1, -1):
        hexa(lambda i, j, k: Vector((s * (3.9 - 0.3 * i - 0.25 * k), ((3.6, 6.0), (2.0, 3.6))[k][j],
                                     D5 + (zt + 0.02 - D5) * k)), "Super")
        cyl((s * 3.7, -8.8, D5), (s * 3.7, -8.8, zt), 0.09, "Steel", 12, caps=False)
    cyl((0, 1.0, zt + 0.25), (0, 1.0, zt + 6.0), 0.18, "Super", 16, taper=lambda t: 1 - 0.5 * t)
    for x, y, z in ((-2.0, 2.2, zt + 0.25), (2.0, 2.2, zt + 0.25), (0.0, 1.0, zt + 4.0)):
        cyl((x, y, z), (x, y, z + 0.6), 0.3, "Super", 12)
        sphere((x, y, z + 1.6), 1.0, "Super", 24, 14)
    box((0, 1.0, zt + 2.6), (4.2, 0.3, 0.3), "Super", Matrix.Rotation(radians(20), 3, "Z"))
    box((0, 1.0, zt + 2.3), (0.6, 0.6, 0.5), "Super")
    sphere((0, 1.0, zt + 6.1), 0.14, "NavWhite", 10, 6)
    for x in (-3.0, 3.0):
        cyl((x, -6.5, zt + 0.25), (x, -7.6, zt + 4.0), 0.035, "Super", 6)
    for s, mat in ((1, "NavGreen"), (-1, "NavRed")):  # sidelights on the bridge deck fascia
        x = s * (DECKS[2][0] + 0.09)
        box((x, 14.0, D4 - 0.15), (0.16, 0.5, 0.28), "Rubber")
        sphere((x + s * 0.1, 14.15, D4 - 0.15), 0.09, mat, 8, 6)

    # glass-sided pool on the bridge deck, aft of the bridge
    zp = D3
    for c, size in (((0, -24.2, zp + 0.6), (6.8, 0.3, 1.2)), ((0, -30.8, zp + 0.6), (6.8, 0.3, 1.2)),
                    ((3.25, -27.5, zp + 0.6), (0.3, 6.9, 1.2)), ((-3.25, -27.5, zp + 0.6), (0.3, 6.9, 1.2))):
        box(c, size, {"+z": "Deck", "*": "Super"})
    poly([(-3.1, -30.65, zp + 1.05), (3.1, -30.65, zp + 1.05), (3.1, -24.35, zp + 1.05), (-3.1, -24.35, zp + 1.05)],
         "Water", facing=(0, 0, 1))
    poly([(-3.1, -30.96, zp + 0.1), (3.1, -30.96, zp + 0.1), (3.1, -30.96, zp + 1.15), (-3.1, -30.96, zp + 1.15)],
         "GlassRail", facing=(0, -1, 0))
    for x in (-4.7, 4.7):
        sunpad(x, -27.5, zp, 1.2, 2.0)

    # beach club at the stern: platform, steps up either side, the club's glass front, ensign staff
    plat = rect_path(-7.0, 7.0, Y0 - 3.0, Y0 + 0.3, 1.2)
    grid([[plat.Wi(j, 0.6) for j in range(len(plat.p))], [plat.Wi(j, 0.95) for j in range(len(plat.p))]], "Super",
         close=True, smooth=False)
    fill(plat, 0.95, "Deck", uv=deck_uv)
    poly([(-4.6, Y0 - 0.02, 1.0), (4.6, Y0 - 0.02, 1.0), (4.6, Y0 - 0.02, 3.8), (-4.6, Y0 - 0.02, 3.8)], "Glass",
         uvs=[(0, 1), (1, 1), (1, 0), (0, 0)], facing=(0, -1, 0))
    for s in (1, -1):
        for k in range(9):
            y0 = Y0 - 2.7 + 0.3 * k
            z = 0.95 + (D1 - 0.95) * (k + 1) / 9
            hexa(lambda i, j, kk: Vector((s * (4.8 + 2.1 * i), (y0, Y0 + 0.1)[j], (0.9, z)[kk])),
                 {"+z": "Deck", "*": "Super"}, uv=deck_uv)
    pts = [Vector((x, Y0 + 0.2, D1)) for x in (-4.6, -1.5, 1.5, 4.6)]
    grid([[p + Vector((0, 0, 0.1)) for p in pts], [p + Vector((0, 0, 0.94)) for p in pts]], "GlassRail", smooth=False)
    tube([p + Vector((0, 0, 1.0)) for p in pts], 0.035, "Steel", 8)
    for x, y, a in ((10.5, -52.0, 0.5), (-9.8, -53.5, -0.35)):  # jet skis waiting off the beach club
        jet_ski(x, y, a)
    cyl((STAFF.x, STAFF.y, D1 + 1.0), STAFF, 0.05, "Steel", 8)
    sphere(STAFF + Vector((0, 0, 0.06)), 0.08, "NavWhite", 8, 6)

    # foredeck: bow rail, helipad, windlasses, bollards
    for side in (1, -1):
        rail = [Vector((side * hull_x(y, sheer(y)) * 0.98, y, sheer(y))) for y in YS if 18.0 < y < Y1 - 0.6]
        tube([p + Vector((0, 0, 0.9)) for p in rail] + [Vector((0, Y1 - 0.4, sheer(Y1 - 0.4) + 0.9))], 0.04, "Steel", 8)
        for p in rail[::3]:
            cyl(p, p + Vector((0, 0, 0.9)), 0.03, "Steel", 6, caps=False)
    # helipad: a round pad on a pedestal, high enough to clear the bow rail, with a helicopter on it
    yh, zh, rh = 38.5, 9.8, 5.5
    lathe([(0, deck_z(37.5)), (2.6, deck_z(37.5)), (1.9, zh - 0.35), (0, zh - 0.35)], (0, 37.5, 0), "Super", 32)
    lathe([(0, -0.35), (rh - 0.2, -0.35), (rh, -0.15), (rh, 0.0), (0, 0.0)], (0, yh, zh),
          lambda i: "Boot" if i == 3 else "Super", 56)
    ring((0, yh, zh + 0.02), rh - 0.9, 0.1, "Accent", axis="z", seg=56, mseg=4)
    for c, size in (((-1.1, yh, zh + 0.02), (0.45, 3.2, 0.04)), ((1.1, yh, zh + 0.02), (0.45, 3.2, 0.04)),
                    ((0, yh, zh + 0.02), (1.8, 0.45, 0.04))):
        box(c, size, "Super")
    net = [[Vector((r * cos(2 * pi * k / 56), yh + r * sin(2 * pi * k / 56), zh + dz)) for k in range(56)]
           for r, dz in ((rh, -0.1), (rh + 0.7, 0.2))]  # safety net, angled out round the edge
    grid(net, "Frame", close=True, smooth=False)
    grid(net[::-1], "Frame", close=True, smooth=False)
    tube(net[1], 0.03, "Steel", 6, close=True)
    ah = radians(65)  # side-on to the usual bow-quarter view; centred so skids and tail stay over the pad
    helicopter(Vector((0, yh, zh)) + Matrix.Rotation(ah, 3, "Z") @ Vector((0, 1.9, 0)), ah)
    for y in (44.0, 45.5):
        zd = deck_z(y)
        cyl((-0.4, y, zd + 0.45), (0.4, y, zd + 0.45), 0.3, "Steel", 14)
        box((0, y, zd + 0.1), (1.0, 0.8, 0.2), "Steel")
    for s, y in ((1, 44.0), (-1, 45.5)):  # anchor chains from the windlasses out to the hawse pipes
        tube([(s * 0.4, y, deck_z(y) + 0.45), (s * (hull_x(46.6, deck_z(46.6)) - 0.5), 46.6, deck_z(46.6) + 0.06)],
             0.07, "Steel", 6)
    for x, y in ((5.4, 22.0), (-5.4, 22.0), (6.4, -44.0), (-6.4, -44.0)):
        bollard(x, y, deck_z(y))

    # main aft deck: lounge; upper aft deck: three long dinner tables; pool deck: sunbeds and two tables;
    # owner's deck: one long table; sun deck: round tables under the hardtop, sunpads forward
    for s in (1, -1):
        sofa(s * 5.6, -40.5, D1, 4.0, 1.0, s * pi / 2)
        box((s * 4.2, -40.5, D1 + 0.2), (0.9, 1.8, 0.4), {"+z": "Deck", "*": "Super"}, uv=deck_uv)
    sofa(0, -37.4, D1, 5.0, 1.0, pi)
    for x in (-4.4, 0.0, 4.4):
        long_table(x, -40.6, -31.4, D2, 6)
    for x in (-5.0, -2.0, 2.0, 5.0):
        sunpad(x, -33.8, D3, 1.0, 2.0)
    for x in (-3.6, 3.6):
        table_set(x, -21.8, D3)
    long_table(0.0, -23.0, -12.0, D4, 8)
    for x in (-2.6, 2.6):
        table_set(x * 0.8, -3.2, D5)
        table_set(x * 0.8, -6.6, D5)
    for x in (-1.8, 1.8):
        sunpad(x, 9.5, D5, 2.6, 2.0)

    # dinner guests at the tables, a few more standing about
    def long_seats(x, y0, y1, z, n):
        return [(x + s * 0.85, y0 + (y1 - y0) * (k + 0.5) / n, z, 0.0 if s > 0 else pi) for k in range(n) for s in (1, -1)]

    def round_seats(x, y, z, n=4):
        return [(x + 0.95 * cos(pi / 4 + 2 * pi * k / n), y + 0.95 * sin(pi / 4 + 2 * pi * k / n), z, pi / 4 + 2 * pi * k / n)
                for k in range(n)]

    seats = [s for x in (-4.4, 0.0, 4.4) for s in long_seats(x, -40.6, -31.4, D2, 6)]
    seats += long_seats(0.0, -23.0, -12.0, D4, 8)
    seats += [s for x in (-3.6, 3.6) for s in round_seats(x, -21.8, D3)]
    seats += [s for x in (-2.08, 2.08) for y in (-3.2, -6.6) for s in round_seats(x, y, D5)]
    guests(seats)
    for x, y, z, a in ((3.0, -42.6, D1, 0.4), (3.6, -43.2, D1, 3.4), (-5.6, -45.0, D1, -1.2), (-0.9, -35.6, D3, 1.7),
                       (-0.2, -35.2, D3, 4.6), (2.6, -13.6, D5, 2.0), (-3.0, -48.6, 0.95, 0.2)):
        person(x, y, z, a, RNG.choice(("Cushion", "Table", "Boot", "Accent")))

    # festoon lights over the open dinner deck and under the sun-deck hardtop
    for x in (-4.4, 0.0, 4.4):
        cyl((x, -41.7, D2), (x, -41.7, D2 + 2.7), 0.04, "Steel", 6)
        string_lights((x, -41.7, D2 + 2.65), (x, -35.9, D3 - 0.5))
    for x in (-3.0, 0.0, 3.0):
        string_lights((x, -9.3, zt - 0.05), (x, -15.6, D5 + 1.0), sag=0.3)

    # ship's gear: limousine tender alongside, life-raft canisters, satcom domes and whip aerials
    tender(13.2, -36.0, 0.04)
    for s in (1, -1):
        for y in (2.0, 4.0, 6.0):  # on the bridge deck's side decks, behind glass rails so they show
            box((s * 5.75, y, D4 + 0.12), (0.7, 0.3, 0.24), "Steel")
            cyl((s * 5.75, y - 0.55, D4 + 0.55), (s * 5.75, y + 0.55, D4 + 0.55), 0.33, "Super", 12)
        cyl((s * 3.0, -8.4, zt + 0.25), (s * 3.0, -8.4, zt + 0.7), 0.15, "Super", 8)
        sphere((s * 3.0, -8.4, zt + 1.05), 0.45, "Super", 16, 10)
        cyl((s * 3.6, -6.0, zt + 0.25), (s * 3.6, -6.0, zt + 5.0), 0.03, "Super", 6, taper=lambda t: 1 - 0.6 * t)

    for e in bm.edges:  # hard corners stay crisp, curved surfaces stay smooth
        if len(e.link_faces) == 2 and e.calc_face_angle(0.0) > radians(40):
            e.smooth = False
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")


def make_mat(name):
    hx, metal, rough, emit = MATS[name]
    lin = [((c / 255 + 0.055) / 1.055) ** 2.4 if c / 255 > 0.04045 else c / 255 / 12.92
           for c in (int(hx[i:i + 2], 16) for i in (1, 3, 5))]
    m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except Exception:
        pass
    nt = m.node_tree
    b = nt.nodes.get("Principled BSDF") or nt.nodes.new("ShaderNodeBsdfPrincipled")
    out = nt.nodes.get("Material Output") or nt.nodes.new("ShaderNodeOutputMaterial")
    if not b.outputs[0].is_linked:
        nt.links.new(b.outputs[0], out.inputs[0])
    b.inputs["Base Color"].default_value = (*lin, 1)
    b.inputs["Metallic"].default_value = metal
    b.inputs["Roughness"].default_value = rough
    if emit:
        b.inputs["Emission Color"].default_value = (*lin, 1)
        b.inputs["Emission Strength"].default_value = emit
    if name == "GlassRail":
        b.inputs["Alpha"].default_value = 0.25
    return m


def to_object():
    me = bpy.data.meshes.new("Boat")
    bm.to_mesh(me)
    for name in NAMES:
        me.materials.append(make_mat(name))
    ob = bpy.data.objects.new("Boat", me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def bake_ao(ob, path, size=2048, samples=256):
    """Second UV set packed by Smart UV Project, then Cycles AO baked into it.
    Glass and lights get no space in it: the page uses the map on lit materials only."""
    me = ob.data
    me.uv_layers.active = me.uv_layers.new(name="AO")
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="DESELECT")
    for i, name in enumerate(NAMES):
        if name not in NO_AO:
            ob.active_material_index = i
            bpy.ops.object.material_slot_select()
    bpy.ops.uv.smart_project(angle_limit=radians(66), island_margin=0.002)
    bpy.ops.uv.pack_islands(rotate=True, margin=0.002)
    bpy.ops.object.mode_set(mode="OBJECT")
    ao = me.uv_layers["AO"].data
    for p in me.polygons:
        if NAMES[p.material_index] in NO_AO:
            for li in p.loop_indices:
                ao[li].uv = (0.9999, 0.9999)
    me.uv_layers.active = me.uv_layers["UVMap"]
    img = bpy.data.images.new("BoatAO", size, size)
    img.colorspace_settings.name = "Non-Color"
    nodes = []
    for m in me.materials:
        n = m.node_tree.nodes.new("ShaderNodeTexImage")
        n.image = img
        m.node_tree.nodes.active = n
        nodes.append((m, n))
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    if sc.world is None:
        sc.world = bpy.data.worlds.new("World")
    sc.world.light_settings.distance = 2.0
    bpy.ops.object.bake(type="AO", uv_layer="AO", margin=8, use_clear=True)
    img.filepath_raw = path
    img.file_format = "JPEG"
    img.save(quality=88)
    for m, n in nodes:
        m.node_tree.nodes.remove(n)


def preview(ob, outdir):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = int(OPT.get("samples", 24))
    sc.cycles.use_denoising = True
    sc.render.resolution_x, sc.render.resolution_y = 1280, 720
    w = sc.world or bpy.data.worlds.new("World")
    sc.world = w
    try:
        w.use_nodes = True
    except Exception:
        pass
    bg = w.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (0.42, 0.55, 0.75, 1)
    bg.inputs[1].default_value = 0.9
    water = bpy.data.meshes.new("Water")
    water.from_pydata([(-400, -400, 0), (400, -400, 0), (400, 400, 0), (-400, 400, 0)], [], [(0, 1, 2, 3)])
    wm = bpy.data.materials.new("WaterMat")
    try:
        wm.use_nodes = True
    except Exception:
        pass
    pb = wm.node_tree.nodes.get("Principled BSDF")
    pb.inputs["Base Color"].default_value = (0.01, 0.04, 0.05, 1)
    pb.inputs["Roughness"].default_value = 0.06
    water.materials.append(wm)
    wo = bpy.data.objects.new("Water", water)
    sc.collection.objects.link(wo)
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy, sun.data.angle = 3.2, radians(1.5)
    sun.rotation_euler = (radians(58), 0, radians(-35))
    sc.collection.objects.link(sun)
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    cam.data.sensor_fit = "VERTICAL"
    cam.data.angle_y = radians(40)
    sc.collection.objects.link(cam)
    sc.camera = cam
    views = {  # around the 98 m yacht, plus close looks
        "hero": ((80, -85, 28), (0, 0, 9)),
        "side": ((-110, -10, 14), (0, 0, 9)),
        "bow": ((-60, 95, 18), (0, 0, 10)),
        "top": ((45, -60, 70), (0, -5, 10)),
        "stern": ((20, -110, 14), (0, -20, 8)),
        "ref": ((70, 60, 35), (0, 5, 8)),
        "aft": ((25, -70, 10), (0, -38, 5)),
        "bowclose": ((22, 70, 5), (0, 44.0, 3)),
        "heli": ((26, 58, 18), (0, 37.0, 10)),
        "dinner": ((22, -62, 13), (0, -36.0, 8)),
    }
    for name in OPT.get("views", "hero,side,bow,top,stern,ref").split(","):
        p, look = views[name]
        cam.location = p
        cam.rotation_euler = (Vector(look) - Vector(p)).to_track_quat("-Z", "Y").to_euler()
        sc.render.filepath = os.path.join(outdir, name + ".png")
        bpy.ops.render.render(write_still=True)


def main():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    build()
    ob = to_object()
    print("BOAT verts", len(ob.data.vertices), "faces", len(ob.data.polygons))
    if "preview" in OPT:
        preview(ob, OPT["preview"])
        return
    if "nobake" not in OPT:
        bake_ao(ob, os.path.join(HERE, "boat-ao.jpg"))
        # the page reads TEXCOORD_1 as uv2 for its aoMap: UV set order is part of the contract
        assert [uv.name for uv in ob.data.uv_layers] == ["UVMap", "AO"], [uv.name for uv in ob.data.uv_layers]
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    glb = os.path.join(bpy.app.tempdir, "boat.glb")
    bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB", use_selection=True,
                              export_yup=True, export_apply=True, export_texcoords=True, export_normals=True,
                              export_materials="EXPORT")
    glb_to_json(glb, os.path.join(HERE, "boat.json"))


def glb_to_json(glb_path, json_path):
    """Artifacts serve .json but not .glb, so ship the same glTF with its one buffer inlined as base64."""
    with open(glb_path, "rb") as f:
        data = f.read()
    n = struct.unpack_from("<I", data, 12)[0]  # JSON chunk length; its bytes start at 20, the BIN chunk's at 28 + n
    doc = json.loads(data[20:20 + n])
    buf = doc["buffers"][0]
    buf["uri"] = "data:application/octet-stream;base64," + base64.b64encode(data[28 + n:28 + n + buf["byteLength"]]).decode()
    with open(json_path, "w") as f:
        json.dump(doc, f, separators=(",", ":"))


main()
