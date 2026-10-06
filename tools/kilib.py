"""Access to KiCad symbol/footprint libraries.

Provides parsing of .kicad_sym files, pin geometry (with instance transform)
and helpers to embed symbol definitions into a schematic's lib_symbols section.
"""

import math
import os
import re

from sexp import parse, find, findall, unq, Raw, Q, num

KICAD = r"C:/Program Files/KiCad/10.0"
SYM_DIR = os.path.join(KICAD, "share", "kicad", "symbols")
FP_DIR = os.path.join(KICAD, "share", "kicad", "footprints")

_cache = {}


def load_symbol(lib, name, _seen=None):
    """Return (top_level_symbol_node, lib_filename), resolving (extends ...)."""
    key = (lib, name)
    if key in _cache:
        return _cache[key]
    path = lib_path(lib)
    if path is None:
        raise KeyError(f"library {lib!r} not found")
    root = parse(open(path, encoding="utf-8").read())
    sym = None
    for s in findall(root, "symbol"):
        if unq(s[1]) == name:
            sym = s
            break
    if sym is None:
        raise KeyError(f"symbol {lib}:{name} not found")
    ext = find(sym, "extends")
    if ext is not None:
        base_name = unq(ext[1])
        _seen = _seen or set()
        if (lib, base_name) in _seen:
            raise RuntimeError(f"extends loop {lib}:{name}")
        _seen.add(key)
        base, _ = load_symbol(lib, base_name, _seen)
        sym = merge_derived(base, sym, name)
    _cache[key] = (sym, path)
    return _cache[key]


def merge_derived(base, derived, name):
    """Merge a derived symbol with its base (properties from derived,
    graphics/pins from base) into a standalone symbol node."""
    from sexp import dumps
    out = parse(dumps(base))
    out[1] = Raw(Q(name))
    # drop base properties that the derived symbol overrides / any extends
    dprops = {}
    for p in findall(derived, "property"):
        dprops[unq(p[1])] = p
    keep = []
    for c in out:
        if isinstance(c, list) and str(c[0]) == "extends":
            continue
        if isinstance(c, list) and str(c[0]) == "property" and unq(c[1]) in dprops:
            continue
        keep.append(c)
    keep.extend(dprops[k] for k in dprops)
    return keep


_libfile_cache = {}


def lib_path(lib):
    if lib in _libfile_cache:
        return _libfile_cache[lib]
    if lib.startswith("psu48_lib"):
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "kicad", "psu48_lib.kicad_sym")
        if os.path.exists(p):
            _libfile_cache[lib] = p
            return p
        _libfile_cache[lib] = None
        return None
    p = os.path.join(SYM_DIR, lib + ".kicad_sym")
    p = p if os.path.exists(p) else None
    _libfile_cache[lib] = p
    return p


def lib_id_split(lib_id):
    if ":" in lib_id:
        return lib_id.split(":", 1)
    raise ValueError(lib_id)


def pins_of(lib_id, unit=1):
    """Pins of the given unit (style 1) -> list of dicts."""
    lib, name = lib_id_split(lib_id)
    sym, _ = load_symbol(lib, name)
    out = []
    for sub in findall(sym, "symbol"):
        subname = unq(sub[1])
        m = re.match(re.escape(name) + r"_(\d+)_(\d+)$", subname)
        if not m:
            # names inside a lib may repeat base name; pattern base_unit_style
            m = re.match(r".*_(\d+)_(\d+)$", subname)
            if not m:
                continue
        u, style = int(m.group(1)), int(m.group(2))
        if style not in (0, 1) or u not in (0, unit):
            continue
        for p in findall(sub, "pin"):
            at = find(p, "at")
            length = float(unq(find(p, "length")[1])) if find(p, "length") else 0.0
            etype = str(p[1])
            pname = unq(find(p, "name")[1]) if find(p, "name") else ""
            pnum = unq(find(p, "number")[1]) if find(p, "number") else ""
            if any(d["num"] == pnum for d in out):
                continue
            out.append(dict(num=pnum, name=pname, etype=etype,
                            x=float(unq(at[1])), y=float(unq(at[2])),
                            ang=int(float(unq(at[3]))) if len(at) > 3 else 0,
                            length=length))
    if not out:
        # fallback: any style for that unit
        for sub in findall(sym, "symbol"):
            subname = unq(sub[1])
            m = re.match(r".*_(\d+)_(\d+)$", subname)
            if not m:
                continue
            u, style = int(m.group(1)), int(m.group(2))
            if u not in (0, unit) or style != 1:
                continue
            for p in findall(sub, "pin"):
                at = find(p, "at")
                out.append(dict(num=unq(find(p, "number")[1]),
                                name=unq(find(p, "name")[1]), etype=str(p[1]),
                                x=float(unq(at[1])), y=float(unq(at[2])),
                                ang=int(float(unq(at[3]))) if len(at) > 3 else 0,
                                length=float(unq(find(p, "length")[1]))))
    return out


