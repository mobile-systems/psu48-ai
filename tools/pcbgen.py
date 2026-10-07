"""Generate kicad/psu48.kicad_pcb (KiCad 10 format) from sch_data.

Stage 4: board outline 280x90 mm, footprints embedded from library files,
net assignment matching the schematic netlist (verify.py split_local logic),
and a first placement pass (explicit structural anchors + sweep-fill packing).
"""

import math
import os
import sys
import uuid

from sexp import parse, find, findall, unq, dumps, Raw, num as knum
import sch_data as D

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KICAD = os.path.join(ROOT_DIR, "kicad")
STOCK_FP = "C:/Program Files/KiCad/10.0/share/kicad/footprints"

NS = uuid.UUID("8f3a1c07-4b2d-4f6a-9c1e-2a5b7d90e614")

BOARD_W, BOARD_H = 280.0, 90.0
MARGIN = 0.2      # min gap between footprint bboxes for packing
PACK_STEP = 0.5


def uid(key):
    return str(uuid.uuid5(NS, key))


def a(x):
    return Raw(knum(x))


def merge_entries():
    """Merge multi-unit entries by reference; return ordered {ref: entry}."""
    merged = {}
    order = []
    for sh in D.SHEETS:
        for e in sh["entries"]:
            ref = e["ref"]
            if ref is None:
                continue
            if ref not in merged:
                merged[ref] = dict(nets=dict(e["nets"]), fp=e["fp"],
                                   lib=e["lib"], val=e["val"], rot=e.get("rot", 0))
                order.append(ref)
            else:
                merged[ref]["nets"].update(e["nets"])
    return merged, order


def net_sheets_map():
    nsh = {}
    for sh in D.SHEETS:
        sid = sh["id"]
        for e in sh["entries"]:
            for net in e["nets"].values():
                if net is not None:
                    nsh.setdefault(net, set()).add(sid)
    return nsh


def global_net_name(net, nsh):
    if net in D.POWER_TERMS or len(nsh.get(net, ())) > 1:
        return net
    for sh in D.SHEETS:
        if net in nsh.get(net, set()) or any(
                net in [v for v in e["nets"].values() if v is not None]
                for e in sh["entries"]):
            return f"{sh['id']}/{net}"
    return net


def fn_of_ref(ref):
    for sh in D.SHEETS:
        for e in sh["entries"]:
            if e["ref"] == ref:
                return sh["id"]
    return "?"


def fp_path(fplib):
    lib, name = fplib.split(":", 1)
    base = os.path.join(KICAD, "psu48.pretty") if lib == "psu48" else \
        os.path.join(STOCK_FP, lib + ".pretty")
    return os.path.join(base, name + ".kicad_mod")


def load_fp(fplib):
    with open(fp_path(fplib), encoding="utf-8") as f:
        return parse(f.read())


def _pt(x, y):
    return [float(x), float(y)]


def fp_bbox(node):
    """Local bounding box (lo_x, lo_y, hi_x, hi_y) of the whole footprint:
    pads + body graphics on the courtyard/silk/fab layers."""
    xs, ys = [], []
    for pad in findall(node, "pad"):
        s = find(pad, "size")
        if s is None:
            continue
        w, h = float(unq(s[1])), float(unq(s[2]))
        at = find(pad, "at")
        px, py = float(unq(at[1])), float(unq(at[2]))
        prot = float(unq(at[3])) if len(at) > 3 else 0.0
        r = math.radians(prot)
        for dx in (-w / 2, w / 2):
            for dy in (-h / 2, h / 2):
                x = px + dx * math.cos(r) - dy * math.sin(r)
                y = py + dx * math.sin(r) + dy * math.cos(r)
                xs.append(x)
                ys.append(y)
    body_layers = {"F.CrtYd", "B.CrtYd", "F.SilkS", "B.SilkS", "F.Fab", "B.Fab"}
    for item in ("fp_rect", "fp_line", "fp_arc", "fp_circle", "fp_poly",
                 "fp_text"):
        for el in findall(node, item):
            lay = find(el, "layer")
            if lay is not None and unq(lay[1]) not in body_layers:
                continue
            if item == "fp_rect":
                st, en = find(el, "start"), find(el, "end")
                xs += [float(unq(st[1])), float(unq(en[1]))]
                ys += [float(unq(st[2])), float(unq(en[2]))]
            elif item in ("fp_line", "fp_arc"):
                st = find(el, "start")
                en = find(el, "end")
                xs += [float(unq(st[1])), float(unq(en[1]))]
                ys += [float(unq(st[2])), float(unq(en[2]))]
                if item == "fp_arc":
                    md = find(el, "mid")
                    xs.append(float(unq(md[1])))
                    ys.append(float(unq(md[2])))
            elif item == "fp_circle":
                c, e = find(el, "center"), find(el, "end")
                cx, cy = float(unq(c[1])), float(unq(c[2]))
                ex, ey = float(unq(e[1])), float(unq(e[2]))
                r = math.hypot(ex - cx, ey - cy)
                xs += [cx - r, cx + r]
                ys += [cy - r, cy + r]
            elif item == "fp_poly":
                for pt in findall(el, "xy"):
                    xs.append(float(unq(pt[1])))
                    ys.append(float(unq(pt[2])))
            elif item == "fp_text":
                at = find(el, "at")
                tx, ty = float(unq(at[1])), float(unq(at[2]))
                tr = math.radians(float(unq(at[3])) if len(at) > 3 else 0.0)
                eff = find(el, "effects")
                fw = fh = 1.0
                if eff is not None:
                    f = find(eff, "font")
                    if f is not None:
                        s = find(f, "size")
                        if s is not None:
                            fw, fh = float(unq(s[1])), float(unq(s[2]))
                half = max(fw, fh) / 2 + 0.15
                cos, sin = math.cos(tr), math.sin(tr)
                for dx0 in (-half, half):
                    for dy0 in (-half, half):
                        xs.append(tx + dx0 * cos - dy0 * sin)
                        ys.append(ty + dx0 * sin + dy0 * cos)
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


