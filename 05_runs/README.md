# 05_runs: running the detonation in parallel

`smoke.slurm` runs the ZND-initialized case (Step 4) with `detonationFoam_V2.0` on many cores.
The same script does the smoke test and longer runs, and it can continue (restart) a run.

## How to use it
Run all of these on a Stampede3 login node **from `$SCRATCH/ozone_detonation/logs`** (`mkdir -p` it first), never from `$HOME` (TACC guidance). The commands below assume `S=~/ozone_detonation/05_runs`:
```bash
sbatch $S/smoke.slurm                                     # smoke test: run "smoke", 2 nodes, until 2 us
sbatch --export=ALL,END_TIME=4e-6 $S/smoke.slurm          # continue the same run to 4 us (restart)
sbatch --export=ALL,RUN_NAME=prop1,END_TIME=2e-5 -t 02:00:00 $S/smoke.slurm   # new run, longer wall time
sbatch --export=ALL,RECONSTRUCT=1 $S/smoke.slurm          # also merge the latest time into one case
squeue -u $USER                                           # is it queued / running?
tail -f det_smoke_<jobid>.log                             # the script's own progress (in the logs dir)
tail -f $SCRATCH/ozone_detonation/smoke/log.detonationFoam.<jobid>   # the solver log
scancel <jobid>                                           # stop a job
```
**Check the cost first.** On `skx-dev`, 1 node-hour = 1 SU. Any job with more than 2 nodes or longer than 30 min needs the user's approval (`AGENTS.md`).

## What the script does
| Stage | What happens | Why |
|---|---|---|
| 1. setup / restart | **New run:** `constant/` and `system/` come from the repo case `03_case/coarse_mesh_slip_of8` (current settings). Only `0/` (ZND fields) and `constant/polyMesh` come from `$SCRATCH/ozone_detonation/init_case`. Then `0/Cx`, `0/Cy` are deleted. **Restart:** if the marker file `.decomposed_ok` exists, keep everything. | Taking settings from the repo makes later decisions apply (see Problem 4). `Cx`/`Cy` are only inputs to the ZND scripts. They were written by OpenFOAM 12, and OpenFOAM 8 refuses them (see "Problems" below). |
| run settings | `endTime` and `writeInterval` are set with `sed` on the run copy | The case in the repo is never edited |
| 2. decompose | `decomposePar` with `simple`, `(16 NY 1)` with NY = ranks/16. 96 ranks gives `(16 6 1)`, about 62 × 20 cells per rank | Stanford used `simple (16 8 1)` with 128 ranks; this uses the same method with fewer pieces. A marker file is written on success. |
| 3. solver | `ibrun detonationFoam_V2.0 -parallel` with `timeout` set to 4 min before the Slurm limit | `ibrun` is TACC's MPI launcher. The time guard lets the summary always run and the job end cleanly. |
| 4. summary | grep the log for setup lines, step count, cells, p/T range, errors, saved times | One place to check health |
| 5. optional | `reconstructPar -latestTime` | Merge the 96 pieces into one field for plotting |
| 6. save | copy logs and dictionaries to `$WORK/ozone_detonation/runs/<RUN_NAME>` | `$SCRATCH` is purged after 10 days |

**Restart:** `controlDict` has `startFrom latestTime`, so the solver continues from the newest time directory in `processor*/`. Resubmit with a larger `END_TIME`. Only the times written every `writeInterval` survive a stop. Everything after the last write is recomputed.

## Smoke test result: job 3730997 (2026-11-17)
**Setup:** `skx-dev`, 2 nodes × 48 = 96 MPI ranks, 30 min limit. Wall time 26:01, so **about 0.9 SU**. The failed first try (job 3730993) used 21 s.

### Software check: PASSED
| Check | Evidence from `log.detonationFoam.3730997` |
|---|---|
| Runs in parallel on 96 ranks | `nProcs : 96` |
| Inviscid physics as chosen | `solverType = Euler` |
| FFCM2 read | `StandardChemistryModel: Number of species = 9 and reactions = 27` |
| DLBFoam load-balanced chemistry active | `method loadBalanced;`, `Selecting ODE solver seulex` |
| AMR works in parallel | `Selecting dynamicFvMesh dynamicRefineFvMesh2D`; cells grew from 120 000 to about 199 500. ⚠️ **It refined to level 3, not the chosen 2** (Problem 4) |
| Many steps | **1819 steps** (t = 1.819 µs at 1 ns each). Stopped by our time guard (exit 124) |
| No crash | 0 FATAL / floating-point exception / NaN lines. FPE trapping was on. The MPI "BAD TERMINATION" banners all say `KILLED BY SIGNAL: 15` (96 ranks), which is the TERM signal from our time guard, not a crash. |
| Output written | `processor*/0, 5e-07, 1e-06, 1.5e-06`, each with p, T, U, rho, 9 species, `maxp`, `cellLevel`, `Qdot` |
| Speed | about **0.82 s per step** with about 200 k cells on 96 cores (1483 s for 1819 steps), at fixed 1 ns. The solver's Courant number was about 0.03 (finest cells 0.0625 mm) |

### Physics: NOT yet validated
These are only observations:
- **Max T** rises slowly, from 2691 to 2809 K.
- **Max p** rises from the ZND spike of 174.5 kPa to about 450 kPa by 1 µs, then stays roughly flat (446–466 kPa).

| Steps | 1 | 401 | 801 | 1001 | 1401 | 1801 |
|---|---|---|---|---|---|---|
| max p (kPa) | 174.5 | 228 | 401 | 466 | 460 | 445 |

  Pressures above the 1D spike are expected once the curved front sets up transverse waves and triple points. 1.8 µs is far too short to judge: the front has moved only about 3 mm, and one detonation cell is several mm long.
