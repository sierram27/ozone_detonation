#!/bin/bash
#SBATCH -J det_recycle
#SBATCH -p skx-dev
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -t 00:30:00
#SBATCH -A TG-MCH260175
#SBATCH -o det_recycle_%j.log
#
# Window recycling ("option B"): move the detonation back in the 0.5 m channel so it can keep going.
#   1. reconstruct the latest save of run SRC_RUN (reconstructParMesh + reconstructPar)
#   2. copy it and shift the copy left by SHIFT m (the old x = SHIFT..0.5 m becomes 0..0.5-SHIFT m)
#   3. new run folder NEW_RUN: case settings from the repo, the 0.5 m base mesh (0.5 mm cells), fresh gas
#   4. recycle_fields.py map: every 0.5 mm base cell gets the area-weighted average of the 1, 4 or 16
#      shifted source cells inside it (maxp: their maximum); beyond 0.5-SHIFT m stays fresh gas.
#      (OpenFOAM 8 mapFields was tried first and was still searching cells after 15 min, job 3740579.)
#   5. checks, decomposePar, .decomposed_ok -> ready for cycle_run.slurm
# Lab position = domain position + OFFSET. OFFSET adds up over cycles; it is written to
# $SCRATCH/ozone_detonation/$NEW_RUN/recycle_info.txt (and to $WORK/ozone_detonation/runs/$NEW_RUN).
# The source run is not changed, except that its latest save is reconstructed (as to_vtk.slurm does).
#
# Usage (submit from $SCRATCH/ozone_detonation/logs):
#   sbatch --export=ALL,SRC_RUN=prop1,NEW_RUN=prop1_cycle1 ~/ozone_detonation/05_runs/recycle.slurm
#   sbatch --export=ALL,SRC_RUN=prop1_cycle1,NEW_RUN=prop1_cycle2 ~/ozone_detonation/05_runs/recycle.slurm   (next cycle)
# Variables: SRC_RUN (default prop1), NEW_RUN (default prop1_cycle1), SHIFT (default 0.30 m),
#            NP (default 96 = MPI ranks of the next run, for decomposePar)
# Cost: 1 node, about 10 min (limit 30 min) = at most 0.5 SU.
# What mapping does to the solution, and why: 05_runs/README.md, "Window recycling".

set -u
case "${SLURM_SUBMIT_DIR:-}" in "$HOME"|"$HOME"/*) echo "WARNING: submitted from \$HOME ($SLURM_SUBMIT_DIR); submit from \$SCRATCH instead";; esac
SRC_RUN=${SRC_RUN:-prop1}
NEW_RUN=${NEW_RUN:-prop1_cycle1}
SHIFT=${SHIFT:-0.30}
NP=${NP:-96}
L=0.5; NCELLS=120000; DXC=0.0005      # base mesh (system/blockMeshDict: 1000 x 120 cells, 0.5 x 0.06 m)
FIELDS="p T U maxp H H2 O O2 OH H2O HO2 H2O2 AR"

source ~/ozone_detonation/01_environment/env.sh
# Python in a subshell, so the OpenFOAM environment is not changed
py() { ( module load python/3.12.11 > /dev/null 2>&1; python3 ~/ozone_detonation/05_runs/recycle_fields.py "$@" ); }

SRC=$SCRATCH/ozone_detonation/$SRC_RUN
NEW=$SCRATCH/ozone_detonation/$NEW_RUN
MAPSRC=$SCRATCH/ozone_detonation/${NEW_RUN}_mapsource      # temporary shifted copy of the source
CASE_SRC=~/ozone_detonation/03_case/coarse_mesh_slip_of8
echo "== Job $SLURM_JOB_ID on $(hostname) at $(date)"

[ -f "$SRC/.decomposed_ok" ] || { echo "ERROR: $SRC is not a run folder (no .decomposed_ok)"; exit 1; }
[ "$SRC" != "$NEW" ] || { echo "ERROR: NEW_RUN must differ from SRC_RUN"; exit 1; }
[ -f "$NEW/.decomposed_ok" ] && { echo "ERROR: $NEW already exists and is complete. Pick another NEW_RUN (nothing was changed)."; exit 1; }
[ -d "$NEW" ] && { echo "   removing incomplete $NEW from an earlier failed attempt"; rm -rf "$NEW"; }
rm -rf "$MAPSRC"

cd "$SRC"
T=$(ls -d processor0/[0-9]* | sed 's|processor0/||' | sort -g | tail -1)
PREV=$(sed -n 's/^OFFSET=//p' recycle_info.txt 2>/dev/null); PREV=${PREV:-0}
OFFSET=$(awk -v a="$PREV" -v b="$SHIFT" 'BEGIN { print a + b }')
echo "== Source $SRC, latest save t = $T s; shift $SHIFT m; lab offset $PREV -> $OFFSET m"
echo "== New run $NEW"

# ---------------------------------------------------------------- [1] reconstruct the source save
echo "== [1] reconstruct t = $T"
if [ ! -f "$T/polyMesh/faces" ]; then
    reconstructParMesh -time "$T" -mergeTol 1e-6 > log.reconstructParMesh.recycle 2>&1 || { tail -20 log.reconstructParMesh.recycle; exit 1; }
fi
reconstructPar -time "$T" -fields "($FIELDS)" > log.reconstructPar.recycle 2>&1 || { tail -20 log.reconstructPar.recycle; exit 1; }
grep -m1 note "$T/polyMesh/owner" | sed 's/^ */   source mesh: /'