def abs_rect(cx, cy, rot, lo, hi):
    """Absolute bounding rectangle of a footprint placed at (cx, cy, rot),
    honouring the offset between its origin and local bbox. rot follows the
    KiCad convention (positive = clockwise)."""
    r = math.radians(-rot)
    cos, sin = math.cos(r), math.sin(r)
    corners = []
    for dx in (lo[0], hi[0]):
        for dy in (lo[1], hi[1]):
            corners.append((cx + dx * cos - dy * sin,
                            cy + dx * sin + dy * cos))
    xs = [p[0] for p in corners]
    ys = [p[1] for p in corners]
    return (min(xs), min(ys), max(xs), max(ys))


def inflate(r, m):
    return (r[0] - m, r[1] - m, r[2] + m, r[3] + m)


def overlap(r1, r2):
    return not (r1[2] <= r2[0] or r2[2] <= r1[0]
                or r1[3] <= r2[1] or r2[3] <= r1[1])


# --- placement ------------------------------------------------------------

# Soft hints (x, y, rot) for structural / power parts. The packer tries these
# first, then falls back to sweeping the part's region to avoid collisions.
PREFER = {
    # input
    "J101": (12, 78, 0), "F101": (24, 78, 0), "CX101": (30, 60, 0),
    "RV101": (12, 30, 0), "RT101": (20, 14, 0), "LF101": (36, 14, 0),
    "CX102": (14, 50, 0), "CY101": (14, 38, 0), "CY102": (14, 44, 0),
    "K101": (28, 34, 0), "BD101": (42, 76, 0),
    "Q101": (12, 70, 0),
    # pfc
    "U201": (60, 16, 0), "L201": (84, 56, 0), "Q201": (58, 78, 0),
    "D201": (88, 78, 0), "R201": (118, 78, 0),
    "C201": (136, 20, 0), "C202": (136, 58, 0), "C203": (156, 38, 0),
    # llc primary + aux
    "Q301": (172, 74, 0), "Q302": (192, 74, 0), "L301": (156, 24, 0),
    "T301": (204, 56, 0), "U301": (206, 24, 0),
    "C310": (156, 46, 0), "C311": (172, 46, 0), "C312": (188, 46, 0),
    "U401": (226, 24, 0), "T401": (226, 40, 0), "U404": (238, 74, 0),
    # sr + output
    "Q310": (232, 78, 0), "Q311": (242, 78, 0),
    "Q312": (232, 66, 0), "Q313": (242, 66, 0),
    "U302": (256, 72, 0), "J301": (272, 40, 0),
    "C320": (252, 20, 0), "C321": (252, 38, 0),
    "C322": (268, 20, 0), "C323": (268, 38, 0),
    "R326": (252, 56, 0), "R327": (262, 56, 0),
    # control (sheet05)
    "U501": (232, 14, 0), "U502": (232, 30, 0), "J501": (270, 58, 0),
    "LED501": (258, 6, 0),
}