- **The propagation test is the next step:** track the leading-shock position over at least about 20 µs, compare the speed with D_CJ = 1616 m/s, and check the `maxp` record for cellular structure.

### Cost outlook (measured, not guessed)
> **Superseded:** after this test the user chose Courant number 0.1 (`03_case/CHANGES.md` #11), and the AMR level is now really 2. Both make steps larger. New costs come from the next run.

At about 0.82 s/step on 2 nodes, the original `endTime = 2e-4` (200 000 steps of 1 ns) would take about **46 h on 2 nodes, or about 90 SU**, and longer if AMR adds cells. Options to discuss before any long run:
- a shorter end time
- more nodes (needs approval; scaling not yet measured)
- `adjustTimeStep yes` with `maxCo 0.2`. The current 1 ns step is far below the stability limit, but changing it departs from Stanford's setup.

## Smoke test 2: job 3731474 (2026-11-17), with AMR level 2 and Courant number 0.1
Run with `sbatch --export=ALL,RUN_NAME=smoke2 smoke.slurm`: a fresh run from the ZND fields with the current repo settings. Setup: `skx-dev`, 2 nodes, 96 ranks. Wall time 4:06, so **about 0.14 SU**.

### Software check: PASSED
| Check | Evidence |
|---|---|
| Settings really used | job output: `adjustTimeStep yes`, `maxCo 0.1`, `maxRefinement 2`, `solverType Euler` |
| AMR level ≤ 2 | `cellLevel` at 2 µs: levels 0/1/2 = 5182 / 803 / 33876 cells, **none at level 3** |
| Reached end time | `Time = 2e-06` after **357 steps**; solver exit code 0 (normal end) |
| No crash | 0 FATAL / FPE / NaN lines |
| Output | `processor*/0, 5e-07, 1e-06, 1.5e-06, 2e-06` |
| Speed | 180 s for 357 steps = **0.5 s/step**, about 152 k cells. That is **about 90 s of wall time per simulated µs**, about 7× faster than smoke test 1 |

### How the Courant number behaves
`Co` is the solver's convective Courant number (`03_case/CHANGES.md` #11). Out of 357 steps:
- **Most steps sit at 0.09–0.10**, with the time step around 7–9 ns.
- **Once every 10 steps (`refineInterval 10`) it jumps for one step** to about 0.15–0.25 (32 steps > 0.15). Then the solver cuts Δt to about 3 ns and ramps back up over about 8 steps.
- **One step reached Co = 0.87** (t = 0.15–0.17 µs). Early on, much of the front was still on 0.5 mm cells, so Δt had grown to 19.6 ns. The next AMR update refined the front to 0.125 mm and that step ran at 4× the intended Courant number. It did not crash.

**Why this happens:** in `solverTypeEuler.H` each step runs `detoCellular.H` (choose Δt from the last Co), then `runTime++`, then `mesh.update()` (AMR), then `calculateDt.H` (measure Co). So Δt is chosen before the mesh is refined. When cells are split, the step that is already sized for the old, larger cells runs on cells half (or a quarter) the size. Part of the measured jump may also come from how fluxes are mapped onto new faces. This is the solver's design, not a setting.

**Decision (user, 2026-11-17): option A**, `maxDeltaT 9e-9` (`03_case/CHANGES.md` #12). Not yet tested in a run. The options considered were:
- `maxDeltaT` of about 9e-9 s, which keeps Δt at the level-2 value and would prevent the startup spike
- a lower `maxCo`
- a code change to measure Co after the AMR update (changes the solver; not preferred)

### Physics: NOT yet validated
- Max p is 432 kPa and max T is 2699 K at 2 µs.
- The solver prints `Leading shock location` every step (cells with p > 101 425 Pa; our vN spike is 174 kPa, so this works): **0.05475 m → 0.05819 m** over the 2 µs. That is about 1.7 km/s, but over only 3.4 mm (about 27 cells), during the start-up transient, so it is not a speed measurement.

### Cost outlook (from this test)
About 90 s per simulated µs on 2 nodes, so 2e-4 s (the original endTime) is about 5 h on 2 nodes, **about 10 SU**, if cell count and Δt stay similar.

## Propagation check: job 3731639 (2026-11-17), run `prop1`
```bash
sbatch -t 02:00:00 -J det_prop1 --export=ALL,RUN_NAME=prop1,END_TIME=1e-4,WRITE_INT=1e-6 smoke.slurm
sbatch --export=ALL,RUN_NAME=prop1,LOGJOB=3731639 analyze.slurm      # job 3732274
```
Settings: Euler, FFCM2, AMR level 2, Co 0.1, Δt ≤ 9 ns. `skx-dev`, 2 nodes, 96 ranks, 1 h 56 min, **about 3.9 SU** (plus 0.1 SU of analysis).
The first submission (3731627) was cancelled by the system (`CANCELLED by 0`) before the script started. It was resubmitted unchanged.

### Software and numerics: PASSED
- 12 408 steps to **t = 66.4 µs** (then stopped by the time guard, exit 124; all 96 ranks got signal 15). 0 FATAL / FPE / NaN.
- Δt about 7.2 ns at Co ≈ 0.1. 1043 of 10 673 steps (about 10%) had Co > 0.1, the one step after each AMR update. **Only one step had Co > 0.3 (max 0.39)**, versus 0.87 before the `maxDeltaT` cap.
- Cells steady at about 153 k (level 0/1/2 = 117 628 / 781 / 34 828). AMR follows the front and the cell count does not grow.
- 67 snapshots (every 1 µs), 4.8 GB in `$SCRATCH/ozone_detonation/prop1`.

### Physics: consistent with a CJ cellular detonation (not yet a full validation)
**Shock speed** (from the solver's `Leading shock location`, `results/prop1/shock_speed.png`):

| Measure | Speed | vs D_CJ = 1616 m/s |
|---|---|---|
| Line fit, 25 µs to end | **1590 m/s** | **−1.6 %** |
| Whole run, 54.75 → 158.81 mm in 66.4 µs | 1568 m/s | −3.0 % (includes start-up) |
| 2 µs windows after 25 µs | 1406–1715 m/s (std 74) | oscillates around CJ |

The speed oscillates with a period of **about 18 µs** (peaks at about 10, 28 and 46 µs), which is about 29 mm of travel. Each peak follows a triple-point collision: the front is briefly overdriven and then decays. This is the normal behaviour of a cellular detonation. A slightly sub-CJ mean (1–3 %) is common for 2D inviscid simulations at moderate resolution.

**Cellular structure** (`results/prop1/fields_final.png`, `maxp_zoom.png`, `maxp_spectra.png`):
- `maxp` shows clear **triple-point tracks** that cross and form diamond-shaped cells, with dark collision spots at the walls (x ≈ 112 mm at y = 0, x ≈ 135 mm at y = 60 mm) and inside the channel.
- At 66 µs the front has **2 triple points**, at y ≈ 22 and 52 mm, i.e. **2 cells across the 60 mm channel (cell width ≈ 30 mm)**. The transverse spectrum of log(maxp) for x = 80–154 mm peaks at **30 mm**.
- The longitudinal spectrum peaks at about 37 mm. The window is only 74 mm long, so the next possible values are 25 and 74 mm, which makes this estimate coarse. The 18 µs speed period (about 29 mm) is a second estimate of the distance between collisions.
- The p and T fields show transverse waves on the front and unburned pockets / vortices behind it (the T "mushrooms" at x ≈ 100–130 mm).

**Caveats (what this does NOT yet show):**
1. **The cell width is not independent of the initial condition.** The ZND front was a sinusoid of wavelength 30 mm (two periods in 60 mm), so 2 cells across the channel may be partly imposed by the start-up. Testing it needs a different initial perturbation (for example one period, or random noise) and a check of whether 30 mm reappears.
2. **Literature value to confirm:** this mixture and channel (2H₂+O₂+7Ar, 6.67 kPa, 298 K, 6 cm) match classic numerical studies (as I recall, Oran et al. 1998, Combust. Flame), which report about 2 cells across 6 cm (λ ≈ 3 cm). **This reference still needs to be checked** before it is cited.
3. Resolution is about 12 cells per induction length (AMR level 2). A level-3 comparison would show how much the 1.6 % speed deficit and the track sharpness depend on resolution.
4. 66 µs is only about 2 cell lengths after start-up. A longer run would show whether the pattern is stable.

## Propagation run continued to 200 µs (2026-11-17/18), run `prop1`
`prop1` was continued from its saves with the same settings (restart via `.decomposed_ok`, `END_TIME=2e-4`, `WRITE_INT=1e-6`), submitted from `$SCRATCH/ozone_detonation/logs`:

| Job | Wall limit | Time span | Steps | Max Co | Errors | Ended by |
|---|---|---|---|---|---|---|
| 3731639 | 2 h | 0 → 66.4 µs | 12 408 | 0.39 | 0 | time guard |
| 3732550 | 2 h | 66 → 145.0 µs | 13 286 | 0.33 | 0 | time guard |
| 3733283 | 1 h | 145 → 185.3 µs | 6 710 | 0.31 | 0 | time guard |
| 3734119 | 30 min | 185 → **200.0 µs** | 2 576 | 0.30 | 0 | reached endTime (exit 0) |

Each restart recomputes from the last 1 µs save. Six other submissions were cancelled by the system at 2:02 (Problem 5).
```bash
sbatch --export=ALL,RUN_NAME=prop1,LOGJOB=3731639:3732550:3733283:3734119,KEEP_SNAPSHOT=1 analyze.slurm   # job 3734187
```
Results: `results/prop1_200us/` (shock speed, fields over the whole channel, maxp zoom and spectra, `prop_summary.json`).

### Software and numerics: PASSED
- 0 FATAL / FPE / NaN in all four logs. Courant number about 0.1, max 0.39 over the whole run.
- About 150 k cells throughout (level 0/1/2 = 117 828 / 775 / 31 652 at 200 µs).
- At 200 µs: p 6.67–240 kPa, T 298–2941 K. The front is at x = 375.7 mm, still 124 mm from the outlet.

### Physics: speed matches CJ; cellular pattern still evolving
| Measure | Speed | vs D_CJ = 1616 m/s |
|---|---|---|
| Line fit, 25 → 200 µs | **1615 m/s** | **−0.03 %** |
| Line fit, last 100 µs | 1622 m/s | +0.4 % |
| Whole run, 54.75 → 375.69 mm | 1605 m/s | −0.7 % (includes start-up) |
| 2 µs windows after 25 µs | 1406–1726 m/s (std 54) | oscillates around CJ |

- **Speed:** the −1.6 % found at 66 µs was the start-up. Over the longer record the mean speed equals D_CJ. After about 60 µs the oscillations are smaller (about 1540–1725 m/s).
- **Cells (`maxp`):** triple-point tracks are visible over the whole 80–370 mm region. Downstream of about 150 mm, the pattern changes from the regular start-up cells (2 across, 30 mm) to **larger, less regular diamonds**. The collision points along the channel centre are about 80–90 mm apart (x ≈ 183, 270, 343 mm).
- **Spectra (80–370 mm):** across the channel, 30 mm (relative power 1.0) and 60 mm (0.81); along the channel, peak at 48 mm. The 60 mm and 48 mm contributions come from the later, larger cells.
- **Reading:** the imposed 30 mm cells did not persist unchanged. The structure is moving towards fewer, larger cells, possibly one cell across the 60 mm channel. That supports caveat 1 above: the 30 mm at 66 µs was at least partly imposed by the initial sinusoid. **The natural cell width is not settled.** It would need a longer domain, a different initial perturbation, and/or higher resolution. The literature value (caveat 2) still has to be checked.

## Continuation to 475 mm: job 3738975 (2026-11-19, submitted by the user), run `prop1`
- **Result:** restarted from 200 µs and stopped by `SW_position_limit 0.475` at t = 260.67 µs, `last Leading shock location = 0.4750625 m`. 9795 steps in 4910 s (about 2.8 SU). `FATAL/FPE/NaN lines: 0`. min/max(T) = 298 / 2961 K. Last save: 260 µs.
- **Expected end-of-run messages:** `solver exit code 255` and `BAD TERMINATION … KILLED BY SIGNAL: 9`. The solver calls `exit()` without shutting MPI down, so MPI kills the other ranks. This is not a crash; the shock-position line above shows it reached the limit.
- **Not cancelled.** This is the first job the user submitted by hand. It is one data point for the cancellation question (problem 5), not proof.
- **Analysis, job 3740049** (`05_runs/results/prop1_260us/`):
  - D = 1621 m/s, fit 25–260 µs (+0.34 % vs CJ)
  - D = 1636 m/s over the last 100 µs (+1.26 %)
  - 150 174 cells
  - The 260 µs snapshot is in `$WORK/ozone_detonation/runs/prop1/snapshot_0.00026` (3360 files, 157 MB).

## Window recycling past 0.5 m ("option B", prepared 2026-11-19; "cut and append" version 2026-11-20)
The goal is to run far enough for the cellular structure to settle, an estimated 0.5–1.0 m more. The channel stays 0.5 m long. Each **cycle** runs until the front reaches 0.475 m. Then `recycle.slurm` shifts the solution 0.30 m to the left and starts the next cycle.

| Script | What it does | Cost |
|---|---|---|
| `recycle.slurm` | **`MODE=cut` (default since 2026-11-20):** reconstructs the latest save of `SRC_RUN` (with its refinement data), keeps the refined cells at x ≥ `SHIFT` exactly, shifts them left, drops the rest and appends fresh 0.5 mm cells (`recycle_fields.py cut`), then checks, `checkMesh` and `decomposePar`. See "Cut and append" below.<br>**`MODE=average`** (the first version, job 3740666): 1. reconstructs the latest save; 2. copies and shifts it (`shift`); 3. creates `NEW_RUN` on the 120 000-cell base mesh with fresh gas (the fresh-gas state is read from the cells ahead of the front and checked to be uniform); 4. averages the shifted cells onto the base cells (`map`); 5. checks, `decomposePar`, `.decomposed_ok`. | 1 node, ≤ 30 min, ≤ 0.5 SU |
| `cycle_run.slurm` | `smoke.slurm` with `SW_LIMIT=0.475`, `WRITE_INT=1e-6`. It refuses a folder without `.decomposed_ok`, because `smoke.slurm` would otherwise restart it from the ZND state at t = 0. Resubmit the same command until the cycle reaches 0.475 m. | 2 nodes, 2 h, ≤ 4 SU per job; about 4.5 h (≈ 9 SU) per cycle |
| `recycle_fields.py` | Plain-Python helper: `shift`, `ambient`, `target`, `map`, `cut`, `check` | — |

**Chain:** `prop1` (to 0.475 m) → recycle → `prop1_cycle1` → recycle → `prop1_cycle2` → …
- **Naming:** `cycleN` means the N-th 0.30 m window of option B. It is not option C1 or C2 (a longer domain), which was not chosen.
- **Lab position = domain position + OFFSET.** OFFSET is 0.30 m after the first shift and adds 0.30 m each cycle. It is stored in `<run>/recycle_info.txt`.
- **Soot foil:** `maxp` is copied with the shift, so the kept 0.20 m carries its record into the next cycle. The full foil is the cycles placed at their offsets.

**What a recycle does to the solution** (recorded as change #13 in `03_case/CHANGES.md`):
- **The front is put onto the coarse grid.** Since job 3740579 this is done by `recycle_fields.py map`, not OpenFOAM's `mapFields`.
  - After a shift of exactly 600 base cells, every 0.5 mm base cell holds exactly 1, 4 or 16 shifted cells (AMR level 0, 1 or 2).
  - The script reads every cell's rectangle from the mesh files and averages p, T, U and the mass fractions over the cells inside each base cell, weighted by area. The averages are exact and the mass fractions still sum to 1. `maxp` takes the **maximum** instead, so the soot-foil tracks are not faded.
  - A shift that is not a whole number of base cells is rejected.
- **The fine detail is lost.** The 0.125 mm level-2 detail at the front is reduced to 0.5 mm for the first steps, until the adaptive mesh refinement (AMR) rebuilds the fine cells. Triple points and transverse waves are weakened.
- **The burned gas is cut.** Only about 0.175 m of burned gas is kept behind the front. The left boundary is `zeroGradient`, as before.
- **Recovery is not yet known.** In cycle 1, compare the collision spacing and the maxp peaks before the recycle (prop1, 400–475 mm) with those after it.
- **Cells not covered by the shifted solution keep the fresh gas.** `check` verifies that every cell beyond 0.5 − SHIFT is still fresh gas. It reads cell positions from the mesh rather than assuming a cell order.
- **`rho` is not mapped.** The solver computes it from the thermodynamic state (`IOobject::NO_READ`), and `rhoU`/`rhoE` likewise.

**Checks in `recycle_fields.py check`** (any failure stops the job before `.decomposed_ok`):
- all values are finite
- the mass fractions sum to 1 within 1e-6, and none are negative
- the cells beyond 0.5 − SHIFT are unchanged fresh gas
- the leading shock (the solver's own test, p > 101 425 Pa) is between 0.5 − SHIFT − 0.05 m and 0.5 − SHIFT, e.g. 0.15–0.20 m

A local test on small synthetic files (2026-11-19) passed. It also caught a wrong front position and a corrupted fresh-gas cell, both inserted on purpose.

### First recycle attempt: job 3740454 (2026-11-19, submitted by the user): FAILED at a safety check, nothing created; fixed
`SRC_RUN=prop1`, `NEW_RUN=prop1_cycle1`, `skx-dev`, 1 node. It ended `FAILED` after 4 min 37 s (about 0.08 SU).

**Steps that worked:**
- **[1] reconstruct:** the 260 µs save was joined into one mesh, `nCells:150174`. That matches the 150 174 cells in the analysis.
- **[2] shift:** `shifted 303472 points by -0.3 m in x: x now -0.300000 .. 0.200000 m`. This is the expected range: the old 0–0.5 m became −0.3–0.2 m.

**Where it stopped:**
- The check that reads the fresh-gas state stopped the job:
  ```
  ERROR: fresh gas is not uniform in p: 6670.48609244 vs 6670.00000052
  ```
- **Cause: the script's test, not the simulation.** It counted any cell within 0.5 Pa of the lowest pressure as "fresh gas". That band also caught at least one cell at 6670.49 Pa. That cell's pressure is 7×10⁻⁵ above ambient, most likely right at the foot of the smeared numerical shock. The lowest pressure itself is 6670.00000052 Pa, not exactly 6670, which suggests round-off-level differences in the fresh gas.
- The check was meant to stop the job when the fresh gas is unclear. It did that, but its selection band was too wide.

**State afterwards:**
- `prop1` is unchanged, apart from the reconstructed 260 µs files (it had these already).
- No `prop1_cycle1` folder was created. The failure came before step [3], so nothing can be run by mistake.
- The temporary `prop1_cycle1_mapsource` is left over. A rerun deletes it first.

**Fix (2026-11-19), in `recycle_fields.py ambient`:**
- **Narrower selection:** fresh-gas cells are those within 10⁻³ Pa and 10⁻³ K of the minimum, instead of 0.5. Cells up to 100 Pa above are counted as "shock foot" and reported.
- **Tolerance:** uniformity is required to 10⁻⁶ relative, instead of 10⁻⁹. The fresh-gas value is the average of the selected cells.
- **Rounding:** the average is rounded to 12 significant digits, the OpenFOAM `writePrecision`. Without this, the "cells beyond the copied region are unchanged" check would fail after the values are written and read back. That check now also uses a 10⁻⁹ relative tolerance.
- **Logging:** the job log lists every fresh-gas value with its spread.
- **Local test:** synthetic data reproduced this failure (one cell at 6670.486 Pa, the others 6670.0000003–6670.0000005 Pa). It now passes, with 1 cell left out as shock foot.
- **Next:** rsync, then resubmit the same command.

### Second recycle attempt: job 3740503 (2026-11-19): FAILED at the same check, on U; fixed
- It ran for 39 s. Steps [1] and [2] were as before.
- **The new selection works:** `fresh-gas cells: 14196 … left out as shock foot (up to 100 Pa above): 1469`, and p = 6670.00001 Pa (spread 9.95e-04 Pa), T = 298.0000002 K (spread 1.6e-05 K).
- **It then stopped at U:**
  ```
  ERROR: fresh gas is not uniform in U: values -3.13274157528e-11 .. 3.3488050206e-05
  ```
- **Cause:** the fresh gas carries acoustic noise at round-off level. The size fits: a pressure ripple of 10⁻³ Pa gives u = p′/(ρc) ≈ 10⁻³ / (0.08 × 330) ≈ 4×10⁻⁵ m/s. The test allowed only 10⁻⁶ relative to max(1, |U|), and U is zero, so it allowed 10⁻⁶ m/s.
- **Fix:** each quantity now has an allowed spread on its own physical scale:

  | Quantity | Allowed spread |
  |---|---|
  | p | 10⁻⁶ × p (0.0067 Pa) |
  | T | 10⁻⁶ × T (0.0003 K) |
  | U | 10⁻³ m/s (3×10⁻⁶ of the sound speed) |
  | maxp | 10⁻⁴ × p (0.67 Pa; only used for the soot foil) |
  | mass fractions | 10⁻⁶ |

- **Logging:** every quantity is printed with its spread, its allowed spread and ok / TOO LARGE, and all failures are listed at once.
- **Local test:** this job's U noise now passes, and a real H2 difference of 10⁻³ still fails.
- **About the averaged U:** the fresh gas written ahead of the front is the average, about 10⁻⁵ m/s. That is the same noise level, not a flow.

### Third recycle attempt: job 3740579 (2026-11-19): fresh-gas check passed; OpenFOAM `mapFields` far too slow; replaced
- **Steps [1]–[3] worked.** All 13 fresh-gas quantities were "ok". The mass fractions are H2 0.01277, O2 0.1014, AR 0.8859, which is exactly 2H₂ + O₂ + 7Ar.
- **Step [4] stalled.** `mapFields` printed `Source mesh size: 150174  Target mesh size: 120000` at 16:11:55 and then searched cells at 100 % CPU (266 MB) for over 15 min. The job's 30 min limit stopped it.
- **Likely cause:** `meshToMesh0` falls back to a slow whole-mesh search whenever its quick containment test fails at the nearest cell. That fallback is triggered for "boundary" cells, and in a 2D mesh every cell touches the empty front/back patch. Also, after the shift the base-cell centres sit exactly on corners of the level-2 cells, where the quick test is unreliable.
- **Replacement:** `recycle_fields.py map`, described above.
- **Local test:** a synthetic mesh with levels 0, 1 and 2 and the same file formats, including a 5-point face with a hanging node.
  - Linear p, T, U fields were averaged exactly: the largest error was 3×10⁻¹¹.
  - maxp equalled the maximum of the sub-cells.
  - A 0.31 m shift was rejected.

### Fourth recycle attempt: job 3740666 (2026-11-19): SUCCEEDED, `prop1_cycle1` ready
It took 1 min 24 s (about 0.02 SU). The fresh-gas values match job 3740579.

**Step [4], map:**
```
source cells: 150174 (72000 shifted out of the domain); base cells filled: 48000 of 120000;
source cells per base cell: {1: 45840, 4: 124, 7: 3, 10: 113, 13: 11, 16: 1909}
```
- **72 000 cells shifted out** = 600 columns × 120 rows, the old 0–0.3 m. All were unrefined.
- **48 000 cells filled** = 400 × 120, the new 0–0.2 m.
- **The counts add up:** 72 000 + 45 840 + 4·124 + 7·3 + 10·113 + 13·11 + 16·1909 = 150 174, every source cell.
- **7, 10 and 13** are base cells refined in part: for example, 13 = one level-1 cell plus 12 level-2 cells. The coverage check confirms they are completely filled.

**Checks:**
- **Mass fractions:** max |ΣY − 1| = 6.3e-13.
- **Cells beyond 0.2 m:** 72 000, all unchanged fresh gas.
- **Leading shock:** x = 0.17375 m in the domain = **0.47375 m lab**. That is consistent with the 260 µs save: 0.4751 m at 260.67 µs minus about 1 mm. The 0.5 mm base cell puts the centre at …375.
- **Burned gas kept:** 0.174 m behind the front. All 29 640 cells more than 50 mm behind the front are burned (hotter than fresh gas + 100 K).
- **Peak values:** max p = 224 kPa (229 kPa before; averaging lowers the peak), max T = 2961 K, max maxp = 295 kPa, min T = 298 K.

**Step [5], decompose:** simple (16 6 1) = 96 pieces, at most 1260 cells each (0.8 % above the average of 1250). Each processor folder holds the 13 fields at 0.00026.

**Folder:** `.decomposed_ok` was written, the temporary `prop1_cycle1_mapsource` was removed, and `recycle_info.txt` (OFFSET = 0.3) and `log.decomposePar` were copied to `$WORK/ozone_detonation/runs/prop1_cycle1/`.

**Not yet known:** whether the solver runs cleanly from this state, and how fast the front recovers. That is the first `cycle_run.slurm` job.

**Superseded (2026-11-20):** the user chose "cut and append" (below), which keeps the front unaveraged. This averaged folder was not run. Rename it to `prop1_cycle1_avg` before making the new `prop1_cycle1`; it can serve as a comparison.

### Cut and append (`MODE=cut`, written 2026-11-20, not yet run on Stampede3)
**Idea (the user's):** as the front moves right, the cells far behind it have coarsened back to 0.5 mm. So instead of averaging the whole solution onto a new mesh, keep the solver's own mesh and values from x = SHIFT onward unchanged, drop the burned gas at x < SHIFT, and add SHIFT m of fresh 0.5 mm cells ahead of the front.

**What was checked before writing it** (read-only, on Stampede3):
- The solver's refinement code (`dynamicMesh2D/.../hexRef82D.C`) reads `cellLevel`, `pointLevel` and `refinementHistory` from the mesh folder at start-up. It stops with a fatal error if their sizes do not match the mesh, and it checks the refinement levels and the mesh for consistency. If `cellLevel` were lost, the 0.125 mm cells would count as base cells and be refined twice more, to 0.03 mm.
- OpenFOAM 8's `reconstructPar` and `decomposePar` carry all three files (`hexRef8Data`). The 260 µs reconstruction of `prop1` has them: `0.00026/polyMesh/{cellLevel,pointLevel,refinementHistory}`, 150 174 cells, 42 392 split-cell entries.
- So only the cut itself needs new code. Reconstructing and decomposing are standard steps.

**`recycle_fields.py cut`:**
- Works on the reconstructed source mesh (`polyMesh` files), which it only reads.
- Keeps every cell with x ≥ SHIFT, with its values, `cellLevel`, the `pointLevel` of its points and its refinement tree. Each tree lies inside one base cell, so a tree is kept or dropped whole. The trees are renumbered.
- Faces between kept and dropped cells become the new `inlet` patch, turned to point outward where needed.
- The old outlet column becomes the joint to SHIFT/0.5 mm × 120 new base cells (level 0, no refinement history), filled with the fresh-gas state from `ambient`/`target`. It requires the outlet column to be plain base cells; refinement reaching the outlet stops the job.
- Writes the new mesh to `NEW_RUN/constant/polyMesh` and the fields to `NEW_RUN/<time>`. Internal faces are put in the order OpenFOAM requires.
- **Self-check from the written files:**
  - every kept cell is exactly its source cell shifted by −SHIFT
  - every new cell is the expected 0.5 mm square
  - total area = 0.5 × 0.06 m²
  - no face normal points into its owner cell
  - the kept p values are identical to the source

**Then in `recycle.slurm`:**
- `check`, as in the averaging version.
- OpenFOAM `checkMesh`. If it does not print `Mesh OK`, the source mesh is checked too, and the job only continues if the new mesh has no more failed checks than the source.
- `decomposePar`, and a check that each processor received the refinement data.
- **For inspection:**
  - The log prints a table of sample cells (leading shock cell, highest p, a level-2 cell, the cells at the cut and the joint, the first new cell): source position → new position, with p and T.
  - The job writes a VTK of the new start: `$WORK/ozone_detonation/runs/<NEW_RUN>/<NEW_RUN>_start_vtk_<time>.tar.gz`. Moved +SHIFT in ParaView, it must match the source save cell for cell.

**Local test (2026-11-20, synthetic files):**
- **The mesh:** 20 × 4 base cells, with refined cells (levels 1 and 2, hanging nodes) in the dropped region, at the cut line and in the kept region.
- **Result:** all checks passed.
  - Kept: 44 cells (levels 0/1/2: 29/11/4). 51 dropped, 4 of them refined.
  - 5 inlet faces at the cut (one cut base cell is refined).
  - 19 of 24 split-cell entries kept.
  - No misplaced cells and no inward faces.
- **It correctly refused:** refinement at the outlet, and a shift that is not a whole number of base cells.
- **Not tested locally:** OpenFOAM itself (`checkMesh`, `decomposePar`, and the solver's own refinement checks). That happens in the recycle job and in the first cycle job.

**What it changes in the physics:** only the burned gas more than about 0.175 m behind the front is dropped, as in the averaging version. The front, its fine cells and `maxp` are not altered.

**First use** (the user submits):
1. Rename the averaged folder.
2. Make `prop1_cycle1` with `MODE=cut`.
3. Run a **30-min** cycle test: `sbatch -t 00:30:00 …`, ≤ 1 SU.
   - **Pass:** the solver starts without a refinement error, the cell count stays near 150 k with no jump from over-refinement, and cells behind the front coarsen normally.
4. Then the full cycle.

## Continuation to 475 mm: how it was prepared
`prop1_to_475mm.slurm` continues `prop1` from 200 µs (shock at 375.7 mm) until the leading shock reaches x = 0.475 m. It sets `RUN_NAME=prop1`, `WRITE_INT=1e-6`, `END_TIME=3e-4` (backstop) and `SW_LIMIT=0.475`, then runs `smoke.slurm`.
- **`SW_LIMIT` is new in `smoke.slurm`.** It sets `SW_position_limit` in the run copy of `constant/solverTypeProperties`. This is detonationFoam's own stop criterion: in `detonationFoam_V2.0.C`, `if (SW_position >= SW_position_limit) exit(EXIT_SUCCESS);`. It only ends the run and doesn't change the equations; the repository case keeps 1.0. The solver exits without a final save, so the last save is the previous 1 µs one.
- **Restore before running.** If the run folder has no `.decomposed_ok` (purged `$SCRATCH`), the wrapper first restores `$WORK/ozone_detonation/runs/prop1/snapshot_0.0002`. Without that, `smoke.slurm` would restart from t = 0.
- **The user submits it.** This tests whether the cancellations are related to jobs being submitted through the AI tool. See `docs/GUIDE.md` part 9.
- **Estimate:** about 62 µs of simulated time, about 90 min on 2 nodes, at most 4 SU (one 2 h `skx-dev` job).

### Analysis scripts
- `paraview_maxp.py` (Mac): ParaView startup script showing `maxp` from a `to_vtk.slurm` file. `VTK_FILE=<file.vtk> /Applications/ParaView-6.2.1.app/Contents/MacOS/paraview --script=05_runs/paraview_maxp.py`. `open -a ParaView file.vtk` doesn't load the file in ParaView 6.2.1.
- `to_vtk.slurm` (1 node, ≤ 20 min, about 0.1 SU): one saved time as VTK for ParaView. `reconstructPar` of all solution fields, then `foamToVTK`, then `$WORK/ozone_detonation/runs/<run>/<run>_vtk_<time>.tar.gz`. `sbatch --export=ALL,RUN_NAME=prop1[,TIME=0.0001] to_vtk.slurm`. The first try (job 3734272) failed because `foamToVTK` reads every file header in the time folder, including the OpenFOAM 12 `Ccx`/`Ccy` (`keyword version is undefined`). The script now moves them aside while it runs (job 3734275: 200 µs, 54 MB, 19 MB packed). Download to the Mac with `ssh stampede3 'cat $WORK/ozone_detonation/runs/prop1/prop1_vtk_0.0002.tar.gz' > local_data/prop1_vtk_0.0002.tar.gz` (`local_data/` is not in git).
- `analyze.slurm` (1 node, ≤ 20 min, about 0.05 SU): `reconstructParMesh` (needed because AMR changed the mesh; the first try, job 3732270, failed in `reconstructPar` with `cannot find file ".../pointProcAddressing"`), then `reconstructPar` of maxp/p/T/cellLevel, then OpenFOAM 12 cell centres, then `analyze_prop.py`.
- `analyze_prop.py`: shock x(t) and D(t) from the solver log; maxp/p/T maps on a 0.125 mm grid; spectra of log(maxp) for the cell size; `prop_summary.json`.

## Problems found and fixed
1. **`decomposePar` stopped on `0/Cy`** (job 3730993): `FOAM FATAL IO ERROR: keyword version is undefined in dictionary ".../0/Cy"`. The file was written by OpenFOAM 12, whose header omits `version`. **Fix:** the run copy deletes `0/Cx` and `0/Cy`, which the solver never reads.
2. **A failed setup left empty `processor*` folders,** which the first version of the script would have taken for a restart. **Fix:** restart only when the `.decomposed_ok` marker exists, otherwise rebuild the run directory.
3. **Summary false alarms:** the FPE banner `sigFpe : Enabling floating point exception trapping` was counted as an error, and every per-processor line of `decomposePar` was printed. **Fix:** tighter greps, plus a count of MPI kill signals (15 = our guard).

4. **The smoke test ran with `maxRefinement 3`** (80 272 level-3 cells at 1.5 µs) although the user had chosen 2. **Cause:** the script copied all dictionaries from `init_case`, which was built (2026-11-16 14:27 CST) before the AMR change was committed (14:37 CST). **Fix:** new runs take `constant/` and `system/` from the repo case and only `0/` and the mesh from `init_case`. The job output now prints `maxRefinement`, `solverType`, `adjustTimeStep` and `maxCo`. The smoke run directory is therefore not continued.
5. **Jobs `CANCELLED by 0` at 2:01–2:02 after starting, with no output file and no recorded reason.** Unresolved; looks like a system-side problem. Facts (2026-11-17, all `skx-dev`, 2 nodes):

   | Job | Wall limit | Nodes | Submitted from | Result |
   |---|---|---|---|---|
   | 3730997, 3731474 | 30 min | various | `$HOME` | ran |
   | 3731627 | 2 h | c454-[002-003] | `$HOME` | cancelled at 2:01 |
   | 3731639 | 2 h | c454-[002-003] | `$HOME` | ran 1:56 |
   | 3732530 | 2 h | c454-[003,012] | `$HOME` | cancelled at 2:02 |
   | 3732539 | 2 h | c454-002, c455-014 | `$HOME` | cancelled at 2:01 |
   | 3732550 | 2 h | c454-[003,081] | `$SCRATCH` | ran 1:56 |
   | 3732551 | 2 h | c454-[021,032] | `$SCRATCH` | cancelled at 2:02 |
   | 3732983 | 2 h | c454-021, c455-014 | `$SCRATCH` | cancelled at 2:02 |
   | 3733283 | 1 h | c455-[042-043] | `$SCRATCH` | ran 0:56 (145 → 185 µs) |
   | 3733284 | 1 h | c454-101, c455-013 | `$SCRATCH` | cancelled at 2:02 |
   | 3734119 | 30 min | (2 nodes) | `$SCRATCH` | ran 0:22 (185 → 200 µs) |
   | 3734177 | 20 min, **1 node** (analysis) | (1 node) | `$SCRATCH` | cancelled at 2:02 |
   | 3734187 | 20 min, 1 node (analysis) | (1 node) | `$SCRATCH` | ran |

   - **Not a node problem:** the same nodes both ran and failed jobs.
   - **Not `$HOME`:** an earlier guess, disproved by 3732551 and 3732983.
   - **Not the 2 h limit, not the size:** 3733284 (1 h) and the 1-node 20-min analysis job 3734177 were cancelled too. 7 cancellations on 2026-11-17/18 in total; none of the 30-min solver jobs so far.
   - The batch step starts, yet the Slurm output file is never created, and `sacct` shows no reason or comment.
   - Each failure costs about 0.07 SU. Downstream `afterok` jobs then never start and must be cancelled.
   - **Next:** report to TACC (draft below). Meanwhile, a cancelled job is simply resubmitted; nothing on disk changes, because the script never starts.

   <details><summary>TACC ticket draft</summary>

   > Subject: Stampede3 skx-dev jobs cancelled by uid 0 about 2 minutes after start, no output file
   >
   > On Stampede3, several of my `skx-dev` jobs (allocation TG-MCH260175) were cancelled by uid 0 at 2:01–2:02 after they started. The batch script never ran: the Slurm output file (`-o`) is never created, and `sacct` shows `CANCELLED by 0` with no reason or comment.
   >
   > Cancelled jobs (2026-11-17/18):
   > - 3731627, 3732530, 3732539, 3732551, 3732983: 2 nodes, 2 h limit
   > - 3733284: 2 nodes, 1 h limit
   > - 3734177: 1 node, 20 min limit
   >
   > Identical resubmissions ran normally, sometimes on the same nodes: 3731639, 3732550, 3733283, 3734119 and 3734187.
   >
   > The cancelled jobs ran on various nodes, and I submitted them from both $HOME and $SCRATCH. Two of them (3732551 and 3733284) were waiting on another job (`-d afterok`). The others were submitted on their own.
   >
   > Is there a known launch or prolog problem, or a policy that would cancel these jobs? Is there anything I should change in how I submit them?
   >
   > Thank you.
   </details>

## Where things are
- Run: `$SCRATCH/ozone_detonation/smoke/` (342 MB; purged after 10 days)
- Logs and dictionaries: `$WORK/ozone_detonation/runs/<run>/`
- **Kept snapshot of `prop1` at 66.4 µs:** `$WORK/ozone_detonation/runs/prop1/snapshot_6.6e-05/` (94 MB). It holds `processor*/6.6e-05` (all fields, 96 pieces; 3360 files, checked equal to the source), `constant/`, `system/`, `.decomposed_ok`, the solver log, and the reconstructed `6.6e-05/` (maxp, p, T, cellLevel, cell centres). To restart from it: copy the folder to `$SCRATCH/ozone_detonation/prop1` and resubmit `smoke.slurm` with `RUN_NAME=prop1` and a later `END_TIME`.
- **Kept snapshot of `prop1` at 200 µs:** `$WORK/ozone_detonation/runs/prop1/snapshot_0.0002/` (95 MB; 3360 processor files, count checked equal to the source by `analyze.slurm` `KEEP_SNAPSHOT=1`). Same contents as above, plus all four solver logs. Analysis: `$WORK/ozone_detonation/runs/prop1/analysis_0.0002/`.
- Script output: `$SCRATCH/ozone_detonation/logs/<name>_<jobid>.log` (older jobs: `~/ozone_detonation/05_runs/`; not in git)
