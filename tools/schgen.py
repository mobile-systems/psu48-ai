import json
import math
import os
import uuid

from sexp import dumps, Raw, Q, num as knum, find, findall, unq
from kilib import (pins_of, bbox_of, units_of, xform, pin_abs, embed,
                   load_symbol, footprint_exists, lib_id_split)
import sch_data as D

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT_DIR, "kicad")

NS = uuid.UUID("6f2b9d43-71c0-4e5a-9b8f-0d4c2a1e5f70")
GRID = 1.27
PAPER_LIMITS = {"A3": (400.0, 265.0), "A2": (570.0, 385.0)}
LIMIT = (400.0, 265.0)
_glob = None


class Overflow(Exception):
    pass


def uid(key):
    return str(uuid.uuid5(NS, key))


def a(x):
    return Raw(knum(x))


def g(v):
    return math.ceil(v / GRID - 1e-9) * GRID


def set_glob(fn):
    global _glob
    _glob = fn


def is_glob(net):
    return _glob(net)


def lbl_w(net):
    return (6.35 if is_glob(net) else 5.08) + 1.27 * len(net)


def prop_by_name(lib_id):
    lib, name = lib_id_split(lib_id)
    sym, _ = load_symbol(lib, name)
    return {unq(p[1]): p for p in findall(sym, "property")}


def prop_hidden(p):
    eff = find(p, "effects")
    if eff is None:
        return False
    h = find(eff, "hide")
    return h is not None and unq(h[1]) in ("yes", "true")


def validate(net_sheets):
    errs = []
    refs = {}
    ref_sheets = {}
    for sh in D.SHEETS:
        for e in sh["entries"]:
            pnums = {p["num"] for p in pins_of(e["lib"], e["unit"])}
            nets = set(e["nets"])
            if pnums != nets:
                errs.append(f"{sh['id']} {e['ref']}: pins {sorted(pnums)} != nets {sorted(nets)}")
            if e["fp"] and not footprint_exists(e["fp"]):
                errs.append(f"{sh['id']} {e['ref']}: footprint {e['fp']} not found")
            if e["ref"]:
                key = (e["ref"], e["unit"])
                if key in refs:
                    errs.append(f"duplicate ref/unit {key}")
                refs[key] = sh["id"]
                ref_sheets.setdefault(e["ref"], set()).add(sh["id"])
            for net in e["nets"].values():
                if net is not None:
                    net_sheets.setdefault(net, set()).add(sh["id"])
    for e in D.ROOT_HOLES:
        if e["fp"] and not footprint_exists(e["fp"]):
            errs.append(f"root {e['ref']}: footprint {e['fp']} not found")
    for r, shs in ref_sheets.items():
        if len(shs) > 1:
            errs.append(f"ref {r} on multiple sheets: {sorted(shs)}")
    if errs:
        raise SystemExit("VALIDATION FAILED:\n" + "\n".join(errs))


def entry_metrics(e, net_sheets):
    pins = pins_of(e["lib"], e["unit"])
    b = bbox_of(e["lib"], e["unit"])
    xs, ys = [], []
    for cx in (b[0], b[2]):
        for cy in (b[1], b[3]):
            px, py = xform(cx, cy, (0, 0), e["rot"])
            xs.append(px)
            ys.append(py)
    allow = {"L": 0.0, "R": 0.0, "U": 0.0, "D": 0.0}
    has_vert = False
    for p in pins:
        net = e["nets"].get(p["num"])
        if net is None:
            continue
        conn, (dx, dy) = pin_abs(p, (0, 0), e["rot"])
        d = (int(round(dx)), int(round(dy)))
        term = D.POWER_TERMS.get(net)
        if d == (1, 0):
            allow["R"] = max(allow["R"], D.STUB + lbl_w(net))
        elif d == (-1, 0):
            allow["L"] = max(allow["L"], D.STUB + lbl_w(net))
        elif d in ((0, -1), (0, 1)):
            has_vert = True
            side = "U" if d[1] < 0 else "D"
            orient = "up" if d[1] < 0 else "down"
            if term and term[1] == orient:
                allow[side] = max(allow[side], D.STUB + 8.89)
                allow["L"] = max(allow["L"], 2.54)
                allow["R"] = max(allow["R"], 2.54)
            else:
                allow[side] = max(allow[side], D.BEND + 3.81)
                hside = "R" if conn[0] >= 0 else "L"
                allow[hside] = max(allow[hside], D.STUB + lbl_w(net))
        else:
            raise SystemExit(f"diagonal pin direction in {e['ref']} pin {p['num']}")
    return dict(
        e=e, b=b, has_vert=has_vert,
        wl=g(max(0.0, -min(xs)) + allow["L"]),
        wr=g(max(0.0, max(xs)) + allow["R"]),
        wu=g(max(0.0, -min(ys)) + allow["U"]),
        wd=g(max(0.0, max(ys)) + allow["D"]),
    )


