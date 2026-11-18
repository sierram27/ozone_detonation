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

### Analysis scripts
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

   - **Not a node problem:** the same nodes both ran and failed jobs.
   - **Not `$HOME`:** an earlier guess, disproved by 3732551 and 3732983.
   - **Not the 2 h limit:** an earlier guess, disproved by 3733284 (1 h). So far 6 of the 9 two-node jobs with limits over 30 min failed. The 30-min jobs and the 1-node jobs never did, but the sample is small.
   - The batch step starts, yet the Slurm output file is never created, and `sacct` shows no reason or comment.
   - Each failure costs about 0.07 SU. Downstream `afterok` jobs then never start and must be cancelled.
   - **Next:** report to TACC (draft below). Retrying blindly just repeats it about 2 times in 3.

   <details><summary>TACC ticket draft</summary>

   > Subject: skx-dev jobs cancelled by root (uid 0) ~2 minutes after start, no output file
   >
   > Several of my 2-node skx-dev jobs (account TG-MCH260175) were cancelled by uid 0 exactly 2:01–2:02 after starting, before the batch script produced any output (the `-o` file is never created; `sacct` shows `CANCELLED by 0`, no reason/comment). Affected: 3731627, 3732530, 3732539, 3732551, 3732983, 3733284. Identical submissions on the same or similar nodes ran normally (3731639, 3732550, 3733283). Jobs were submitted from both $HOME and $SCRATCH, with 2:00:00 and 1:00:00 limits; my 30-minute and 1-node jobs have not been affected. Is there a known launch/prolog issue or a policy that cancels these jobs? Thank you.
   </details>

## Where things are
- Run: `$SCRATCH/ozone_detonation/smoke/` (342 MB; purged after 10 days)
- Logs and dictionaries: `$WORK/ozone_detonation/runs/<run>/`
- **Kept snapshot of `prop1` at 66.4 µs:** `$WORK/ozone_detonation/runs/prop1/snapshot_6.6e-05/` (94 MB). It holds `processor*/6.6e-05` (all fields, 96 pieces; 3360 files, checked equal to the source), `constant/`, `system/`, `.decomposed_ok`, the solver log, and the reconstructed `6.6e-05/` (maxp, p, T, cellLevel, cell centres). To restart from it: copy the folder to `$SCRATCH/ozone_detonation/prop1` and resubmit `smoke.slurm` with `RUN_NAME=prop1` and a later `END_TIME`.
- Script output: `$SCRATCH/ozone_detonation/logs/<name>_<jobid>.log` (older jobs: `~/ozone_detonation/05_runs/`; not in git)
