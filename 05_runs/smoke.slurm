#!/bin/bash
#SBATCH -J det_smoke
#SBATCH -p skx-dev
#SBATCH -N 2
#SBATCH -n 96
#SBATCH -t 00:30:00
#SBATCH -A TG-MCH260175
#SBATCH -o det_smoke_%j.log
#
# Step 5/6: parallel run of the ZND-initialized 2D H2/O2/Ar detonation case.
#   detonationFoam_V2.0 (v1.2, OpenFOAM 8), solverType Euler, FFCM2, AMR max level 2.
#
# Defaults = SMOKE TEST: 2 nodes x 48 = 96 MPI ranks, simulate 2 us (~2000 steps of 1 ns).
#
# Variables (set them on the sbatch line, e.g.  sbatch --export=ALL,END_TIME=4e-6 smoke.slurm):
#   RUN_NAME     run directory name under $SCRATCH/ozone_detonation   (default: smoke)
#   END_TIME     simulated end time in s                              (default: 2e-6)
#   WRITE_INT    write interval in s                                  (default: 5e-7)
#   RECONSTRUCT  1 = run reconstructPar -latestTime after the solver  (default: 0)
#
# RESTART: if $SCRATCH/ozone_detonation/$RUN_NAME/.decomposed_ok exists (written only after a
# successful decomposePar), the script skips setup and decomposition and continues from the
# latest time saved in the processor directories (controlDict has startFrom latestTime).
# Resubmit with a later END_TIME. A run dir WITHOUT that marker is a failed setup and is
# deleted and rebuilt.
#
# The case files in the repo are never changed; endTime/writeInterval/decomposition are
# set on the run copy only.

set -u
RUN_NAME=${RUN_NAME:-smoke}
END_TIME=${END_TIME:-2e-6}
WRITE_INT=${WRITE_INT:-5e-7}
RECONSTRUCT=${RECONSTRUCT:-0}
NP=$SLURM_NTASKS                                   # number of MPI ranks = subdomains

source ~/ozone_detonation/01_environment/env.sh    # OpenFOAM 8 + our detonationFoam build

INIT=$SCRATCH/ozone_detonation/init_case           # ZND-initialized case from Step 4
RUN=$SCRATCH/ozone_detonation/$RUN_NAME
echo "== Job $SLURM_JOB_ID: $SLURM_JOB_NUM_NODES nodes, $NP ranks, on $(hostname) at $(date)"
echo "== Run dir: $RUN   END_TIME=$END_TIME  WRITE_INT=$WRITE_INT"

# ---------------------------------------------------------------- [1] setup or restart
if [ -f "$RUN/.decomposed_ok" ]; then
    echo "== [1] RESTART: run was decomposed earlier, continuing from latest time"
    cd "$RUN"
    ls -d processor0/[0-9]* | sed 's|processor0/||' | sort -g | tail -1 | xargs echo "   latest saved time:"
else
    echo "== [1] NEW RUN: copy initialized case from $INIT"
    [ -f "$INIT/0/T" ] && [ -d "$INIT/constant/polyMesh" ] || { echo "ERROR: $INIT is not initialized (run 04_znd_init/init.slurm)"; exit 1; }
    [ -d "$RUN" ] && { echo "   removing incomplete run dir from a failed setup"; rm -rf "$RUN"; }
    mkdir -p "$RUN"; cd "$RUN"
    cp -r "$INIT"/{0,constant,system} .
    # 0/Cx, 0/Cy: cell centres used only as input to the ZND scripts. They were written by
    # OpenFOAM 12 (no "version" header entry), which OpenFOAM 8's decomposePar rejects
    # (job 3730993). The solver never reads them, so the run copy drops them.
    rm -f 0/Cx 0/Cy
fi

# Settings for this run (run copy only)
# (plain sed: TACC's OpenFOAM 8 utilities have proven fragile, see 04_znd_init/README.md)
sed -i -E "s/^endTime[[:space:]].*/endTime         $END_TIME;/; s/^writeInterval[[:space:]].*/writeInterval   $WRITE_INT;/" system/controlDict
grep -E "^(application|startFrom|endTime|deltaT|adjustTimeStep|writeInterval)" system/controlDict | sed 's/^/   /'

