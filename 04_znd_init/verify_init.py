#!/usr/bin/env python3
"""Check the ZND-initialized OpenFOAM fields written by Dr. Johnson's ZND_Init scripts.

This script only verifies the result. It does not change any field.
Run from the case directory after to_openfoam.py:
    python verify_init.py [--plots-dir DIR]

Checks: species order vs mechanism, sum(Y)=1, no NaN/negative values, ambient state
ahead of the front, post-shock state behind it vs the ZND solution (von Neumann
spike, CJ state), velocity sign, boundary patch names vs the mesh. It also writes
plots: the centreline profile against the ZND solution, and a 2D temperature map.
"""
import argparse, json, re, sys
from pathlib import Path
import numpy as np

SPECIES = ["H", "H2", "O", "O2", "OH", "H2O", "HO2", "H2O2", "AR"]   # FFCM2 order
AMBIENT = dict(p=6670.0, T=298.0, H2=0.01277243, O2=0.10136214, AR=0.88586543)

def read_internal(path):
    """Return the internalField of an OpenFOAM ascii field as a numpy array."""
    txt = Path(path).read_text()
    m = re.search(r"internalField\s+nonuniform\s+List<(scalar|vector)>\s*(\d+)\s*\(", txt)
    if not m:
        m2 = re.search(r"internalField\s+uniform\s+([^;]+);", txt)
        raise ValueError(f"{path}: internalField is uniform ({m2.group(1) if m2 else '?'})")
    kind, n = m.group(1), int(m.group(2))
    body = txt[m.end():]
    if kind == "scalar":
        vals = np.array(body.split(")", 1)[0].split(), dtype=float)
    else:
        rows = re.findall(r"\(([^()]*)\)", body)[:n]
        vals = np.array([r.split() for r in rows], dtype=float)
    assert len(vals) == n, f"{path}: expected {n} values, found {len(vals)}"
    return vals

def patch_names_in_field(path):
    txt = Path(path).read_text()
    bf = txt[txt.index("boundaryField") + len("boundaryField"):]
    return set(re.findall(r"^\s*(\w+)\s*\n\s*\{", bf, re.M))

def patch_types_in_field(path):
    txt = Path(path).read_text()
    bf = txt[txt.index("boundaryField"):]
    return dict(re.findall(r"^\s*(\w+)\s*\n\s*\{\s*type\s+(\w+);", bf, re.M))

def mesh_patch_names(case):
    txt = (case / "constant/polyMesh/boundary").read_text()
    return set(re.findall(r"^\s*(\w+)\s*\n\s*\{\s*\n\s*type", txt, re.M))

def mechanism_species(case):
    txt = (case / "constant/chemFFCM2").read_text()
    m = re.search(r"species\s*\n?\s*(\d+)\s*\(([^)]*)\)", txt)
    return m.group(2).split()

