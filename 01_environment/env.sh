# Environment for OpenFOAM 8 + detonationFoam v1.2 on TACC Stampede3.
# Usage (login node, compute node, or inside a Slurm job):
#     source ~/ozone_detonation/01_environment/env.sh
#
# Why each line exists is explained in 01_environment/README.md.

# 1. TACC's OpenFOAM 8 was built with Intel 23.1 + Intel MPI 21.9.
#    The default environment has intel/24.0 + impi/21.11, so swap them.
module purge  > /dev/null 2>&1
module load TACC > /dev/null 2>&1
module swap intel intel/23.1 > /dev/null 2>&1
module swap impi  impi/21.9  > /dev/null 2>&1
module load openfoam/8

# 2. Keep compiled user code (detonationFoam binaries and libraries) in $WORK.
#    The module hard-codes $SCRATCH, which is purged after 10 days.
export WM_PROJECT_USER_DIR=$WORK/OpenFOAM/$USER-$WM_PROJECT_VERSION
export FOAM_USER_APPBIN=$WM_PROJECT_USER_DIR/platforms/$WM_OPTIONS/bin
export FOAM_USER_LIBBIN=$WM_PROJECT_USER_DIR/platforms/$WM_OPTIONS/lib
export FOAM_RUN=$SCRATCH/ozone_detonation
export PATH=$FOAM_USER_APPBIN:$PATH
export LD_LIBRARY_PATH=$FOAM_USER_LIBBIN:$LD_LIBRARY_PATH

# 3. Fix a packaging bug in the TACC module: it sets FOAM_LIBBIN to the ThirdParty
#    folder. OpenFOAM's own etc/config.sh/settings sets it to the line below.
export FOAM_LIBBIN=$WM_PROJECT_DIR/platforms/$WM_OPTIONS/lib

mkdir -p "$FOAM_USER_APPBIN" "$FOAM_USER_LIBBIN" "$FOAM_RUN"
