#!/bin/bash
#SBATCH -J znd_init
#SBATCH -p skx-dev
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -t 00:30:00
#SBATCH -A TG-MCH260175
#SBATCH -o znd_init_%j.log
#
# Step 4: initialize the 2D case from a 1D ZND detonation profile, using
# Dr. Ryan Johnson's scripts from stanford_collaboration/Wang/nn_chemistry/ZND_Init
# (run UNMODIFIED). See 04_znd_init/README.md for the physics and each step.
#
# Output: $SCRATCH/ozone_detonation/init_case  (initialized case, ready for decomposePar)
#         copy of 0/ + ZND CSV + plots in $WORK/ozone_detonation/znd_init_<jobid>

set -u
# Submit from $SCRATCH (e.g. $SCRATCH/ozone_detonation/logs), never from $HOME: jobs whose
# working dir / output file were in $HOME were killed by the system at ~2 min (2026-11-17).
case "${SLURM_SUBMIT_DIR:-}" in "$HOME"|"$HOME"/*) echo "WARNING: submitted from \$HOME ($SLURM_SUBMIT_DIR); submit from \$SCRATCH instead";; esac
source ~/ozone_detonation/01_environment/env.sh          # OpenFOAM 8
module load python/3.12.11 > /dev/null 2>&1               # Python for the ZND scripts
source $WORK/venvs/znd/bin/activate                        # Cantera 3.1.0, SDToolbox, pandas 2.2.3
export MPLBACKEND=Agg                                      # plotting without a display

ZND=$WORK/src/stanford_collaboration/Wang/nn_chemistry/ZND_Init
CASE_SRC=~/ozone_detonation/03_case/coarse_mesh_slip_of8
RUN=$SCRATCH/ozone_detonation/init_case
rm -rf "$RUN"; mkdir -p "$RUN"; cp -r "$CASE_SRC"/{0,constant,system} "$RUN"/
cd "$RUN"
echo "== Job $SLURM_JOB_ID on $(hostname) at $(date); case: $RUN"
echo "== ZND scripts from $ZND (stanford_collaboration commit $(git -C $ZND rev-parse --short HEAD))"
python -c "import cantera, pandas, scipy, numpy; print('cantera', cantera.__version__, 'pandas', pandas.__version__, 'scipy', scipy.__version__, 'numpy', numpy.__version__)"

# Scripts and mechanism must sit in the case directory: they read 0/Cx, 0/Cy and
# FFCM2_H2_Ar.yaml from the current directory and write into 0/.
cp $ZND/{znd_solution_generator.py,consolidate_from_OF.py,interpolate_znd_on_openfoam.py,to_openfoam.py} .
cp constant/FFCM2_H2_Ar.yaml .

echo "== [1] blockMesh"
blockMesh > log.blockMesh 2>&1 || { tail -20 log.blockMesh; exit 1; }
checkMesh > log.checkMesh 2>&1; grep -E "cells:|Mesh OK|\*\*\*" log.checkMesh

echo "== [2] cell centres -> 0/Cx, 0/Cy"
# TACC's OpenFOAM 8 build crashes on EVERY function object, writeCellCentres included
# ("error in IOstream OSHA1stream.sinkFile_"). So TACC's OpenFOAM 12 writes the centres
# of the same mesh instead. It runs in an isolated subshell on a copy that holds only
# polyMesh + system (OF8-only libs removed). OF12 names the components Ccx/Ccy; they are
# copied to the names the Stanford script expects (0/Cx, 0/Cy). verify_init.py checks them
# against the exact uniform-grid values.
CC=$SCRATCH/ozone_detonation/init_cellcentres; rm -rf $CC; mkdir -p $CC/0 $CC/constant
cp -r constant/polyMesh $CC/constant/; cp -r system $CC/
(   module purge > /dev/null 2>&1; module load TACC > /dev/null 2>&1; module load openfoam/12 > /dev/null 2>&1
    cd $CC; foamDictionary -entry libs -remove system/controlDict > /dev/null 2>&1
    foamPostProcess -func writeCellCentres -time 0 ) > log.writeCellCentres 2>&1
cp $CC/0/Ccx 0/Cx; cp $CC/0/Ccy 0/Cy
grep -E "Writing|End" log.writeCellCentres; grep -m1 "internalField" 0/Cx

echo "== [3] znd_solution_generator.py (SDToolbox: CJ speed, post-shock state, ZND integration)"
( time python znd_solution_generator.py ) > log.znd_solution_generator 2>&1 || { tail -30 log.znd_solution_generator; exit 1; }
tail -5 log.znd_solution_generator; wc -l ffcm2hydrogen_ZND_solution.csv; head -c 300 ffcm2hydrogen_ZND_solution.csv; echo

echo "== [4] consolidate_from_OF.py (0/Cx, 0/Cy -> consolidated_with_xy_znd.csv)"
python consolidate_from_OF.py > log.consolidate 2>&1 || { tail -20 log.consolidate; exit 1; }
cat log.consolidate; head -3 consolidated_with_xy_znd.csv

echo "== [5] interpolate_znd_on_openfoam.py (map ZND profile behind the sinusoidal front)"
( time python interpolate_znd_on_openfoam.py ) > log.interpolate 2>&1 || { tail -30 log.interpolate; exit 1; }
tail -5 log.interpolate; head -3 initialization_for_openfoam.csv

echo "== [6] to_openfoam.py (write 0/T, 0/p, 0/<9 species>, 0/U)"
python to_openfoam.py > log.to_openfoam 2>&1 || { tail -20 log.to_openfoam; exit 1; }
ls -la 0/

echo "== [7] verification"
python ~/ozone_detonation/04_znd_init/verify_init.py --plots-dir verify_plots
VERIFY=$?

echo "== [8] OpenFOAM reads the fields: 2 serial Euler steps on a throwaway copy"
rm -rf ../init_readtest; mkdir ../init_readtest; cp -r 0 constant system ../init_readtest/
( cd ../init_readtest
  foamDictionary -entry endTime -set 2e-9 system/controlDict > /dev/null
  foamDictionary -entry writeInterval -set 1 system/controlDict > /dev/null
  detonationFoam_V2.0 > log.readtest 2>&1
  grep -E "solverType|species|^Time =|min/max|FATAL|Floating" log.readtest | head -20; tail -3 log.readtest )

echo "== [9] save results to \$WORK"
SAVE=$WORK/ozone_detonation/znd_init_$SLURM_JOB_ID; mkdir -p $SAVE
cp -r 0 ffcm2hydrogen_ZND_solution.csv verify_plots log.* $SAVE/
echo "saved to $SAVE"
echo "== END $(date); verification exit code $VERIFY"