def read_znd(path):
    with open(path) as f:
        header = re.findall(r'"([^"]+)"', f.readline())
    data = np.loadtxt(path, skiprows=1)
    return header, data

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default=".")
    ap.add_argument("--plots-dir", default="verify_plots")
    a = ap.parse_args()
    case = Path(a.case); out = Path(a.plots_dir); out.mkdir(exist_ok=True)
    results, summary = [], {}

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    # --- inputs
    Cx, Cy = read_internal(case / "0/Cx"), read_internal(case / "0/Cy")
    n = len(Cx)
    p, T, U = read_internal(case / "0/p"), read_internal(case / "0/T"), read_internal(case / "0/U")
    Y = {s: read_internal(case / f"0/{s}") for s in SPECIES}
    header, znd = read_znd(case / "ffcm2hydrogen_ZND_solution.csv")
    col = {h: i for i, h in enumerate(header)}

    # --- cell centres: independent check against the analytic uniform blockMesh grid
    # (1000 x 120 cells over 0.5 m x 0.06 m; blockMesh numbers cells x-fastest)
    nx, ny, dx, dy = 1000, 120, 0.5 / 1000, 0.06 / 120
    i, j = np.arange(n) % nx, np.arange(n) // nx
    cc_err = max(np.abs(Cx - (i + 0.5) * dx).max(), np.abs(Cy - (j + 0.5) * dy).max())
    check("Cx, Cy = exact uniform-grid cell centres in OpenFOAM cell order", n == nx * ny and cc_err < 1e-9,
          f"{n} cells, max deviation {cc_err:.1e} m")

    # --- species order
    mech = mechanism_species(case)
    check("Mechanism species order = FFCM2 order used by the scripts", mech == SPECIES, f"chemFFCM2: {mech}")
    znd_sp = header[5:]
    check("ZND CSV species order = FFCM2 order", [s.upper() for s in znd_sp] == [s.upper() for s in SPECIES], f"ZND: {znd_sp}")

    # --- sizes, NaN, bounds
    check("All fields have one value per cell", all(len(v) == n for v in [p, T, U, *Y.values()]), f"{n} cells")
    allvals = np.concatenate([p, T, U.ravel(), *Y.values()])
    check("No NaN/Inf", np.all(np.isfinite(allvals)))
    Ymin = min(v.min() for v in Y.values())
    check("Mass fractions >= 0 (tolerance -1e-12)", Ymin >= -1e-12, f"min Y = {Ymin:.3e}")
    sumY = sum(Y.values())
    check("Sum of 9 mass fractions = 1 (|err| < 1e-5)", np.abs(sumY - 1).max() < 1e-5,
          f"max |sumY-1| = {np.abs(sumY-1).max():.2e}")
    check("p > 0 and T > 0", p.min() > 0 and T.min() > 0, f"p {p.min():.4g}..{p.max():.4g} Pa, T {T.min():.4g}..{T.max():.4g} K")
    check("U is purely x-directed (2D, Uy = Uz = 0)", np.abs(U[:, 1:]).max() == 0.0)

    # --- front geometry used by interpolate_znd_on_openfoam.py
    x_front = 0.005 * np.sin(4 * np.pi * Cy / 0.06) + 0.05
    ahead, behind = Cx >= x_front, Cx < x_front
    summary.update(cells=int(n), cells_behind_front=int(behind.sum()), cells_ahead=int(ahead.sum()))

    # --- ambient (unburned) state ahead of the front
    amb_ok = (np.allclose(p[ahead], AMBIENT["p"]) and np.allclose(T[ahead], AMBIENT["T"])
              and np.allclose(Y["H2"][ahead], AMBIENT["H2"], rtol=1e-6)
              and np.allclose(Y["O2"][ahead], AMBIENT["O2"], rtol=1e-6)
              and np.allclose(Y["AR"][ahead], AMBIENT["AR"], rtol=1e-6)
              and np.all(U[ahead, 0] == 0))
    check("Ahead of front: 6670 Pa, 298 K, H2/O2/AR = 2/1/7 by mole, at rest", amb_ok)

    # --- ZND reference states
    xz, Pz, Tz, Vz = znd[:, col["X"]], znd[:, col["Pressure"]], znd[:, col["Temperature"]], znd[:, col["Velocity"]]
    summary.update(znd_points=int(len(xz)), znd_x_max_m=float(xz.max()),
                   vN_p_Pa=float(Pz[0]), vN_T_K=float(Tz[0]), vN_u_lab_mps=float(Vz[0]),
                   end_p_Pa=float(Pz[-1]), end_T_K=float(Tz[-1]), end_u_lab_mps=float(Vz[-1]),
                   Tmax_K=float(Tz.max()))
    i_ind = int(np.argmax(np.gradient(Tz, xz)))
    summary["induction_length_m (max dT/dx)"] = float(xz[i_ind])
    check("ZND profile extends past the deepest burned cell", xz.max() >= (x_front - Cx)[behind].max(),
          f"ZND x_max = {xz.max():.4g} m, max distance behind front = {(x_front - Cx)[behind].max():.4g} m")
    check("Behind front: gas moves +x (toward the unburned gas)", np.all(U[behind, 0] > 0),
          f"Ux behind: {U[behind,0].min():.1f}..{U[behind,0].max():.1f} m/s")
    check("Peak p in field <= ZND von Neumann pressure (+0.1%)", p.max() <= Pz.max() * 1.001,
          f"field max p {p.max():.4g} vs ZND max {Pz.max():.4g} Pa")

    # CJ speed (independent recomputation with SDToolbox, same mechanism)
    try:
        from sdtoolbox.postshock import CJspeed
        D = CJspeed(6670.0, 298.0, "H2:0.2,O2:0.1,AR:0.7", str(case / "FFCM2_H2_Ar.yaml"))
        summary["CJ_speed_mps"] = float(D)
    except Exception as e:  # informative only
        summary["CJ_speed_mps"] = f"not computed: {e}"

    # --- boundary patches
    mesh_patches = mesh_patch_names(case)
    bad = [f for f in ["p", "T", "U", *SPECIES] if patch_names_in_field(case / f"0/{f}") != mesh_patches]
    check("Field boundary names match mesh patches", not bad, f"mesh: {sorted(mesh_patches)}; mismatched: {bad}")
    Ut = patch_types_in_field(case / "0/U")
    check("U: slip on top/bottom; zeroGradient inlet/outlet", Ut.get("top") == "slip" and Ut.get("bottom") == "slip"
          and Ut.get("inlet") == "zeroGradient" and Ut.get("outlet") == "zeroGradient", str(Ut))

    # --- plots
    try:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        yc = np.unique(Cy)[np.argmin(np.abs(np.unique(Cy) - 0.03))]
        line = np.isclose(Cy, yc); order = np.argsort(Cx[line])
        xl = Cx[line][order]; xf = 0.005 * np.sin(4 * np.pi * yc / 0.06) + 0.05
        fig, ax = plt.subplots(4, 1, figsize=(8, 10), sharex=True)
        for k, (fld, zc, lab) in enumerate([(p, Pz, "p [Pa]"), (T, Tz, "T [K]"), (U[:, 0], Vz, "Ux [m/s]")]):
            ax[k].plot(xl * 1e3, fld[line][order], ".", ms=3, label="OpenFOAM cells (y = %.4f m)" % yc)
            ax[k].plot((xf - xz) * 1e3, zc, "-", lw=1, label="ZND solution")
            ax[k].set_ylabel(lab)
        for s in ["H2", "O2", "H2O", "OH"]:
            ax[3].plot(xl * 1e3, Y[s][line][order], ".", ms=3, label=s)
        ax[3].set_ylabel("Y"); ax[3].set_xlabel("x [mm]"); ax[3].legend(fontsize=8)
        ax[0].legend(fontsize=8); ax[0].set_xlim(0, 80)
        fig.suptitle("ZND initialization: centreline"); fig.tight_layout()
        fig.savefig(out / "centreline_profile.png", dpi=130); plt.close(fig)

        sel = Cx < 0.08
        fig, ax = plt.subplots(figsize=(9, 3.2))
        sc = ax.scatter(Cx[sel] * 1e3, Cy[sel] * 1e3, c=T[sel], s=2, marker="s", cmap="inferno")
        ax.set_aspect("equal"); ax.set_xlabel("x [mm]"); ax.set_ylabel("y [mm]")
        fig.colorbar(sc, label="T [K]"); ax.set_title("Initial temperature near the sinusoidal front")
        fig.tight_layout(); fig.savefig(out / "T_initial_2D.png", dpi=130); plt.close(fig)
        summary["plots"] = [str(out / "centreline_profile.png"), str(out / "T_initial_2D.png")]
    except Exception as e:
        summary["plots"] = f"failed: {e}"

    # --- report
    print("\n==== ZND initialization checks ====")
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    print("\n==== Summary ====")
    print(json.dumps(summary, indent=2))
    (out / "verify_summary.json").write_text(json.dumps(
        dict(checks=[dict(check=c, passed=o, detail=d) for c, o, d in results], summary=summary), indent=2))
    nfail = sum(not ok for _, ok, _ in results)
    print(f"\nRESULT: {'ALL CHECKS PASSED' if nfail == 0 else f'{nfail} CHECK(S) FAILED'}")
    sys.exit(1 if nfail else 0)

if __name__ == "__main__":
    main()