def layout_sheet(sheet, net_sheets):
    ms = [entry_metrics(e, net_sheets) for e in sheet["entries"]]
    lx, ly = LIMIT
    rows, cur = [], []

    def row_w(lst):
        return sum(x["wl"] + x["wr"] + D.GAP for x in lst)

    for m in ms:
        if cur and D.X0 + row_w(cur) + m["wl"] + m["wr"] + D.GAP > lx:
            rows.append(cur)
            cur = [m]
        else:
            cur.append(m)
    if cur:
        rows.append(cur)

    placed = []
    col_x, y, col_right = D.X0, D.Y0, D.X0
    for row in rows:
        row_h = max(m["wu"] + m["wd"] for m in row)
        if y + row_h > ly:
            col_x = g(col_right + D.COL_GAP)
            y = D.Y0
        rw = row_w(row) - D.GAP
        if col_x + rw > lx:
            raise Overflow(sheet["id"])
        yc = g(y + row_h / 2)
        x = col_x
        for m in row:
            px = g(x + m["wl"])
            placed.append((m, (px, yc)))
            x = px + m["wr"] + D.GAP
        col_right = max(col_right, x - D.GAP)
        y = g(y + row_h + D.ROW_GAP)
    return placed


def effects(size=1.27, justify=None, hide=False):
    eff = ["effects", ["font", ["size", a(size), a(size)]]]
    if justify:
        eff.append(["justify", Raw(justify)])
    if hide:
        eff.append(["hide", "yes"])
    return eff


def label_node(net, pos, angle, key):
    if is_glob(net):
        just = "left" if angle == 0 else "right"
        return ["global_label", Raw(Q(net)),
                ["shape", "bidirectional"],
                ["at", a(pos[0]), a(pos[1]), a(angle)],
                ["fields_autoplaced", "yes"],
                effects(justify=just),
                ["uuid", Raw(Q(uid(key)))]]
    just = "left bottom" if angle == 0 else "right bottom"
    return ["label", Raw(Q(net)),
            ["at", a(pos[0]), a(pos[1]), a(angle)],
            effects(justify=just),
            ["uuid", Raw(Q(uid(key)))]]


def wire_node(pts, key):
    pts_node = ["pts"]
    for p in pts:
        pts_node.append(["xy", a(p[0]), a(p[1])])
    return ["wire", pts_node,
            ["stroke", ["width", a(0)], ["type", "default"]],
            ["uuid", Raw(Q(uid(key)))]]


def pin_numbers_all(lib_id):
    nums = []
    for u in units_of(lib_id):
        if u == 0:
            continue
        for p in pins_of(lib_id, u):
            if p["num"] not in nums:
                nums.append(p["num"])
    if not nums:
        for p in pins_of(lib_id, 1):
            if p["num"] not in nums:
                nums.append(p["num"])
    return nums


