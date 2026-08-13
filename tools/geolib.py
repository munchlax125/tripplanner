# -*- coding: utf-8 -*-
"""Minimal geometry toolkit: clip / simplify / stitch / emit SVG paths (no deps)."""
import math

# ---------------------------------------------------------------- projection
class Proj:
    """Equirectangular projection recovered from the original maps."""
    def __init__(self, p):
        self.s, self.x0, self.y0 = p["s"], p["x0"], p["y0"]
        self.lat0, self.lon0, self.cosf = p["lat0"], p["lon0"], p["cosf"]
        self.vb = p["vb"]

    def __call__(self, lon, lat):
        return (self.x0 + (lon - self.lon0) * self.s * self.cosf,
                self.y0 - (lat - self.lat0) * self.s)

    def rect(self, pad=6.0):
        x, y, w, h = self.vb
        return (x - pad, y - pad, x + w + pad, y + h + pad)

    def lonlat_box(self, pad=6.0):
        x0, y0, x1, y1 = self.rect(pad)
        lo_a = self.lon0 + (x0 - self.x0) / (self.s * self.cosf)
        lo_b = self.lon0 + (x1 - self.x0) / (self.s * self.cosf)
        la_b = self.lat0 - (y0 - self.y0) / self.s
        la_a = self.lat0 - (y1 - self.y0) / self.s
        return (lo_a, la_a, lo_b, la_b)

# ---------------------------------------------------------------- clipping
def _inside(p, edge, r):
    x0, y0, x1, y1 = r
    return (p[0] >= x0, p[0] <= x1, p[1] >= y0, p[1] <= y1)[edge]

def _isect(a, b, edge, r):
    x0, y0, x1, y1 = r
    if edge < 2:
        xv = x0 if edge == 0 else x1
        t = (xv - a[0]) / (b[0] - a[0])
        return (xv, a[1] + t * (b[1] - a[1]))
    yv = y0 if edge == 2 else y1
    t = (yv - a[1]) / (b[1] - a[1])
    return (a[0] + t * (b[0] - a[0]), yv)

def clip_polygon(pts, r):
    """Sutherland-Hodgman against an axis-aligned rect."""
    out = pts
    for e in range(4):
        if not out: return []
        inp, out = out, []
        prev = inp[-1]
        pin = _inside(prev, e, r)
        for cur in inp:
            cin = _inside(cur, e, r)
            if cin:
                if not pin: out.append(_isect(prev, cur, e, r))
                out.append(cur)
            elif pin:
                out.append(_isect(prev, cur, e, r))
            prev, pin = cur, cin
    return out

def clip_line(pts, r):
    """Clip a polyline to a rect -> list of chains."""
    x0, y0, x1, y1 = r
    def code(p):
        c = 0
        if p[0] < x0: c |= 1
        elif p[0] > x1: c |= 2
        if p[1] < y0: c |= 4
        elif p[1] > y1: c |= 8
        return c
    # A closed ring must not be split at its arbitrary seam vertex: if that vertex sits
    # inside the rect the first and last clipped chains are really one piece, and both
    # would end up dangling in mid-frame. Rotate the ring to start outside instead.
    if len(pts) > 2 and pts[0] == pts[-1]:
        i0 = next((i for i, p in enumerate(pts[:-1]) if code(p)), None)
        if i0:
            pts = pts[i0:-1] + pts[:i0 + 1]

    chains, cur = [], []
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        ca, cb = code(a), code(b)
        ax, ay, bx, by = a[0], a[1], b[0], b[1]
        accept = False
        while True:
            if not (ca | cb): accept = True; break
            if ca & cb: break
            c = ca or cb
            if c & 8:   x, y = ax + (bx - ax) * (y1 - ay) / (by - ay), y1
            elif c & 4: x, y = ax + (bx - ax) * (y0 - ay) / (by - ay), y0
            elif c & 2: x, y = x1, ay + (by - ay) * (x1 - ax) / (bx - ax)
            else:       x, y = x0, ay + (by - ay) * (x0 - ax) / (bx - ax)
            if c == ca: ax, ay = x, y; ca = code((ax, ay))
            else:       bx, by = x, y; cb = code((bx, by))
        if accept:
            p, q = (ax, ay), (bx, by)
            if cur and abs(cur[-1][0] - p[0]) < 1e-9 and abs(cur[-1][1] - p[1]) < 1e-9:
                cur.append(q)
            else:
                if len(cur) > 1: chains.append(cur)
                cur = [p, q]
        else:
            if len(cur) > 1: chains.append(cur)
            cur = []
    if len(cur) > 1: chains.append(cur)
    return chains

