#!/bin/bash
#SBATCH -J build_detFoam          # job name
#SBATCH -p skx-dev                # debug queue: 48-core Skylake nodes, max 2 h
#SBATCH -N 1                      # 1 node
#SBATCH -n 1                      # 1 task; make runs in parallel on the node's cores
#SBATCH -t 00:45:00               # wall-time limit (expected ~10-20 min)
#SBATCH -A TG-MCH260175           # allocation to charge
#SBATCH -o build_%j.log           # stdout+stderr -> build_<jobid>.log
#
# Builds detonationFoam v1.2 (branch detonationFoam_V1.2_OF8) against TACC's OpenFOAM 8.
# Submit from the login node:   cd ~/ozone_detonation/02_build && sbatch build.slurm

set -u
# Submit from $SCRATCH (e.g. $SCRATCH/ozone_detonation/logs), never from $HOME: jobs whose
# working dir / output file were in $HOME were killed by the system at ~2 min (2026-11-17).
case "${SLURM_SUBMIT_DIR:-}" in "$HOME"|"$HOME"/*) echo "WARNING: submitted from \$HOME ($SLURM_SUBMIT_DIR); submit from \$SCRATCH instead";; esac
source ~/ozone_detonation/01_environment/env.sh
export WM_NCOMPPROCS=48           # let wmake/make compile up to 48 files at once

# Compiler: TACC's mpiicpc wrapper uses the LLVM-based icpx (I_MPI_CXX=icpx), the same
# compiler that built TACC's OpenFOAM 8. See 02_build/README.md, "Build problems and fixes".
echo "C++ compiler behind mpiicpc: $(mpiicpc --version 2>&1 | grep -v remark | head -1)"

# Delete any previous build outputs so the final check reflects only this build.
rm -f "$FOAM_USER_APPBIN/detonationFoam_V2.0" "$FOAM_USER_LIBBIN"/lib{dynamicMesh2D,dynamicFvMesh2D,chemistryModel_DLB,fluxSchemes_improved}.so

echo "== Job $SLURM_JOB_ID on $(hostname) at $(date)"
module -t list 2>&1 | tr '\n' ' '; echo
echo "WM_OPTIONS=$WM_OPTIONS  FOAM_USER_APPBIN=$FOAM_USER_APPBIN  FOAM_USER_LIBBIN=$FOAM_USER_LIBBIN"

# Compile from a scratch copy (TACC: compute nodes should do their I/O in $SCRATCH).
# Only the finished binaries are written to $WORK (FOAM_USER_APPBIN / FOAM_USER_LIBBIN).
SRC=$WORK/src/detonationFoam
BLD=$SCRATCH/build/detonationFoam
rm -rf "$BLD"; mkdir -p "$(dirname "$BLD")"
cp -r "$SRC" "$BLD"
echo "== Source: $SRC (branch $(git -C $SRC rev-parse --abbrev-ref HEAD), commit $(git -C $SRC rev-parse --short HEAD))"

# icpx rejects 12 lines written as copy-initialization from a tmp<> field
# ("conversion ... is ambiguous"). The patch rewrites them as direct initialization
# (T x = expr;  ->  T x(expr);). Same meaning, no physics change. It is applied
# only to this scratch copy; $WORK/src/detonationFoam stays untouched.
echo "== Applying patches/icpx_direct_init.patch"
patch -p1 -d "$BLD" < ~/ozone_detonation/02_build/patches/icpx_direct_init.patch || { echo "PATCH FAILED"; exit 1; }

cd "$BLD/applications/solvers/detonationFoam_V2.0"
echo "== Running Allwmake (unmodified, from the detonationFoam repository) at $(date)"
# The repository stores Allwmake without the execute bit (mode 644), so './Allwmake'
# gives "Permission denied". Run it with sh, which its own '#!/bin/sh' line names.
sh ./Allwmake 2>&1
echo "== Allwmake finished at $(date)"

echo "== Verification"
status=0
for f in "$FOAM_USER_APPBIN/detonationFoam_V2.0" \
         "$FOAM_USER_LIBBIN/libdynamicMesh2D.so" \
         "$FOAM_USER_LIBBIN/libdynamicFvMesh2D.so" \
         "$FOAM_USER_LIBBIN/libchemistryModel_DLB.so" \
         "$FOAM_USER_LIBBIN/libfluxSchemes_improved.so"; do
    if [ -f "$f" ]; then
        echo "OK      $f"
        missing=$(ldd "$f" | grep "not found")
        [ -n "$missing" ] && { echo "  unresolved libraries:"; echo "$missing"; status=1; }
    else
        echo "MISSING $f"; status=1
    fi
done
echo "== detonationFoam_V2.0 -help"
detonationFoam_V2.0 -help 2>&1 | head -30
echo "== BUILD STATUS: $([ $status -eq 0 ] && echo SUCCESS || echo FAILED)"
exit $status
