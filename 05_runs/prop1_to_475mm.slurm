#!/bin/bash
#SBATCH -J det_prop1_475
#SBATCH -p skx-dev
#SBATCH -N 2
#SBATCH -n 96
#SBATCH -t 02:00:00
#SBATCH -A TG-MCH260175
#SBATCH -o det_prop1_475_%j.log
#
# Continue run prop1 (saved to 200 us, leading shock at 375.7 mm) until the leading shock
# reaches x = 0.475 m (25 mm before the outlet at 0.5 m).
#
# Submit it yourself, from $SCRATCH (see docs/GUIDE.md, part 9):
#     cd $SCRATCH/ozone_detonation/logs
#     sbatch ~/ozone_detonation/05_runs/prop1_to_475mm.slurm
#
# Estimate: about 100 mm at about 1.6 mm/us = about 62 us of simulated time, at about
# 85 s per us on 2 nodes = about 90 min. Cost: 2 nodes x up to 2 h = at most 4 SU.
# If the job ends before 475 mm (time limit, or a system cancellation), submit the SAME
# command again: it restarts from the latest 1 us save. For shorter jobs, override the
# limit on the command line, e.g.  sbatch -t 00:30:00 ~/ozone_detonation/05_runs/prop1_to_475mm.slurm
#
# The work is done by smoke.slurm (setup/restart, solver with time guard, log summary,
# logs copied to $WORK). This file only fixes the settings for this continuation:
export RUN_NAME=prop1     # run folder $SCRATCH/ozone_detonation/prop1
export END_TIME=3e-4      # backstop only; the shock-position stop should end the run near 262 us
export WRITE_INT=1e-6     # save every 1 us, as before
export SW_LIMIT=0.475     # stop when the leading shock reaches x = 0.475 m

set -u
RUN=$SCRATCH/ozone_detonation/$RUN_NAME
SNAP=$WORK/ozone_detonation/runs/prop1/snapshot_0.0002
# Safety: without the .decomposed_ok marker, smoke.slurm would treat prop1 as a NEW run and
# start again from t = 0. That happens if $SCRATCH was purged (10 days). In that case restore
# the 200 us snapshot kept in $WORK first.
if [ ! -f "$RUN/.decomposed_ok" ]; then
    [ -f "$SNAP/.decomposed_ok" ] || { echo "ERROR: $RUN has no .decomposed_ok and no snapshot in $SNAP. Stopping."; exit 1; }
    echo "== $RUN missing or incomplete: restoring the 200 us snapshot from $SNAP"
    [ -d "$RUN" ] && mv "$RUN" "${RUN}_incomplete_$(date +%Y%m%d%H%M)"
    cp -r "$SNAP" "$RUN" || { echo "ERROR: restore failed"; exit 1; }
fi

bash ~/ozone_detonation/05_runs/smoke.slurm