def units_of(lib_id):
    lib, name = lib_id_split(lib_id)
    sym, _ = load_symbol(lib, name)
    us = set()
    for sub in findall(sym, "symbol"):
        m = re.match(r".*_(\d+)_(\d+)$", unq(sub[1]))
        if m:
            us.add(int(m.group(1)))
    return sorted(us)


def bbox_of(lib_id):
    """Approximate graphical bounding box in library coordinates."""
    lib, name = lib_id_split(lib_id)
    sym, _ = load_symbol(lib, name)
    xs, ys = [], []

    def walk(node):
        for c in node:
            if isinstance(c, list) and c:
                tag = str(c[0])
                if tag in ("rectangle",):
                    s, e = find(c, "start"), find(c, "end")
                    xs.extend([float(unq(s[1])), float(unq(e[1]))])
                    ys.extend([float(unq(s[2])), float(unq(e[2]))])
                elif tag == "polyline":
                    pts = find(c, "pts")
                    for xy in findall(pts, "xy"):
                        xs.append(float(unq(xy[1])))
                        ys.append(float(unq(xy[2])))
                elif tag == "circle":
                    c0, e = find(c, "center"), find(c, "end")
                    r = math.dist((float(unq(c0[1])), float(unq(c0[2]))),
                                  (float(unq(e[1])), float(unq(e[2]))))
                    cx, cy = float(unq(c0[1])), float(unq(c0[2]))
                    xs.extend([cx - r, cx + r])
                    ys.extend([cy - r, cy + r])
                elif tag == "arc":
                    for k in ("start", "mid", "end"):
                        a = find(c, k)
                        if a:
                            xs.append(float(unq(a[1])))
                            ys.append(float(unq(a[2])))
                elif tag == "text":
                    a = find(c, "at")
                    xs.append(float(unq(a[1])))
                    ys.append(float(unq(a[2])))
                elif tag == "pin":
                    at = find(c, "at")
                    xs.append(float(unq(at[1])))
                    ys.append(float(unq(at[2])))
                walk(c)

    walk(sym)
    if not xs:
        return (-2.54, -2.54, 2.54, 2.54)
    return (min(xs), min(ys), max(xs), max(ys))


def xform(px, py, at, rot, mirror=None):
    """Library point -> schematic coordinates for an instance."""
    x, y = at
    if mirror == "x":
        py = -py
    elif mirror == "y":
        px = -px
    r = math.radians(rot)
    sx = px
    sy = -py
    ox = sx * math.cos(r) + sy * math.sin(r)
    oy = -sx * math.sin(r) + sy * math.cos(r)
    return (round(x + ox, 4), round(y + oy, 4))


def pin_abs(pin, at, rot, mirror=None):
    """Return (connection point, outward direction vector in schematic coords)."""
    conn = xform(pin["x"], pin["y"], at, rot, mirror)
    # pin is drawn from connection point towards 'ang'; outward is opposite
    a = math.radians(pin["ang"] + 180)
    dx, dy = math.cos(a), math.sin(a)  # lib coords (y up)
    r = math.radians(rot)
    sx, sy = dx, -dy
    ox = sx * math.cos(r) + sy * math.sin(r)
    oy = -sx * math.sin(r) + sy * math.cos(r)
    return conn, (round(ox, 4), round(oy, 4))


def embed(lib_id):
    """Return symbol node renamed to full lib_id for lib_symbols."""
    lib, name = lib_id_split(lib_id)
    sym, _ = load_symbol(lib, name)
    node = parse_dumps_roundtrip(sym)
    node[1] = Raw(Q(lib_id))
    return node


def parse_dumps_roundtrip(node):
    from sexp import dumps
    return parse(dumps(node))


def footprint_exists(fp):
    """'Lib:Name' -> bool"""
    if ":" not in fp:
        return False
    lib, name = fp.split(":", 1)
    if lib == "psu48":
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "kicad", "psu48.pretty", name + ".kicad_mod")
        return os.path.exists(p)
    d = os.path.join(FP_DIR, lib + ".pretty")
    return os.path.exists(os.path.join(d, name + ".kicad_mod"))
