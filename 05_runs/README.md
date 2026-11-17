# 05_runs: running the detonation in parallel

`smoke.slurm` runs the ZND-initialized case (Step 4) with `detonationFoam_V2.0` on many cores.
The same script does the smoke test and longer runs, and it can continue (restart) a run.

## How to use it
Run all of these on a Stampede3 login node from `~/ozone_detonation/05_runs`:
```bash
sbatch smoke.slurm                                        # smoke test: run "smoke", 2 nodes, until 2 us
sbatch --export=ALL,END_TIME=4e-6 smoke.slurm             # continue the same run to 4 us (restart)
sbatch --export=ALL,RUN_NAME=prop1,END_TIME=2e-5 -t 02:00:00 smoke.slurm   # new run, longer wall time
sbatch --export=ALL,RECONSTRUCT=1 smoke.slurm             # also merge the latest time into one case
squeue -u $USER                                           # is it queued / running?
tail -f det_smoke_<jobid>.log                             # the script's own progress
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

**Options (user decision pending):**
- `maxDeltaT` of about 9e-9 s, which keeps Δt at the level-2 value and would prevent the startup spike
- a lower `maxCo`
- a code change to measure Co after the AMR update (changes the solver; not preferred)

### Physics: NOT yet validated
- Max p is 432 kPa and max T is 2699 K at 2 µs.
- The solver prints `Leading shock location` every step (cells with p > 101 425 Pa; our vN spike is 174 kPa, so this works): **0.05475 m → 0.05819 m** over the 2 µs. That is about 1.7 km/s, but over only 3.4 mm (about 27 cells), during the start-up transient, so it is not a speed measurement.

### Cost outlook (from this test)
About 90 s per simulated µs on 2 nodes, so 2e-4 s (the original endTime) is about 5 h on 2 nodes, **about 10 SU**, if cell count and Δt stay similar.

## Problems found and fixed
1. **`decomposePar` stopped on `0/Cy`** (job 3730993): `FOAM FATAL IO ERROR: keyword version is undefined in dictionary ".../0/Cy"`. The file was written by OpenFOAM 12, whose header omits `version`. **Fix:** the run copy deletes `0/Cx` and `0/Cy`, which the solver never reads.
2. **A failed setup left empty `processor*` folders,** which the first version of the script would have taken for a restart. **Fix:** restart only when the `.decomposed_ok` marker exists, otherwise rebuild the run directory.
3. **Summary false alarms:** the FPE banner `sigFpe : Enabling floating point exception trapping` was counted as an error, and every per-processor line of `decomposePar` was printed. **Fix:** tighter greps, plus a count of MPI kill signals (15 = our guard).

4. **The smoke test ran with `maxRefinement 3`** (80 272 level-3 cells at 1.5 µs) although the user had chosen 2. **Cause:** the script copied all dictionaries from `init_case`, which was built (2026-11-16 14:27 CST) before the AMR change was committed (14:37 CST). **Fix:** new runs take `constant/` and `system/` from the repo case and only `0/` and the mesh from `init_case`. The job output now prints `maxRefinement`, `solverType`, `adjustTimeStep` and `maxCo`. The smoke run directory is therefore not continued.

## Where things are
- Run: `$SCRATCH/ozone_detonation/smoke/` (342 MB; purged after 10 days)
- Logs and dictionaries: `$WORK/ozone_detonation/runs/smoke/`
- Script output: `~/ozone_detonation/05_runs/det_smoke_<jobid>.log` (not in git)
