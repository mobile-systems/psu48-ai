import sys

p = r"C:/Program Files/KiCad/10.0/share/kicad/symbols/Device.kicad_sym"
s = open(p, encoding="utf-8").read()
i = s.find('(symbol "R"')
j = s.find('\n\t(symbol "', i + 5)
print(s[i:j])
