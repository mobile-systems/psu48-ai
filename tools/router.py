"""Auto-router for the PSU48 PCB.

Grid maze router over the footprints placed by pcbgen.py. Routes all netlist
nets with >= 2 pads by A* on F.Cu/B.Cu (STEP = 0.2 mm), wide tracks for power,
vias 1.2/0.6 mm. Output is appended to the board node written by pcbgen.

Run from tools/:  "C:/Program Files/KiCad/10.0/bin/python.exe" router.py
"""

import heapq
import math
import os

import pcbgen as P
from sexp import Raw, find, findall, dumps, unq


def _envf(n, d):
    try:
        return float(os.environ.get(n, d))
    except (TypeError, ValueError):
        return float(d)


STEP = _envf("PSU_STEP", 0.2)
SIG_W = _envf("PSU_SIGW", 0.3)
ROUTE_CL = _envf("PSU_CL", 0.25)  # uniform clearance enforced during routing
PAD_CAP = _envf("PSU_RCAP", 1.0)  # 0..1 narrowing of raster ring radius
BOARD_W = P.BOARD_W
BOARD_H = P.BOARD_H
BELT = 2.0
W = int(round(BOARD_W / STEP))
H = int(round(BOARD_H / STEP))

N0 = int(round((0 + BELT) / STEP))
N1 = int(round((BOARD_W - BELT) / STEP))
M0 = int(round((0 + BELT) / STEP))
M1 = int(round((BOARD_H - BELT) / STEP))

VIA_SIZE = 1.2
VIA_DRILL = 0.6
VIA_COST = 4.0                   # cells; ~0.8 mm of track equivalent per via
PAD_BASE = 0.15                 # extra safety around pad AABB


def via_radius():
    return max(1, int(math.ceil((VIA_SIZE / 2.0 + ROUTE_CL) / STEP)))


def pad_radius(w):
    """Ring radius (cells) for pads/tracks of a net with track width w."""
    r = (w / 2.0 + ROUTE_CL) / STEP
    return max(1, int(math.ceil(r * PAD_CAP + (1 - PAD_CAP))))


def route_cls_w(net):
    cls, w, _ = net_style(net)
    return w

RELAX = False                    # set True for the second, tighter pass


def sig_style():
    return ("SIG", SIG_W, 0.25)


def net_style(net):
    """(cls, width, clearance) per net name."""
    if net in ("+48V",):
        return ("OUT", 2.5, 0.8)
    if net in ("VBUS400", "VRECT", "AC_L", "AC_N", "L", "N"):
        return ("HV", 1.5, 1.0)
    if net in ("GND", "GND48", "PGND_OUT"):
        return ("PWR", 1.2, 0.8)
    if net in ("+15V", "+15VS", "+12V"):
        return ("PWR", 0.8, 0.6)
    return sig_style()


def rot_cos_sin(rot):
    r = math.radians(-rot)
    return math.cos(r), math.sin(r)


def wpt(cx, cy, cos, sin, x, y):
    return (cx + x * cos - y * sin, cy + x * sin + y * cos)


def num(v):
    return float(str(v))


def pcb_net(net):
    nsh = P.net_sheets_map()
    if net in P.D.POWER_TERMS or len(nsh.get(net, ())) > 1:
        return net
    return f"{sorted(nsh[net])[0]}/{net}"


def pad_boxes(merged, order, positions):
    """World AABBs of every copper pad: (x0, y0, x1, y1, f_on, b_on, net)."""
    boxes = []
    for ref in order:
        cx, cy, rot = positions[ref]
        cos, sin = rot_cos_sin(rot)
        fp = P.load_fp(merged[ref]["fp"])
        nets = merged[ref]["nets"]
        for pad in findall(fp, "pad"):
            pin = unq(pad[1])
            net = nets.get(pin)
            at = find(pad, "at")
            if at is None:
                continue
            px, py = num(at[1]), num(at[2])
            prot = num(at[3]) if len(at) > 3 else 0.0
            shape = find(pad, "shape")
            shape = shape[1] if shape else "round"
            size = find(pad, "size")
            w = num(size[1]) if size is not None and len(size) > 1 else 0.0
            h = num(size[2]) if size is not None and len(size) > 2 else w
            layers = [unq(x) for x in find(pad, "layers")[1:]] if find(pad, "layers") else []
            f_on = "*" in "".join(layers) or "F.Cu" in layers or "*.Cu" in layers
            b_on = "*" in "".join(layers) or "B.Cu" in layers or "*.Cu" in layers
            pcos, psin = rot_cos_sin(prot)
            pts = []
            if str(shape) == "custom":
                for xy in _custom_pts(pad):
                    wx, wy = wpt(cx, cy, cos, sin, px + xy[0], py + xy[1])
                    pts.append((wx, wy))
            else:
                hlw, hlh = w / 2.0, h / 2.0
                for dx in (-hlw, hlw):
                    for dy in (-hlh, hlh):
                        rx = dx * pcos - dy * psin
                        ry = dx * psin + dy * pcos
                        wx, wy = wpt(cx, cy, cos, sin, px + rx, py + ry)
                        pts.append((wx, wy))
            if not pts:
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            nm = pcb_net(net) if net else None
            boxes.append((min(xs), min(ys), max(xs), max(ys), f_on, b_on, nm,
                          ref, pin))
    return boxes


