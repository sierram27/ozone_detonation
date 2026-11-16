# Step 2 — Building detonationFoam v1.2 on Stampede3

**Result: success** (job 3727370, 2026-11-16). `detonationFoam_V2.0` and its 4 libraries are built and run.

## What we use
| Component | Version | Where |
|---|---|---|
| OpenFOAM | 8, **TACC's prebuilt module** (no need to compile it) | `/home1/apps/intel23/impi21/OpenFOAM/OpenFOAM-8` |
| Compiler / MPI | Intel oneAPI 2023.1 (`icpx`, via `mpiicpc`) / Intel MPI 2021.9 | modules `intel/23.1`, `impi/21.9` |
| detonationFoam | branch `detonationFoam_V1.2_OF8`, commit `04239c9` (2026-11-05) | source: `$WORK/src/detonationFoam` |
| Build output | `WM_OPTIONS=linux64IccDPInt32Opt` (64-bit Linux, Intel, double precision, 32-bit labels, optimized) | `$WORK/OpenFOAM/smartinez627-8/platforms/linux64IccDPInt32Opt/{bin,lib}` |

Environment: `source ~/ozone_detonation/01_environment/env.sh`. See `01_environment/README.md`.

## Exact commands
```bash
# login node (light work: download only)
mkdir -p $WORK/src && cd $WORK/src
git clone -b detonationFoam_V1.2_OF8 https://github.com/JieSun-pku/detonationFoam.git
git clone https://github.com/drryjoh/stanford_collaboration.git

# compile on a compute node (TACC AI policy)
cd ~/ozone_detonation/02_build
sbatch build.slurm            # writes build_<jobid>.log; ends with "BUILD STATUS: SUCCESS"
```
What [`build.slurm`](build.slurm) does (skx-dev, 1 node, ≤45 min):
1. Loads the environment and sets `WM_NCOMPPROCS=48` so it compiles 48 files at once.
2. Copies the source to `$SCRATCH/build/detonationFoam`, because jobs should do their file work in `$SCRATCH`.
3. Applies [`patches/icpx_direct_init.patch`](patches/icpx_direct_init.patch). See the next section.
4. Runs detonationFoam's own `Allwmake` with `sh ./Allwmake`. That script builds, in order:
   - `libdynamicMesh2D` and `libdynamicFvMesh2D`: 2D adaptive mesh refinement (AMR)
   - `libchemistryModel_DLB`: DLBFoam, which spreads the chemistry work evenly across processors
   - `libfluxSchemes_improved`: the Riemann/flux schemes (Kurganov, HLLC, AUSM+ …)
   - `detonationFoam_V2.0`: the solver
5. Checks that every file exists, that `ldd` finds no missing libraries, and that `detonationFoam_V2.0 -help` runs.

## Build problems and fixes (4 attempts, ≈0.3 SU in total)
| Job | Problem | Fix |
|---|---|---|
| 3726793 | `./Allwmake: Permission denied`. The repository stores `Allwmake` without the execute bit. | Run it as `sh ./Allwmake`. |
| 3726838 | 12 lines fail: `conversion from 'tmp<GeometricField…>' to 'volScalarField' is ambiguous` | see below |
| 3727277 | Tried the classic Intel compiler `icpc` (`I_MPI_CXX=icpc`) to avoid editing code. It can't read the OS's math header (`_Float32 is undefined` in `/usr/include/bits/mathcalls.h`). `icpc` is deprecated and too old for this OS. | Abandoned. |
| **3727370** | — | **Patch the 12 lines; build succeeds.** |

**About the patch.** TACC's MPI compiler wrapper uses Intel's LLVM-based `icpx`, which also built TACC's OpenFOAM 8. `icpx` enforces a C++ rule that GCC lets slide. Writing `volScalarField p = rho*rPsi;` can mean two different conversions, so the compiler calls it ambiguous. Writing `volScalarField p(rho*rPsi);` means exactly one thing. The patch makes that change on 12 lines:
- 5 in `fluxSchemes_improved/fluxScheme/fluxScheme.C`
- 4 in `solverTypeNS_mixtureAverage/rhoYEqn_NS_mixtureAverage.H`
- 3 in `solverTypeNS_mixtureAverage/transport/updateTransProperties.H`

The arithmetic and physics are identical. The patch is applied only to the scratch build copy, so `$WORK/src/detonationFoam` stays as published.

**Harmless warning:** `icpx: … Unsupported command line options … -fp-trap=common`. This flag comes from TACC's OpenFOAM build rules and is meant for the older `icpc`. OpenFOAM still traps floating-point errors at run time through its own `FOAM_SIGFPE` setting, which is on by default.

## How v1.2 differs from v1.0 (OpenFOAM 6), which the Stanford case used
| | v1.0 (OpenFOAM 6), used by Stanford | v1.2 (OpenFOAM 8), used here |
|---|---|---|
| Solvers | 3 separate programs: `detonationEulerFoam`, `detonationNSFoam_Sutherland`, `detonationNSFoam_mixtureAverage` | **one** program, `detonationFoam_V2.0` |
| Choosing physics | pick the program (`application` in `controlDict`) | `constant/solverTypeProperties` → `solverType Euler;` / `NS_Sutherland;` / `NS_mixtureAverage;` (default `Euler`) |
| Run stop | `endTime` | `endTime`, **or** when the leading shock passes `SW_position_limit` in `solverTypeProperties` (default 1.0 m) |
| Turbulence dictionary | `constant/turbulenceProperties` | `constant/momentumTransport` (OpenFOAM 8 renamed it) |
| Mechanism input | `chemistryReader foamChemistryReader` + `foamChemistryFile`/`foamChemistryThermoFile` | `mixture multiComponentMixture`, with species/thermo `#include`d in `thermophysicalProperties` and reactions `#include`d in `chemistryProperties` |
| Other | — | turbulence-initialization bug fixed; changed which variables are reconstructed for the flux calculation |

The Stanford case ran `detonationNSFoam_Sutherland`, so we will set **`solverType NS_Sutherland;`** to keep the same equations (Navier–Stokes with Sutherland viscosity).

**`SW_position_limit` caveat.** The solver finds the "leading shock" as the furthest cell where `p > 101325 + 100` Pa. This threshold is hard-coded for a 1-atm mixture, and ours starts at **6670 Pa**. It only controls when the run stops early and doesn't affect the physics. We'll set the limit so it can't cut the run short; see Step 3.

**Note for Step 3:** the v1.2 tutorial's `controlDict` loads `libODE_DLB.so`, but **no build script in the repository produces that library**. We won't list it.
