# ozone_detonation

**To run everything yourself, step by step, follow [`docs/GUIDE.md`](docs/GUIDE.md).**

This project runs 2D H2–O2–Ar detonation simulations with **detonationFoam v1.2 (OpenFOAM 8)** on **TACC Stampede3**. It is the baseline for a later study of how ozone affects detonation ([`docs/future_ozone.md`](docs/future_ozone.md)).

It reuses Dr. Ryan Johnson's Stanford-collaboration case `Wang/nn_chemistry/2D_Ar_H2_O2/ffcm2/coarse_mesh_slip` (FFCM2 chemistry) and his ZND initialization scripts (`Wang/nn_chemistry/ZND_Init/`). Changes are kept to what OpenFOAM 8 needs, plus the user decisions listed below.

## The case at a glance
| Item | Value |
|---|---|
| Mixture | 2H₂ + O₂ + 7Ar (X = 0.2 / 0.1 / 0.7), 6670 Pa, 298 K |
| Chemistry | FFCM2 H₂/Ar: 9 species, 27 reactions; DLBFoam load-balanced, seulex (absTol 1e-9, relTol 1e-6) |
| Equations | inviscid reactive Euler (`solverType Euler`), Kurganov flux |
| Domain | 0.5 × 0.06 m, 1000 × 120 base cells (0.5 mm); AMR up to 2 levels (0.125 mm) |
| Boundaries | left inlet / right outlet zeroGradient; top/bottom slip walls; 2D (`empty` front/back) |
| Time step | adaptive, Courant number 0.1, Δt ≤ 9 ns |
| Initial condition | 1D ZND profile behind a sinusoidal front x = 0.05 + 0.005 sin(4πy/0.06) m |

## Results so far
| Check | Result | Where |
|---|---|---|
| ZND / CJ (SDToolbox + Cantera) | D_CJ = 1616 m/s; vN spike 174.5 kPa, 1900 K; induction length 1.56 mm | `04_znd_init/` |
| Software: parallel run (96 ranks) | runs cleanly; FFCM2, DLB, AMR, Euler all active; no FATAL/FPE/NaN | `05_runs/` (jobs 3731474, 3731639) |
| **Physics: propagation, 260 µs (shock at 475 mm)** | **D = 1621 m/s (+0.34 % vs CJ)**, fit 25–260 µs (1636 m/s, +1.3 %, over the last 100 µs); oscillating as a cellular front | `05_runs/results/prop1_260us/` (200 µs: `prop1_200us/`) |
| Physics: cellular structure | triple-point tracks in `maxp`; 2 cells across (30 mm) after start-up, then larger, less regular cells (spectra: 30 and 60 mm) | same; 66 µs results in `results/prop1/` |

**Not yet validated:**
- **The natural cell width is not settled.** The early 30 mm cells equal the initial perturbation wavelength, and by 200 µs the pattern has moved towards larger cells. A longer domain, a different initial front, or higher resolution would settle it.
- **The literature comparison still has to be checked.** This mixture and channel match classic studies of 2H₂+O₂+7Ar at 6.67 kPa, which report about 2 cells across 6 cm.
- **Resolution is modest:** about 12 cells per induction length.

## Reproduce from scratch
Run each command on Stampede3 unless it says otherwise. **All computing goes in batch jobs** (TACC AI policy). Login nodes are for git, `sbatch` and reading logs only. Allocation `TG-MCH260175`; every job below is `skx-dev`.

**Submit every job from `$SCRATCH`, never from `$HOME`** (TACC guidance, `AGENTS.md` rule 14). The scripts live in `~/ozone_detonation`, but `sbatch` is run from `$SCRATCH/ozone_detonation/logs`, so the job's working directory and output file are in `$SCRATCH`.