def symbol_node(lib, val, fp, rot, unit, pos, path, ref, ref_pos, val_pos,
                val_hide, key, ref_hide=False, desc=""):
    node = ["symbol",
            ["lib_id", Raw(Q(lib))],
            ["at", a(pos[0]), a(pos[1]), a(rot)],
            ["unit", str(unit)],
            ["exclude_from_sim", "no"],
            ["in_bom", "yes"],
            ["on_board", "yes"],
            ["dnp", "no"],
            ["uuid", Raw(Q(uid(key)))]]
    node.append(["property", Raw(Q("Reference")), Raw(Q(ref)),
                 ["at", a(ref_pos[0]), a(ref_pos[1]), a(0)],
                 effects(hide=ref_hide)])
    node.append(["property", Raw(Q("Value")), Raw(Q(val)),
                 ["at", a(val_pos[0]), a(val_pos[1]), a(0)],
                 effects(hide=val_hide)])
    node.append(["property", Raw(Q("Footprint")), Raw(Q(fp)),
                 ["at", a(pos[0]), a(pos[1]), a(0)], effects(hide=True)])
    node.append(["property", Raw(Q("Datasheet")), Raw(Q("")),
                 ["at", a(pos[0]), a(pos[1]), a(0)], effects(hide=True)])
    node.append(["property", Raw(Q("Description")), Raw(Q(desc)),
                 ["at", a(pos[0]), a(pos[1]), a(0)], effects(hide=True)])
    for pnum in pin_numbers_all(lib):
        node.append(["pin", Raw(Q(pnum)),
                     ["uuid", Raw(Q(uid(key + ":pin:" + pnum)))]])
    node.append(["instances",
                 ["project", Raw(Q(D.PROJECT)),
                  ["path", Raw(Q(path)),
                   ["reference", Raw(Q(ref))],
                   ["unit", str(unit)]]]])
    return node


def term_symbol(lib_id, net, pos, path, ref, key):
    props = prop_by_name(lib_id)
    rp = find(props["Reference"], "at")
    vp = find(props["Value"], "at")
    rx, ry = float(unq(rp[1])), float(unq(rp[2]))
    vx, vy = float(unq(vp[1])), float(unq(vp[2]))
    return symbol_node(lib_id, net, "", 0, 1, pos, path, ref,
                       (g(pos[0] + rx), g(pos[1] - ry)),
                       (g(pos[0] + vx), g(pos[1] - vy)),
                       prop_hidden(props["Value"]), key, ref_hide=True)


def build_sheet(sheet, net_sheets, path_prefix, counters):
    used_libs = {}
    items = []
    seen_conn = set()

    for e in sheet["entries"]:
        used_libs[e["lib"]] = True

    def term(net, pos):
        lib_id, _ = D.POWER_TERMS[net]
        used_libs[lib_id] = True
        counters["pwr"] += 1
        ref = f"#PWR{counters['pwr']:04d}"
        items.append(term_symbol(lib_id, net, pos, path_prefix, ref,
                                 f"{sheet['id']}:pwr:{counters['pwr']}"))

    for m, pos in layout_sheet(sheet, net_sheets):
        e = m["e"]
        b = m["b"]
        xs, ys = [], []
        for cx in (b[0], b[2]):
            for cy in (b[1], b[3]):
                px, py = xform(cx, cy, pos, e["rot"])
                xs.append(px)
                ys.append(py)
        top, bottom = min(ys), max(ys)
        if m["has_vert"]:
            rx = g(max(xs) + 2.54)
            ref_pos = (rx, g(top - 1.27))
            val_pos = (rx, g(bottom + 1.27))
        else:
            ref_pos = (g(pos[0]), g(top - 1.27))
            val_pos = (g(pos[0]), g(bottom + 1.27))
        if e["ref"] is None:
            counters["flg"] += 1
            ref = f"#FLG{counters['flg']:04d}"
            ref_hide = True
            key = f"{sheet['id']}:flg:{counters['flg']}"
        else:
            ref = e["ref"]
            ref_hide = ref.startswith("#")
            key = f"{sheet['id']}:{e['ref']}:{e['unit']}"
        items.append(symbol_node(
            e["lib"], e["val"], e["fp"], e["rot"], e["unit"], pos,
            path_prefix, ref, ref_pos, val_pos,
            val_hide=(e["unit"] != 1), key=key, ref_hide=ref_hide,
            desc=e.get("desc", "")))

        for p in pins_of(e["lib"], e["unit"]):
            net = e["nets"].get(p["num"])
            conn, (dx, dy) = pin_abs(p, pos, e["rot"])
            ck = (round(conn[0], 4), round(conn[1], 4))
            if net is None:
                items.append(["no_connect", ["at", a(conn[0]), a(conn[1])],
                              ["uuid", Raw(Q(uid(key + ":nc:" + p["num"])))]])
                continue
            if (ck, net) in seen_conn:
                continue
            seen_conn.add((ck, net))
            d = (int(round(dx)), int(round(dy)))
            termdef = D.POWER_TERMS.get(net)
            wkey = f"{sheet['id']}:w:{ck[0]}:{ck[1]}:{net}"
            lkey = f"{sheet['id']}:l:{ck[0]}:{ck[1]}:{net}"
            if d in ((0, -1), (0, 1)) and termdef:
                orient = "up" if d[1] < 0 else "down"
                if termdef[1] == orient:
                    end = (conn[0], conn[1] + d[1] * D.STUB)
                    items.append(wire_node([conn, end], wkey))
                    term(net, end)
                    continue
            if d in ((0, -1), (0, 1)):
                side = 1 if conn[0] >= pos[0] else -1
                mid = (conn[0], conn[1] + d[1] * D.BEND)
                end = (mid[0] + side * D.STUB, mid[1])
                items.append(wire_node([conn, mid], wkey + ":a"))
                items.append(wire_node([mid, end], wkey + ":b"))
                items.append(label_node(net, end, 0 if side > 0 else 180, lkey))
            else:
                end = (conn[0] + d[0] * D.STUB, conn[1])
                items.append(wire_node([conn, end], wkey))
                items.append(label_node(net, end, 0 if d[0] > 0 else 180, lkey))

    lib_syms = ["lib_symbols"]
    for lid in sorted(used_libs):
        lib_syms.append(embed(lid))
    return lib_syms, items