def _custom_pts(pad):
    out = []
    stack = list(pad)
    while stack:
        c = stack.pop()
        if isinstance(c, list):
            if c and str(c[0]) == "xy" and len(c) > 2:
                out.append((num(c[1]), num(c[2])))
            else:
                stack.extend(x for x in reversed(c) if isinstance(x, list))
    return out


def cell(x, y):
    i = int(round(x / STEP))
    j = int(round(y / STEP))
    return max(0, min(W - 1, i)), max(0, min(H - 1, j))


class Router:
    def __init__(self, boxes):
        self.boxes = boxes
        self.trackF = bytearray(W * H)
        self.trackB = bytearray(W * H)
        self.masks = {}
        self.own_reuse = set()
        self.mm = (bytearray(W * H), bytearray(W * H))
        self.vm = None
        self.live_r = None
        self.pad_masks()

    def tgrid(self, l):
        return self.trackF if l == 0 else self.trackB

    def is_free(self, l, i, j):
        c = (i, j, l)
        if c in self.own_reuse:
            return True
        idx = j * W + i
        if self.mm[l][idx] != 0:
            return False
        return self.tgrid(l)[idx] == 0

    def via_free(self, l, i, j):
        c = (i, j, l)
        if c in self.own_reuse:
            return True
        idx = j * W + i
        if self.vm[l][idx] != 0:
            return False
        return self.tgrid(l)[idx] == 0

    def _fill(self, l, i0, j0, i1, j1, g=None):
        g = g if g is not None else self.masks[self.live_r][l]
        i0 = max(0, i0)
        i1 = min(W - 1, i1)
        j0 = max(0, j0)
        j1 = min(H - 1, j1)
        for j in range(j0, j1 + 1):
            base = j * W
            for i in range(i0, i1 + 1):
                g[base + i] = 1

    def pad_masks(self):
        """Per track-width radius: one dilated pad mask (both layers, +belt)."""
        for cls, w in (("OUT", 2.5), ("HV", 1.5), ("PWR", 1.2),
                       ("PWRB", 0.8), ("SIG", SIG_W)):
            r = pad_radius(w)
            if r in self.masks:
                continue
            mf = bytearray(W * H)
            mb = bytearray(W * H)
            self.masks[r] = (mf, mb)
            for first in (mf, mb):
                for j in range(0, max(1, M0)):
                    for i in range(0, W):
                        first[j * W + i] = 1
                for j in range(M1 + 1, H):
                    for i in range(0, W):
                        first[j * W + i] = 1
                for i in range(0, max(1, N0)):
                    for j in range(0, H):
                        first[j * W + i] = 1
                for i in range(N1 + 1, W):
                    for j in range(0, H):
                        first[j * W + i] = 1
        for r in self.masks:
            self.live_r = r
            for (x0, y0, x1, y1, f_on, b_on, _net, _r, _p) in self.boxes:
                i0, j0 = cell(x0 - r * STEP, y0 - r * STEP)
                i1, j1 = cell(x1 + r * STEP, y1 + r * STEP)
                if f_on:
                    self._fill(0, i0, j0, i1, j1)
                if b_on:
                    self._fill(1, i0, j0, i1, j1)
        vf = bytearray(W * H)
        vb = bytearray(W * H)
        rv = via_radius()
        for first in (vf, vb):
            for j in range(0, max(1, M0)):
                for i in range(0, W):
                    first[j * W + i] = 1
            for j in range(M1 + 1, H):
                for i in range(0, W):
                    first[j * W + i] = 1
            for i in range(0, max(1, N0)):
                for j in range(0, H):
                    first[j * W + i] = 1
            for i in range(N1 + 1, W):
                for j in range(0, H):
                    first[j * W + i] = 1
        for (x0, y0, x1, y1, f_on, b_on, _net, _r, _p) in self.boxes:
            i0, j0 = cell(x0 - rv * STEP, y0 - rv * STEP)
            i1, j1 = cell(x1 + rv * STEP, y1 + rv * STEP)
            if f_on:
                self._fill(0, i0, j0, i1, j1, g=vf)
            if b_on:
                self._fill(1, i0, j0, i1, j1, g=vb)
        self.vm_all = (vf, vb)
        self.live_r = None

    def use_mask(self, r):
        self.live_r = r

    def prep_route(self, nets, r):
        """Foreign mask = dilated pads MINUS own pads dilation; own free+reuse on."""
        self.live_r = r
        self.own_reuse.clear()
        mf = bytearray(self.masks[r][0])
        mb = bytearray(self.masks[r][1])
        vf = bytearray(self.vm_all[0])
        vb = bytearray(self.vm_all[1])
        for (x0, y0, x1, y1, f_on, b_on, net, _r, _p) in self.boxes:
            if net not in nets:
                continue
            i0, j0 = cell(x0 - r * STEP, y0 - r * STEP)
            i1, j1 = cell(x1 + r * STEP, y1 + r * STEP)
            i0 = max(0, i0)
            i1 = min(W - 1, i1)
            j0 = max(0, j0)
            j1 = min(H - 1, j1)
            for l, g in ((0, mf), (1, mb)):
                if (l == 0 and not f_on) or (l == 1 and not b_on):
                    continue
                for j in range(j0, j1 + 1):
                    base = j * W
                    for i in range(i0, i1 + 1):
                        g[base + i] = 0
            rv = via_radius()
            i2, j2 = cell(x0 - rv * STEP, y0 - rv * STEP)
            i3, j3 = cell(x1 + rv * STEP, y1 + rv * STEP)
            i2 = max(0, i2)
            i3 = min(W - 1, i3)
            j2 = max(0, j2)
            j3 = min(H - 1, j3)
            for l, g in ((0, vf), (1, vb)):
                if (l == 0 and not f_on) or (l == 1 and not b_on):
                    continue
                for j in range(j2, j3 + 1):
                    base = j * W
                    for i in range(i2, i3 + 1):
                        g[base + i] = 0
        self.mm = (mf, mb)
        self.vm = (vf, vb)

    def mark_track(self, path, w):
        r = pad_radius(w)
        for (i, j, l) in path:
            self.own_reuse.add((i, j, l))
            self._tdisk(l, i, j, r)

    def _tdisk(self, l, i, j, r):
        g = self.tgrid(l)
        for dj in range(-r, r + 1):
            jj = j + dj
            if jj < 0 or jj >= H:
                continue
            base = jj * W
            for di in range(-r, r + 1):
                ii = i + di
                if ii < 0 or ii >= W:
                    continue
                if di * di + dj * dj <= r * r:
                    g[base + ii] = 1

    def pad_cells(self, box):
        x0, y0, x1, y1, f_on, b_on = box[:6]
        i0, j0 = cell(x0, y0)
        i1, j1 = cell(x1, y1)
        out = set()
        for l in (0, 1):
            if (l == 0 and not f_on) or (l == 1 and not b_on):
                continue
            for j in range(j0, j1 + 1):
                for i in range(i0, i1 + 1):
                    out.add((i, j, l))
        return out

    def astar(self, sources, targets, max_nodes=1400000):
        """A* multi-source; returns path cells (i, j, layer) end->sources."""
        openq = []
        g = {}
        for s in sources:
            if self.is_free(s[2], s[0], s[1]):
                g[s] = 0
                openq.append((0.0, 0, s))
        tx = sorted(t[0] for t in targets)
        ty = sorted(t[1] for t in targets)
        ti = tx[len(tx) // 2]
        tj = ty[len(ty) // 2]
        parent = {}
        closed = set()
        order = 0
        while openq:
            f, _, node = heapq.heappop(openq)
            if node in closed:
                continue
            closed.add(node)
            if node in targets:
                path = [node]
                while node in parent:
                    node = parent[node]
                    path.append(node)
                return path
            i, j, l = node
            gn = g[node]
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ni, nj = i + di, j + dj
                if not (0 <= ni < W and 0 <= nj < H):
                    continue
                if not self.is_free(l, ni, nj):
                    continue
                n = (ni, nj, l)
                ng = gn + 1.0
                if ng < g.get(n, 1e18):
                    g[n] = ng
                    parent[n] = node
                    h = abs(ni - ti) + abs(nj - tj)
                    heapq.heappush(openq, (ng + h, -gn, n))
            nl = 1 - l
            if self.via_free(nl, i, j):
                n = (i, j, nl)
                ng = gn + VIA_COST
                if ng < g.get(n, 1e18):
                    g[n] = ng
                    parent[n] = node
                    h = abs(i - ti) + abs(j - tj)
                    heapq.heappush(openq, (ng + h, -gn, n))
            if len(closed) > max_nodes:
                return None
        return None


def split_path(path):
    """Group path (cells in source->target order) into segment runs + vias."""
    rev = list(reversed(path))
    segs = []   # (i0, j0, l, i1, j1)
    vias = []
    run = [rev[0]]
    for cur, nxt in zip(rev, rev[1:]):
        if cur[2] == nxt[2]:
            run.append(nxt)
        else:
            if len(run) > 1:
                segs.append((run[0][0], run[0][1], run[0][2],
                             run[-1][0], run[-1][1]))
            else:
                vias.append((run[0][0], run[0][1]))
            vias.append((nxt[0], nxt[1]) if cur[2] != nxt[2] else None)
            run = [nxt]
    if len(run) > 1:
        segs.append((run[0][0], run[0][1], run[0][2], run[-1][0], run[-1][1]))
    else:
        vias.append((run[0][0], run[0][1]))
    return segs, [v for v in vias if v is not None]


def route_one(router, nm, pads, trk, vi):
    _, w, _ = net_style(nm)
    router.prep_route({nm}, pad_radius(w))
    ok = True
    all_pads = set()
    for pp in pads:
        all_pads.update(router.pad_cells(pp))
    for p in pads[1:]:
        targets = router.pad_cells(p)
        sources = set(all_pads) - targets
        path = router.astar(sources, targets)
        if path is None:
            ok = False
            break
        router.mark_track(path, w)
        cells = [(i, j, l) for (i, j, l) in path]
        segs, vias = split_path(cells)
        for (i0, j0, l, i1, j1) in segs:
            trk.append((nm, w, l, i0, j0, i1, j1))
        for (i, j) in vias:
            vi.append((nm, i, j))
    return ok


def main():
    merged, order = P.merge_entries()
    positions, _ = P.place(merged, order)
    boxes = pad_boxes(merged, order, positions)
    router = Router(boxes)

    by_net = {}
    for b in boxes:
        if b[6] is None:
            continue
        by_net.setdefault(b[6], []).append(b)

    def route_key(nm):
        cls, w, cl = net_style(nm)
        prio = {"OUT": 0, "HV": 1, "PWR": 2, "SIG": 3}[cls]
        return (prio, -len(by_net[nm]))
    ordered = sorted(by_net, key=route_key)

    node = P.build_board(merged, order, positions)
    trk = []
    vi = []
    done = set()
    pending = set(ordered)
    while pending:
        progressed = False
        for nm in (n for n in ordered if n in pending):
            if len(by_net[nm]) < 2:
                pending.discard(nm)
                continue
            if route_one(router, nm, by_net[nm], trk, vi):
                done.add(nm)
                pending.discard(nm)
                progressed = True
        if not progressed:
            break
    unrouted = sorted(n for n in ordered if len(by_net[n]) >= 2 and n not in done)

    tstamp = 0
    def uid(k):
        return '"%s"' % P.uid("rt:%s" % k)

    # append tracks/vias after footprints (before trailing embedded_fonts)
    if node and node[-1] == ["embedded_fonts", "no"]:
        head = node[:-1]
        tail = [node[-1]]
    else:
        head, tail = node, []
    for (nm, w, l, i0, j0, i1, j1) in trk:
        head.append(["segment",
                     ["start", P.a(i0 * STEP), P.a(j0 * STEP)],
                     ["end", P.a(i1 * STEP), P.a(j1 * STEP)],
                     ["width", P.a(w)],
                     ["layer", Raw('"F.Cu"' if l == 0 else '"B.Cu"')],
                     ["net", str(P.NETCODE[nm])],
                     ["uuid", Raw(uid(tstamp))]])
        tstamp += 1
    for (nm, i, j) in vi:
        head.append(["via",
                     ["at", P.a(i * STEP), P.a(j * STEP)],
                     ["size", P.a(VIA_SIZE)],
                     ["drill", P.a(VIA_DRILL)],
                     ["layers", Raw('"F.Cu"'), Raw('"B.Cu"')],
                     ["net", str(P.NETCODE[nm])],
                     ["uuid", Raw(uid(tstamp))]])
        tstamp += 1
    node = head + tail

    out = os.path.join(P.KICAD, P.D.PROJECT + ".kicad_pcb")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(dumps(node) + "\n")
    print(f"wrote {out}")
    print(f"segments: {len(trk)}, vias: {len(vi)}")
    routed = len(done)
    total = sum(1 for n in ordered if len(by_net[n]) >= 2)
    print(f"nets routed: {routed}/{total}")
    for nm in unrouted:
        print(f"  UNROUTED {nm} ({len(by_net[nm])} pads)")


if __name__ == "__main__":
    main()