```bash
# 0. Log in (your Mac). Password + Duo; the SSH config shares one connection.
stampede                      # alias -> ~/.ssh/scripts/stampede.exp, or: ssh stampede3

# 1. This repo in $HOME (the Slurm scripts expect ~/ozone_detonation)
git clone https://github.com/sierram27/ozone_detonation.git ~/ozone_detonation    # or rsync from your Mac

# 2. Sources (login node, download only)
mkdir -p $WORK/src && cd $WORK/src
git clone -b detonationFoam_V1.2_OF8 https://github.com/JieSun-pku/detonationFoam.git   # used: 04239c9
git clone https://github.com/drryjoh/stanford_collaboration.git                          # used: 8439738

# 3. Python environment for the ZND scripts (see 04_znd_init/README.md for why each pin)
module load python/3.12.11
python3 -m venv $WORK/venvs/znd && source $WORK/venvs/znd/bin/activate
pip install cantera==3.1.0 numpy scipy "pandas==2.2.3" matplotlib
mkdir -p $WORK/src/SDToolbox && cd $WORK/src/SDToolbox
curl -o SDToolbox.zip https://shepherd.caltech.edu/EDL/PublicResources/sdt/SDToolbox.zip && unzip SDToolbox.zip && rm SDToolbox.zip
echo $WORK/src/SDToolbox/SDToolbox/Python3 > $(python -c "import site;print(site.getsitepackages()[0])")/sdtoolbox.pth

# All jobs: submit from here; Slurm output files <name>_<jobid>.log land here too
mkdir -p $SCRATCH/ozone_detonation/logs && cd $SCRATCH/ozone_detonation/logs
R=~/ozone_detonation

# 4. Build detonationFoam v1.2 (1 node, ≈10 min). Log ends "BUILD STATUS: SUCCESS"
sbatch $R/02_build/build.slurm

# 5. (optional) case check: mesh + 20 serial steps (1 core, ≈10 min)
sbatch $R/03_case/check_case.slurm

# 6. ZND initial condition -> $SCRATCH/ozone_detonation/init_case (1 node, ≈7 min). Log ends with 15/15 PASS
sbatch $R/04_znd_init/init.slurm

# 7. Smoke test: 2 nodes / 96 ranks, to 2 µs (≈4 min, ≈0.15 SU)
sbatch --export=ALL,RUN_NAME=smoke2 $R/05_runs/smoke.slurm

# 8. Propagation run: 2 nodes, 2 h (≈4 SU) -> about 66 µs
sbatch -t 02:00:00 -J det_prop1 --export=ALL,RUN_NAME=prop1,END_TIME=1e-4,WRITE_INT=1e-6 $R/05_runs/smoke.slurm
#    continue it later: resubmit with the same RUN_NAME and a later END_TIME (200 µs was reached with 4 jobs). Chain several 2 h jobs:
#    j1=$(sbatch --parsable ... | tail -1); sbatch -d afterok:$j1 ...   (tail -1: TACC prints a banner)

# 9. Analysis: shock speed, maxp cells, plots (1 node, ≈3 min)
sbatch --export=ALL,RUN_NAME=prop1,LOGJOB=<solver job ids, colon-separated>,KEEP_SNAPSHOT=1 $R/05_runs/analyze.slurm
```
Monitor with `squeue -u $USER`. Read progress with `tail -f $SCRATCH/ozone_detonation/logs/<name>_<jobid>.log` and `tail -f $SCRATCH/ozone_detonation/<run>/log.detonationFoam.<jobid>`. **Ask for approval before any job with more than 2 nodes or longer than 30 min** (see `AGENTS.md`).

**Software used:** OpenFOAM 8 (TACC module `openfoam/8`, with `intel/23.1` + `impi/21.9`, loaded by `01_environment/env.sh`). OpenFOAM 12 (TACC module) is used only to write cell centres. Python 3.12.11, Cantera 3.1.0, pandas 2.2.3, numpy 2.5.5, scipy 1.18.1.

**Storage:** sources, build and venv in `$WORK`; runs in `$SCRATCH` (**purged after 10 days**); logs and analysis copied to `$WORK/ozone_detonation/`.

## Decisions that differ from the Stanford case
Every edit is listed with before/after in [`03_case/CHANGES.md`](03_case/CHANGES.md). Format-only fixes for OpenFOAM 8 / v1.2 are #1–#8. User decisions:

| # | Decision | Date |
|---|---|---|
| 9 | Inviscid: `solverType Euler` (Stanford: viscous NS-Sutherland) | 2026-11-16 |
| 10 | AMR max level 2 (Stanford: 3) | 2026-11-16 |
| 11 | Adaptive time step, Courant number 0.1 (Stanford: fixed Δt = 1 ns) | 2026-11-17 |
| 12 | `maxDeltaT 9e-9` to limit Courant overshoot after AMR updates | 2026-11-17 |

Kept unchanged: mesh, mixture, FFCM2 data, boundary conditions, schemes, chemistry solver tolerances, the ZND scripts.

