# Sierra's shell aliases for Stampede3 (bash), translated from the Mac ~/.zshrc.
# Loaded by one line in ~/.bashrc on Stampede3:
#   [ -f ~/ozone_detonation/01_environment/stampede_aliases.sh ] && source ~/ozone_detonation/01_environment/stampede_aliases.sh
# Interactive shells only: batch jobs and scripted "ssh stampede3 '...'" commands are not affected
# (the cd-with-listing function below would otherwise print a listing at every cd in a job script).
[[ $- == *i* ]] || return 0

# Mac "home" -> "log": the folder jobs are submitted from and write their logs to
alias log='cd $SCRATCH/ozone_detonation/logs'

alias ll='ls -lF --color=auto'     # Mac: ls -lFG. On Linux (GNU ls) -G means "hide the group column", not colour
alias ..='cd ..'
alias ...='cd ../../'
alias ....='cd ../../../'
alias .....='cd ../../../../'
alias ......='cd ../../../../../'
alias clc='clear'
alias jot='vim'
alias p='readlink -f'
# Mac: "conda activate sdtoolbox". On Stampede3 SDToolbox + Cantera live in this Python venv (see 04_znd_init)
alias sdtoolbox='module load python/3.12.11 > /dev/null 2>&1; source $WORK/venvs/znd/bin/activate'

# Mac: cd lists the new folder (ls -lF) after changing into it
cd() {
    builtin cd "$@" || return
    ls -lF
}
