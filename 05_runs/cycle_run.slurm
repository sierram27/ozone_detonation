#!/bin/bash
#SBATCH -J det_cycle
#SBATCH -p skx-dev
#SBATCH -N 2
#SBATCH -n 96
#SBATCH -t 02:00:00
#SBATCH -A TG-MCH260175
#SBATCH -o det_cycle_%j.log
#
# Run one recycled window (made by recycle.slurm) until the leading shock reaches x = 0.475 m in the
# domain, i.e. 0.30 m of travel per cycle (about 190 us of simulated time, about 4.5 h on 2 nodes).
#
# Usage (submit from $SCRATCH/ozone_detonation/logs):
#   sbatch --export=ALL,RUN_NAME=prop1_cycle1 ~/ozone_detonation/05_runs/cycle_run.slurm
# A 2 h job will not finish a cycle: submit the SAME command again; it restarts from the latest 1 us save.
# The cycle is done when the job log shows "last Leading shock location = 0.475..." (see docs/GUIDE.md).
# Cost: 2 nodes x up to 2 h = at most 4 SU per job.
#
# The work is done by smoke.slurm (restart, solver with time guard, log summary, logs to $WORK).
set -u
: "${RUN_NAME:?set RUN_NAME, e.g. sbatch --export=ALL,RUN_NAME=prop1_cycle1 cycle_run.slurm}"
# Safety: smoke.slurm treats a folder WITHOUT .decomposed_ok as a new run, deletes it and starts again
# from the ZND initial condition at t = 0. A recycled run must never take that path.
[ -f "$SCRATCH/ozone_detonation/$RUN_NAME/.decomposed_ok" ] || {
    echo "ERROR: $SCRATCH/ozone_detonation/$RUN_NAME is missing or incomplete. Run recycle.slurm first. Stopping."; exit 1; }
cat "$SCRATCH/ozone_detonation/$RUN_NAME/recycle_info.txt" 2>/dev/null | sed 's/^/   recycle_info: /'

export RUN_NAME
export END_TIME=${END_TIME:-1e-2}      # backstop only; the shock-position stop ends the cycle
export WRITE_INT=${WRITE_INT:-1e-6}    # save every 1 us, as in prop1
export SW_LIMIT=${SW_LIMIT:-0.475}     # stop when the leading shock reaches x = 0.475 m (domain coordinates)
bash ~/ozone_detonation/05_runs/smoke.slurm
