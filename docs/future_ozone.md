# Future work: adding ozone

**Status: planning notes only.** Nothing here has been implemented or run. Items marked **(to decide)** need input from the user and Dr. Johnson.

## Goal
Study how ozone (O₃) changes the H₂–O₂–Ar detonation of the baseline: CJ speed, induction length, cell size, and what happens when the detonation crosses an ozone-containing layer. Ozone breaks down quickly into O₂ + O when heated, and the extra O atoms shorten the induction time. That is why small ozone fractions can change ignition and detonation behaviour.

## What the baseline gives us
- A working, documented 2D case (`03_case/coarse_mesh_slip_of8`), ZND initialization (`04_znd_init`), and run/analysis scripts (`05_runs`).
- A reference result to compare against: D = 1590 m/s (−1.6 % vs D_CJ = 1616 m/s), cell width ≈ 30 mm, induction length 1.56 mm.

## 1. Chemistry: FFCM2 has no ozone
The FFCM2 H₂/Ar mechanism has 9 species (H H2 O O2 OH H2O HO2 H2O2 AR) and **no O₃**. An ozone sub-mechanism has to be added:
- **Species:** O3 (thermo data in NASA-7 form, e.g. from the Burcat database or from the sub-mechanism's own source).
- **Typical reactions** (rate constants come from the chosen sub-mechanism):
  - O3 (+M) ⇌ O2 + O (+M), which dominates the decomposition
  - O3 + O ⇌ O2 + O2
  - O3 + H ⇌ OH + O2
  - O3 + OH ⇌ HO2 + O2
  - O3 + HO2 ⇌ OH + O2 + O2
- **Which sub-mechanism (to decide).** Several ozone sub-mechanisms have been published for ozone-assisted combustion. The choice should be made with Dr. Johnson and be consistent with FFCM2's H₂/O₂ core. Third-body efficiencies, especially Ar, need checking.
- **Validation of the merged mechanism:** before any CFD, check it in Cantera:
  - with O₃ = 0 it must reproduce FFCM2 exactly
  - ozone decomposition rate against published data
  - ignition delay with and without O₃

## 2. Getting the mechanism into OpenFOAM and the ZND scripts
Three files must stay consistent (same species and species order):

| File | Used by | How to update |
|---|---|---|
| `constant/FFCM2_H2_Ar.yaml` (new name, e.g. `FFCM2_O3.yaml`) | Cantera / SDToolbox (ZND scripts) | merge the O3 species and reactions into the YAML |
| `constant/chemFFCM2` (reactions) | OpenFOAM chemistry | convert. The Stanford case folder has converter scripts (`cti_to_foam.py`, `cttherm_to_foam.py`, `convert_thermo.py`). Reuse them before writing anything new |
| `constant/thermFFCM2` (species thermo) | OpenFOAM thermo | add an O3 `janaf` entry |

Notes:
- OpenFOAM 8's `chemkinToFoam` could not parse the case's therm file (Step 3), so the Python converters are the better route.
- Keep the OpenFOAM 8 spelling `reversibleThirdBodyArrheniusReaction` (`03_case/CHANGES.md` #6). Troe fall-off for the O3 decomposition must use the OF8 reaction type names.
- The ZND scripts hard-code the 9 species: `to_openfoam.py` has `n_species = 9` and a name list, and `interpolate_znd_on_openfoam.py` writes species by fixed column index (e.g. `columns[11]` = H2O2). Adding O3 means editing both. That is a minimal, documented change to Dr. Johnson's scripts, so record it.
- A new field `0/O3` is needed, plus an updated `Ydefault`.
- Check after conversion: species count 10, reaction count 27 + N, and a short serial OpenFOAM run that prints `Number of species = 10`.

## 3. Case setups (to decide)
**A. Uniform ozone-doped mixture.** Replace part of the O₂ (or add O₃ at fixed Ar dilution) everywhere.
- Rerun the ZND/CJ calculation for the new mixture with the existing `04_znd_init` workflow.
- Compare D_CJ, induction length and cell width with the baseline.
- Simplest; isolates the chemistry effect.

**B. Ozone layer.** The baseline mixture with a band of ozone-doped gas ahead of the detonation (for example a slab at some x, or a layer in y), to see how the front responds when it enters or runs alongside it.
- Place the layer with OpenFOAM `setFields` (a utility, not a function object, so it should work on TACC's OF8; test this). Alternatively, edit `0/` with a small Python script like the ZND scripts do.
- The layer must start far enough ahead of the front that the detonation has settled (the baseline settles after about 25 µs, i.e. at x ≳ 0.09 m).

**C. Restart from the baseline (saves compute).** Instead of restarting from ZND, take an established baseline detonation (e.g. `prop1` at 66 µs) and add ozone ahead of it:
- **Option 1:** `mapFields` from the reconstructed baseline (`reconstructParMesh` + `reconstructPar`, see `05_runs/analyze.slurm`) onto a fresh case that has the O3 field, then `setFields` for the layer. The AMR mesh will be mapped onto the base mesh and refined again.
- **Option 2:** add an O3 field (zero everywhere) to the processor directories and set the layer there. Fewer steps, but more manual.
- Either way, the unburned region ahead of the front is uniform, so only that region needs changing.

Questions **(to decide)**:
- O₃ fraction(s): for example a few hundred ppm to a few percent.
- Replace O₂ or add on top?
- Layer position, thickness and orientation.
- Keep inviscid Euler and AMR level 2 for the ozone runs, as in the baseline?

## 4. Practical notes
- **Shock detection** in detonationFoam (`p > 101425 Pa`, hard-coded) still works if ambient pressure stays at 6670 Pa, because the post-shock pressure is far above that.
- **Cost:** about 90 s of wall time per simulated µs on 2 nodes for the baseline. Chemistry with one more species should cost a bit more. 100 µs ≈ 5 SU on 2 nodes.
- **Validation steps,** same as the baseline:
  1. ZND/CJ for the new mixture
  2. smoke test
  3. propagation speed vs the new D_CJ
  4. `maxp` cell pattern
- **Before the ozone study, consider settling** whether the baseline 30 mm cell width is physical or imposed by the initial perturbation (run with a different initial front). Otherwise an ozone-induced change in cell size could be hidden by the same imposed wavelength.