# Global work area: all parts pack anywhere on the board.
REGION_BOARD = (2.0, 2.0, 278.0, 88.0)


def region_of(ref):
    return REGION_BOARD


# Functional cluster anchors. Each part first tries a small spiral search
# around its anchor (its own PREFER, else its group default), so power stages
# stay coherent; overflow falls back to a global sweep.
GROUP_ANCHOR = {
    "01_ac_input": (32.0, 45.0),
    "02_pfc": (100.0, 45.0),
    "03_llc": (170.0, 45.0),
    "04_aux": (198.0, 45.0),
    "05_ctrl": (250.0, 45.0),
    "SR": (250.0, 60.0),
    "OUT": (250.0, 30.0),
}


def anchor_of(ref):
    p = PREFER.get(ref)
    if p:
        return (p[0], p[1])
    if ref in {"Q310", "Q311", "Q312", "Q313", "U302", "C320", "C321", "C322",
               "C323", "R326", "R327", "J301", "R320", "C330", "R321", "R322",
               "R323", "U306"}:
        return GROUP_ANCHOR["SR"]
    if ref in {"C324", "C325", "C326", "C327", "C316", "R316", "R317", "C313",
               "R324", "R325", "C331", "C332", "U304", "U305"}:
        return GROUP_ANCHOR["OUT"]
    for sh in D.SHEETS:
        if any(e["ref"] == ref for e in sh["entries"]):
            return GROUP_ANCHOR[sh["id"]]
    return GROUP_ANCHOR["01_ac_input"]


HOLE_POS = [(6, 6), (274, 6), (6, 84), (274, 84)]


def place(merged, order):
    positions = {}
    rects = {}
    hole_rects = {}
    for i, e in enumerate(D.ROOT_HOLES):
        lo, hi = fp_bbox(parse(open(fp_path(e["fp"]), encoding="utf-8").read()))[:2], \
            fp_bbox(parse(open(fp_path(e["fp"]), encoding="utf-8").read()))[2:]
        hole_rects[e["ref"]] = abs_rect(HOLE_POS[i][0], HOLE_POS[i][1], 0, lo, hi)
    rects = dict(hole_rects)
    box = {}
    for ref in order:
        m = merged[ref]
        box[ref] = fp_bbox(parse(open(fp_path(m["fp"]), encoding="utf-8").read()))
    # largest first limits packing fragmentation
    for ref in sorted(order, key=lambda r: -(box[r][2] - box[r][0])
                      * (box[r][3] - box[r][1])):
        m = merged[ref]
        lo, hi = box[ref][:2], box[ref][2:]
        pref = PREFER.get(ref)
        w, h = hi[0] - lo[0], hi[1] - lo[1]
        cx, cy, rot = find_spot(w, h, ref, pref, rects, lo, hi)
        rects[ref] = abs_rect(cx, cy, rot, lo, hi)
        positions[ref] = (cx, cy, rot)
    return positions, rects


def find_spot(w, h, ref, pref, rects, lo, hi):
    region = region_of(ref)
    rot = pref[2] if pref else 0
    placed_rects = [inflate(r, MARGIN) for r in rects.values()]

    def free(cx, cy):
        r = inflate(abs_rect(cx, cy, rot, lo, hi), MARGIN)
        return (r[0] >= region[0] and r[1] >= region[1]
                and r[2] <= region[2] and r[3] <= region[3]
                and all(not overlap(r, pr) for pr in placed_rects))

    ax, ay = anchor_of(ref)
    if pref and free(pref[0], pref[1]):
        return pref
    # spiral search around the cluster anchor first
    step = PACK_STEP
    for radius in range(1, int(16 / step) + 1):
        ring = []
        for dx in range(-radius, radius + 1):
            ring.append((ax + dx * step, ay + radius * step))
            ring.append((ax + dx * step, ay - radius * step))
        for dy in range(-radius, radius + 1):
            ring.append((ax + radius * step, ay + dy * step))
            ring.append((ax - radius * step, ay + dy * step))
        for cx, cy in ring:
            if free(cx, cy):
                return (cx, cy, rot)
    # global fallback sweep
    x0, y0, x1, y1 = region
    if rot % 180 == 0:
        rw, rh = w + 2 * MARGIN, h + 2 * MARGIN
    else:
        rw, rh = h + 2 * MARGIN, w + 2 * MARGIN
    x, y = x0, y0
    while True:
        cx, cy = x + rw / 2, y + rh / 2
        if x + rw <= x1 and y + rh <= y1 and free(cx, cy):
            return (cx, cy, rot)
        x += PACK_STEP
        if x + rw > x1:
            x = x0
            y += PACK_STEP
            if y + rh > y1:
                raise SystemExit(
                    f"no free spot for {ref} {w:.1f}x{h:.1f} in region {region}")


