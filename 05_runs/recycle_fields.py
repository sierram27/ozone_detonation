#!/usr/bin/env python3
"""Helper for recycle.slurm (window recycling, "option B"). Plain Python, no extra packages.
Reads and writes OpenFOAM ASCII files (writeFormat ascii in controlDict).

Subcommands
  shift   POINTS DX                        move every mesh point by DX in x (file rewritten in place)
  ambient SRC_TIME_DIR OUT.json            fresh-gas state = the cells ahead of the front (lowest p and T);
                                           fails if those cells are not all identical
  target  TEMPLATE_0_DIR TGT_TIME_DIR AMBIENT.json
                                           write every field to be mapped, filled with the fresh-gas state
                                           (boundary conditions taken from the case's 0/ templates)
  check   TGT_TIME_DIR AMBIENT.json NX DXC L SHIFT OFFSET
                                           checks after mapFields on the base mesh (NX cells in x, size DXC)
"""
import json
import math
import os
import re
import sys

SPECIES = ["H", "H2", "O", "O2", "OH", "H2O", "HO2", "H2O2", "AR"]
FIELDS = ["p", "T", "U", "maxp"] + SPECIES
P_SHOCK = 101325 + 100          # the solver's leading-shock test (solverTypeEuler.H): p > 101325+100


def parse_value(s):
    s = s.strip()
    if s.startswith("("):
        return tuple(float(v) for v in s.strip("()").split())
    return float(s)


def fmt_value(v):
    if isinstance(v, tuple):
        return "(" + " ".join(repr(c) for c in v) + ")"
    return repr(v)


def split_list(text, start, n, path):
    """Items of an OpenFOAM list whose '(' ends at text[start]. One item per line, as OpenFOAM writes them."""
    rest = text[start:]
    if not rest.startswith("\n"):
        sys.exit(f"ERROR: unexpected list layout in {path}")
    parts = rest[1:].split("\n", n)
    if len(parts) <= n or not parts[n].startswith(")"):
        sys.exit(f"ERROR: could not read {n} list items in {path}")
    return parts[:n], parts[n]


def read_field(path):
    """internalField of a vol field: ('uniform', value) or ('list', [values])."""
    text = open(path).read()
    m = re.search(r"^internalField\s+uniform\s+([^;]+);", text, re.M)
    if m:
        return "uniform", parse_value(m.group(1))
    m = re.search(r"^internalField\s+nonuniform\s+List<\w+>\s*(\d+)\s*\(", text, re.M)
    if not m:
        sys.exit(f"ERROR: no internalField in {path}")
    items, _ = split_list(text, m.end(), int(m.group(1)), path)
    return "list", [parse_value(s) for s in items]


def values(path, n=None):
    kind, v = read_field(path)
    if kind == "uniform":
        if n is None:
            sys.exit(f"ERROR: {path} is uniform; cell count needed")
        return [v] * n
    return v


def cmd_shift(points, dx):
    dx = float(dx)
    text = open(points).read()
    head_end = text.index("}", text.index("FoamFile"))
    m = re.compile(r"\n(\d+)\s*\n\(").search(text, head_end)
    n = int(m.group(1))
    items, tail = split_list(text, m.end(), n, points)
    out = []
    for s in items:
        x, y, z = parse_value(s)
        out.append(fmt_value((x + dx, y, z)))
    with open(points, "w") as f:
        f.write(text[:m.end()] + "\n" + "\n".join(out) + "\n" + tail)
    xs = [parse_value(s)[0] for s in out]
    print(f"   shifted {n} points by {dx} m in x: x now {min(xs):.6f} .. {max(xs):.6f} m")


def cmd_ambient(tdir, out):
    p = values(os.path.join(tdir, "p"))
    n = len(p)
    T = values(os.path.join(tdir, "T"), n)
    pmin, Tmin = min(p), min(T)
    # Fresh gas = cells within 1e-3 Pa and 1e-3 K of the minimum. A wider band (0.5 Pa, job 3740454)
    # also caught cells at the foot of the numerically smeared shock (6670.49 Pa).
    cells = [i for i in range(n) if p[i] <= pmin + 1e-3 and T[i] <= Tmin + 1e-3]
    foot = sum(1 for i in range(n) if pmin + 1e-3 < p[i] <= pmin + 100)
    if not cells:
        sys.exit("ERROR: no fresh-gas cells found")
    print(f"   fresh-gas cells: {len(cells)} (p within 1e-3 Pa of {pmin}, T within 1e-3 K of {Tmin}); "
          f"left out as shock foot (up to 100 Pa above): {foot}")
    # Allowed spread inside the fresh gas, on each quantity's own physical scale. The fresh gas carries
    # round-off-level acoustic noise: job 3740503 found p spread 1e-3 Pa and |U| up to 3.3e-5 m/s
    # (consistent: u = p'/(rho c) = 1e-3 / (0.08 * 330) = 4e-5 m/s). A relative test on U (whose value
    # is 0) wrongly rejected that.
    tol = {"p": 1e-6 * pmin,      # 0.0067 Pa
           "T": 1e-6 * Tmin,      # 0.0003 K
           "U": 1e-3,             # m/s, 3e-6 of the sound speed
           "maxp": 1e-4 * pmin}   # 0.67 Pa; peak-pressure record, only used for the soot foil
    amb, bad = {}, []
    for f in FIELDS:
        v = values(os.path.join(tdir, f), n)
        vec = isinstance(v[cells[0]], tuple)
        rows = [v[i] if vec else (v[i],) for i in cells]
        mean, spread = [], 0.0
        for c in range(len(rows[0])):
            col = [r[c] for r in rows]
            m = sum(col) / len(col)
            spread = max(spread, max(col) - min(col))
            # 12 significant digits = OpenFOAM writePrecision, so the value survives being written and read back
            mean.append(float(f"{m:.12g}"))
        amb[f] = tuple(mean) if vec else mean[0]
        t = tol.get(f, 1e-6)              # mass fractions: 1e-6 absolute
        ok = spread <= t
        print(f"     {f:5s} = {fmt_value(amb[f])}   (spread {spread:.2e}, allowed {t:.1e}) {'ok' if ok else 'TOO LARGE'}")
        if not ok:
            bad.append(f)
    if bad:
        sys.exit(f"ERROR: fresh gas is not uniform in {', '.join(bad)}")
    json.dump(amb, open(out, "w"), indent=1)
    print(f"   fresh gas from {len(cells)} cells ahead of the front: p = {amb['p']} Pa, T = {amb['T']} K, "
          f"U = {amb['U']}, Y(H2, O2, AR) = {amb['H2']}, {amb['O2']}, {amb['AR']}")
    ysum = sum(amb[s] for s in SPECIES)
    if abs(ysum - 1) > 1e-6:
        sys.exit(f"ERROR: fresh-gas mass fractions sum to {ysum}")


