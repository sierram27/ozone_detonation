#!/bin/bash
#SBATCH -J det_vtk
#SBATCH -p skx-dev
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -t 00:20:00
#SBATCH -A TG-MCH260175
#SBATCH -o det_vtk_%j.log
#
# Write one saved time of a run as VTK for ParaView (read-only on the processor data):
#   1. reconstructParMesh (if needed) + reconstructPar of all solution fields at that time
#   2. foamToVTK (OpenFOAM 8) -> $RUN/VTK
#   3. tar the VTK folder into $WORK/ozone_detonation/runs/$RUN_NAME/ for download
# Usage:  sbatch --export=ALL,RUN_NAME=prop1 to_vtk.slurm            (latest time)
#         sbatch --export=ALL,RUN_NAME=prop1,TIME=0.0001 to_vtk.slurm
# Ccx/Ccy (written by OpenFOAM 12 in analyze.slurm) are moved aside during foamToVTK: OF8 cannot read their header.

set -u
# Submit from $SCRATCH (e.g. $SCRATCH/ozone_detonation/logs), never from $HOME (TACC guidance).
case "${SLURM_SUBMIT_DIR:-}" in "$HOME"|"$HOME"/*) echo "WARNING: submitted from \$HOME ($SLURM_SUBMIT_DIR); submit from \$SCRATCH instead";; esac
RUN_NAME=${RUN_NAME:-prop1}
source ~/ozone_detonation/01_environment/env.sh
RUN=$SCRATCH/ozone_detonation/$RUN_NAME; cd "$RUN"
T=${TIME:-$(ls -d processor0/[0-9]* | sed 's|processor0/||' | sort -g | tail -1)}
FIELDS='(p T U rho maxp Qdot magGradrho cellLevel H H2 O O2 OH H2O HO2 H2O2 AR)'
echo "== Job $SLURM_JOB_ID: $RUN, time $T"

echo "== [1] reconstruct"
if [ ! -f "$T/polyMesh/faces" ]; then
  reconstructParMesh -time "$T" -mergeTol 1e-6 > log.reconstructParMesh.vtk 2>&1 || { tail -20 log.reconstructParMesh.vtk; exit 1; }
fi
reconstructPar -time "$T" -fields "$FIELDS" > log.reconstructPar.vtk 2>&1 || { tail -20 log.reconstructPar.vtk; exit 1; }
ls "$T"

echo "== [2] foamToVTK"
rm -rf VTK
# foamToVTK reads the header of every file in $T, and OF8 cannot read the OF12 Ccx/Ccy headers
# ("keyword version is undefined", job 3734272): move them aside and put them back afterwards.
mkdir -p "$T/.of12"; mv "$T"/Cc[xy] "$T/.of12/" 2>/dev/null
foamToVTK -time "$T" -fields "$FIELDS" > log.foamToVTK 2>&1; rc=$?
mv "$T"/.of12/* "$T"/ 2>/dev/null; rmdir "$T/.of12"
[ $rc = 0 ] || { tail -30 log.foamToVTK; exit 1; }
grep -iE "FATAL|Error" log.foamToVTK; find VTK -type f | head; du -sh VTK

echo "== [3] archive"
SAVE=$WORK/ozone_detonation/runs/$RUN_NAME; mkdir -p $SAVE
TAR=$SAVE/${RUN_NAME}_vtk_$T.tar.gz
tar czf $TAR VTK && ls -la $TAR
echo "== END $(date)"
