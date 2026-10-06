"""Generate project library: kicad/psu48_lib.kicad_sym, kicad/psu48.pretty/*, lib tables.

Node convention (see sexp.py): list nodes hold the head token WITHOUT
parentheses, dumps() adds balanced parens.

Run:  python mklib.py
"""

import math
import os

from sexp import parse, dumps, findall, unq, Raw, Q, num

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KICAD_DIR = os.path.join(ROOT, "kicad")
PRETTY = os.path.join(KICAD_DIR, "psu48.pretty")
SYM_DIR = os.path.join(r"C:/Program Files/KiCad/10.0/share/kicad/symbols")


def a(x):
    """Number or string -> atom (numbers formatted KiCad style)."""
    if isinstance(x, str):
        return Raw(Q(x))
    return Raw(num(x))


def eff(size=1.27, hide=False, justify=None):
    node = ["effects", ["font", ["size", a(size), a(size)]]]
    if justify:
        node.append(["justify", Raw(justify)])
    if hide:
        node.append(["hide", "yes"])
    return node


def prop(name, value, x, y, rot=0, hide=False, size=1.27, justify=None):
    return ["property", Raw(Q(name)), Raw(Q(value)),
            ["at", a(x), a(y), a(rot)],
            eff(size, hide, justify)]


def pin(etype, x, y, ang, length, name, number, hide_name=False):
    return ["pin", Raw(etype), Raw("line"),
            ["at", a(x), a(y), a(ang)],
            ["length", a(length)],
            ["name", Raw(Q(name)), eff(1.27, hide_name)],
            ["number", Raw(Q(number)), eff(1.27, False)]]


def rect(x1, y1, x2, y2, fill=False):
    node = ["rectangle", ["start", a(x1), a(y1)], ["end", a(x2), a(y2)],
            ["stroke", ["width", a(0.254)], ["type", "default"]],
            ["fill", ["type", "background" if fill else "none"]]]
    return node


def poly(pts):
    node = ["polyline", ["pts"]]
    for x, y in pts:
        node[1].append(["xy", a(x), a(y)])
    node += [["stroke", ["width", a(0.254)], ["type", "default"]],
             ["fill", ["type", "none"]]]
    return node


def line(x1, y1, x2, y2):
    # symbols only support polyline graphics (no 'line' tag)
    return poly([(x1, y1), (x2, y2)])


def make_symbol(name, pins, graphics, props, pin_names_hide=True,
                pin_numbers_hide=False):
    sym = ["symbol", Raw(Q(name))]
    pn = ["pin_numbers"]
    if pin_numbers_hide:
        pn.append(["hide", "yes"])
    sym.append(pn)
    pnm = ["pin_names", ["offset", a(1.016)]]
    if pin_names_hide:
        pnm.append(["hide", "yes"])
    sym.append(pnm)
    sym += [["exclude_from_sim", "no"], ["in_bom", "yes"],
            ["on_board", "yes"], ["in_pos_files", "yes"]]
    sym += props
    sym.append(["symbol", Raw(Q(name + "_0_1"))] + graphics)
    sym.append(["symbol", Raw(Q(name + "_1_1"))] + pins)
    sym += [["embedded_fonts", "no"]]
    return sym


# ---------------------------------------------------------------- symbols --

def build_power_clone(base_node, new_name, value, description):
    """Clone a power lib symbol, rename top-level + sub-symbols + Value."""
    import re
    node = parse(dumps(base_node))
    node[0] = "symbol"
    node[1] = Raw(Q(new_name))
    for c in node[1:]:
        if isinstance(c, list) and str(c[0]) == "symbol":
            # rename sub-symbol: "<anything>_u_s" -> "<new_name>_u_s"
            m = re.search(r"(_\d+_\d+)$", unq(c[1]))
            if m:
                c[1] = Raw(Q(new_name + m.group(1)))
    for p in findall(node, "property"):
        k = unq(p[1])
        if k == "Value":
            p[2] = Raw(Q(value))
        elif k == "Reference":
            p[2] = Raw('"#PWR"')
        elif k == "Description":
            p[2] = Raw(Q(description))
    return node