# --- board assembly -------------------------------------------------------

def net_table(nets):
    return [["net", "0", Raw('""')]] + [
        ["net", str(i), '"' + name + '"']
        for i, name in enumerate(sorted(nets), 1)]


def clone_uuids(node, key):
    """Regenerate all uuid leaves inside node (deterministic per instance)."""
    if isinstance(node, list):
        if node and str(node[0]) == "uuid" and len(node) > 1:
            node[1] = Raw('"' + uid(key + ":" + str(node[1])) + '"')
        for c in node:
            clone_uuids(c, key)
    return node


def set_property(node, name, text, key):
    for p in findall(node, "property"):
        if len(p) > 1 and unq(p[1]) == name:
            p[2] = Raw('"' + text + '"')
            # unhide Reference / Value text
            if name in ("Reference", "Value"):
                eff = find(p, "effects")
                if eff is not None:
                    h = find(eff, "hide")
                    if h is not None:
                        eff.remove(h)
    return node


def fp_node(fplib, ref, value, pos, rot, padnets, key):
    node = load_fp(fplib)
    lib, name = fplib.split(":", 1)
    # rebuild head: (footprint "LIB:NAME") then only list children
    head = ["footprint", Raw('"' + fplib + '"')]
    keep = []
    for c in node[1:]:
        if not isinstance(c, list):
            continue
        if isinstance(c, list) and c and str(c[0]) in ("version", "generator"):
            continue
        keep.append(c)
    node = head + keep
    # layer + uuid near the top, then (at ...), then the rest
    inert = []
    rest = []
    for c in keep:
        if isinstance(c, list) and c and str(c[0]) in ("uuid", "layer"):
            inert.append(c)
        else:
            rest.append(c)
    node = head + inert + [["at", a(pos[0]), a(pos[1]), a(rot)]] + rest
    set_property(node, "Reference", ref, key)
    set_property(node, "Value", value, key)
    for pad in findall(node, "pad"):
        pnum = unq(pad[1])
        net = padnets.get(pnum)
        keep = [c for c in pad if not (isinstance(c, list) and c and str(c[0]) == "net")]
        if net:
            keep.append(["net", str(NETCODE[net]), Raw('"' + net + '"')])
        else:
            keep.append(["net", "0", Raw('""')])
        pad[:] = keep
    clone_uuids(node, key)
    return node


def build_board(merged, order, positions):
    nsh = net_sheets_map()

    def net_name(net):
        if net in D.POWER_TERMS or len(nsh.get(net, ())) > 1:
            return net
        return f"{sorted(nsh[net])[0]}/{net}"

    nets = set()
    for ref in order:
        for net in merged[ref]["nets"].values():
            if net is not None:
                nets.add(net_name(net))
    global NETCODE
    NETCODE = {n: i for i, n in enumerate(sorted(nets), 1)}
    node = ["kicad_pcb",
            ["version", Raw("20260206")],
            ["generator", Raw('"PSU48 pcbgen"')],
            ["generator_version", Raw('"1.0"')],
            ["general", ["thickness", a(1.6)], ["legacy_teardrops", "no"]],
            ["paper", Raw('"A3"')],
            ["title_block",
             ["title", Raw('"PSU48-800 220VAC->_48VDC_800W_PFC+LLC_PCB"')],
             ["date", Raw('"' + D.DATE + '"')],
             ["rev", Raw('"' + D.REV + '"')],
             ["company", Raw('"PSU48"')]],
            LAYERS_NODE,
            SETUP_NODE]
    node.extend(net_table(nets))

    for ref in order:
        m = merged[ref]
        cx, cy, rot = positions[ref]
        padnets = {pn: net_name(n) for pn, n in m["nets"].items()
                   if n is not None}
        node.append(fp_node(m["fp"], ref, m["val"], (cx, cy), rot,
                            padnets, "pcb:" + ref))
    for i, e in enumerate(D.ROOT_HOLES):
        hx, hy = HOLE_POS[i]
        node.append(fp_node(e["fp"], e["ref"], e["val"], (hx, hy), 0,
                            {}, "pcb:" + e["ref"]))

    edge = [(0, 0), (BOARD_W, 0), (BOARD_W, BOARD_H), (0, BOARD_H), (0, 0)]
    for i in range(4):
        p0, p1 = edge[i], edge[i + 1]
        node.append(["gr_line",
                     ["start", a(p0[0]), a(p0[1])],
                     ["end", a(p1[0]), a(p1[1])],
                     ["stroke", ["width", a(0.1)], ["type", "default"]],
                     ["layer", Raw('"Edge.Cuts"')],
                     ["uuid", Raw('"' + uid("edge:" + str(i)) + '"')]])
    node.append(["embedded_fonts", "no"])
    return node


