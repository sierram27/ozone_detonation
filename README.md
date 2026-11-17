# ozone_detonation

This project runs 2D H2–O2–Ar detonation simulations with **detonationFoam v1.2 (OpenFOAM 8)** on **TACC Stampede3**. The aim is to study later how ozone affects detonation.

The baseline reuses Dr. Ryan Johnson's Stanford-collaboration case `Wang/nn_chemistry/2D_Ar_H2_O2/ffcm2/coarse_mesh_slip` (FFCM2 chemistry) and his ZND initialization scripts (`Wang/nn_chemistry/ZND_Init/`).

## Where things are
| Directory | What it holds |
|---|---|
| `01_environment/` | Connecting to Stampede3, TACC policies, modules, directories |
| `02_build/` | Building detonationFoam v1.2 against TACC's OpenFOAM 8 |
| `03_case/` | The migrated Stanford case, plus `CHANGES.md` listing every edit |
| `04_znd_init/` | How the detonation is initialized from a 1D ZND solution |
| `05_runs/` | Slurm scripts, the smoke test, monitoring, restart |
| `docs/` | Future work, such as ozone |

`AGENTS.md` holds the working rules for AI agents on this project.

## Progress log
| Step | Status | Notes |
|---|---|---|
| 0. Repo setup | done | Rules (`AGENTS.md`), README skeleton |
| 1. Environment | done | TACC's `openfoam/8` module (intel/23.1 + impi/21.9) works through `01_environment/env.sh`; all compute goes in batch jobs (TACC AI policy) |
| 2. Build detonationFoam v1.2 | done | `detonationFoam_V2.0` + 4 libraries built in `$WORK` (job 3727370); 12-line syntax-only patch needed for TACC's `icpx` compiler |
| 3. Migrate Stanford case | done | `03_case/coarse_mesh_slip_of8`: 8 format-only edits + user choices: inviscid `solverType Euler`, AMR max level 2, Courant number 0.1 with Δt ≤ 9 ns (`03_case/CHANGES.md`); OF8 reads it and runs 20 steps with FFCM2 (9 species, 27 reactions), job 3727443 |
| 4. ZND initialization | done | Dr. Johnson's 4 ZND scripts run unmodified (job 3727629); D_CJ = 1616 m/s, vN spike 174.5 kPa / 1900 K, induction length 1.56 mm; 15/15 checks pass; OF8 reads the fields. Cell centres come from TACC's OF12 (OF8 function objects are broken on TACC) |
| 5. Slurm workflow | done | `05_runs/smoke.slurm`: copy init case → `decomposePar` simple (16 6 1) → `ibrun detonationFoam_V2.0 -parallel` with time guard → log summary → logs to `$WORK`; restart by resubmitting with a later `END_TIME` |
| 6. Smoke test | software done; physics pending | Job 3730997, 96 ranks, 0.9 SU: 1819 steps to 1.82 µs, Euler + FFCM2 (9/27) + DLB `loadBalanced` + AMR (→ 200 k cells), no FATAL/FPE/NaN, fields saved. 0.82 s/step. ⚠️ Ran at AMR level 3 (stale init_case dictionaries; fixed). Rerun job 3731474 with AMR 2 + Co 0.1 (`CHANGES.md` #11): 357 steps to 2 µs, 0.14 SU, no errors, max level 2; Co ≈ 0.1 except one-step spikes after each AMR update (max 0.87 once). About 10 SU for the full 200 µs. Propagation check still to do |
| 7. Reproducible README | pending | |