def build_cmchoke():
    pins = [
        pin("passive", -10.16, 3.81, 0, 2.54, "1", "1"),
        pin("passive", 10.16, 3.81, 180, 2.54, "2", "2"),
        pin("passive", -10.16, -3.81, 0, 2.54, "3", "3"),
        pin("passive", 10.16, -3.81, 180, 2.54, "4", "4"),
    ]
    graphics = [
        rect(-7.62, 1.27, -3.81, 6.35),
        rect(3.81, 1.27, 7.62, 6.35),
        rect(-7.62, -6.35, -3.81, -1.27),
        rect(3.81, -6.35, 7.62, -1.27),
        line(-2.54, 7.62, -2.54, -7.62),
        line(2.54, 7.62, 2.54, -7.62),
        line(-10.16, 3.81, -7.62, 3.81),
        line(7.62, 3.81, 10.16, 3.81),
        line(-10.16, -3.81, -7.62, -3.81),
        line(7.62, -3.81, 10.16, -3.81),
    ]
    props = [
        prop("Reference", "LF", 0, 10.16),
        prop("Value", "CMChoke", 0, -10.16),
        prop("Footprint", "", 0, 0, 0, hide=True),
        prop("Datasheet", "", 0, 0, 0, hide=True),
        prop("Description", "Common mode choke, 4 pins", 0, 0, 0, hide=True),
    ]
    return make_symbol("CMChoke", pins, graphics, props)


def build_tllc():
    pins = [
        pin("passive", -7.62, 2.54, 0, 2.54, "1", "1"),
        pin("passive", -7.62, -2.54, 0, 2.54, "2", "2"),
        pin("passive", 7.62, 5.08, 180, 2.54, "3", "3"),
        pin("passive", 7.62, 0.0, 180, 2.54, "4", "4"),
        pin("passive", 7.62, -5.08, 180, 2.54, "5", "5"),
    ]
    graphics = [
        rect(-5.08, 3.81, -1.27, -3.81),
        rect(1.27, 6.35, 5.08, -6.35),
        line(0, 8.89, 0, -8.89),
        line(-7.62, 2.54, -5.08, 2.54),
        line(-7.62, -2.54, -5.08, -2.54),
        line(5.08, 5.08, 7.62, 5.08),
        line(5.08, 0, 7.62, 0),
        line(5.08, -5.08, 7.62, -5.08),
    ]
    props = [
        prop("Reference", "T", 0, 11.43),
        prop("Value", "T_LLC", 0, -11.43),
        prop("Footprint", "", 0, 0, 0, hide=True),
        prop("Datasheet", "", 0, 0, 0, hide=True),
        prop("Description", "LLC transformer: primary 1-2, secondary CT 3-4-5",
             0, 0, 0, hide=True),
    ]
    return make_symbol("T_LLC", pins, graphics, props)


def build_taux():
    pins = [
        pin("passive", -7.62, 6.35, 0, 2.54, "1", "1"),
        pin("passive", -7.62, 3.81, 0, 2.54, "2", "2"),
        pin("passive", -7.62, -1.27, 0, 2.54, "3", "3"),
        pin("passive", -7.62, -3.81, 0, 2.54, "4", "4"),
        pin("passive", 7.62, 2.54, 180, 2.54, "5", "5"),
        pin("passive", 7.62, -2.54, 180, 2.54, "6", "6"),
    ]
    graphics = [
        rect(-5.08, 7.62, -1.27, 2.54),
        rect(-5.08, -0.635, -1.27, -5.08),
        rect(1.27, 3.81, 5.08, -3.81),
        line(0, 8.89, 0, -8.89),
        line(-7.62, 6.35, -5.08, 6.35),
        line(-7.62, 3.81, -5.08, 3.81),
        line(-7.62, -1.27, -5.08, -1.27),
        line(-7.62, -3.81, -5.08, -3.81),
        line(5.08, 2.54, 7.62, 2.54),
        line(5.08, -2.54, 7.62, -2.54),
    ]
    props = [
        prop("Reference", "T", 0, 11.43),
        prop("Value", "T_AUX", 0, -11.43),
        prop("Footprint", "", 0, 0, 0, hide=True),
        prop("Datasheet", "", 0, 0, 0, hide=True),
        prop("Description", "Flyback transformer: pri 1-2, aux 3-4, sec 5-6",
             0, 0, 0, hide=True),
    ]
    return make_symbol("T_AUX", pins, graphics, props)