# ---------------------------------------------------------------- [2] shifted copy
echo "== [2] shifted copy in $MAPSRC"
mkdir -p "$MAPSRC/$T"
cp -r "$T/polyMesh" "$MAPSRC/$T/"
for f in $FIELDS; do cp "$T/$f" "$MAPSRC/$T/" || exit 1; done
py shift "$MAPSRC/$T/polyMesh/points" "-$SHIFT" || exit 1
py ambient "$MAPSRC/$T" "$MAPSRC/ambient.json" || exit 1

# ---------------------------------------------------------------- [3] new run folder with fresh gas
echo "== [3] new run folder: settings from $CASE_SRC, base mesh from $SRC/constant, fresh gas everywhere"
mkdir -p "$NEW"; cd "$NEW"
cp -r "$CASE_SRC"/{constant,system} .
rm -rf constant/polyMesh; cp -r "$SRC/constant/polyMesh" constant/
grep -q "nCells: $NCELLS " constant/polyMesh/owner || { echo "ERROR: $SRC/constant/polyMesh is not the $NCELLS-cell base mesh"; exit 1; }
py target "$CASE_SRC/0" "$T" "$MAPSRC/ambient.json" || exit 1

# ---------------------------------------------------------------- [4] map
echo "== [4] map: average the shifted source cells onto the base cells"
py map "$MAPSRC/$T" "$T" constant/polyMesh $DXC || exit 1
py check "$T" "$MAPSRC/ambient.json" constant/polyMesh $L "$SHIFT" "$OFFSET" || exit 1

# ---------------------------------------------------------------- [5] decompose (as in smoke.slurm)
NY=$((NP / 16)); [ $((16 * NY)) -eq "$NP" ] || { echo "ERROR: NP=$NP must be a multiple of 16"; exit 1; }
sed -i -E "s/^numberOfSubdomains.*/numberOfSubdomains $NP;/; s/n +\(16 8 1\);/n               (16 $NY 1);/" system/decomposeParDict
grep -q "(16 $NY 1)" system/decomposeParDict || { echo "ERROR: decomposeParDict edit failed"; exit 1; }
echo "== [5] decomposePar: simple (16 $NY 1) = $NP subdomains"
decomposePar -force -time "$T" > log.decomposePar 2>&1 || { tail -30 log.decomposePar; exit 1; }
grep -E "^Number of processor faces|^Max number of cells" log.decomposePar | sed 's/^/   /'
ls processor0/"$T" | tr '\n' ' ' | sed 's/^/   processor0\/'"$T"': /'; echo

printf "SOURCE=%s\nSOURCE_TIME=%s\nSHIFT=%s\nOFFSET=%s\nJOB=%s\n" "$SRC_RUN" "$T" "$SHIFT" "$OFFSET" "$SLURM_JOB_ID" > recycle_info.txt
touch .decomposed_ok
rm -rf "$MAPSRC"

SAVE=$WORK/ozone_detonation/runs/$NEW_RUN; mkdir -p "$SAVE"
cp recycle_info.txt log.decomposePar "$SAVE"/
echo "== END $(date): $NEW is ready. Lab position = domain position + $OFFSET m."
echo "   Next: sbatch --export=ALL,RUN_NAME=$NEW_RUN ~/ozone_detonation/05_runs/cycle_run.slurm"