def cmd_target(tmpl_dir, tdir, amb_json):
    amb = json.load(open(amb_json))
    os.makedirs(tdir, exist_ok=True)
    for f in FIELDS:
        if f == "maxp":
            tmpl = "p"                       # same units and boundary types as p
        elif f in SPECIES and not os.path.exists(os.path.join(tmpl_dir, f)):
            tmpl = "Ydefault"                # species without their own template file
        else:
            tmpl = f
        text = open(os.path.join(tmpl_dir, tmpl)).read()
        v = amb[f]
        v = tuple(v) if isinstance(v, list) else v
        text, n1 = re.subn(r"^internalField\s+[^;]*;", f"internalField   uniform {fmt_value(v)};", text, flags=re.M)
        text, n2 = re.subn(r"^(\s*object\s+)\S+;", rf"\g<1>{f};", text, count=1, flags=re.M)
        text = re.sub(r'^(\s*location\s+)"[^"]*";', rf'\g<1>"{os.path.basename(tdir.rstrip("/"))}";', text, flags=re.M)
        if n1 != 1 or n2 != 1:
            sys.exit(f"ERROR: template {tmpl} not understood")
        open(os.path.join(tdir, f), "w").write(text)
    print(f"   wrote {len(FIELDS)} fresh-gas fields in {tdir}: {' '.join(FIELDS)}")


def cmd_check(tdir, amb_json, nx, dxc, length, shift, offset):
    nx, dxc, length, shift, offset = int(nx), float(dxc), float(length), float(shift), float(offset)
    amb = json.load(open(amb_json))
    p = values(os.path.join(tdir, "p"))
    n = len(p)
    v = {f: values(os.path.join(tdir, f), n) for f in FIELDS}
    x = [((i % nx) + 0.5) * dxc for i in range(n)]
    edge = length - shift                      # copied region is 0 .. edge
    bad = []

    nonfinite = sum(1 for f in FIELDS for a in v[f]
                    for c in (a if isinstance(a, tuple) else (a,)) if not math.isfinite(c))
    if nonfinite:
        bad.append(f"{nonfinite} non-finite values")

    ysum = [sum(v[s][i] for s in SPECIES) for i in range(n)]
    dev = max(abs(s - 1) for s in ysum)
    ymin = min(min(v[s]) for s in SPECIES)
    print(f"   sum of mass fractions: max |sum - 1| = {dev:.2e}; smallest mass fraction = {ymin:.2e}")
    if dev > 1e-6:
        bad.append("mass fractions do not sum to 1")
    if ymin < -1e-9:
        bad.append("negative mass fraction")

    ahead = [i for i in range(n) if x[i] > edge]
    close = lambda a, b: abs(a - b) <= 1e-9 * max(1.0, abs(b))
    changed = sum(1 for i in ahead if not (close(v["p"][i], amb["p"]) and close(v["T"][i], amb["T"])
                                           and close(v["H2"][i], amb["H2"])))
    print(f"   cells beyond x = {edge:.3f} m (not copied): {len(ahead)}, of which not fresh gas: {changed}")
    if changed:
        bad.append("cells beyond the copied region were changed")

    shocked = [x[i] for i in range(n) if v["p"][i] > P_SHOCK]
    front = max(shocked) if shocked else float("nan")
    print(f"   leading shock (solver test p > {P_SHOCK} Pa): x = {front:.5f} m in the domain = "
          f"{front + offset:.5f} m lab (offset {offset} m)")
    if not (edge - 0.05 < front <= edge):
        bad.append(f"leading shock at {front} m, expected just below {edge} m")

    behind = [i for i in range(n) if x[i] < front - 0.05]
    hot = sum(1 for i in behind if v["T"][i] > amb["T"] + 100)
    print(f"   burned gas kept behind the front: {front:.3f} m; cells there hotter than fresh gas + 100 K: "
          f"{hot} of {len(behind)}")
    print(f"   max p = {max(v['p']):.0f} Pa, max T = {max(v['T']):.0f} K, max maxp = {max(v['maxp']):.0f} Pa, "
          f"min T = {min(v['T']):.1f} K")

    if bad:
        sys.exit("ERROR: " + "; ".join(bad))
    print("   checks passed")


if __name__ == "__main__":
    cmds = {"shift": cmd_shift, "ambient": cmd_ambient, "target": cmd_target, "check": cmd_check}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        sys.exit(__doc__)
    cmds[sys.argv[1]](*sys.argv[2:])