def gen_child(sheet, net_sheets, counters, paper):
    global LIMIT
    sheet_uuid = uid("sheet:" + sheet["id"])
    path_prefix = f"/{uid('root')}/{sheet_uuid}"
    lib_syms, items = build_sheet(sheet, net_sheets, path_prefix, counters)
    node = ["kicad_sch",
            ["version", Raw("20250114")],
            ["generator", Raw(Q("eeschema"))],
            ["generator_version", Raw(Q("9.0"))],
            ["uuid", Raw(Q(uid("file:" + sheet["id"])))],
            ["paper", Raw(Q(paper))],
            ["title_block",
             ["title", Raw(Q(f"PSU48-800 — {sheet['title']}"))],
             ["date", Raw(Q(D.DATE))],
             ["rev", Raw(Q(D.REV))],
             ["company", Raw(Q("PSU48"))]],
            lib_syms]
    node.extend(items)
    node.append(["embedded_fonts", "no"])
    return node


def gen_root():
    used = {}
    holes = []
    w, h = 40.64, 30.48
    for i, e in enumerate(D.ROOT_HOLES):
        x = g(25.4 + i * (w + 10.16))
        y = g(120.65)
        used[e["lib"]] = True
        holes.append(symbol_node(
            e["lib"], e["val"], e["fp"], e["rot"], e["unit"], (x, y),
            f"/{uid('root')}", e["ref"],
            (g(x), g(y - 5.08)), (g(x), g(y + 5.08)), False,
            f"root:{e['ref']}"))
    sheet_nodes = []
    for i, sh in enumerate(D.SHEETS):
        x = g(15.24 + i * (w + 10.16))
        y = g(50.8)
        sn = ["sheet",
              ["at", a(x), a(y)],
              ["size", a(w), a(h)],
              ["exclude_from_sim", "no"],
              ["in_bom", "yes"],
              ["on_board", "yes"],
              ["dnp", "no"],
              ["stroke", ["width", a(0)], ["type", "default"]],
              ["fill", ["color", a(0), a(0), a(0), a(0.0000)]],
              ["uuid", Raw(Q(uid("sheet:" + sh["id"])))],
              ["property", Raw(Q("Sheetname")), Raw(Q(sh["id"])),
               ["at", a(x), a(y - 0.7625), a(0)],
               effects(1.524, justify="left bottom")],
              ["property", Raw(Q("Sheetfile")), Raw(Q(sh["id"] + ".kicad_sch")),
               ["at", a(x), a(y + h + 0.6101), a(0)],
               effects(1.524, justify="left top")],
              ["instances",
               ["project", Raw(Q(D.PROJECT)),
                ["path", Raw(Q(f"/{uid('root')}")),
                 ["page", Raw(Q(str(i + 2)))]]]]]
        sheet_nodes.append(sn)
    lib_syms = ["lib_symbols"]
    for lid in sorted(used):
        lib_syms.append(embed(lid))
    node = ["kicad_sch",
            ["version", Raw("20250114")],
            ["generator", Raw(Q("eeschema"))],
            ["generator_version", Raw(Q("9.0"))],
            ["uuid", Raw(Q(uid("root")))],
            ["paper", Raw(Q("A4"))],
            ["title_block",
             ["title", Raw(Q(D.ROOT_TITLE))],
             ["date", Raw(Q(D.DATE))],
             ["rev", Raw(Q(D.REV))],
             ["company", Raw(Q("PSU48"))]],
            lib_syms]
    node.extend(holes)
    node.extend(sheet_nodes)
    node.append(["sheet_instances",
                 ["path", Raw(Q("/")), ["page", Raw(Q("1"))]]])
    node.append(["embedded_fonts", "no"])
    return node


