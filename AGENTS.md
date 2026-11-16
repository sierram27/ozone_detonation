# Rules for AI agents working in this repository

These rules apply to any AI coding agent (Claude Code, etc.) working on this project.

## Workflow
1. **Work one step at a time and check in.** After each step, stop. Explain what was done and why, what was verified (with evidence), what is unresolved, and the proposed next action. Wait for the user's go-ahead before continuing.
2. **Teach as you go.** The user is learning this workflow. Explain commands and concepts in plain language, not just results.
3. **Document every step.** Keep the top-level `README.md` concise and current: an overview plus a progress log. Put details in the step directory's own `README.md`.
4. **Commit and push after each step** to this repository (`ozone_detonation`, branch `main`), with a clear message.
5. **Keep the layout small.** Use a few numbered working directories (`01_environment/`, `02_build/`, `03_case/`, `04_znd_init/`, `05_runs/`, `docs/`). Each one has a Markdown file explaining it.

## Science and code
6. **Inspect before modifying.** Read the source files, documentation and scripts before proposing changes.
7. **Reuse existing work.** Prefer Dr. Ryan Johnson's Stanford-collaboration case and ZND scripts (`drryjoh/stanford_collaboration`, `Wang/nn_chemistry/`) over new implementations. Do not build a new detonation simulation from scratch.
8. **Preserve FFCM2** and the H2/O2/Ar mixture throughout the baseline.
9. **Minimize changes.** Change only what is needed for OpenFOAM 8 / detonationFoam v1.2 compatibility and stability. Never change the physical model just to get rid of a numerical error. Record every change in `03_case/CHANGES.md`.
10. **Don't claim success without evidence.** Back claims with log lines, file contents or checks. Keep a *software smoke test* separate from *physical validation*.
11. **Never push to upstream repositories** (stanford_collaboration, detonationFoam). They are read-only references.

## TACC Stampede3
12. **Compute on compute nodes only.** TACC policy says AI-assisted workloads must run on compute nodes. On login nodes, do only light file management, git, `sbatch`, `squeue`, `scancel`, and reading logs. All compiling, meshing, Python processing and solver runs go in Slurm batch jobs.
13. **Watch costs.** Charge allocation `TG-MCH260175` unless told otherwise. Before any job larger than a small `skx-dev` debug job (more than 2 nodes or more than 30 min), show the user the partition, node/core count, wall time and estimated SUs, and get approval.
14. **Run jobs in `$SCRATCH`, which is purged after 10 days.** Keep builds and important results in `$WORK`. Do not run jobs in `$HOME`.
15. **Never request, store or expose** passwords, MFA/Duo codes, tokens or private keys. The user signs in interactively. The agent reuses the SSH ControlMaster connection (`ssh stampede3 ...`).