# ---------------------------------------------------------------- simplify
def simplify(pts, tol):
    if len(pts) < 3: return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    t2 = tol * tol
    while stack:
        i, j = stack.pop()
        if j - i < 2: continue
        ax, ay = pts[i]; bx, by = pts[j]
        dx, dy = bx - ax, by - ay
        dd = dx * dx + dy * dy
        best, bi = -1.0, -1
        for k in range(i + 1, j):
            px, py = pts[k]
            if dd == 0:
                d2 = (px - ax) ** 2 + (py - ay) ** 2
            else:
                t = ((px - ax) * dx + (py - ay) * dy) / dd
                t = 0.0 if t < 0 else (1.0 if t > 1 else t)
                d2 = (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2
            if d2 > best: best, bi = d2, k
        if best > t2:
            keep[bi] = True
            stack.append((i, bi)); stack.append((bi, j))
    return [p for p, k in zip(pts, keep) if k]

# ---------------------------------------------------------------- stitching
def stitch(ways, q=7):
    """Join line fragments that share endpoints (lon/lat, rounded to `q` places)."""
    def key(p): return (round(p[0], q), round(p[1], q))
    ends = {}
    segs = [list(w) for w in ways if len(w) > 1]
    for i, s in enumerate(segs):
        ends.setdefault(key(s[0]), []).append((i, 0))
        ends.setdefault(key(s[-1]), []).append((i, 1))
    used = [False] * len(segs)
    out = []
    for i in range(len(segs)):
        if used[i]: continue
        used[i] = True
        chain = segs[i][:]
        for _ in range(2):                       # extend forward, then backward
            while True:
                k = key(chain[-1])
                nxt = None
                for j, side in ends.get(k, []):
                    if not used[j]: nxt = (j, side); break
                if not nxt: break
                j, side = nxt; used[j] = True
                add = segs[j] if side == 0 else segs[j][::-1]
                chain += add[1:]
                if key(chain[0]) == key(chain[-1]): break
            chain.reverse()
        out.append(chain)
    return out

# ---------------------------------------------------------------- coast fill
def land_rings(chains, r, eps=1e-6):
    """Close coastline chains into land polygons.

    OSM puts land on the left of a coastline way in lon/lat, and the y-flip of the
    projection preserves that: land stays on the visual left. So the closing walk
    around the viewBox must also keep the interior on its left, i.e. run
    right edge upwards -> top edge leftwards -> left edge down -> bottom rightwards.
    """
    x0, y0, x1, y1 = r
    W, H = x1 - x0, y1 - y0
    def onb(p):
        return (abs(p[0]-x0) < 1e-6 or abs(p[0]-x1) < 1e-6 or
                abs(p[1]-y0) < 1e-6 or abs(p[1]-y1) < 1e-6)
    def param(p):
        if abs(p[0] - x1) < 1e-6: return (y1 - p[1]) / H          # right edge, up
        if abs(p[1] - y0) < 1e-6: return 1 + (x1 - p[0]) / W      # top edge, left
        if abs(p[0] - x0) < 1e-6: return 2 + (p[1] - y0) / H      # left edge, down
        return 3 + (p[0] - x0) / W                                # bottom edge, right
    corners = {1.0: (x1, y0), 2.0: (x0, y0), 3.0: (x0, y1), 4.0: (x1, y1)}

    rings, open_ch = [], []
    for c in chains:
        if len(c) < 2: continue
        if (abs(c[0][0]-c[-1][0]) < eps and abs(c[0][1]-c[-1][1]) < eps):
            rings.append(c)                       # island fully inside
        elif onb(c[0]) and onb(c[-1]):
            open_ch.append(c)
    if not open_ch:
        return rings
    starts = sorted(range(len(open_ch)), key=lambda i: param(open_ch[i][0]))
    used = set()
    for i0 in range(len(open_ch)):
        if i0 in used: continue
        ring, cur = [], i0
        guard = 0
        while cur not in used and guard < 4 * len(open_ch) + 8:
            guard += 1
            used.add(cur)
            ring += open_ch[cur][:]
            te = param(open_ch[cur][-1])
            nxt, best = None, None
            for j in starts:
                if j in used and j != i0: continue
                ts = param(open_ch[j][0])
                d = (ts - te) % 4.0
                if d < 1e-9: d += 4.0
                if best is None or d < best: best, nxt = d, j
            if nxt is None: break
            swept = []
            for cp in corners:                    # corners swept over, in walk order
                d = (cp - te) % 4.0
                if d < 1e-9: d = 4.0
                if d < best: swept.append((d, cp))
            for _, cp in sorted(swept): ring.append(corners[cp])
            if nxt == i0: break
            cur = nxt
        if len(ring) > 2: rings.append(ring)
    return rings

# ---------------------------------------------------------------- output
def d_line(chains, tol=.35, prec=1):
    f = "%%.%df" % prec
    out = []
    for c in chains:
        c = simplify(c, tol)
        if len(c) < 2: continue
        out.append("M" + " ".join((f + "," + f) % (p[0], p[1]) for p in c))
    return "".join(out)

def d_poly(rings, tol=.35, prec=1):
    f = "%%.%df" % prec
    out = []
    for c in rings:
        c = simplify(c, tol)
        if len(c) < 3: continue
        out.append("M" + " ".join((f + "," + f) % (p[0], p[1]) for p in c) + "Z")
    return "".join(out)

def bbox_of(coords):
    xs = [c[0] for c in coords]; ys = [c[1] for c in coords]
    return min(xs), min(ys), max(xs), max(ys)

def overlaps(b, box):
    return not (b[2] < box[0] or b[0] > box[2] or b[3] < box[1] or b[1] > box[3])
