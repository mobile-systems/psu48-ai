"""Minimal S-expression parser/serializer compatible with KiCad files.

Leaves keep their raw source text (quoted strings keep quotes), so a parse ->
serialize round trip reproduces the original content exactly.
"""

import re


def Q(s):
    """Quote a python string into a KiCad quoted atom."""
    s = str(s)
    s = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return '"' + s + '"'


def unq(raw):
    """Strip quotes/unescape a raw leaf."""
    if isinstance(raw, Raw):
        raw = str(raw)
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        body = raw[1:-1]
        out = []
        i = 0
        while i < len(body):
            c = body[i]
            if c == "\\" and i + 1 < len(body):
                n = body[i + 1]
                out.append({"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}.get(n, n))
                i += 2
            else:
                out.append(c)
                i += 1
        return "".join(out)
    return raw


class Raw(str):
    """A raw leaf exactly as it appeared in the source (may include quotes)."""


_TOKEN = re.compile(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+')


def parse(text):
    tokens = _TOKEN.findall(text)
    pos = 0

    def rd():
        nonlocal pos
        t = tokens[pos]
        pos += 1
        if t == "(":
            node = []
            while tokens[pos] != ")":
                node.append(rd())
            pos += 1
            return node
        if t == ")":
            raise ValueError("unexpected )")
        return Raw(t)

    out = []
    while pos < len(tokens):
        out.append(rd())
    return out[0] if len(out) == 1 else out


def dumps(node, indent=0):
    """Serialize with tab indentation similar to KiCad style."""
    pad = "\t" * indent
    if isinstance(node, list):
        if not node:
            return pad + "()"
        # short lists (only atoms) go on one line
        if all(not isinstance(c, list) for c in node):
            return pad + "(" + " ".join(_leaf(c) for c in node) + ")"
        n = head_len(node)
        if any(not isinstance(c, list) for c in node[n:]):
            raise ValueError(
                "atoms after child lists cannot be serialized: "
                + repr(node)[:200])
        parts = [pad + "(" + " ".join(_leaf(c) for c in node[:n])]
        for c in node[n:]:
            parts.append(dumps(c, indent + 1))
        parts.append(pad + ")")
        return "\n".join(parts)
    return pad + _leaf(node)


def _leaf(c):
    return str(c)


def _head(node):
    h = node[0]
    # first atom plus following atoms up to the first list stay on the header line
    out = [str(h)]
    for c in node[1:]:
        if isinstance(c, list):
            break
        out.append(str(c))
    return " ".join(out)


def head_len(node):
    n = 0
    for c in node:
        if isinstance(c, list):
            break
        n += 1
    return n


# --- small helpers -------------------------------------------------------

def find(node, name):
    for c in node:
        if isinstance(c, list) and c and str(c[0]) == name:
            return c
    return None


def findall(node, name):
    return [c for c in node if isinstance(c, list) and c and str(c[0]) == name]


def atom(node, name, default=None):
    c = find(node, name)
    if c is None or len(c) < 2:
        return default
    return unq(c[1])


def num(x):
    """Format a number the way KiCad does (up to 6 decimals, no trailing zeros)."""
    s = f"{float(x):.6f}".rstrip("0").rstrip(".")
    return s if s not in ("-0", "") else "0"