def build_relay():
    pins = [
        pin("passive", -7.62, 2.54, 0, 2.54, "A1", "A1"),
        pin("passive", -7.62, -2.54, 0, 2.54, "A2", "A2"),
        pin("passive", 10.16, 7.62, 180, 2.54, "11", "11"),
        pin("passive", 10.16, 5.08, 180, 2.54, "12", "12"),
        pin("passive", 10.16, 2.54, 180, 2.54, "14", "14"),
        pin("passive", 10.16, -2.54, 180, 2.54, "21", "21"),
        pin("passive", 10.16, -5.08, 180, 2.54, "22", "22"),
        pin("passive", 10.16, -7.62, 180, 2.54, "24", "24"),
    ]
    graphics = [
        rect(-5.08, 3.81, 0, -3.81),
        line(-7.62, 2.54, -5.08, 2.54),
        line(-7.62, -2.54, -5.08, -2.54),
        line(5.08, 7.62, 7.62, 7.62),
        line(7.62, 7.62, 10.16, 7.62),
        line(7.62, 7.62, 9.5, 3.4),
        line(5.08, 2.54, 10.16, 2.54),
        line(5.08, 5.08, 10.16, 5.08),
        line(5.08, -2.54, 7.62, -2.54),
        line(7.62, -2.54, 9.5, -6.7),
        line(5.08, -7.62, 10.16, -7.62),
        line(5.08, -5.08, 10.16, -5.08),
        line(0, 6.35, 7.62, 7.62),
    ]
    props = [
        prop("Reference", "K", 0, 10.16),
        prop("Value", "Relay_DPDT", 0, -10.16),
        prop("Footprint", "", 0, 0, 0, hide=True),
        prop("Datasheet", "", 0, 0, 0, hide=True),
        prop("Description", "DPDT relay: coil A1/A2, contacts 11/12/14 21/22/24",
             0, 0, 0, hide=True),
    ]
    return make_symbol("Relay_DPDT", pins, graphics, props,
                       pin_names_hide=True)