# ---------------------------------------------------------------- [2] decompose
if [ ! -f .decomposed_ok ]; then
    # Stanford: simple (16 8 1) = 128 pieces. Here 96 pieces: 16 in x, NP/16 in y.
    NY=$((NP / 16)); [ $((16 * NY)) -eq "$NP" ] || { echo "ERROR: NP=$NP must be a multiple of 16"; exit 1; }
    sed -i -E "s/^numberOfSubdomains.*/numberOfSubdomains $NP;/; s/n +\(16 8 1\);/n               (16 $NY 1);/" system/decomposeParDict
    grep -E "^numberOfSubdomains|\(16 $NY 1\)" system/decomposeParDict | sed 's/^/   /' | grep -q "16 $NY 1" || { echo "ERROR: decomposeParDict edit failed"; exit 1; }
    echo "== [2] decomposePar: simple (16 $NY 1) = $NP subdomains"
    decomposePar -force > log.decomposePar 2>&1 || { tail -30 log.decomposePar; exit 1; }
    grep -E "^Number of processor faces|^Max number of cells" log.decomposePar | sed 's/^/   /'
    touch .decomposed_ok
fi

# ---------------------------------------------------------------- [3] solver
# Stop 4 min before the Slurm limit so the summary below always runs (TERM -> OpenFOAM exits).
LIMIT_S=$(( $(squeue -h -j $SLURM_JOB_ID -o %L | awk -F: '{ if (NF==3) print $1*3600+$2*60+$3; else print $1*60+$2 }') - 240 ))
LOG=log.detonationFoam.$SLURM_JOB_ID
echo "== [3] ibrun detonationFoam_V2.0 -parallel  (log: $RUN/$LOG, wall limit ${LIMIT_S}s)"
START=$(date +%s)
timeout --signal=TERM ${LIMIT_S}s ibrun detonationFoam_V2.0 -parallel > $LOG 2>&1
RC=$?
echo "   solver exit code $RC (124 = stopped by our time guard), wall time $(( $(date +%s) - START )) s"

# ---------------------------------------------------------------- [4] summary
echo "== [4] log summary"
grep -m1 -E "Selecting dynamicFvMesh"                  $LOG | sed 's/^/   /'
grep -m1 -E "Number of species"                        $LOG | sed 's/^/   /'
grep -m1 -E "Selecting chemistry|loadBalanc|DLB"       $LOG | sed 's/^/   /'
grep -m1 -E "Selecting ODE solver"                     $LOG | sed 's/^/   /'
grep -m1 -E "solverType ="                             $LOG | sed 's/^/   /'
echo "   time steps completed: $(grep -c '^Time = ' $LOG)"
grep '^Time = ' $LOG | tail -1 | sed 's/^/   last /'
grep -E "^Refined|^Unrefined" $LOG | tail -1 | sed 's/^/   /'
grep -E "min/max\(p\)" $LOG | tail -1 | sed 's/^/   /'
grep -E "min/max\(T\)" $LOG | tail -1 | sed 's/^/   /'
grep -E "ExecutionTime" $LOG | tail -1 | sed 's/^/   /'
# (the startup banner "sigFpe : Enabling floating point exception trapping" is not an error)
ERRS=$(grep -iE 'FOAM FATAL|sigFpe|Floating point exception|\bnan\b|Segmentation' $LOG | grep -v 'Enabling floating point')
echo "   FATAL/FPE/NaN lines: $(echo -n "$ERRS" | grep -c .)"; [ -n "$ERRS" ] && echo "$ERRS" | head -5
# If our time guard stopped the run (exit 124), MPI prints "BAD TERMINATION ... KILLED BY SIGNAL: 15"
# for every rank. That is expected; signal 15 = our TERM. Any other signal is a real crash.
grep -oE 'KILLED BY SIGNAL: [0-9]+' $LOG | sort | uniq -c | sed 's/^/   MPI: /'
echo "   saved times in processor0: $(ls -d processor0/[0-9]* 2>/dev/null | sed 's|processor0/||' | sort -g | tr '\n' ' ')"

# ---------------------------------------------------------------- [5] optional reconstruct
if [ "$RECONSTRUCT" = "1" ]; then
    echo "== [5] reconstructPar -latestTime"
    reconstructPar -latestTime > log.reconstructPar 2>&1; tail -3 log.reconstructPar
fi

# ---------------------------------------------------------------- [6] keep logs in $WORK
SAVE=$WORK/ozone_detonation/runs/$RUN_NAME; mkdir -p "$SAVE"
cp $LOG log.decomposePar system/controlDict system/decomposeParDict "$SAVE"/ 2>/dev/null
echo "== END $(date); logs copied to $SAVE"
