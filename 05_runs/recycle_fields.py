#!/usr/bin/env python3
"""Helper for recycle.slurm (window recycling, "option B"; MODE=cut or MODE=average). Plain Python, no extra packages.
Reads and writes OpenFOAM ASCII files (writeFormat ascii in controlDict).

Subcommands
  shift   POINTS DX                        move every mesh point by DX in x (file rewritten in place)
  ambient SRC_TIME_DIR OUT.json            fresh-gas state = the cells ahead of the front (lowest p and T);
                                           fails if those cells are not all identical
  target  TEMPLATE_0_DIR TGT_TIME_DIR AMBIENT.json
                                           write every field to be mapped, filled with the fresh-gas state
                                           (boundary conditions taken from the case's 0/ templates)
  map     SRC_TIME_DIR TGT_TIME_DIR TGT_POLYMESH DXC
                                           average the (shifted) source cells onto the base cells containing
                                           them; replaces OpenFOAM 8 mapFields, which took > 15 min (job 3740579)
  cut     SRC_TIME_DIR TGT_TIME_DIR TGT_POLYMESH SHIFT L DXC
                                           "cut and append" (MODE=cut): keep the refined source cells at
                                           x >= SHIFT exactly (mesh, values, refinement data), shift them left,
                                           drop x < SHIFT, append fresh base cells; fields in TGT_TIME_DIR must
                                           be the uniform fresh-gas fields from 'target'
  check   TGT_TIME_DIR AMBIENT.json TGT_POLYMESH L SHIFT OFFSET
                                           checks after mapping (cell positions read from the target mesh)
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
    if n == 0:
        return [], rest.lstrip()
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


def read_list(path, conv):
    """A plain OpenFOAM list file (points, faces, owner, neighbour): header, N, '(', one item per line, ')'."""
    text = open(path).read()
    head_end = text.index("}", text.index("FoamFile"))
    m = re.compile(r"\n(\d+)\s*\n\(").search(text, head_end)
    items, _ = split_list(text, m.end(), int(m.group(1)), path)
    return [conv(s) for s in items]


def parse_face(s):
    return [int(a) for a in s[s.index("(") + 1:-1].split()]


def read_mesh(polymesh):
    pts = read_list(os.path.join(polymesh, "points"), parse_value)
    faces = read_list(os.path.join(polymesh, "faces"), parse_face)
    owner = read_list(os.path.join(polymesh, "owner"), int)
    neigh = read_list(os.path.join(polymesh, "neighbour"), int)
    return pts, faces, owner, neigh


def mesh_boxes(polymesh):
    """Per cell: (xmin, xmax, ymin, ymax). Every cell of this 2D mesh, refined or not, is an axis-aligned
    rectangle, so the bounding box of the points on its faces is the cell itself."""
    return cell_boxes(*read_mesh(polymesh))


def cell_boxes(pts, faces, owner, neigh):
    n = max(owner) + 1
    inf = float("inf")
    x0, x1, y0, y1 = [inf] * n, [-inf] * n, [inf] * n, [-inf] * n
    for fi, face in enumerate(faces):
        xs = [pts[k][0] for k in face]
        ys = [pts[k][1] for k in face]
        a, b, c, d = min(xs), max(xs), min(ys), max(ys)
        for ci in ((owner[fi], neigh[fi]) if fi < len(neigh) else (owner[fi],)):
            if a < x0[ci]: x0[ci] = a
            if b > x1[ci]: x1[ci] = b
            if c < y0[ci]: y0[ci] = c
            if d > y1[ci]: y1[ci] = d
    return list(zip(x0, x1, y0, y1))


def cmd_map(src_tdir, tgt_tdir, tgt_polymesh, dxc):
    """Average the shifted source cells onto the base-mesh cells that contain them.
    Each base cell (dxc x dxc) holds exactly 1, 4 or 16 source cells (AMR level 0, 1, 2) when the shift is
    a whole number of base cells. Values: area-weighted average; maxp: maximum (a peak record is not averaged).
    Base cells with no source cells keep the fresh-gas values already in tgt_tdir."""
    dxc = float(dxc)
    sb = mesh_boxes(os.path.join(src_tdir, "polyMesh"))
    tb = mesh_boxes(tgt_polymesh)
    key = lambda xc, yc: (math.floor(xc / dxc), math.floor(yc / dxc))
    tindex = {key((a + b) / 2, (c + d) / 2): i for i, (a, b, c, d) in enumerate(tb)}
    if len(tindex) != len(tb):
        sys.exit("ERROR: target mesh is not a uniform grid of size DXC")
    groups, misaligned, cut = {}, 0, 0
    for si, (a, b, c, d) in enumerate(sb):
        k = key((a + b) / 2, (c + d) / 2)
        if k not in tindex:
            cut += 1                                   # shifted out of the domain (x < 0)
            continue
        ix, iy = k
        eps = 1e-9 * dxc
        if a < ix * dxc - eps or b > (ix + 1) * dxc + eps or c < iy * dxc - eps or d > (iy + 1) * dxc + eps:
            misaligned += 1
        groups.setdefault(tindex[k], []).append((si, (b - a) * (d - c)))
    if misaligned:
        sys.exit(f"ERROR: {misaligned} source cells straddle base cells (SHIFT must be a multiple of {dxc} m)")
    gap = [ti for ti, g in groups.items() if abs(sum(w for _, w in g) - dxc * dxc) > 1e-6 * dxc * dxc]
    if gap:
        sys.exit(f"ERROR: {len(gap)} base cells are only partly covered by source cells")
    sizes = {}
    for g in groups.values():
        sizes[len(g)] = sizes.get(len(g), 0) + 1
    print(f"   source cells: {len(sb)} ({cut} shifted out of the domain); base cells filled: {len(groups)} of "
          f"{len(tb)}; source cells per base cell: {dict(sorted(sizes.items()))}")

    ns = len(sb)
    for f in FIELDS:
        sv = values(os.path.join(src_tdir, f), ns)
        tpath = os.path.join(tgt_tdir, f)
        tv = values(tpath, len(tb))
        vec = isinstance(tv[0], tuple)
        for ti, g in groups.items():
            if f == "maxp":
                tv[ti] = max(sv[si] for si, _ in g)
            elif vec:
                area = sum(w for _, w in g)
                tv[ti] = tuple(sum(sv[si][c] * w for si, w in g) / area for c in range(3))
            else:
                area = sum(w for _, w in g)
                tv[ti] = sum(sv[si] * w for si, w in g) / area
        write_internal(tpath, tv)
    print(f"   mapped {len(FIELDS)} fields: {' '.join(FIELDS)} (maxp as maximum, others area-weighted average)")


def write_internal(tpath, tv):
    """Replace the 'internalField uniform ...' written by cmd_target with a per-cell list."""
    vec = isinstance(tv[0], tuple)
    text = open(tpath).read()
    body = (f"internalField   nonuniform List<{'vector' if vec else 'scalar'}> \n{len(tv)}\n(\n"
            + "\n".join(fmt_value(a) for a in tv) + "\n)\n;")
    text, n1 = re.subn(r"^internalField\s+uniform\s+[^;]*;", lambda _: body, text, flags=re.M)
    if n1 != 1:
        sys.exit(f"ERROR: {tpath} has no uniform internalField to replace")
    open(tpath, "w").write(text)


# ------------------------------------------------------------------------------------------------ cut
# "Cut and append" recycling: keep the solver's own refined mesh and values for x >= SHIFT (no averaging),
# shift them left, drop the burned gas at x < SHIFT and append fresh 0.5 mm base cells on the right.
# The adaptive-mesh bookkeeping (cellLevel, pointLevel, refinementHistory: read by hexRef82D at start-up)
# is carried over for the kept cells; new cells are level 0 with no history.

def newell(c):
    """Area vector of a polygon (right-hand rule over its point order, as OpenFOAM defines face normals)."""
    nx = ny = nz = 0.0
    for i in range(len(c)):
        x1, y1, z1 = c[i]
        x2, y2, z2 = c[(i + 1) % len(c)]
        nx += (y1 - y2) * (z1 + z2)
        ny += (z1 - z2) * (x1 + x2)
        nz += (x1 - x2) * (y1 + y2)
    return nx, ny, nz


def read_history(path):
    """refinementHistory: splitCells [(parent, [children])] and visibleCells [index or -1]."""
    text = open(path).read()
    out = []
    for tag in ("// splitCells", "// visibleCells"):
        m = re.compile(r"(\d+)\s*\n\(").search(text, text.index(tag))
        items, _ = split_list(text, m.end(), int(m.group(1)), path)
        out.append(items)
    split = []
    for s in out[0]:
        par, rest = s.strip().split(None, 1)
        split.append((int(par), [int(a) for a in rest[rest.index("(") + 1:rest.rindex(")")].split()]))
    return text[:text.index("// splitCells")], split, [int(s) for s in out[1]]


def foam_header(src_path, location, note=None):
    """Header of an existing OpenFOAM file (FoamFile dict and banner), with a new location (and note)."""
    text = open(src_path).read()
    end = re.compile(r"\n(\d+)\s*\n\(").search(text, text.index("}", text.index("FoamFile"))).start()
    head = re.sub(r'^(\s*location\s+)"[^"]*";', rf'\g<1>"{location}";', text[:end], flags=re.M)
    if note is not None:
        head = re.sub(r'^(\s*note\s+)"[^"]*";', rf'\g<1>"{note}";', head, flags=re.M)
    return head


def write_foam_list(path, head, items):
    with open(path, "w") as f:
        f.write(head.rstrip("\n") + "\n\n\n" + f"{len(items)}\n(\n" + "\n".join(items)
                + "\n)\n\n\n// " + "*" * 73 + " //\n")


def cmd_cut(src_tdir, tgt_tdir, tgt_polymesh, shift, length, dxc):
    S, L, d = float(shift), float(length), float(dxc)
    nb = round(S / d)
    if abs(nb * d - S) > 1e-9:
        sys.exit(f"ERROR: SHIFT {S} m is not a whole number of base cells ({d} m)")
    pm = os.path.join(src_tdir, "polyMesh")
    pts, faces, owner, neigh = read_mesh(pm)
    clev = read_list(os.path.join(pm, "cellLevel"), int)
    plev = read_list(os.path.join(pm, "pointLevel"), int)
    hhead, split, visible = read_history(os.path.join(pm, "refinementHistory"))
    btext = open(os.path.join(pm, "boundary")).read()
    patches = [(m.group(1), int(re.search(r"nFaces\s+(\d+);", m.group(2)).group(1)),
                int(re.search(r"startFace\s+(\d+);", m.group(2)).group(1)))
               for m in re.finditer(r"\n\s*(\w+)\s*\n\s*\{([^}]*)\}", btext) if "nFaces" in m.group(2)]
    names = [p[0] for p in patches]
    for need in ("inlet", "outlet", "bottom", "top", "frontAndBack"):
        if need not in names:
            sys.exit(f"ERROR: patch {need} not in {names}")
    nold, nif = len(clev), len(neigh)
    if len(visible) != nold or len(plev) != len(pts) or max(owner) + 1 != nold:
        sys.exit("ERROR: cellLevel / pointLevel / refinementHistory sizes do not match the source mesh")
    eps = 1e-6 * d
    boxes = cell_boxes(pts, faces, owner, neigh)
    ymin = min(p[1] for p in pts); ymax = max(p[1] for p in pts)
    z0 = min(p[2] for p in pts); z1 = max(p[2] for p in pts)
    ny = round((ymax - ymin) / d)
    if abs(max(p[0] for p in pts) - L) > eps or abs(min(p[0] for p in pts)) > eps:
        sys.exit(f"ERROR: source mesh does not span x = 0 .. {L} m")

    # ---- which cells stay
    straddle = sum(1 for a, b, _, _ in boxes if a < S - eps and b > S + eps)
    if straddle:
        sys.exit(f"ERROR: {straddle} cells straddle the cut at x = {S} m")
    keep = [c for c in range(nold) if boxes[c][0] >= S - eps]
    newc = [-1] * nold
    for k, c in enumerate(keep):
        newc[c] = k
    nk = len(keep)
    removed_ref = sum(1 for c in range(nold) if newc[c] < 0 and clev[c] > 0)

    # ---- faces of the kept cells
    internal, inlet = [], []                        # internal: (owner, neighbour, old point list)
    for f in range(nif):
        o, n = newc[owner[f]], newc[neigh[f]]
        if o >= 0 and n >= 0:
            internal.append((o, n, faces[f]))
        elif o >= 0:
            inlet.append((o, faces[f]))             # normal already points out of the kept cell (-x)
        elif n >= 0:
            inlet.append((n, faces[f][::-1]))       # was the neighbour: reverse so the normal points out
    if any(abs(pts[k][0] - S) > eps for _, f in inlet for k in f):
        sys.exit("ERROR: a new inlet face is not on the cut line")
    bfaces = {name: [] for name in names}           # kept boundary faces per patch: (owner, old points)
    outlet_old = []
    for name, nf, start in patches:
        for f in range(start, start + nf):
            o = newc[owner[f]]
            if o < 0:
                continue
            if name == "inlet":
                sys.exit("ERROR: a kept cell touches the old inlet")
            if name == "outlet":
                outlet_old.append(f)
            else:
                bfaces[name].append((o, faces[f]))

    # ---- the old outlet becomes the joint to the appended block: it must be plain base cells
    if len(outlet_old) != ny:
        sys.exit(f"ERROR: {len(outlet_old)} outlet faces, expected {ny} (refined cells at the outlet?)")
    joint, rows = {}, {}
    for f in outlet_old:
        fp = faces[f]
        ys = [pts[k][1] for k in fp]
        if (len(fp) != 4 or any(abs(pts[k][0] - L) > eps for k in fp) or clev[owner[f]] != 0
                or any(plev[k] != 0 for k in fp) or abs(max(ys) - min(ys) - d) > eps):
            sys.exit("ERROR: an outlet face is not a plain base-cell face (refinement reaches the outlet)")
        j = round((min(ys) - ymin) / d)
        rows[j] = f
        for k in fp:
            joint[(round((pts[k][1] - ymin) / d), 0 if abs(pts[k][2] - z0) < eps else 1)] = k
    if sorted(rows) != list(range(ny)) or len(joint) != 2 * (ny + 1):
        sys.exit("ERROR: outlet faces do not form one column of base cells")

    # ---- points: the kept ones (shifted by -S), then the new block
    used = sorted({k for _, _, f in internal for k in f} | {k for _, f in inlet for k in f}
                  | {k for v in bfaces.values() for _, f in v for k in f} | {k for f in outlet_old for k in faces[f]})
    newp = {k: i for i, k in enumerate(used)}
    coords = [(pts[k][0] - S, pts[k][1], pts[k][2]) for k in used]
    levels = [plev[k] for k in used]
    pid = {}
    for i in range(nb + 1):
        for j in range(ny + 1):
            for kz in (0, 1):
                if i == 0:
                    pid[(i, j, kz)] = newp[joint[(j, kz)]]
                else:
                    pid[(i, j, kz)] = len(coords)
                    coords.append((L - S + i * d, ymin + j * d, z1 if kz else z0))
                    levels.append(0)
    P = lambda i, j, kz: pid[(i, j, kz)]
    C = lambda i, j: nk + j * nb + i

    def checked(pl, want):
        """The templates below already give outward normals; stop if one does not (no silent flipping)."""
        n = newell([coords[k] for k in pl])
        if sum(a * b for a, b in zip(n, want)) <= 0:
            sys.exit("ERROR: new face template has the wrong orientation")
        return pl

    # New cells copy blockMesh's point order exactly (read from never-refined cells of prop1, 2026-11-23).
    # In particular a cell's back face (z min) and front face (z max) start at the same corner and run in
    # opposite directions (back = 00 01 11 10, front = 00 10 11 01). The solver's 2D refinement (hexRef82D)
    # relies on that pairing: cycle test job 3747361 crashed when it unrefined a cell built with
    # mismatched back/front faces ("edge has too few face neighbours", removeFaces).
    # Q(i, j, dx, dy, kz) = corner (dx, dy) of base cell (i, j), kz = 0 back, 1 front.
    Q = lambda i, j, dx, dy, kz: P(i + dx, j + dy, kz)
    XF = lambda i, j: [Q(i, j, 1, 0, 0), Q(i, j, 1, 1, 0), Q(i, j, 1, 1, 1), Q(i, j, 1, 0, 1)]   # +x face of (i, j)
    YF = lambda i, j: [Q(i, j, 0, 1, 0), Q(i, j, 0, 1, 1), Q(i, j, 1, 1, 1), Q(i, j, 1, 1, 0)]   # +y face of (i, j)

    internal = [(o, n, [newp[k] for k in f]) for o, n, f in internal]
    inlet = [(o, [newp[k] for k in f]) for o, f in inlet]
    for name in bfaces:
        bfaces[name] = [(o, [newp[k] for k in f]) for o, f in bfaces[name]]
    newb = {name: [] for name in names}
    for j in range(ny):
        # joint: the old outlet face (blockMesh's +x face of the last kept cell), now internal
        internal.append((newc[owner[rows[j]]], C(0, j), checked([newp[k] for k in faces[rows[j]]], (1, 0, 0))))
        for i in range(1, nb):
            internal.append((C(i - 1, j), C(i, j), checked(XF(i - 1, j), (1, 0, 0))))
        newb["outlet"].append((C(nb - 1, j), checked(XF(nb - 1, j), (1, 0, 0))))
    for i in range(nb):
        for j in range(1, ny):
            internal.append((C(i, j - 1), C(i, j), checked(YF(i, j - 1), (0, 1, 0))))
        newb["bottom"].append((C(i, 0), checked([Q(i, 0, 0, 0, 0), Q(i, 0, 1, 0, 0), Q(i, 0, 1, 0, 1), Q(i, 0, 0, 0, 1)], (0, -1, 0))))
        newb["top"].append((C(i, ny - 1), checked(YF(i, ny - 1), (0, 1, 0))))
        for j in range(ny):
            newb["frontAndBack"].append((C(i, j), checked([Q(i, j, 0, 0, 0), Q(i, j, 0, 1, 0), Q(i, j, 1, 1, 0), Q(i, j, 1, 0, 0)], (0, 0, -1))))
            newb["frontAndBack"].append((C(i, j), checked([Q(i, j, 0, 0, 1), Q(i, j, 1, 0, 1), Q(i, j, 1, 1, 1), Q(i, j, 0, 1, 1)], (0, 0, 1))))
    if any(o >= n for o, n, _ in internal):
        sys.exit("ERROR: internal face with owner >= neighbour")
    internal.sort(key=lambda t: (t[0], t[1]))       # upper-triangular order, as OpenFOAM requires
    ncell = nk + nb * ny

    # ---- assemble and write the mesh
    allf = [f for _, _, f in internal]
    own = [o for o, _, _ in internal]
    nei = [n for _, n, _ in internal]
    starts = {}
    for name in names:
        lst = inlet if name == "inlet" else bfaces[name] + newb[name]
        starts[name] = (len(allf), len(lst))
        allf += [f for _, f in lst]
        own += [o for o, _ in lst]
    os.makedirs(tgt_polymesh, exist_ok=True)
    loc = "constant/polyMesh"
    note = f"nPoints:{len(coords)}  nCells:{ncell}  nFaces:{len(allf)}  nInternalFaces:{len(nei)}"
    W = lambda fn: os.path.join(tgt_polymesh, fn)
    write_foam_list(W("points"), foam_header(os.path.join(pm, "points"), loc), [fmt_value(c) for c in coords])
    write_foam_list(W("faces"), foam_header(os.path.join(pm, "faces"), loc),
                    [f"{len(f)}({' '.join(map(str, f))})" for f in allf])
    write_foam_list(W("owner"), foam_header(os.path.join(pm, "owner"), loc, note), [str(o) for o in own])
    write_foam_list(W("neighbour"), foam_header(os.path.join(pm, "neighbour"), loc, note), [str(n) for n in nei])
    write_foam_list(W("cellLevel"), foam_header(os.path.join(pm, "cellLevel"), loc),
                    [str(clev[c]) for c in keep] + ["0"] * (nb * ny))
    write_foam_list(W("pointLevel"), foam_header(os.path.join(pm, "pointLevel"), loc), [str(v) for v in levels])
    bt = re.sub(r'^(\s*location\s+)"[^"]*";', rf'\g<1>"{loc}";', btext, flags=re.M)
    for name in names:
        s, n = starts[name]
        bt, k1 = re.subn(rf"(\n\s*{name}\s*\n\s*\{{[^}}]*?nFaces\s+)\d+;", rf"\g<1>{n};", bt)
        bt, k2 = re.subn(rf"(\n\s*{name}\s*\n\s*\{{[^}}]*?startFace\s+)\d+;", rf"\g<1>{s};", bt)
        if k1 != 1 or k2 != 1:
            sys.exit(f"ERROR: could not update patch {name} in boundary")
    open(W("boundary"), "w").write(bt)

    # ---- refinement history: keep the split trees of the kept cells (each tree lies inside one base
    # cell, so it is either kept whole or dropped whole), renumber, new cells get -1 (never split)
    mark = [False] * len(split)
    for c in keep:
        v = visible[c]
        while v >= 0 and not mark[v]:
            mark[v] = True
            v = split[v][0]
    for i, (_, ch) in enumerate(split):
        if mark[i] and any(k >= 0 and not mark[k] for k in ch):
            sys.exit("ERROR: refinementHistory: a kept split cell has a dropped child")
    hmap, k = [-1] * len(split), 0
    for i in range(len(split)):
        if mark[i]:
            hmap[i], k = k, k + 1
    lines = []
    for i, (par, ch) in enumerate(split):
        if mark[i]:
            c2 = [hmap[a] if a >= 0 else -1 for a in ch]
            lines.append(f"{hmap[par] if par >= 0 else -1} {len(c2)}({' '.join(map(str, c2))})")
    vis = [hmap[visible[c]] if visible[c] >= 0 else -1 for c in keep] + ["-1"] * (nb * ny)
    hhead = re.sub(r'^(\s*location\s+)"[^"]*";', rf'\g<1>"{loc}";', hhead, flags=re.M)
    with open(W("refinementHistory"), "w") as f:
        f.write(hhead + f"// splitCells\n\n{len(lines)}\n(\n" + "\n".join(lines) + "\n)\n\n// visibleCells\n\n"
                + f"{len(vis)}\n(\n" + "\n".join(map(str, vis)) + "\n)\n\n\n// " + "*" * 73 + " //\n")

    # ---- fields: kept cells copied unchanged, new cells = fresh gas already written by cmd_target
    for fn in FIELDS:
        sv = values(os.path.join(src_tdir, fn), nold)
        kind, amb = read_field(os.path.join(tgt_tdir, fn))
        if kind != "uniform":
            sys.exit(f"ERROR: {tgt_tdir}/{fn} is not the uniform fresh-gas field from 'target'")
        write_internal(os.path.join(tgt_tdir, fn), [sv[c] for c in keep] + [amb] * (nb * ny))

    lv = {}
    for c in keep:
        lv[clev[c]] = lv.get(clev[c], 0) + 1
    print(f"   source: {nold} cells; removed (x < {S} m): {nold - nk} (of them refined: {removed_ref}); "
          f"kept: {nk}, cells per refinement level {dict(sorted(lv.items()))}")
    print(f"   new inlet faces at the cut: {len(inlet)}; appended base cells: {nb} x {ny} = {nb * ny}")
    print(f"   new mesh: {note}")
    print(f"   refinementHistory: {sum(mark)} of {len(split)} split-cell entries kept")

    # ---- self-check, from the files just written
    pts2, faces2, own2, nei2 = read_mesh(tgt_polymesh)
    b2 = cell_boxes(pts2, faces2, own2, nei2)
    if len(b2) != ncell:
        sys.exit("ERROR: written mesh has the wrong number of cells")
    bad = 0
    for k, c in enumerate(keep):
        a, b, y0, y1 = boxes[c]
        bad += any(abs(u - v) > eps for u, v in zip(b2[k], (a - S, b - S, y0, y1)))
    for j in range(ny):
        for i in range(nb):
            bad += any(abs(u - v) > eps for u, v in zip(b2[C(i, j)], (L - S + i * d, L - S + (i + 1) * d,
                                                                       ymin + j * d, ymin + (j + 1) * d)))
    area = sum((b - a) * (y1 - y0) for a, b, y0, y1 in b2)
    cen = [((a + b) / 2, (y0 + y1) / 2, (z0 + z1) / 2) for a, b, y0, y1 in b2]
    wrong = 0
    for fi, f in enumerate(faces2):
        n = newell([pts2[k] for k in f])
        fc = [sum(pts2[k][q] for k in f) / len(f) for q in range(3)]
        o = cen[own2[fi]]
        if sum(n[q] * (fc[q] - o[q]) for q in range(3)) <= 0:      # must point out of the owner
            wrong += 1
    # every cell: back and front face start at the same (x, y) corner and run in opposite directions
    zb, zf = {}, {}
    for fi in range(len(nei2), len(faces2)):
        f = faces2[fi]
        if all(abs(pts2[k][2] - pts2[f[0]][2]) < eps for k in f):
            (zb if pts2[f[0]][2] < (z0 + z1) / 2 else zf)[own2[fi]] = f
    unpaired = 0
    for c in range(ncell):
        fb, ff = zb.get(c), zf.get(c)
        if fb is None or ff is None or len(fb) != len(ff) or any(
                abs(pts2[fb[k]][0] - pts2[ff[(len(fb) - k) % len(fb)]][0]) > eps or
                abs(pts2[fb[k]][1] - pts2[ff[(len(fb) - k) % len(fb)]][1]) > eps for k in range(len(fb))):
            unpaired += 1
    print(f"   self-check: cells in the wrong place: {bad}; total area {area:.9f} m2 (expected {L * (ymax - ymin):.9f}); "
          f"faces pointing into their owner: {wrong}; cells whose back/front faces are not mirrored: {unpaired}")
    if bad or wrong or unpaired or abs(area - L * (ymax - ymin)) > 1e-9:
        sys.exit("ERROR: self-check of the new mesh failed")
    p2 = values(os.path.join(tgt_tdir, "p"), ncell)
    psrc = values(os.path.join(src_tdir, "p"), nold)
    if any(p2[k] != psrc[c] for k, c in enumerate(keep)):
        sys.exit("ERROR: kept p values changed")

    # ---- a few cells side by side, so the shift can be seen in the log
    Ts, T2 = values(os.path.join(src_tdir, "T"), nold), values(os.path.join(tgt_tdir, "T"), ncell)
    shocked = [k for k, c in enumerate(keep) if psrc[c] > P_SHOCK]
    picks = []
    if shocked:
        picks.append(("leading shock cell", max(shocked, key=lambda k: b2[k][1])))
    picks.append(("highest p", max(range(nk), key=lambda k: p2[k])))
    fine = [k for k, c in enumerate(keep) if clev[c] == 2]
    if fine:
        picks.append(("a level-2 cell (0.125 mm)", fine[len(fine) // 2]))
    picks.append(("first kept cell (at the cut)", min(range(nk), key=lambda k: (b2[k][0], b2[k][2]))))
    picks.append(("last kept cell (old outlet)", newc[owner[rows[ny // 2]]]))
    picks.append(("first new cell", C(0, ny // 2)))
    print(f"   {'cell':30s} {'source x, y (m)':>22s} {'new x, y (m)':>22s}   p (Pa) source -> new        T (K) source -> new")
    for label, k in picks:
        a, b, y0, y1 = b2[k]
        nx_, ny_ = (a + b) / 2, (y0 + y1) / 2
        if k < nk:
            c = keep[k]
            sx, sy = (boxes[c][0] + boxes[c][1]) / 2, (boxes[c][2] + boxes[c][3]) / 2
            src = f"{sx:10.6f}, {sy:9.6f}"
            sp, st = f"{psrc[c]:12.2f}", f"{Ts[c]:8.2f}"
        else:
            src, sp, st = f"{'(new)':>21s}", f"{'-':>12s}", f"{'-':>8s}"
        print(f"   {label:30s} {src:>22s} {nx_:10.6f}, {ny_:9.6f}   {sp} -> {p2[k]:12.2f}   {st} -> {T2[k]:8.2f}")
    print("   cut done: kept cells and values are identical to the source (shifted); fresh base cells appended")


def cmd_check(tdir, amb_json, tgt_polymesh, length, shift, offset):
    length, shift, offset = float(length), float(shift), float(offset)
    amb = json.load(open(amb_json))
    x = [(a + b) / 2 for a, b, _, _ in mesh_boxes(tgt_polymesh)]
    n = len(x)
    v = {f: values(os.path.join(tdir, f), n) for f in FIELDS}
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
    cmds = {"shift": cmd_shift, "ambient": cmd_ambient, "target": cmd_target, "map": cmd_map, "cut": cmd_cut,
            "check": cmd_check}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        sys.exit(__doc__)
    cmds[sys.argv[1]](*sys.argv[2:])