def build_ucc24624():
    pins = [
        pin("output", -7.62, 3.81, 0, 2.54, "VG1", "1"),
        pin("power_in", -7.62, 1.27, 0, 2.54, "PGND", "2"),
        pin("power_out", -7.62, -1.27, 0, 2.54, "REG", "3"),
        pin("input", -7.62, -3.81, 0, 2.54, "VD1", "4"),
        pin("passive", 7.62, -3.81, 180, 2.54, "VSS", "5"),
        pin("input", 7.62, -1.27, 180, 2.54, "VD2", "6"),
        pin("power_in", 7.62, 1.27, 180, 2.54, "VDD", "7"),
        pin("output", 7.62, 3.81, 180, 2.54, "VG2", "8"),
    ]
    graphics = [
        rect(-5.08, 2.54, 5.08, -2.54),
        line(-5.08, 2.54, -5.08, -2.54),
        line(5.08, 2.54, 5.08, -2.54),
    ]
    props = [
        prop("Reference", "U", 0, 5.08),
        prop("Value", "UCC24624", 0, -5.08),
        prop("Footprint", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", 0, 0, 0, hide=True),
        prop("Datasheet", "https://www.ti.com/lit/ds/symlink/ucc24624.pdf",
             0, 0, 0, hide=True),
        prop("Description",
             "Dual-channel synchronous rectifier controller for LLC converters, "
             "230V VD sense, 8-pin SOIC", 0, 0, 0, hide=True),
    ]
    return make_symbol("UCC24624", pins, graphics, props, pin_names_hide=True)


def write_sym_lib():
    os.makedirs(KICAD_DIR, exist_ok=True)
    power = parse(open(os.path.join(SYM_DIR, "power.kicad_sym"),
                       encoding="utf-8").read())
    pwr_syms = {unq(s[1]): s for s in findall(power, "symbol")}

    lib = ["kicad_symbol_lib",
           ["version", Raw("20251024")],
           ["generator", Raw(Q("kicad_symbol_editor"))],
           ["generator_version", Raw(Q("9.0"))]]
    for new, base, value, desc in [
        ("VRECT", "+15V", "VRECT", "Rectified AC rail power symbol"),
        ("VBUS400", "+15V", "VBUS400", "PFC bus 400V power symbol"),
        ("+15VS", "+15V", "+15VS", "Isolated 15V rail power symbol"),
        ("GND48", "GND", "GND48", "Secondary ground power symbol"),
    ]:
        lib.append(build_power_clone(pwr_syms[base], new, value, desc))
    lib.append(build_cmchoke())
    lib.append(build_tllc())
    lib.append(build_taux())
    lib.append(build_relay())
    lib.append(build_ucc24624())
    path = os.path.join(KICAD_DIR, "psu48_lib.kicad_sym")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(dumps(lib) + "\n")
    print("wrote", path)


# -------------------------------------------------------------- footprints --

def th_pad(num_, x, y, drill, size, shape="circle"):
    return ["pad", Raw(Q(num_)), "thru_hole", Raw(shape),
            ["at", a(x), a(y)],
            ["size", a(size), a(size)],
            ["drill", a(drill)],
            ["layers", Raw('"*.Cu"'), Raw('"*.Mask"')],
            ["remove_unused_layers", "no"]]


def fline(x1, y1, x2, y2, layer, width=0.12):
    return ["fp_line", ["start", a(x1), a(y1)], ["end", a(x2), a(y2)],
            ["stroke", ["width", a(width)], ["type", "solid"]],
            ["layer", Raw(Q(layer))]]


def fcircle(cx, cy, r, layer, width=0.12):
    return ["fp_circle", ["center", a(cx), a(cy)], ["end", a(cx + r), a(cy)],
            ["stroke", ["width", a(width)], ["type", "solid"]],
            ["fill", "no"],
            ["layer", Raw(Q(layer))]]


def frect(x1, y1, x2, y2, layer, width=0.12):
    return ["fp_rect", ["start", a(x1), a(y1)], ["end", a(x2), a(y2)],
            ["stroke", ["width", a(width)], ["type", "solid"]],
            ["fill", "no"],
            ["layer", Raw(Q(layer))]]


def ftext(kind, text, x, y, layer, size=1.0):
    return ["fp_text", Raw(kind), Raw(Q(text)),
            ["at", a(x), a(y)],
            ["layer", Raw(Q(layer))],
            ["effects", ["font", ["size", a(size), a(size)],
                         ["thickness", a(round(size * 0.15, 3))]]]]


def make_fp(name, descr, tags, attr, pads, graphics):
    return ["footprint", Raw(Q(name)),
            ["version", Raw("20240108")],
            ["generator", Raw(Q("psu48-mklib"))],
            ["layer", Raw('"F.Cu"')],
            ["descr", Raw(Q(descr))],
            ["tags", Raw(Q(tags))],
            ["property", Raw('"Reference"'), Raw('"REF**"'),
             ["at", "0", "-2", "0"], ["layer", Raw('"F.SilkS"')],
             ["effects", ["font", ["size", "1", "1"],
                          ["thickness", "0.15"]]]],
            ["property", Raw('"Value"'), Raw(Q(name)),
             ["at", "0", "3", "0"], ["layer", Raw('"F.Fab"')],
             ["effects", ["font", ["size", "1", "1"],
                          ["thickness", "0.15"]]]],
            ["property", Raw('"Datasheet"'), Raw('""'),
             ["at", "0", "0", "0"], ["layer", Raw('"F.Fab"')],
             ["effects", ["font", ["size", "1.27", "1.27"]], ["hide", "yes"]]],
            ["property", Raw('"Description"'), Raw('""'),
             ["at", "0", "0", "0"], ["layer", Raw('"F.Fab"')],
             ["effects", ["font", ["size", "1.27", "1.27"]], ["hide", "yes"]]],
            ["attr", Raw(attr)]] + graphics + pads


def rect_silk(x1, y1, x2, y2, crt=1.0):
    return [
        fline(x1, y1, x2, y1, "F.SilkS"),
        fline(x2, y1, x2, y2, "F.SilkS"),
        fline(x2, y2, x1, y2, "F.SilkS"),
        fline(x1, y2, x1, y1, "F.SilkS"),
        fline(x1 - crt, y1 - crt, x2 + crt, y1 - crt, "F.CrtYd", 0.05),
        fline(x2 + crt, y1 - crt, x2 + crt, y2 + crt, "F.CrtYd", 0.05),
        fline(x2 + crt, y2 + crt, x1 - crt, y2 + crt, "F.CrtYd", 0.05),
        fline(x1 - crt, y2 + crt, x1 - crt, y1 - crt, "F.CrtYd", 0.05),
        frect(x1, y1, x2, y2, "F.Fab"),
    ]


def write_fps():
    os.makedirs(PRETTY, exist_ok=True)

    def save(name, fp):
        with open(os.path.join(PRETTY, name + ".kicad_mod"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write(dumps(fp) + "\n")

    # 1. polarized radial cap D35 P10
    save("CP_Radial_D35.0mm_P10.00mm", make_fp(
        "CP_Radial_D35.0mm_P10.00mm",
        "Polarized radial electrolytic, D35mm, pitch 10mm",
        "capacitor electrolytic radial", "through_hole",
        [th_pad("1", 0, 0, 1.5, 3.0, "rect"), th_pad("2", 10, 0, 1.5, 3.0)],
        [fcircle(5, -17.5, 17.5, "F.SilkS"),
         fcircle(5, -17.5, 18.0, "F.CrtYd", 0.05),
         fcircle(5, -17.5, 17.5, "F.Fab"),
         ftext("user", "${REFERENCE}", 5, -17.5, "F.Fab")]))

    # 2. NTC disc 11mm P5
    save("NTC_D11.0mm_P5.00mm", make_fp(
        "NTC_D11.0mm_P5.00mm", "NTC thermistor disc 11mm, pitch 5mm",
        "ntc thermistor disc", "through_hole",
        [th_pad("1", 0, 0, 1.0, 2.0), th_pad("2", 5, 0, 1.0, 2.0)],
        [fcircle(2.5, -5.5, 5.5, "F.SilkS"),
         fcircle(2.5, -5.5, 6.0, "F.CrtYd", 0.05),
         fcircle(2.5, -5.5, 5.5, "F.Fab"),
         ftext("user", "${REFERENCE}", 2.5, -5.5, "F.Fab")]))

    # 3. CM choke 25x20, pins x=0/20, y=0/10
    pads = [th_pad(str(n), x, y, 1.0, 2.2)
            for n, (x, y) in enumerate(
                [(0, 0), (20, 0), (0, 10), (20, 10)], 1)]
    g = rect_silk(-2.5, -2.5, 22.5, 17.5) + \
        [ftext("user", "${REFERENCE}", 10, 7.5, "F.Fab")]
    save("CMChoke_25x20_P20x10",
         make_fp("CMChoke_25x20_P20x10",
                 "Common mode choke body 25x20mm, pins 20mm x 10mm",
                 "choke common mode", "through_hole", pads, g))

    # 4. power inductor D30 P15
    save("L_THT_D30.0mm_P15.00mm", make_fp(
        "L_THT_D30.0mm_P15.00mm", "Power inductor body D30mm, pitch 15mm",
        "inductor power tht", "through_hole",
        [th_pad("1", 0, 0, 1.2, 2.6), th_pad("2", 15, 0, 1.2, 2.6)],
        [fcircle(7.5, -15, 15, "F.SilkS"),
         fcircle(7.5, -15, 15.5, "F.CrtYd", 0.05),
         fcircle(7.5, -15, 15, "F.Fab"),
         ftext("user", "${REFERENCE}", 7.5, -15, "F.Fab")]))

    # 5. inductor 25x20 P10
    save("L_THT_25x20_P10.00mm", make_fp(
        "L_THT_25x20_P10.00mm", "Inductor body 25x20mm, pitch 10mm",
        "inductor power tht", "through_hole",
        [th_pad("1", 0, 0, 1.0, 2.2), th_pad("2", 10, 0, 1.0, 2.2)],
        rect_silk(-2.5, -2.5, 22.5, 12.5) +
        [ftext("user", "${REFERENCE}", 10, 5, "F.Fab")]))

    # 6. EE35 5 pins P5
    pads = [th_pad(str(i + 1), i * 5, 0, 1.0, 2.0) for i in range(5)]
    save("T_EE35_5pin_P5.00mm", make_fp(
        "T_EE35_5pin_P5.00mm", "Transformer EE35 bobbin, 5 pins pitch 5mm",
        "transformer ee35", "through_hole", pads,
        rect_silk(-7.5, -32.5, 27.5, -2.5) +
        [ftext("user", "${REFERENCE}", 10, -17.5, "F.Fab")]))

    # 7. EE16 6 pins P2.5
    pads = [th_pad(str(i + 1), i * 2.5, 0, 0.8, 1.6) for i in range(6)]
    save("T_EE16_6pin_P2.50mm", make_fp(
        "T_EE16_6pin_P2.50mm", "Transformer EE16 bobbin, 6 pins pitch 2.5mm",
        "transformer ee16", "through_hole", pads,
        rect_silk(-3, -13.5, 15.5, -1.5) +
        [ftext("user", "${REFERENCE}", 6, -7.5, "F.Fab")]))
    print("wrote footprints to", PRETTY)


def write_tables():
    with open(os.path.join(KICAD_DIR, "sym-lib-table"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write('(sym_lib_table\n  (version 7)\n'
                '  (lib (name "psu48_lib")(type "KiCad")'
                '(uri "${KIPRJMOD}/psu48_lib.kicad_sym")(options "")'
                '(descr "PSU48 custom symbols"))\n)\n')
    with open(os.path.join(KICAD_DIR, "fp-lib-table"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write('(fp_lib_table\n  (version 7)\n'
                '  (lib (name "psu48")(type "KiCad")'
                '(uri "${KIPRJMOD}/psu48.pretty")(options "")'
                '(descr "PSU48 custom footprints"))\n)\n')
    print("wrote lib tables")


if __name__ == "__main__":
    write_sym_lib()
    write_fps()
    write_tables()