def write_sch(path, node):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(dumps(node) + "\n")


def write_project():
    sheets = [[uid("root"), "Root"]] + [
        [uid("sheet:" + sh["id"]), sh["id"]] for sh in D.SHEETS]
    pro = {
        "board": {"design_settings": {"defaults": {}, "diff_pair_dimensions": [],
                                       "drc_exclusions": [], "rules": {},
                                       "track_widths": [], "via_dimensions": []}},
        "boards": [],
        "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "meta": {"filename": f"{D.PROJECT}.kicad_pro", "version": 1},
        "net_settings": {
            "classes": [
                {"name": "Default", "clearance": 0.2, "track_width": 0.25,
                 "via_diameter": 0.8, "via_drill": 0.4,
                 "microvia_diameter": 0.3, "microvia_drill": 0.1,
                 "diff_pair_width": 0.2, "diff_pair_gap": 0.25},
                {"name": "Power", "clearance": 0.4, "track_width": 1.0,
                 "via_diameter": 1.2, "via_drill": 0.6,
                 "microvia_diameter": 0.3, "microvia_drill": 0.1,
                 "diff_pair_width": 0.2, "diff_pair_gap": 0.25}],
            "meta": {"version": 4}},
        "pcbnew": {"page_layout_descr_file": ""},
        "sheets": sheets,
        "text_variables": {}}
    with open(os.path.join(OUT_DIR, f"{D.PROJECT}.kicad_pro"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump(pro, f, indent=2, ensure_ascii=False)
        f.write("\n")


def main():
    global LIMIT
    net_sheets = {}
    validate(net_sheets)
    set_glob(lambda net: is_glob_net(net, net_sheets))
    counters = {"pwr": 100, "flg": 100}

    write_sch(os.path.join(OUT_DIR, f"{D.PROJECT}.kicad_sch"), gen_root())
    print(f"wrote {D.PROJECT}.kicad_sch")

    for sh in D.SHEETS:
        last_err = None
        for paper, (lx, ly) in PAPER_LIMITS.items():
            LIMIT = (lx, ly)
            saved = dict(counters)
            try:
                node = gen_child(sh, net_sheets, counters, paper)
                break
            except Overflow:
                counters.clear()
                counters.update(saved)
                last_err = Overflow(sh["id"])
        else:
            raise SystemExit(f"sheet {sh['id']}: {last_err}")
        write_sch(os.path.join(OUT_DIR, sh["id"] + ".kicad_sch"), node)
        print(f"wrote {sh['id']}.kicad_sch ({paper})")

    write_project()
    print(f"wrote {D.PROJECT}.kicad_pro")


def is_glob_net(net, net_sheets):
    return net in D.POWER_TERMS or len(net_sheets.get(net, ())) > 1


if __name__ == "__main__":
    main()
