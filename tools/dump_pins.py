"""Dump pin lists for symbols:  python dump_pins.py Device:R Device:C ..."""

import sys

import kilib

for lib_id in sys.argv[1:]:
    try:
        pins = kilib.pins_of(lib_id)
        print(f"== {lib_id}  (units: {kilib.units_of(lib_id)})")
        for p in sorted(pins, key=lambda d: d["num"]):
            print(f"  {p['num']:>4}  {p['name']:<12} {p['etype']:<14} "
                  f"at=({p['x']},{p['y']}) ang={p['ang']} len={p['length']}")
        bb = kilib.bbox_of(lib_id)
        print(f"  bbox: {bb}")
    except Exception as e:
        print(f"== {lib_id}: ERROR {e}")
