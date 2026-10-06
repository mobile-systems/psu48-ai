import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sexp import parse, dumps, find, findall, unq
from kilib import bbox_of, xform, lib_id_split, load_symbol
import sch_data as D

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KICAD = os.path.join(ROOT_DIR, "kicad")


def texts_of(path):
    root = parse(open(path, encoding="utf-8").read())
    out = []
    for lbl in findall(root, "label"):
        at = find(lbl, "at")
        out.append((unq(lbl[1]), float(unq(at[1])), float(unq(at[2])),
                    float(unq(at[3])) if len(at) > 3 else 0))
    for lbl in findall(root, "global_label"):
        at = find(lbl, "at")
        out.append((unq(lbl[1]), float(unq(at[1])), float(unq(at[2])),
                    float(unq(at[3])) if len(at) > 3 else 0))
    # symbol references & values (visible ones)
    for sym in findall(root, "symbol"):
        p = find(sym, "property")
        for prop in findall(sym, "property"):
            name = unq(prop[1])
            if name not in ("Reference", "Value"):
                continue
            eff = find(prop, "effects")
            hide = eff is not None and find(eff, "hide") is not None
            if hide:
                continue
            at = find(prop, "at")
            pos = find(sym, "at")
            ref = unq(find(sym, "lib_id")[1])
            out.append((f"{unq(prop[2])}#{name}@{ref}", float(unq(at[1])),
                        float(unq(at[2])), float(unq(at[3])) if len(at) > 3 else 0))
    return out


def text_w(t):
    return 0.60 * 1.27 * len(t)


def sym_bboxes(path):
    root = parse(open(path, encoding="utf-8").read())
    for sym in findall(root, "symbol"):
        lib = unq(find(sym, "lib_id")[1])
        at = find(sym, "at")
        x, y = float(unq(at[1])), float(unq(at[2]))
        rot = float(unq(at[3])) if len(at) > 3 else 0
        unit = int(unq(find(sym, "unit")[1])) if find(sym, "unit") else 1
        try:
            b = bbox_of(lib, unit)
        except Exception:
            continue
        xs, ys = [], []
        for cx in (b[0], b[2]):
            for cy in (b[1], b[3]):
                px, py = xform(cx, cy, (x, y), rot)
                xs.append(px)
                ys.append(py)
        yield (min(xs), min(ys), max(xs), max(ys), f"{lib}@{x},{y}")


def label_point(t, sheet_w, sheet_h):
    raw, x, y, ang = t
    name = raw.split("#", 1)[0]
    a = math.radians(ang)
    # label anchor is (x,y); text body grows in -x for angle 0 (justify left bottom)
    dx, dy = 0.0, 0.0
    w = text_w(name) + 1.0
    if abs(math.sin(a)) < 0.001:
        dx = -w if math.cos(a) > 0 else w
        dy = 0
    else:
        dx = -w
    return name, (x + dx, y - 0.635), (x + 0.0, y + 0.635)


def run():
    papers = {"psu48": (297, 210),
              "01_ac_input": (420, 297), "02_pfc": (420, 297),
              "03_llc": (594, 420), "04_aux": (420, 297),
              "05_ctrl": (420, 297)}
    issues = []
    for sh, (W, H) in papers.items():
        path = os.path.join(KICAD, sh + ".kicad_sch")
        if not os.path.exists(path):
            continue
        txts = texts_of(path)
        boxes = list(sym_bboxes(path))
        tpts = [label_point(t, W, H) for t in txts]
        # 1) text-vs-text too close
        for i in range(len(tpts)):
            for j in range(i + 1, len(tpts)):
                n1, p1, q1 = tpts[i]
                n2, p2, q2 = tpts[j]
                d1 = max(math.dist(p1, p2), math.dist(p1, q2),
                         math.dist(q1, p2), math.dist(q1, q2))
                d2 = min(math.dist(p1, p2), math.dist(p1, q2),
                         math.dist(q1, p2), math.dist(q1, q2))
                if d2 < 0.5:
                    issues.append(f"{sh}: text overlap {n1} vs {n2} (d={d2:.2f})")
        # 2) label text inside a symbol box (inflated)
        for name, p, q in tpts:
            for (x0, y0, x1, y1, ident) in boxes:
                if x0 - 1.0 <= p[0] <= x1 + 1.0 and y0 - 1.0 <= p[1] <= y1 + 1.0:
                    if x0 - 1.0 <= q[0] <= x1 + 1.0 and y0 - 1.0 <= q[1] <= y1 + 1.0:
                        issues.append(f"{sh}: text {name} inside symbol {ident}")
        # 3) bounds
        for name, p, q in tpts:
            if p[0] < -2 or q[0] < -2 or p[0] > W + 2 or q[0] > W + 2:
                issues.append(f"{sh}: text {name} beyond right/left ({p[0]},{q[0]})")
            if p[1] < -2 or q[1] < -2 or p[1] > H + 2 or q[1] > H + 2:
                issues.append(f"{sh}: text {name} beyond top/bottom ({p[1]},{q[1]})")
    if issues:
        print("QA ISSUES:")
        print("\n".join(issues))
    else:
        print("QA OK")


if __name__ == "__main__":
    run()