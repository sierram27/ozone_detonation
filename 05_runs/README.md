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
| 1. setup / restart | **New run:** copy `$SCRATCH/ozone_detonation/init_case` into `$SCRATCH/ozone_detonation/<RUN_NAME>` and delete `0/Cx`, `0/Cy`. **Restart:** if the marker file `.decomposed_ok` exists, keep everything. | `Cx`/`Cy` are only inputs to the ZND scripts. They were written by OpenFOAM 12, and OpenFOAM 8 refuses them (see "Problems" below). |
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
| AMR works in parallel | `Selecting dynamicFvMesh dynamicRefineFvMesh2D`; cells grew from 120 000 to about 199 500 |
| Many steps | **1819 steps** (t = 1.819 µs at 1 ns each). Stopped by our time guard (exit 124) |
| No crash | 0 FATAL / floating-point exception / NaN lines. FPE trapping was on. The MPI "BAD TERMINATION" banners all say `KILLED BY SIGNAL: 15` (96 ranks), which is the TERM signal from our time guard, not a crash. |
| Output written | `processor*/0, 5e-07, 1e-06, 1.5e-06`, each with p, T, U, rho, 9 species, `maxp`, `cellLevel`, `Qdot` |
| Speed | about **0.82 s per step** with about 200 k cells on 96 cores (1483 s for 1819 steps) |

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
At about 0.82 s/step on 2 nodes, the original `endTime = 2e-4` (200 000 steps of 1 ns) would take about **46 h on 2 nodes, or about 90 SU**, and longer if AMR adds cells. Options to discuss before any long run:
- a shorter end time
- more nodes (needs approval; scaling not yet measured)
- `adjustTimeStep yes` with `maxCo 0.2`. The current 1 ns step is far below the stability limit, but changing it departs from Stanford's setup.

## Problems found and fixed
1. **`decomposePar` stopped on `0/Cy`** (job 3730993): `FOAM FATAL IO ERROR: keyword version is undefined in dictionary ".../0/Cy"`. The file was written by OpenFOAM 12, whose header omits `version`. **Fix:** the run copy deletes `0/Cx` and `0/Cy`, which the solver never reads.
2. **A failed setup left empty `processor*` folders,** which the first version of the script would have taken for a restart. **Fix:** restart only when the `.decomposed_ok` marker exists, otherwise rebuild the run directory.
3. **Summary false alarms:** the FPE banner `sigFpe : Enabling floating point exception trapping` was counted as an error, and every per-processor line of `decomposePar` was printed. **Fix:** tighter greps, plus a count of MPI kill signals (15 = our guard).

## Where things are
- Run: `$SCRATCH/ozone_detonation/smoke/` (342 MB; purged after 10 days)
- Logs and dictionaries: `$WORK/ozone_detonation/runs/smoke/`
- Script output: `~/ozone_detonation/05_runs/det_smoke_<jobid>.log` (not in git)