## Troubleshooting (problems met and how they were fixed)
| Symptom | Cause | Fix | Details |
|---|---|---|---|
| `ambiguous conversion … tmp<GeometricField>` in 12 lines | TACC's `icpx` compiler is stricter | syntax-only patch `T x(expr);` | `02_build/` |
| `./Allwmake: Permission denied` | stored without the execute bit | `sh ./Allwmake` | `02_build/` |
| `Unknown reaction type reversiblethirdBodyArrheniusReaction` | OF8 spells it `ThirdBody` | capital T (4 places) | `03_case/CHANGES.md` #6 |
| Every function object crashes (`OSHA1stream`) | TACC's OF8 build | use TACC's OF12 `foamPostProcess` for cell centres; **no function objects in runs** | `04_znd_init/` |
| pandas `delim_whitespace` error | removed in pandas 3 | pin pandas 2.2.3 | `04_znd_init/` |
| `module load X \| tail` does nothing | pipe = subshell | never pipe `module load` | `04_znd_init/` |
| `decomposePar`: `keyword version is undefined … 0/Cy` | OF12 header in Cx/Cy | run copy deletes `0/Cx`, `0/Cy` | `05_runs/` |
| Run used AMR level 3 | dictionaries copied from an old `init_case` | runs take `constant/`, `system/` from the repo | `05_runs/` |
| One step at Co = 0.87 | solver picks Δt before AMR refines | `maxDeltaT 9e-9` (now max 0.39) | `05_runs/` |
| `reconstructPar`: `cannot find … pointProcAddressing` | AMR changed the mesh | `reconstructParMesh` first | `05_runs/analyze.slurm` |
| MPI `BAD TERMINATION … SIGNAL 15` at the end of a run | our time guard stopping the solver | expected. Any other signal is a crash | `05_runs/` |
| Job `CANCELLED by 0` at 2:01–2:02 after start, no output file, no reason recorded (7 jobs on 2026-11-17/18) | **unknown, system side.** Not node-specific, not `$HOME`, not the wall limit or job size (also a 1-node 20-min job) | resubmit (nothing on disk changes); ticket draft for TACC in `05_runs/README.md` | `05_runs/` |

## Where things are
| Directory | What it holds |
|---|---|
| `01_environment/` | Connecting to Stampede3, TACC policies, modules, `env.sh` |
| `02_build/` | Building detonationFoam v1.2 against TACC's OpenFOAM 8; compiler patch |
| `03_case/` | The migrated case `coarse_mesh_slip_of8/` and `CHANGES.md` |
| `04_znd_init/` | ZND initialization: background, workflow, checks |
| `05_runs/` | Run, restart and analysis scripts; smoke and propagation results |
| `docs/` | `GUIDE.md` (step-by-step guide to the whole workflow); future work: ozone |

`AGENTS.md` holds the working rules for AI agents on this project.

## Progress log
| Step | Status | Notes |
|---|---|---|
| 0. Repo setup | done | Rules (`AGENTS.md`), README skeleton |
| 1. Environment | done | TACC's `openfoam/8` module (intel/23.1 + impi/21.9) through `01_environment/env.sh`; all compute in batch jobs |
| 2. Build detonationFoam v1.2 | done | `detonationFoam_V2.0` + 4 libraries (job 3727370); 12-line syntax patch for `icpx` |
| 3. Migrate Stanford case | done | 8 format-only edits + user decisions #9–#12; OF8 reads it, 20 steps with FFCM2 (job 3727443) |
| 4. ZND initialization | done | Stanford scripts unmodified (job 3727629); D_CJ = 1616 m/s; 15/15 checks pass |
| 5. Slurm workflow | done | `05_runs/smoke.slurm`: setup → decompose → `ibrun` with time guard → summary → restart; `analyze.slurm` |
| 6. Smoke + propagation | software done; physics partly | Smoke 3731474 (AMR 2, Co 0.1): clean. Propagation `prop1` to 200 µs (4 jobs): D = 1615 m/s (−0.03 %), cellular tracks. Cell width not settled |
| 7. Reproducible README | done | This file + `docs/future_ozone.md` |
| 8. User guide; continue `prop1` to 475 mm | done | `docs/GUIDE.md`. Job 3738975 (submitted by the user, not cancelled) stopped at 0.4751 m, t = 260.7 µs; clean. Analysis 3740049 |
| 9. Window recycling past 0.5 m (option B, S = 0.30 m) | Averaging recycle done (job 3740666, after 3 failed attempts) but **not run**. Replaced by the user's **"cut and append"** (2026-11-20): the refined cells and their values are kept exactly, shifted, and fresh cells are appended. Cut checked on the laptop and in ParaView; `prop1_cycle1` made (job 3744345). Cycle test 3747361 crashed at 13.9 µs because the appended cells had a different point order than the solver's 2D refinement expects. **Fixed; retest 3749428 passed:** 19 µs, the front crossed the joint to 0.505 m lab at about 1650 m/s, no errors, 75 s/µs. **Cycle 1 can continue.** Also found: OpenFOAM 8 `decomposePar` drops 2D refinement history, which leaves about 30 000 extra fine cells per cycle (cost only) | Run folders `prop1_cycle1`, `prop1_cycle2`, … (one per 0.30 m cycle). `05_runs/recycle.slurm` + `cycle_run.slurm` + `recycle_fields.py`; change #13 in `03_case/CHANGES.md`; GUIDE part 9b. Goal: about 0.5–1 m more travel (2–4 cycles, ~9 SU each) |

**Compute used so far:** about 16 SU of TG-MCH260175 (including about 0.5 SU of system-cancelled jobs).
