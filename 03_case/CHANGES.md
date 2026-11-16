# Changes from the Stanford case (OpenFOAM 6 / detonationFoam v1.0 → OpenFOAM 8 / detonationFoam v1.2)

**Source:** `drryjoh/stanford_collaboration` @ `8439738`, `Wang/nn_chemistry/2D_Ar_H2_O2/ffcm2/coarse_mesh_slip/`
**Migrated copy:** `03_case/coarse_mesh_slip_of8/`

**Rule:** change only what OpenFOAM 8 / v1.2 needs. Mesh, mixture, FFCM2 rate data, boundary conditions, numerical schemes, solver tolerances and time step stay exactly as Stanford had them.

## Changed
| # | File | Before (Stanford) | After (here) | Why |
|---|---|---|---|---|
| 1 | `system/controlDict` | `application detonationNSFoam_Sutherland;` | `application detonationFoam_V2.0;` | v1.2 has a single solver |
| 2 | `constant/solverTypeProperties` | *(did not exist)* | `solverType NS_Sutherland;` `SW_position_limit 1.0;` | v1.2 picks the equations here. NS_Sutherland = the original solver. The shock-position stop is set beyond the 0.5 m domain so it never fires (its detection threshold `p > 101425 Pa` is hard-coded for 1 atm, and ours starts at 6670 Pa) |
| 3 | `constant/turbulenceProperties` → `constant/momentumTransport` | file name and `object` | renamed; content unchanged (`simulationType laminar;`) | OpenFOAM 8 renamed this dictionary |
| 4 | `constant/thermophysicalProperties` | `mixture reactingMixture;` + `chemistryReader foamChemistryReader;` `foamChemistryFile …/chemFFCM2;` `foamChemistryThermoFile …/thermFFCM2;` | `mixture multiComponentMixture;` + `#include "$FOAM_CASE/constant/chemFFCM2"` + `#include "$FOAM_CASE/constant/thermFFCM2"` | OpenFOAM 8 removed `chemistryReader`. Same files, now included directly, as in the v1.2 tutorial |
| 5 | `constant/chemistryProperties` | reactions came from `foamChemistryFile` | added `#include "$FOAM_CASE/constant/chemFFCM2"` | in OpenFOAM 8 the reactions are read from `chemistryProperties` |
| 6 | `constant/chemFFCM2` | `type reversiblethirdBodyArrheniusReaction;` (4 reactions) | `type reversibleThirdBodyArrheniusReaction;` | OpenFOAM 8 spells the type name with a capital **T** (`FOAM FATAL ERROR: Unknown reaction type reversiblethirdBodyArrheniusReaction`). Only the keyword changed; every rate coefficient is untouched |
| 7 | `system/fvSchemes` | `div(phi,Yi_h) Gauss vanLeer;` | kept, **plus** `div(rhoPhi,Yi_h) Gauss vanLeer;` | v1.2 names the species-convection term `div(rhoPhi,Yi_h)`. Without the entry it would fall back to the default `Gauss linear` (unbounded) instead of the original vanLeer |
| 9 | `constant/solverTypeProperties` | (Stanford: viscous `detonationNSFoam_Sutherland`) | `solverType Euler;` | **Physics choice by the user (2026-11-16), not a compatibility fix.** Run inviscid: reactive Euler equations with no viscosity, heat conduction or species diffusion. Top and bottom walls are slip (inviscid) walls, which is consistent with Euler. As a side effect, the placeholder Sutherland coefficients below are no longer used. |
| 8 | `system/fvSchemes` | `reconstruct(U) MinmodV; reconstruct(p) Minmod;` | kept, **plus** `reconstruct(rhoU) MinmodV; reconstruct(rPsi) Minmod;` | v1.2 reconstructs `rho, rhoU, rPsi, e, c` (`fluxScheme.C`) instead of `U` and `p`. Without entries, `rhoU`/`rPsi` would fall back to `linear` (no limiter). Same limiters as the original |

## Deliberately NOT changed
- **Mesh** (`blockMeshDict`): 0.5 × 0.06 m, 1000 × 120 cells (Δx = Δy = 0.5 mm), walls top and bottom (slip velocity BC).
- **AMR** (`dynamicMeshDict`): `dynamicRefineFvMesh2D` on `magGradrho`, max 3 levels. The v1.2 library reads the same keys.
- **`controlDict` libs:** `libchemistryModel_DLB.so libdynamicMesh2D.so libdynamicFvMesh2D.so`. The v1.2 tutorial also lists `libODE_DLB.so`, but nothing in the repository builds it, so it is not added.
- **Time stepping:** fixed `deltaT 1e-9`, `adjustTimeStep no`, `endTime 2e-4`, `writeInterval 1e-6`.
- **`fvSolution`** (identical to the v1.2 tutorial), **`chemistryProperties`** solver settings (seulex, absTol 1e-9, relTol 1e-6, DLB load balancing), and **`combustionProperties`** (laminar).
- **FFCM2 data** in `chemFFCM2`/`thermFFCM2`: 9 species, **27 reactions** (21 Arrhenius, 4 third-body, 2 Troe fall-off).
- **Sutherland transport coefficients** in `thermFFCM2`: every species has the same placeholder `As = 1.67e-6, Ts = 170` (commented "possibly unused"). **They are used** by `NS_Sutherland` for viscosity and conductivity. Kept to match what Stanford ran. Since change #9 (`solverType Euler`) they are **not used**. ⚠️ Revisit them if a viscous solver type is used again.
- The Step-3 check run (job 3727443) used `NS_Sutherland`. Euler mode is verified in the smoke test (Step 6).
- **Initial fields in `0/`:** these are uniform placeholders. The real initial condition comes from the ZND scripts (Step 4).
- Unused files from the Stanford folder (FFCM1/Li-2007 mechanisms, `*_1D` dictionaries, `setFieldsDict`, `funkySetFieldsDict`, the PBS script `submit_2D_AR_H2_O2_new.js`, converter scripts) are kept for reference.

## Verification: `03_case/check_case.slurm` (job 3727443, skx-dev, 1 core, 10.4 min)
This is a read-and-step check, not a physics test. It uses Stanford's `setFieldsDict` (mixture plus 2500 K / 5.5 bar hot regions) only to exercise the chemistry.

- `blockMesh` and `checkMesh`: 120000 cells, `Mesh OK.`
- The solver log shows:
  ```
  Selecting dynamicFvMesh dynamicRefineFvMesh2D
  StandardChemistryModel: Number of species = 9 and reactions = 27
  Selecting ODE solver seulex
  Selecting fluxScheme: Kurganov
  solverType = NS_Sutherland
  Time = 1e-09 … Time = 2e-08     (20 steps)
  Refined from 120000 to 142689 cells … Refined from 142689 to 190773 cells
  min/max(p) = 6670, 549997.5   min/max(T) = 298, 2499.99
  End
  ```
- No `FOAM FATAL` and no floating-point exceptions (trapping on). Time directories `1e-08` and `2e-08` were written.
- **Cost note:** about 22 s per step in serial (with AMR growing to about 190 k cells).
- **Side note:** OpenFOAM 8 `chemkinToFoam` could not parse the case's `ffcm2_h2_ar_therm.dat` (formula columns not in strict CHEMKIN fixed format). Not needed, because the original foam-format files load.

## Still to confirm in later steps
- That DLBFoam's load-balanced chemistry is actually active in parallel. The log prints the base-class line `StandardChemistryModel`, which is expected for the derived `loadBalanced` model, but we will confirm in Step 6.
