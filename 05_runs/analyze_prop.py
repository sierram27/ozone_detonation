#!/usr/bin/env python3
"""Analyse a propagation run: shock speed vs time and the maxp (cellular) pattern.

Usage (inside a batch job, from the run directory):
    python analyze_prop.py <solver log[,log2,...]> <time dir with maxp,p,T,cellLevel,Ccx,Ccy> <out dir>
  Several comma-separated logs (a run continued over chained jobs) are merged in time order.
  After a restart the solver recomputes from the last save, so overlapping times are taken
  from the later log.

Reads only; writes PNG plots and a JSON summary into <out dir>.
  - Shock position: the solver's own "Leading shock location" line (largest x with
    p > 101425 Pa), one value per time step.
  - maxp: highest pressure each cell has seen. Triple points leave high-maxp tracks,
    which outline the detonation cells.
"""
import json, re, sys, os
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
from scipy.interpolate import griddata

D_CJ = 1615.9          # m/s, SDToolbox (Step 4)
H = 0.06               # channel height, m

log_path, tdir, out = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(out, exist_ok=True)
summary = {}

# ---------------------------------------------------------------- shock position
t, xs = [], []
for lp in log_path.split(","):
    lt, lx, cur = [], [], None
    with open(lp) as f:
        for line in f:
            if line.startswith("Time = "):
                cur = float(line.split()[2])
            elif line.startswith("Leading shock location") and cur is not None:
                lt.append(cur); lx.append(float(line.split()[-2]))
    if lt:   # drop earlier entries that this (later) log recomputes
        keep = [i for i, tt in enumerate(t) if tt < lt[0]]
        t = [t[i] for i in keep] + lt; xs = [xs[i] for i in keep] + lx
t, xs = np.array(t), np.array(xs)
summary["logs"] = log_path.split(",")

def fit(t0, t1):
    m = (t >= t0) & (t <= t1)
    return np.polyfit(t[m], xs[m], 1)[0], int(m.sum())

D_all = (xs[-1] - xs[0]) / (t[-1] - t[0])
D_fit25, n25 = fit(25e-6, t[-1])
D_last100, n100 = fit(max(25e-6, t[-1] - 100e-6), t[-1])
win = 2e-6
edges = np.arange(t[0], t[-1] + 1e-12, win)
tc, Dw = [], []
for a, b in zip(edges[:-1], edges[1:]):
    m = (t >= a) & (t <= b)
    if m.sum() > 2:
        tc.append(0.5 * (a + b)); Dw.append(np.polyfit(t[m], xs[m], 1)[0])
tc, Dw = np.array(tc), np.array(Dw)
late = tc >= 25e-6
summary.update({
    "t_end_us": t[-1] * 1e6, "x_start_mm": xs[0] * 1e3, "x_end_mm": xs[-1] * 1e3,
    "D_mean_whole_run": D_all, "D_linear_fit_25us_to_end": D_fit25, "fit_points": n25,
    "D_fit_vs_CJ_percent": 100 * (D_fit25 / D_CJ - 1),
    "D_linear_fit_last_100us": D_last100, "D_last100_vs_CJ_percent": 100 * (D_last100 / D_CJ - 1),
    "D_2us_windows_after_25us_min_max_std": [float(Dw[late].min()), float(Dw[late].max()), float(Dw[late].std())],
})

fig, ax = plt.subplots(2, 1, figsize=(8, 7), sharex=True)
ax[0].plot(t * 1e6, xs * 1e3, lw=1, label="leading shock (solver)")
ax[0].plot(t * 1e6, (xs[0] + D_CJ * (t - t[0])) * 1e3, "k--", lw=1, label=f"D_CJ = {D_CJ:.0f} m/s from start")
ax[0].set_ylabel("x (mm)"); ax[0].legend(); ax[0].grid(alpha=.3)
ax[1].step(tc * 1e6, Dw, where="mid", label="speed in 2 µs windows")
ax[1].axhline(D_CJ, color="k", ls="--", lw=1, label="D_CJ")
ax[1].axhline(D_fit25, color="C3", ls=":", lw=1.5, label=f"fit 25 µs–end: {D_fit25:.0f} m/s")
ax[1].set_xlabel("t (µs)"); ax[1].set_ylabel("D (m/s)"); ax[1].legend(); ax[1].grid(alpha=.3)
fig.tight_layout(); fig.savefig(f"{out}/shock_speed.png", dpi=150); plt.close(fig)

# ---------------------------------------------------------------- fields
def read_field(name):
    txt = open(os.path.join(tdir, name)).read()
    m = re.search(r"internalField\s+nonuniform\s+List<scalar>\s*(\d+)\s*\(", txt)
    n = int(m.group(1))
    vals = np.array(txt[m.end():].split(")", 1)[0].split(), dtype=float)
    assert vals.size == n, (name, vals.size, n)
    return vals

cx, cy = read_field("Ccx"), read_field("Ccy")
maxp, p, T, lev = (read_field(k) for k in ("maxp", "p", "T", "cellLevel"))
summary.update({"cells": int(cx.size),
                "cells_per_level": {int(k): int((lev == k).sum()) for k in np.unique(lev)},
                "maxp_max_kPa": float(maxp.max() / 1e3)})

