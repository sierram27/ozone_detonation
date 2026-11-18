#!/bin/bash
#SBATCH -J det_analyze
#SBATCH -p skx-dev
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -t 00:20:00
#SBATCH -A TG-MCH260175
#SBATCH -o det_analyze_%j.log
#
# Post-process a finished run (read-only on the processor data):
#   1. reconstructPar (OpenFOAM 8) of the latest time: maxp p T cellLevel
#   2. cell centres of that (AMR-refined) mesh with TACC's OpenFOAM 12 (OF8 function objects crash)
#   3. analyze_prop.py: shock speed vs time, maxp cell pattern, spectra -> PNG + JSON
# Usage:  sbatch --export=ALL,RUN_NAME=prop1,LOGJOB=3731639 analyze.slurm
#         LOGJOB may list several solver jobs of one continued run, in order: LOGJOB=3731639:3732550:3732551
#         KEEP_SNAPSHOT=1 also copies the latest time (restartable) to $WORK/ozone_detonation/runs/$RUN_NAME/

set -u
# Submit from $SCRATCH (e.g. $SCRATCH/ozone_detonation/logs), never from $HOME (TACC guidance).
case "${SLURM_SUBMIT_DIR:-}" in "$HOME"|"$HOME"/*) echo "WARNING: submitted from \$HOME ($SLURM_SUBMIT_DIR); submit from \$SCRATCH instead";; esac
RUN_NAME=${RUN_NAME:-prop1}
LOGJOB=${LOGJOB:?set LOGJOB = job id of the solver run}
source ~/ozone_detonation/01_environment/env.sh
RUN=$SCRATCH/ozone_detonation/$RUN_NAME; cd "$RUN"
LAST=$(ls -d processor0/[0-9]* | sed 's|processor0/||' | sort -g | tail -1)
echo "== Job $SLURM_JOB_ID: analyse $RUN, latest time $LAST, solver log job $LOGJOB"

echo "== [1] reconstructParMesh + reconstructPar -time $LAST"
# AMR changed the mesh, so decomposePar's cell/face/point maps no longer apply: first merge the
# 96 processor meshes (writes the merged mesh to $LAST/polyMesh and new *ProcAddressing files
# in processor*/$LAST/polyMesh), then map the fields. Solution fields are not modified.
reconstructParMesh -time "$LAST" -mergeTol 1e-6 > log.reconstructParMesh 2>&1 || { tail -20 log.reconstructParMesh; exit 1; }
grep -E "nCells|Writing" log.reconstructParMesh | tail -3
reconstructPar -time "$LAST" -fields '(maxp p T cellLevel)' > log.reconstructPar 2>&1 || { tail -20 log.reconstructPar; exit 1; }
ls "$LAST"

echo "== [2] cell centres (OpenFOAM 12) of the mesh at $LAST"
CC=$SCRATCH/ozone_detonation/${RUN_NAME}_cellcentres; rm -rf $CC; mkdir -p $CC/0 $CC/constant
cp -r "$LAST"/polyMesh $CC/constant/polyMesh; cp -r system $CC/
(   module purge > /dev/null 2>&1; module load TACC > /dev/null 2>&1; module load openfoam/12 > /dev/null 2>&1
    cd $CC; foamDictionary -entry libs -remove system/controlDict > /dev/null 2>&1
    foamPostProcess -func writeCellCentres -time 0 ) > log.writeCellCentres 2>&1
grep -E "Writing|End|FATAL" log.writeCellCentres
cp $CC/0/Ccx $CC/0/Ccy "$LAST"/ || { tail -30 log.writeCellCentres; exit 1; }

echo "== [3] analyze_prop.py"
module load python/3.12.11 > /dev/null 2>&1
source $WORK/venvs/znd/bin/activate
export MPLBACKEND=Agg
OUT=$RUN/analysis_$LAST; mkdir -p $OUT
LOGS=$(echo "$LOGJOB" | tr ':' '\n' | sed 's/^/log.detonationFoam./' | paste -sd, -)
python ~/ozone_detonation/05_runs/analyze_prop.py "$LOGS" "$LAST" $OUT || exit 1

SAVE=$WORK/ozone_detonation/runs/$RUN_NAME/analysis_$LAST; mkdir -p $SAVE; cp $OUT/* $SAVE/

# [4] optional (KEEP_SNAPSHOT=1): keep the latest time in $WORK ($SCRATCH is purged after 10 days).
#     Enough to restart the run or re-analyse it: processor*/$LAST, constant, system, marker, logs,
#     and the reconstructed $LAST. File counts of source and copy are compared.
if [ "${KEEP_SNAPSHOT:-0}" = 1 ]; then
  SNAP=$WORK/ozone_detonation/runs/$RUN_NAME/snapshot_$LAST; mkdir -p $SNAP
  echo "== [4] snapshot -> $SNAP"
  for d in processor*; do mkdir -p $SNAP/$d; cp -r $d/$LAST $SNAP/$d/; done
  cp -r constant system .decomposed_ok "$LAST" log.detonationFoam.* $SNAP/
  a=$(ls -d processor*/$LAST | xargs -I{} find {} -type f | wc -l); b=$(cd $SNAP && ls -d processor*/$LAST | xargs -I{} find {} -type f | wc -l)
  echo "   processor files: source $a, copy $b $([ "$a" = "$b" ] && echo OK || echo MISMATCH)"; du -sh $SNAP
fi
echo "== END $(date); results in $OUT and $SAVE"
