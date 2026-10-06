import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sexp import parse, findall, find, unq
import sch_data as D

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KICAD = os.path.join(ROOT_DIR, "kicad")

CLI = r"C:/Program Files/KiCad/10.0/bin/kicad-cli.exe"


def run(args):
    r = subprocess.run([CLI] + args, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"kicad-cli {args[0]} failed: {r.stdout} {r.stderr}")
    return r.stdout


def netlist(root_sch):
    out = subprocess.run(
        [CLI, "sch", "export", "netlist", root_sch, "-o", "C:/tmp/verify.net"],
        capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"netlist export failed: {out.stdout} {out.stderr}")
    root = parse(open("C:/tmp/verify.net", encoding="utf-8").read())
    nnode = next(c for c in root[1:]
                 if isinstance(c, list) and str(c[0]) == "nets")
    nets = {}
    for n in nnode[1:]:
        if not (isinstance(n, list) and str(n[0]) == "net"):
            continue
        code = unq(find(n, "code")[1])
        name = unq(find(n, "name")[1]).lstrip("/")
        nodes = []
        for nd in findall(n, "node"):
            nodes.append((unq(find(nd, "ref")[1]), unq(find(nd, "pin")[1])))
        nets[code] = (name, nodes)
    return nets


def split_local(netname):
    m = re.match(r"^([0-9]{2}_[a-z_]+)/(.*)$", netname)
    if m:
        return m.group(2)
    return netname


def main():
    root_sch = os.path.join(KICAD, D.PROJECT + ".kicad_sch")
    nets = netlist(root_sch)

    actual = {}
    for code, (_name, nodes) in nets.items():
        for ref, pin in nodes:
            actual.setdefault(ref, {})[pin] = _name

    errs = []
    total_pins = 0
    for sh in D.SHEETS:
        for e in sh["entries"]:
            if e["ref"] is None:
                continue
            got = actual.get(e["ref"], {})
            for pnum, net in e["nets"].items():
                total_pins += 1
                want = split_local(net) if net else "<none>"
                g = got.get(pnum)
                if net is None:
                    if g not in (None, "~", "") and not g.startswith("unconnected-"):
                        errs.append(f"{sh['id']} {e['ref']} pin{pnum}: expected unconnected, got {g!r}")
                    continue
                if g is None:
                    errs.append(f"{sh['id']} {e['ref']} pin{pnum}: net {want} missing in netlist")
                elif split_local(g) != want:
                    errs.append(f"{sh['id']} {e['ref']} pin{pnum}: expected {want}, got {g}")
    for e in D.ROOT_HOLES:
        pass

    if errs:
        raise SystemExit("PARTITION MISMATCH (" + str(len(errs)) + "):\n" + "\n".join(errs[:40]))
    print(f"OK: {total_pins} pins verified across {len(nets)} netlist nets")


if __name__ == "__main__":
    main()