# regular 0.125 mm grid (finest AMR cells), nearest-cell values keep the AMR detail
dx = 0.125e-3
x0, x1 = 0.0, 0.50                     # whole channel
gx = np.arange(x0 + dx / 2, x1, dx); gy = np.arange(dx / 2, H, dx)
GX, GY = np.meshgrid(gx, gy)
sel = cx < x1 + 1e-3
grid = lambda v: griddata((cx[sel], cy[sel]), v[sel], (GX, GY), method="nearest")
Gmaxp, Gp, GT = grid(maxp), grid(p), grid(T)

ext = [x0 * 1e3, x1 * 1e3, 0, H * 1e3]
fig, ax = plt.subplots(3, 1, figsize=(16, 7), sharex=True)
im = ax[0].imshow(Gmaxp, origin="lower", extent=ext, cmap="Greys", norm=LogNorm(vmin=1.5e5, vmax=np.percentile(maxp, 99.9)), aspect="equal")
ax[0].set_title(f"maxp (peak pressure history) at t = {t[-1]*1e6:.1f} µs: triple-point tracks"); fig.colorbar(im, ax=ax[0], label="Pa")
im = ax[1].imshow(Gp / 1e3, origin="lower", extent=ext, cmap="viridis", aspect="equal")
ax[1].set_title("p (kPa), final time"); fig.colorbar(im, ax=ax[1])
im = ax[2].imshow(GT, origin="lower", extent=ext, cmap="inferno", aspect="equal")
ax[2].set_title("T (K), final time"); fig.colorbar(im, ax=ax[2])
for a in ax: a.set_ylabel("y (mm)")
ax[2].set_xlabel("x (mm)")
fig.tight_layout(); fig.savefig(f"{out}/fields_final.png", dpi=150); plt.close(fig)

# ---------------------------------------------------------------- cell size from maxp
# Region swept by the front after the start-up: x from 80 mm to 5 mm behind the final front.
xa, xb = 0.080, xs[-1] - 0.005
cols = (gx >= xa) & (gx <= xb)
A = np.log(Gmaxp[:, cols]); A = A - A.mean(axis=0)
# transverse (y) spectrum, averaged over columns. Wavelengths H/k for k = 1..40
Py = (np.abs(np.fft.rfft(A, axis=0)) ** 2).mean(axis=1)
ky = np.arange(Py.size)
lam_y = np.where(ky > 0, H / np.maximum(ky, 1), np.inf)
# longitudinal (x) spectrum, averaged over rows
B = np.log(Gmaxp[:, cols]); B = B - B.mean(axis=1, keepdims=True)
Px = (np.abs(np.fft.rfft(B, axis=1)) ** 2).mean(axis=0)
Lx = cols.sum() * dx
lam_x = np.where(np.arange(Px.size) > 0, Lx / np.maximum(np.arange(Px.size), 1), np.inf)
topy = [(float(lam_y[i] * 1e3), float(Py[i] / Py[1:].max())) for i in np.argsort(Py[1:41])[::-1][:5] + 1]
mx = (lam_x > 2e-3) & (lam_x < 0.06)
ix = np.where(mx)[0]
topx = [(float(lam_x[i] * 1e3), float(Px[i] / Px[ix].max())) for i in ix[np.argsort(Px[ix])[::-1][:5]]]
summary.update({"cell_analysis_region_mm": [xa * 1e3, xb * 1e3],
                "y_spectrum_top5_wavelength_mm_relpower": topy,
                "x_spectrum_top5_wavelength_mm_relpower": topx})

fig, ax = plt.subplots(1, 2, figsize=(11, 4))
ax[0].plot(lam_y[1:41] * 1e3, Py[1:41] / Py[1:41].max(), "o-"); ax[0].set_xscale("log")
ax[0].set_xlabel("transverse wavelength (mm)"); ax[0].set_ylabel("relative power"); ax[0].set_title("log maxp, spectrum across the channel"); ax[0].grid(alpha=.3)
ax[1].plot(lam_x[ix] * 1e3, Px[ix] / Px[ix].max(), "o-"); ax[1].set_xscale("log")
ax[1].set_xlabel("longitudinal wavelength (mm)"); ax[1].set_title("log maxp, spectrum along the channel"); ax[1].grid(alpha=.3)
fig.tight_layout(); fig.savefig(f"{out}/maxp_spectra.png", dpi=150); plt.close(fig)

# zoom of the maxp tracks in the analysis region
fig, ax = plt.subplots(figsize=(12, 4))
im = ax.imshow(Gmaxp[:, cols], origin="lower", extent=[xa * 1e3, xb * 1e3, 0, H * 1e3], cmap="Greys",
               norm=LogNorm(vmin=1.5e5, vmax=np.percentile(maxp, 99.9)), aspect="equal")
ax.set_xlabel("x (mm)"); ax.set_ylabel("y (mm)"); ax.set_title("maxp, swept region after start-up")
fig.colorbar(im, ax=ax, label="Pa"); fig.tight_layout(); fig.savefig(f"{out}/maxp_zoom.png", dpi=170); plt.close(fig)

json.dump(summary, open(f"{out}/prop_summary.json", "w"), indent=2)
print(json.dumps(summary, indent=2))
