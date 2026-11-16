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
| 2. Build detonationFoam v1.2 | pending | |
| 3. Migrate Stanford case | pending | |
| 4. ZND initialization | pending | |
| 5. Slurm workflow | pending | |
| 6. Smoke test | pending | |
| 7. Reproducible README | pending | |
