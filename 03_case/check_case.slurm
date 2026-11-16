#!/bin/bash
#SBATCH -J check_case
#SBATCH -p skx-dev
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -t 00:20:00
#SBATCH -A TG-MCH260175
#SBATCH -o check_case_%j.log
#
# Step 3 check: can OpenFOAM 8 / detonationFoam v1.2 read the migrated case
# (mesh, dictionaries, FFCM2 chemistry) and take a few time steps?
# Works on a scratch copy. The case in the repository is never modified.
# NOT the real initialization: setFieldsDict (from the Stanford case) is used only
# to put a reacting H2/O2/Ar mixture plus hot regions in the domain.

set -u
source ~/ozone_detonation/01_environment/env.sh
CASE_SRC=~/ozone_detonation/03_case/coarse_mesh_slip_of8
RUN=$SCRATCH/ozone_detonation/check_case
rm -rf "$RUN"; mkdir -p "$RUN"; cp -r "$CASE_SRC"/{0,constant,system} "$RUN"/
cd "$RUN"
echo "== Job $SLURM_JOB_ID on $(hostname), case copy: $RUN"

echo "== blockMesh";  blockMesh  > log.blockMesh 2>&1  || { tail -30 log.blockMesh; exit 1; }
echo "== checkMesh";  checkMesh  > log.checkMesh 2>&1; grep -E "cells:|Mesh OK|Failed|\*\*\*" log.checkMesh

echo "== chemkinToFoam (OF8 conversion of the case's own FFCM2 CHEMKIN files, for comparison)"
mkdir -p chemkin_of8
chemkinToFoam constant/FFCM2_H2_Ar.ck constant/ffcm2_h2_ar_therm.dat constant/openfoam_transport.txt \
    chemkin_of8/reactions chemkin_of8/thermo > log.chemkinToFoam 2>&1
tail -5 log.chemkinToFoam
echo "species/reactions in chemkinToFoam output:"
grep -A12 "^species" chemkin_of8/reactions | head -13 | tr '\n' ' '; echo
grep -cE "^\s+type\s" chemkin_of8/reactions
grep -E "^\s+type\s" chemkin_of8/reactions | sort | uniq -c

echo "== setFields (Stanford setFieldsDict, for this check only)"
setFields > log.setFields 2>&1 || { tail -30 log.setFields; exit 1; }
grep -iE "warn|error" log.setFields | head

# Short run: 20 steps of deltaT = 1e-9 s
foamDictionary -entry endTime       -set 2e-8 system/controlDict > /dev/null
foamDictionary -entry writeInterval -set 1e-8 system/controlDict > /dev/null

run_solver () {
    echo "== detonationFoam_V2.0 (serial, 20 steps) - $1"
    ( time detonationFoam_V2.0 > log.solver_$1 2>&1 ) 2>&1 | grep real
    local rc=${PIPESTATUS[0]}
    grep -E "solverType|SW_position_limit|Selecting|species|reactions|^Time = " log.solver_$1 | head -40
    grep -nE "FOAM FATAL|Floating point|sigFpe|nan" log.solver_$1 | head -20
    tail -15 log.solver_$1
    grep -q "^End" log.solver_$1 || tail -n 50 log.solver_$1 | grep -q "Time = 2e-08"
}

if run_solver original_chemFiles; then
    echo "== RESULT: original chemFFCM2/thermFFCM2 load and run under OF8"
else
    echo "== Original chemistry files failed. Retrying with chemkinToFoam output."
    rm -rf 1e-08 2e-08
    cp chemkin_of8/reactions constant/chemFFCM2
    cp chemkin_of8/thermo    constant/thermFFCM2
    if run_solver chemkinToFoam_files; then
        echo "== RESULT: chemkinToFoam-generated files load and run under OF8"
    else
        echo "== RESULT: FAILED with both chemistry file versions"
    fi
fi
ls -d [0-9]* 2>/dev/null | tr '\n' ' '; echo