LAYERS_NODE = ["layers",
               ["0", Raw('"F.Cu"'), "signal"],
               ["2", Raw('"B.Cu"'), "signal"],
               ["9", Raw('"F.Adhes"'), "user", Raw('"F.Adhesive"')],
               ["11", Raw('"B.Adhes"'), "user", Raw('"B.Adhesive"')],
               ["13", Raw('"F.Paste"'), "user"],
               ["15", Raw('"B.Paste"'), "user"],
               ["5", Raw('"F.SilkS"'), "user", Raw('"F.Silkscreen"')],
               ["7", Raw('"B.SilkS"'), "user", Raw('"B.Silkscreen"')],
               ["1", Raw('"F.Mask"'), "user"],
               ["3", Raw('"B.Mask"'), "user"],
               ["17", Raw('"Dwgs.User"'), "user", Raw('"User.Drawings"')],
               ["19", Raw('"Cmts.User"'), "user", Raw('"User.Comments"')],
               ["21", Raw('"Eco1.User"'), "user", Raw('"User.Eco1"')],
               ["23", Raw('"Eco2.User"'), "user", Raw('"User.Eco2"')],
               ["25", Raw('"Edge.Cuts"'), "user"],
               ["27", Raw('"Margin"'), "user"],
               ["31", Raw('"F.CrtYd"'), "user", Raw('"F.Courtyard"')],
               ["29", Raw('"B.CrtYd"'), "user", Raw('"B.Courtyard"')],
               ["35", Raw('"F.Fab"'), "user"],
               ["33", Raw('"B.Fab"'), "user"]]

SETUP_NODE = ["setup",
              ["pad_to_mask_clearance", a(0)],
              ["allow_soldermask_bridges_in_footprints", "no"],
              ["pcbplotparams",
               ["layerselection", Raw("0x00000000_00000000_55555555_5755f5ff")],
               ["plot_on_all_layers_selection", Raw("0x00000000_00000000_00000000_00000000")],
               ["disableapertmacros", "no"],
               ["usegerberextensions", "no"],
               ["usegerberattributes", "yes"],
               ["usegerberadvancedattributes", "yes"],
               ["creategerberjobfile", "yes"],
               ["svgprecision", "4"],
               ["plotframeref", "no"],
               ["mode", "1"],
               ["useauxorigin", "no"],
               ["pdf_front_fp_property_popups", "yes"],
               ["pdf_back_fp_property_popups", "yes"],
               ["pdf_metadata", "yes"],
               ["pdf_single_document", "no"],
               ["dxfpolygonmode", "yes"],
               ["dxfimperialunits", "yes"],
               ["dxfusepcbnewfont", "yes"],
               ["psnegative", "no"],
               ["psa4output", "no"],
               ["plot_black_and_white", "yes"],
               ["sketchpadsonfab", "no"],
               ["plotpadnumbers", "no"],
               ["hidednponfab", "no"],
               ["sketchdnponfab", "yes"],
               ["crossoutdnponfab", "yes"],
               ["subtractmaskfromsilk", "no"],
               ["outputformat", "1"],
               ["mirror", "no"],
               ["drillshape", "1"],
               ["scaleselection", "1"],
               ["outputdirectory", Raw('""')]]]


def main():
    merged, order = merge_entries()
    positions, rects = place(merged, order)
    node = build_board(merged, order, positions)
    out = os.path.join(KICAD, D.PROJECT + ".kicad_pcb")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(dumps(node) + "\n")
    print(f"wrote {out} ({len(order)} footprints + {len(D.ROOT_HOLES)} holes)")
    for ref, r in rects.items():
        if r[0] < 2 or r[1] < 2 or r[2] > BOARD_W - 2 or r[3] > BOARD_H - 2:
            print(f"WARN {ref} near/outside board: {r}")


if __name__ == "__main__":
    main()