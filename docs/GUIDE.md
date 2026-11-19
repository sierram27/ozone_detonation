# Step-by-step guide: running the 2D H₂–O₂–Ar detonation on Stampede3 by yourself

This guide covers the whole workflow of this project, from logging in to looking at results in ParaView. With it you should be able to repeat or extend the work without help. Each step says **what to type**, **what it does and why**, and **what you should see**.

The other READMEs in this repository hold the background and the history: what was changed, which problems came up and how they were fixed. This guide is the "how to run it" part. Where a step has more background, the guide points to it.

---

## Contents
0. [How to read this guide](#0-how-to-read-this-guide)
1. [Ideas you need first](#1-ideas-you-need-first)
2. [Logging in to Stampede3](#2-logging-in-to-stampede3)
3. [Where everything lives](#3-where-everything-lives)
4. [Copying your scripts from the Mac to Stampede3](#4-copying-your-scripts-from-the-mac-to-stampede3)
5. [Rules and costs](#5-rules-and-costs)
6. [One-time setup (already done)](#6-one-time-setup-already-done)
7. [Making the initial condition (ZND initialization)](#7-making-the-initial-condition-znd-initialization)
8. [Running a simulation: smoke test, then a real run](#8-running-a-simulation-smoke-test-then-a-real-run)
9. [Continuing `prop1` until the shock reaches 475 mm](#9-continuing-prop1-until-the-shock-reaches-475-mm)
   - 9b. [Going past 0.5 m: window recycling](#9b-going-past-05-m-window-recycling-cycles-of-030-m)
10. [Watching a job and judging whether it is healthy](#10-watching-a-job-and-judging-whether-it-is-healthy)
11. [Analysis: shock speed and cell pattern](#11-analysis-shock-speed-and-cell-pattern)
12. [ParaView: VTK files and pictures on your Mac](#12-paraview-vtk-files-and-pictures-on-your-mac)
13. [Keeping results safe](#13-keeping-results-safe)
14. [Recording your work in git](#14-recording-your-work-in-git)
15. [Troubleshooting](#15-troubleshooting)
16. [Cheat sheet](#16-cheat-sheet)

---

## 0. How to read this guide
- **Two computers.** Every command block says where to type it:
  - **[Mac]**: Terminal on your laptop. The repository is at `~/Documents/Research/repos/ozone_detonation`.
  - **[Stampede3]**: a terminal that is logged in to Stampede3 (see Part 2). The prompt looks like `login2.stampede3(1)$`.
- **Placeholders** are written in angle brackets, e.g. `<jobid>`. Replace the whole thing, brackets included, e.g. `3734119`.
- Lines starting with `#` inside command blocks are comments. You don't need to type them.
- **Times on Stampede3 are US Central (CST).** Your Mac shows Eastern, one hour later.

---

## 1. Ideas you need first

**Supercomputer layout.** Stampede3 has two kinds of machines:
- **Login nodes.** You land here when you log in. They are shared by hundreds of users, so you only do light work on them: editing, copying files, `git`, submitting and checking jobs, reading logs.
- **Compute nodes.** Thousands of machines with 48 cores each on the `skx` partitions. You don't log in to them directly. You ask for them with a **batch job**.

**Slurm** is the program that runs batch jobs.
- You write a **job script** (a `.slurm` file). Its first lines (`#SBATCH ...`) say how many nodes, for how long, and which allocation pays.
- `sbatch <script>` puts the job in the **queue**. Slurm starts it when nodes are free and writes everything the script prints to an **output file**.
- `squeue` shows waiting and running jobs; `sacct` shows finished ones.

**SU (service unit)** is the currency of the allocation. On `skx-dev` and `skx`, **1 SU = 1 node for 1 hour**. A 2-node job that runs 2 hours costs 4 SU. You are charged for the time actually used, not the time requested. The project allocation is **TG-MCH260175** (about 3100 SU at the start).

**Partitions (queues)** used here:
- `skx-dev`: for development; at most 2 hours per job, starts within minutes. Everything in this project so far used it.
- `skx`: for production; up to 48 hours per job, but the wait can be many hours.

**OpenFOAM case.** A simulation is a folder with three kinds of subfolders:
- `constant/`: physics and mesh. Chemistry (FFCM2), thermodynamics, the mesh in `constant/polyMesh`, AMR settings, solver type.
- `system/`: numerics and run control. `controlDict` (time step, end time, write interval), `fvSchemes`, `fvSolution`, `decomposeParDict`.
- **Time folders** (`0`, `1e-06`, `2e-06`, …): the solution (p, T, U, species, …) at each saved time. `0/` is the initial condition.

**Parallel run.**
- The domain is cut into 96 pieces, one per CPU core, by `decomposePar`. Each piece is a `processor0` … `processor95` folder with its own time folders.
- The solver runs on all 96 cores at once using MPI (`ibrun detonationFoam_V2.0 -parallel`).
- To look at the whole domain again, the pieces are joined back together by `reconstructParMesh` (mesh) and `reconstructPar` (fields).

**AMR (adaptive mesh refinement).** The base mesh has 0.5 mm cells. Near the detonation front, cells are split into 0.25 mm (level 1) and 0.125 mm (level 2) cells, and joined again behind it. So the mesh changes during the run, which is why `reconstructParMesh` is needed before `reconstructPar`.

**Courant number (Co).**
- Co = how far the flow moves in one time step, measured in cells.
- The solver adjusts the time step Δt to keep **Co ≈ 0.1**. That gives Δt ≈ 7–9 ns. Δt is never larger than 9 ns (`maxDeltaT`).
- One step after each AMR refinement can go above 0.1. Up to about 0.4 is normal here.

**Restart.**
- Every 1 µs of simulated time, the solver saves all fields.
- If a job stops, a new job with the same run name continues from the latest save. The script detects this through a marker file `.decomposed_ok` in the run folder.
- Work done after the last save is lost and recomputed, so at most 1 µs.

**What is being simulated.** A 2D channel, 0.5 m × 0.06 m, filled with 2H₂ + O₂ + 7Ar at 6.67 kPa and 298 K. A detonation is placed at x ≈ 0.05 m at t = 0, as a 1D ZND profile behind a wavy front. It travels to the right at about the CJ speed, 1616 m/s. The "leading shock location" printed by the solver is how far it has got.

---

## 2. Logging in to Stampede3

Do this at the start of every working session.

**[Mac]**
```bash
stampede
```
- `stampede` is a shortcut (alias in `~/.zshrc`) for `expect ~/.ssh/scripts/stampede.exp`. The script types your TACC password from the macOS Keychain.
- Then **type your 6-digit Duo/TACC token code** and press Return.
- Alternatively, run `ssh stampede3` and type the password yourself.

**What you should see:** a TACC welcome banner and a prompt like `login2.stampede3(1)$`.

**Why only once per session:** your `~/.ssh/config` turns this first login into a "master" connection (`ControlMaster`). Every later `ssh stampede3`, `scp` or `rsync` from the Mac reuses it with no password or Duo. The master stays alive while that terminal is open, and up to 12 hours after you close it (`ControlPersist 12h`).

**The connection is lost** when the Mac goes into full sleep for a while, loses Wi-Fi, or changes network (e.g. going home). Signs:
- a command asks for your password again
- `Permission denied (publickey,keyboard-interactive)`

Then just run `stampede` again.

**Checking the connection:**

**[Mac]**
```bash
ssh -O check stampede3     # "Master running (pid=...)" = connection alive
ssh -O exit stampede3      # close it on purpose
```

**Never** put your password or Duo codes into a file or script, and never run `ssh-keygen` on Stampede3 (TACC says it breaks batch jobs).

---

## 3. Where everything lives

**Your three storage areas on Stampede3:**

| Name | Path | Size | Backed up? | What goes there |
|---|---|---|---|---|
| `$HOME` (`~`) | `/home1/12029/smartinez627` | 15 GB | yes | the copy of this repository: `~/ozone_detonation` |
| `$WORK` | `/work2/12029/smartinez627/stampede3` | 1 TB | no | source code, the compiled solver, Python environment, **results you want to keep** |
| `$SCRATCH` | `/scratch/12029/smartinez627` | no limit | no, and **files not used for 10 days are deleted** | where jobs run: run folders and job output files |

`$HOME`, `$WORK` and `$SCRATCH` are shell variables. On Stampede3 you can type `cd $SCRATCH` instead of the full path.

**Project folders on Stampede3:**

| Path | Contents |
|---|---|
| `~/ozone_detonation/` | copy of this repository (scripts, case). Not a git repository there; it is updated from the Mac with `rsync` (Part 4) |
| `$WORK/src/detonationFoam` | detonationFoam source code (branch `detonationFoam_V1.2_OF8`) |
| `$WORK/src/stanford_collaboration` | Dr. Johnson's repository (read-only reference; ZND scripts) |
| `$WORK/src/SDToolbox` | Caltech Shock and Detonation Toolbox (ZND/CJ calculations) |
| `$WORK/venvs/znd` | Python environment (Cantera 3.1.0, pandas 2.2.3, …) |
| `$WORK/OpenFOAM/smartinez627-8/platforms/linux64IccDPInt32Opt/{bin,lib}` | the compiled solver `detonationFoam_V2.0` and its libraries |
| `$SCRATCH/ozone_detonation/init_case` | the ZND-initialized case (Part 7) |
| `$SCRATCH/ozone_detonation/prop1` | **the 200 µs run** (all saves, 96 processor folders) |
| `$SCRATCH/ozone_detonation/logs` | **submit every job from here**; job output files land here |
| `$WORK/ozone_detonation/runs/prop1/` | kept copies: solver logs, `analysis_<time>/`, `snapshot_0.0002/` (restartable 200 µs state), `prop1_vtk_0.0002.tar.gz` |

**On the Mac:**

| Path | Contents |
|---|---|
| `~/Documents/Research/repos/ozone_detonation` | the git repository (pushed to GitHub `sierram27/ozone_detonation`) |
| `…/local_data/` | big downloads (VTK files). Ignored by git |

**Scripts in the repository:**

| Script | Folder | What it does |
|---|---|---|
| `env.sh` | `01_environment/` | loads OpenFOAM 8 and points to our compiled solver. Every job uses it |
| `build.slurm` | `02_build/` | compiles detonationFoam (one-time) |
| `check_case.slurm` | `03_case/` | quick test that OpenFOAM 8 can read the case (optional) |
| `init.slurm` | `04_znd_init/` | makes the ZND initial condition |
| `smoke.slurm` | `05_runs/` | **the main run script**: new run or restart, solver, summary |
| `prop1_to_475mm.slurm` | `05_runs/` | continues `prop1` until the shock reaches 475 mm (uses `smoke.slurm`) |
| `analyze.slurm` + `analyze_prop.py` | `05_runs/` | shock speed, cell-pattern plots, optional snapshot to `$WORK` |
| `to_vtk.slurm` | `05_runs/` | writes one saved time as VTK for ParaView |
| `paraview_maxp.py` | `05_runs/` | ParaView startup script for the Mac |

---

## 4. Copying your scripts from the Mac to Stampede3

You edit files on the Mac (in VS Code) and keep them in git there. The job scripts read the copy in `~/ozone_detonation` on Stampede3. **After any change on the Mac, copy it over** before submitting jobs.

**[Mac]**
```bash
rsync -av --exclude .git --exclude local_data \
    ~/Documents/Research/repos/ozone_detonation/ stampede3:ozone_detonation/
```
- `rsync` copies only files that changed. `-a` keeps permissions and dates, `-v` lists what it copied.
- The **trailing `/`** after `ozone_detonation/` on the Mac side means "the contents of this folder". Without it, you'd get `ozone_detonation/ozone_detonation`.
- `stampede3:ozone_detonation/` means "the folder `ozone_detonation` in my home directory on Stampede3".
- `--exclude .git` skips git's internal data. `--exclude local_data` skips the big VTK downloads.
- It never deletes files on Stampede3.

**Checking that a script is the same on both sides** (optional):

**[Mac]**
```bash
md5 -q ~/Documents/Research/repos/ozone_detonation/05_runs/smoke.slurm
ssh stampede3 'md5sum ~/ozone_detonation/05_runs/smoke.slurm'
```
The two long hexadecimal numbers must be identical.

---

## 5. Rules and costs

**TACC rules that matter here:**
- **Compute only in batch jobs.** No solver runs, compiling, meshing or Python processing on login nodes.
- **Jobs run in `$SCRATCH`.** Submit every job from `$SCRATCH/ozone_detonation/logs` (`cd` there first). The job's working directory and output file are then in `$SCRATCH`, not `$HOME`. Every script prints a WARNING if submitted from `$HOME`.
- **AI tools:** TACC's user guide says AI-assisted workloads must run on compute nodes only, and you are responsible for whatever an AI tool submits. When you submit jobs yourself, this guide is all you need.

**Typical costs** (2 nodes = 96 cores, `skx-dev`):

| Job | Nodes × time | SU |
|---|---|---|
| smoke test (2 µs) | 2 × about 5 min | about 0.15 |
| propagation, 2 h job | 2 × 2 h | ≤ 4 (about 70–80 µs of simulated time) |
| analysis / VTK | 1 × 3–5 min | under 0.1 |

The solver needs **about 85 seconds of wall time per simulated microsecond** on 2 nodes.

**Checking how many SU are left:**

**[Stampede3]**
```bash
/usr/local/etc/taccinfo
```
It prints a table of your projects with "Avail SUs". It is updated about once a day, so recent jobs may not show yet.

---

## 6. One-time setup (already done)

These steps were done on 2026-11-16 and do **not** need repeating, unless TACC removes something (e.g. a module update) or you work on a new account. They are listed so you know what exists and how to rebuild it. Details: `README.md` ("Reproduce from scratch"), `02_build/README.md`, `04_znd_init/README.md`.

**6.1 Download source code** (light, so allowed on the login node)

**[Stampede3]**
```bash
mkdir -p $WORK/src && cd $WORK/src
git clone -b detonationFoam_V1.2_OF8 https://github.com/JieSun-pku/detonationFoam.git
git clone https://github.com/drryjoh/stanford_collaboration.git
```
These are read-only references. Never push to them.

**6.2 Python environment for the ZND scripts**

**[Stampede3]**
```bash
module load python/3.12.11
python3 -m venv $WORK/venvs/znd && source $WORK/venvs/znd/bin/activate
pip install cantera==3.1.0 numpy scipy "pandas==2.2.3" matplotlib
```
- A "venv" is a private Python installation where you can install packages.
- pandas is pinned to 2.2.3 because the Stanford scripts use an option removed in pandas 3.

SDToolbox (Caltech) is installed next to it. See `README.md`, step 3 of "Reproduce from scratch", for the commands.

**6.3 Compile detonationFoam** (a batch job, about 10 minutes, about 0.2 SU)

**[Stampede3]**
```bash
cd $SCRATCH/ozone_detonation/logs
sbatch ~/ozone_detonation/02_build/build.slurm
```
- The script loads `env.sh`, copies the source to `$SCRATCH` and applies a small syntax patch for TACC's Intel compiler (`02_build/patches/`). It then compiles with `Allwmake` and installs the solver into `$WORK/OpenFOAM/...`.
- **Success:** the output file `build_<jobid>.log` ends with `BUILD STATUS: SUCCESS`.
- **Check later** that the solver is found:

  **[Stampede3]**
  ```bash
  source ~/ozone_detonation/01_environment/env.sh; which detonationFoam_V2.0
  ```

---

## 7. Making the initial condition (ZND initialization)

**Needed only for a NEW run started from t = 0.** The existing `prop1` run doesn't need it. The result is in `$SCRATCH/ozone_detonation/init_case`. Because `$SCRATCH` is purged, re-run this before any new run if that folder is gone.

**What it does** (background in `04_znd_init/README.md`):
1. Builds the mesh (`blockMesh`) and writes the cell-centre coordinates.
2. Runs Dr. Johnson's scripts:
   - computes the CJ speed and the 1D ZND profile (temperature, pressure, species behind the shock) with SDToolbox and Cantera
   - maps that profile onto the 2D mesh behind the wavy front x = 0.05 + 0.005·sin(4πy/0.06) m
   - writes `0/T`, `0/p`, `0/U` and the 9 species
3. Checks the result (15 checks), then lets OpenFOAM take 2 test steps.

**[Stampede3]**
```bash
cd $SCRATCH/ozone_detonation/logs
sbatch ~/ozone_detonation/04_znd_init/init.slurm
```
**Takes** about 7 minutes on 1 node (about 0.1 SU).

**Success:** in `znd_init_<jobid>.log`, the verification shows **15/15 PASS**, D_CJ ≈ 1616 m/s, and the 2 OpenFOAM steps run.

---

## 8. Running a simulation: smoke test, then a real run

All runs use `05_runs/smoke.slurm`. You control it with **variables** given on the `sbatch` line, in the form `--export=ALL,NAME=value,NAME=value`. `ALL` passes your normal environment too; always keep it.

| Variable | Meaning | Default |
|---|---|---|
| `RUN_NAME` | run folder name: `$SCRATCH/ozone_detonation/<RUN_NAME>` | `smoke` |
| `END_TIME` | simulated time to stop at, in seconds (`2e-4` = 200 µs) | `2e-6` |
| `WRITE_INT` | how often to save, in seconds (`1e-6` = every 1 µs) | `5e-7` |
| `SW_LIMIT` | stop when the leading shock reaches this x, in metres | not set (never) |
| `RECONSTRUCT` | `1` = join the pieces after the run | `0` |

You can also override the `#SBATCH` settings on the command line, e.g. `-t 02:00:00` for the time limit, or `-J name` for the job name.

**What the script does, in order** (each stage prints a line starting with `==`):
1. **[1] Setup or restart.**
   - If `<run>/.decomposed_ok` exists, it's a **restart**: it continues from the latest save.
   - Otherwise it's a **new run**. It copies the settings from the repository case (`03_case/coarse_mesh_slip_of8`) and the mesh and initial fields from `init_case`.
   - It then writes `END_TIME`, `WRITE_INT` (and `SW_LIMIT`) into the run's own copy of the settings. The repository is never changed.
2. **[2] decomposePar.** New runs only: cuts the domain into 96 pieces (16 along x × 6 along y) and creates `.decomposed_ok`.
3. **[3] Solver.**
   - Runs `ibrun detonationFoam_V2.0 -parallel`, writing to `log.detonationFoam.<jobid>` in the run folder.
   - A **time guard** stops the solver 4 minutes before the job's time limit (exit code 124), so the summary still runs.
4. **[4] Summary.** Which models were used, steps, last time, last shock position, maximum Courant number, pressure and temperature range, and the number of error lines.
5. **[6] Copy logs** to `$WORK/ozone_detonation/runs/<RUN_NAME>/`.

> **Warning: the run name decides "new" or "restart".**
> - A run folder **without** `.decomposed_ok` is treated as a failed setup: it is **deleted** and rebuilt from t = 0.
> - Never reuse the name of a run you want to keep unless its `.decomposed_ok` exists.
> - For a new experiment, choose a new name (e.g. `prop2`).

**8.1 Smoke test** (does everything work? about 5 minutes)

**[Stampede3]**
```bash
cd $SCRATCH/ozone_detonation/logs
sbatch --export=ALL,RUN_NAME=smoke3 ~/ozone_detonation/05_runs/smoke.slurm
```
- Runs to 2 µs.
- **Success:** the summary shows `FATAL/FPE/NaN lines: 0`, about 350 steps, `last Time = 2e-06`, and Co around 0.1.

**8.2 A new propagation run** (example: new run `prop2` to 100 µs, one 2 h job, about 4 SU)

**[Stampede3]**
```bash
cd $SCRATCH/ozone_detonation/logs
sbatch -t 02:00:00 -J det_prop2 --export=ALL,RUN_NAME=prop2,END_TIME=1e-4,WRITE_INT=1e-6 \
    ~/ozone_detonation/05_runs/smoke.slurm
```
A 2 h job covers about 75–80 µs. For longer runs, see 8.3.

**8.3 Continuing a run** (restart)

Submit **the same command again**, with a later `END_TIME` if needed. Each job continues from the latest save.

To queue several jobs that run **one after another**, use a dependency:

**[Stampede3]**
```bash
cd $SCRATCH/ozone_detonation/logs
S=~/ozone_detonation/05_runs/smoke.slurm
E="--export=ALL,RUN_NAME=prop2,END_TIME=2e-4,WRITE_INT=1e-6"
j1=$(sbatch --parsable -t 02:00:00 -J det_prop2 $E $S | tail -1); echo $j1
j2=$(sbatch --parsable -t 02:00:00 -J det_prop2 -d afterok:$j1 $E $S | tail -1); echo $j2
```
- `--parsable` makes `sbatch` print just the job number. `| tail -1` drops TACC's banner text, which would otherwise end up in `$j1`.
- `-d afterok:$j1` means "start only after job `$j1` has finished successfully".
- **If the first job is cancelled**, the second stays pending forever with reason `DependencyNeverSatisfied`. Cancel it with `scancel <jobid>` and resubmit.

---

## 9. Continuing `prop1` until the shock reaches 475 mm

**Where things stand:** `prop1` is saved to **200 µs**, with the leading shock at **x = 375.7 mm**. The channel ends at 500 mm. The goal is to continue until the shock reaches **475 mm**, 25 mm before the outlet.

**The script:** `05_runs/prop1_to_475mm.slurm`. It is a short wrapper that sets:
- `RUN_NAME=prop1`
- `WRITE_INT=1e-6` (save every 1 µs, as before)
- `SW_LIMIT=0.475`: the solver's built-in shock-position stop (`SW_position_limit`) is set to 0.475 m in the run's copy of `constant/solverTypeProperties`. When the printed "Leading shock location" reaches 0.475 m, the solver stops by itself.
- `END_TIME=3e-4` (300 µs): only a backstop in case the position stop never triggers.

It then runs `smoke.slurm`, which does the restart, the solver and the summary.

**Expected:**
- 99 mm at about 1.6 mm/µs ≈ **62 µs** of simulated time, ending near t ≈ 262 µs.
- At about 85 s per µs that is about **90 minutes** on 2 nodes.
- **Cost: 2 nodes × up to 2 h = at most 4 SU** (`skx-dev`).

**Safety built into the wrapper:** if `$SCRATCH/ozone_detonation/prop1` has been purged or is incomplete, it restores the 200 µs snapshot from `$WORK/ozone_detonation/runs/prop1/snapshot_0.0002` first. Without this, `smoke.slurm` would start the run again from t = 0.

**9.1 Make sure Stampede3 has the latest scripts**

**[Mac]**
```bash
rsync -av --exclude .git --exclude local_data \
    ~/Documents/Research/repos/ozone_detonation/ stampede3:ozone_detonation/
```

**9.2 Check the starting point**

**[Stampede3]**
```bash
ls $SCRATCH/ozone_detonation/prop1/.decomposed_ok
ls -d $SCRATCH/ozone_detonation/prop1/processor0/[0-9]* | sed 's|.*/||' | sort -g | tail -1
squeue -u $USER
```
- **First line:** prints the path if the marker exists. If it says "No such file", the wrapper will restore the snapshot; that's fine.
- **Second line:** the latest save. Expect `0.0002`.
- **Third line:** your jobs in the queue. Only the header line should show (no other job running on `prop1`). **Never run two jobs on the same run folder at the same time.**

**9.3 Submit**

**[Stampede3]**
```bash
cd $SCRATCH/ozone_detonation/logs
sbatch ~/ozone_detonation/05_runs/prop1_to_475mm.slurm
```
- It prints a TACC banner and then `Submitted batch job <jobid>`. **Write down the job number**; you need it for the analysis.
- **If you'd rather use shorter jobs** (e.g. while the cancellation problem is unresolved), override the time limit:

  **[Stampede3]**
  ```bash
  sbatch -t 00:30:00 ~/ozone_detonation/05_runs/prop1_to_475mm.slurm
  ```
  A 30-minute job covers about 18 µs, so you'd need about 4 in a row (each costs at most 1 SU). Submit the next one after the previous one has finished.

**9.4 Watch it** (Part 10). Specific to this run, the shock position:

**[Stampede3]**
```bash
grep "^Leading shock" $SCRATCH/ozone_detonation/prop1/log.detonationFoam.<jobid> | tail -1
```
It should grow by about 1.6 mm per µs: 0.38 m at the start, 0.475 m at the end.

**9.5 How it ends and what to check**

The Slurm output file is `$SCRATCH/ozone_detonation/logs/det_prop1_475_<jobid>.log`. Look at its end:

**[Stampede3]**
```bash
tail -40 $SCRATCH/ozone_detonation/logs/det_prop1_475_<jobid>.log
```
- **Reached 475 mm:**
  - `last Leading shock location = 0.475… m` (or just above).
  - The solver exits at that moment **without writing a final save**, so the last saved time is the previous 1 µs save, with the shock about 1–2 mm short of 475 mm.
  - The solver leaves through a plain `exit()`, without shutting MPI down cleanly, so MPI may print termination messages, and the exit code may not be 0. That is expected. Check the shock position and the `FATAL/FPE/NaN lines: 0` line instead.
- **Ran out of time first** (`solver exit code 124`, shock below 0.475): submit the **same command** again (9.3). It continues from the latest save.
- **Cancelled after about 2 minutes** with no output file (Part 15): submit the same command again.

**After it finishes:** run the analysis (Part 11) and, if you want pictures, the VTK conversion (Part 12). The analysis must list **all** solver jobs of `prop1`: `3731639:3732550:3733283:3734119` plus your new job number(s).

---

## 9b. Going past 0.5 m: window recycling (cycles of 0.30 m)

**Idea:** the channel is only 0.5 m long. Each **cycle** runs until the front reaches 0.475 m. Then a short job, `recycle.slurm`:
1. takes the last save
2. shifts it 0.30 m to the left, so the front lands at about 0.175 m with about 0.175 m of burned gas behind it
3. fills the rest of the channel with fresh gas
4. starts a new run folder

The soot-foil record `maxp` moves with the shift. Each cycle adds 0.30 m of travel:

| Run folder | Lab distance covered | Made by |
|---|---|---|
| `prop1` | 0.05 → 0.475 m | done (jobs 3731639 … 3738975) |
| `prop1_cycle1` | 0.475 → 0.775 m | recycle of `prop1` |
| `prop1_cycle2` | 0.775 → 1.075 m | recycle of `prop1_cycle1` |
| `prop1_cycle3` | 1.075 → 1.375 m | recycle of `prop1_cycle2` |

**Lab position = domain position + OFFSET.** The OFFSET is in `<run folder>/recycle_info.txt` (0.30 for `prop1_cycle1`, 0.60 for `prop1_cycle2`, …). Positions printed in the solver log are **domain** positions (0–0.5 m).

**What it costs the physics:**
- Each recycle averages the 0.125 mm front cells onto 0.5 mm cells. The adaptive mesh refinement (AMR) rebuilds the fine cells within a few steps, but the lost detail stays lost.
- Each recycle also drops the burned gas far behind the front.
- So the soot foil just after a recycle shows the front recovering. Judge regularity on the later part of each cycle, and compare cycles with each other.

**Cost per cycle:** about 190 µs of simulated time, about 4.5 h on 2 nodes, about 9 SU. That is three 2 h jobs, plus one recycle job of under 0.5 SU.

**9b.1 Copy the scripts** (Part 4, **[Mac]**): the rsync command from 9.1.

**9b.2 Make the next run folder**

**[Stampede3]**
```bash
squeue -u $USER          # nothing may be running on the source run folder
cd $SCRATCH/ozone_detonation/logs
sbatch --export=ALL,SRC_RUN=prop1,NEW_RUN=prop1_cycle1 ~/ozone_detonation/05_runs/recycle.slurm
```
- `SRC_RUN` is the folder that has just reached 0.475 m. `NEW_RUN` is the folder to create.
- For the next cycles, use `SRC_RUN=prop1_cycle1,NEW_RUN=prop1_cycle2`, then `SRC_RUN=prop1_cycle2,NEW_RUN=prop1_cycle3`, and so on.
- The job takes about 10 minutes. The source run is not changed.
- If `NEW_RUN` already exists and is complete, the job stops without touching it.

**9b.3 Check the recycle job**

**[Stampede3]**
```bash
tail -30 $SCRATCH/ozone_detonation/logs/det_recycle_<jobid>.log
```
What you should see:
- `fresh gas from … cells ahead of the front: p = 6670 Pa, T = 298 K, U = (0, 0, 0)`
- `fields mapped: 13 (expected 13)`
- `max |sum - 1|` very small (below 1e-6)
- `cells beyond x = 0.200 m (not copied): …, of which not fresh gas: 0`
- `leading shock … x = 0.17… m in the domain = 0.47… m lab` (for `prop1_cycle1`; one OFFSET more for each later cycle)
- `checks passed`, then `is ready`

If it says `ERROR`, nothing usable was created. Send the log to someone who can look at it before going on.

**9b.4 Run the cycle** (same command every time, until the cycle reaches 0.475 m)

**[Stampede3]**
```bash
cd $SCRATCH/ozone_detonation/logs
sbatch --export=ALL,RUN_NAME=prop1_cycle1 ~/ozone_detonation/05_runs/cycle_run.slurm
```
- Each job runs up to 2 h (at most 4 SU) and covers about 85 µs, about 0.13 m. **A cycle takes about 3 jobs.**
- Submit the next job only after the previous one has ended.
- The output file is `det_cycle_<jobid>.log`. Judge it as in 9.5:
  - `solver exit code 124` with the shock below 0.475 means "out of time", so submit again.
  - `last Leading shock location = 0.475…` means the cycle is done, so go to 9b.2 for the next cycle.
  - `FATAL/FPE/NaN lines: 0` must hold every time.
- `cycle_run.slurm` refuses a folder without `.decomposed_ok`. Without that safeguard, `smoke.slurm` would wipe it and restart from t = 0.

**9b.5 Analysis of a cycle:** as in Part 11, with `RUN_NAME=prop1_cycle1` and that cycle's job numbers. The speed is unaffected by the offset. For the full soot foil, place each cycle's `maxp` at its OFFSET.

---

## 10. Watching a job and judging whether it is healthy

**Is it queued or running?**

**[Stampede3]**
```bash
squeue -u $USER
```
- `ST` column: `PD` = pending (waiting), `R` = running, `CG` = completing.
- `NODELIST(REASON)`: for pending jobs, the reason, e.g. `(Priority)`, `(Resources)`, `(Dependency)`.

**After it ended:**

**[Stampede3]**
```bash
sacct -j <jobid> -X -o JobID,JobName%15,State%20,Elapsed,NodeList
```
States: `COMPLETED`, `FAILED` (the script returned an error), `TIMEOUT`, `CANCELLED by <uid>`. `CANCELLED by 0` means the system cancelled it, not you.

**Cancel a job** (yours only): `scancel <jobid>`

**Two log files per run job:**
1. **Slurm output file** in `$SCRATCH/ozone_detonation/logs/` (e.g. `det_prop1_475_<jobid>.log`): the stages `== [1]` … `== END` and the summary.
2. **Solver log** in the run folder: `$SCRATCH/ozone_detonation/<run>/log.detonationFoam.<jobid>`. One block per time step.

**Follow the solver live** (press Ctrl-C to stop watching; the job keeps running):

**[Stampede3]**
```bash
tail -f $SCRATCH/ozone_detonation/prop1/log.detonationFoam.<jobid>
```

**Quick health check while it runs:**

**[Stampede3]**
```bash
L=$SCRATCH/ozone_detonation/prop1/log.detonationFoam.<jobid>
grep "^Time = " $L | tail -1                          # simulated time reached
grep "^Leading shock" $L | tail -1                    # shock position
grep "Max Courant" $L | awk '{print $NF}' | sort -g | tail -1   # largest Co so far
grep -ciE "FOAM FATAL|nan|Floating point exception" $L          # see note below
```

**What healthy looks like:**
- **Time:** `Time =` increases by about 0.7 µs per minute of wall time.
- **Courant number:** mostly 0.09–0.10; occasional single values up to about 0.4 right after AMR refinements.
- **Time step:** `deltaT` about 7–9 × 10⁻⁹ s.
- **Shock position:** about 1.6 mm per µs (oscillating; see Part 11).
- **Error count:** the last command prints **1**, from the harmless startup line `sigFpe : Enabling floating point exception trapping`. Anything above 1 needs a look: `grep -niE "FOAM FATAL|nan|Floating point exception" $L | head`.
- **Saves:** new folders `processor0/<time>` appear every 1 µs.

**The summary at the end of the Slurm output file:**

| Line | Healthy value |
|---|---|
| `Number of species = 9 and reactions = 27` | FFCM2 loaded |
| `Selecting dynamicFvMesh dynamicRefineFvMesh2D` | AMR on |
| `solverType = Euler` | inviscid equations, as decided |
| `max Courant number over the run` | below about 0.5 |
| `FATAL/FPE/NaN lines: 0` | no numerical errors |
| `solver exit code 124` + `MPI: 96 KILLED BY SIGNAL: 15` | normal end by the time guard (signal 15 = our stop request). **Any other signal number means a crash** |
| `solver exit code 0` | normal end at `END_TIME` |

---

## 11. Analysis: shock speed and cell pattern

`05_runs/analyze.slurm` (1 node, about 3–5 minutes):
1. Joins the 96 pieces at the latest saved time (`reconstructParMesh`, then `reconstructPar` for maxp, p, T, cellLevel).
2. Writes cell-centre coordinates. This uses TACC's OpenFOAM 12, because this tool is broken in TACC's OpenFOAM 8.
3. Runs `analyze_prop.py`:
   - **Shock speed:** reads "Leading shock location" from all solver logs and fits position against time. It gives the mean speed from 25 µs to the end and over the last 100 µs, plus 2 µs windows.
   - **Fields:** `maxp`, p and T over the whole channel at the final time.
   - **Cell pattern:** a zoom of `maxp` and its Fourier spectra across and along the channel.
4. With `KEEP_SNAPSHOT=1`, it also copies the latest time, in a form you can restart from, to `$WORK` and compares file counts.

**[Stampede3]**
```bash
cd $SCRATCH/ozone_detonation/logs
sbatch --export=ALL,RUN_NAME=prop1,LOGJOB=3731639:3732550:3733283:3734119:<new jobid(s)>,KEEP_SNAPSHOT=1 \
    ~/ozone_detonation/05_runs/analyze.slurm
```
- `LOGJOB` lists **every** solver job of the run, in order, separated by `:`.
- Leave out jobs that were cancelled at 2 minutes: they have no solver log.
- After a restart the solver recomputes from the last save. Where two logs overlap, the script uses the later one.

**Output:**
- `det_analyze_<jobid>.log`: the summary as JSON text. The key lines:
  - `"D_linear_fit_25us_to_end"`: the mean detonation speed in m/s
  - `"D_fit_vs_CJ_percent"`: difference from D_CJ = 1615.9 m/s
- Plots and `prop_summary.json` in `$SCRATCH/ozone_detonation/prop1/analysis_<time>/` and `$WORK/ozone_detonation/runs/prop1/analysis_<time>/`.
- Snapshot in `$WORK/ozone_detonation/runs/prop1/snapshot_<time>/`. The log line `processor files: source N, copy N OK` confirms it.

**Copy the plots to the Mac** (example for a final time of 0.000261; use the folder name you see):

**[Mac]**
```bash
mkdir -p ~/Documents/Research/repos/ozone_detonation/05_runs/results/prop1_475mm
scp 'stampede3:/work2/12029/smartinez627/stampede3/ozone_detonation/runs/prop1/analysis_0.000261/*' \
    ~/Documents/Research/repos/ozone_detonation/05_runs/results/prop1_475mm/
```
The quotes stop your Mac's shell from trying to expand the `*` itself.

**Reading the plots:**

| Plot | What it shows | What to look for |
|---|---|---|
| `shock_speed.png` | top: shock position vs time with the CJ line; bottom: speed in 2 µs windows | position follows the CJ line; speed oscillates around 1616 m/s (±5–10 %) |
| `fields_final.png` | maxp, p, T over the whole channel | a sharp front; diamond-shaped tracks in maxp |
| `maxp_zoom.png` | maxp in the swept region | the cell pattern. Cell width = spacing of the tracks across the channel; cell length = distance between collision points along it |
| `maxp_spectra.png` | which spacings dominate (across / along) | the largest peaks. A peak at 30 mm across = 2 cells in 60 mm |

---

## 12. ParaView: VTK files and pictures on your Mac

**12.1 Write the VTK file** (batch job, about 4 minutes)

**[Stampede3]**
```bash
cd $SCRATCH/ozone_detonation/logs
sbatch --export=ALL,RUN_NAME=prop1 ~/ozone_detonation/05_runs/to_vtk.slurm
```
- Uses the latest saved time. For another time, add `,TIME=<time folder name>`, e.g. `,TIME=0.0001`.
- **Result:** `$WORK/ozone_detonation/runs/prop1/prop1_vtk_<time>.tar.gz`, about 20 MB.
- The output file `det_vtk_<jobid>.log` ends with the archive's path.
- **Fields included:**
  - p, T, U, rho
  - the 9 species
  - `maxp`
  - `Qdot` (heat release rate)
  - `magGradrho` (density gradient, for schlieren-like images)
  - `cellLevel` (AMR level)

**12.2 Download and unpack**

**[Mac]**
```bash
cd ~/Documents/Research/repos/ozone_detonation/local_data
scp stampede3:/work2/12029/smartinez627/stampede3/ozone_detonation/runs/prop1/prop1_vtk_<time>.tar.gz .
mkdir -p prop1_vtk_<time> && tar xzf prop1_vtk_<time>.tar.gz -C prop1_vtk_<time>
ls prop1_vtk_<time>/VTK
```
- The main file is the big `.vtk` file directly inside `VTK/`, e.g. `prop1_34863.vtk`. The number is OpenFOAM's step counter, not a time.
- The subfolders (`top`, `bottom`, `inlet`, `outlet`, `frontAndBack`) are boundary surfaces; you can ignore them.

**12.3 Open in ParaView with the maxp view ready**

**[Mac]**
```bash
VTK_FILE=$HOME/Documents/Research/repos/ozone_detonation/local_data/prop1_vtk_<time>/VTK/<name>.vtk \
  /Applications/ParaView-6.2.1.app/Contents/MacOS/paraview \
  --script=$HOME/Documents/Research/repos/ozone_detonation/05_runs/paraview_maxp.py &
```
- The script loads the file, colours it by `maxp` on an inverted grey log scale from 1.5 to 3.3 × 10⁵ Pa, and looks straight at the 2D plane.
- **Don't use `open -a ParaView file.vtk`:** ParaView 6.2.1 ignores files passed that way ("No proxy that matches…").
- **By hand instead:** start ParaView, choose **File → Open**, pick the `.vtk` file, then click **Apply** in the Properties panel. Nothing is drawn until you click Apply.

**12.4 Useful things to do in ParaView:**
- **Change field:** use the drop-down in the second toolbar row (it shows `maxp`) to switch to `p`, `T`, `Qdot`, `magGradrho`, `cellLevel`.
- **Colour range:**
  - **Rescale to Data Range** (colour bar icon with arrows) fits the current field.
  - **Rescale to Custom Range** (icon with "C") lets you type a range.
  - A log scale must have a positive minimum; otherwise ParaView warns "Ranges not valid for log-space".
- **Schlieren-like picture:** colour by `magGradrho`. Under **Edit Color Map**, choose a grey preset, click **Rescale to Data Range**, then set a custom range with a positive minimum (e.g. 1 to the maximum shown) and tick **Use log scale**.
- **Mesh:** in the representation drop-down, choose **Surface With Edges** to see the AMR cells. Zoom near the front.
- **View:** **Reset Camera** (box icon) fits the domain; the **−Z** button looks straight at the plane.
- **Save a picture:** **File → Save Screenshot**.

---

## 13. Keeping results safe

- **`$SCRATCH` deletes files not accessed for 10 days.** The full run (all 1 µs saves, about 70 MB each) lives there. Keep what matters in `$WORK`:
  - the **analysis** (Part 11)
  - a **snapshot** of the final time (`KEEP_SNAPSHOT=1`, about 95 MB)
  - the **solver logs**, which `smoke.slurm` copies automatically
- **Restarting from a snapshot** (if `$SCRATCH` was purged). `prop1_to_475mm.slurm` does this by itself. By hand:

  **[Stampede3]**
  ```bash
  cp -r $WORK/ozone_detonation/runs/prop1/snapshot_0.0002 $SCRATCH/ozone_detonation/prop1
  ```
  Then submit the run command as usual. It finds `.decomposed_ok` and continues from the snapshot's time.
- **Small results** (PNG plots, JSON) go into the git repository on the Mac (`05_runs/results/...`). **Big files** (VTK) stay in `local_data/`, which git ignores.

---

## 14. Recording your work in git

The project's habit is to write down what was run and what came out, then commit and push.
1. **Results:** copy plots into `05_runs/results/<name>/` (Part 11).
2. **Notes:** add a short section to `05_runs/README.md` covering:
   - the job number(s), command, time span and steps
   - the health checks (max Co, error lines)
   - the key results (speed, cell pattern)
3. **Progress table:** update the "Results so far" and "Progress log" tables in `README.md` if something important changed.
4. **Commit and push:**

   **[Mac]**
   ```bash
   cd ~/Documents/Research/repos/ozone_detonation
   git status                       # what changed
   git add -A                       # stage everything (local_data/ is ignored automatically)
   git commit -m "prop1 continued to 475 mm (job <jobid>): <short result>"
   git push
   ```
   - `git status` lists changed and new files.
   - `git commit` records a snapshot with a message.
   - `git push` sends it to GitHub.
5. **Changing the physics or numerics** (anything in `03_case/coarse_mesh_slip_of8`) must be recorded in `03_case/CHANGES.md`, with before, after and the reason.

---

## 15. Troubleshooting

| Symptom | Meaning | What to do |
|---|---|---|
| Asked for password, or `Permission denied (publickey,keyboard-interactive)` | the shared SSH connection ended (sleep, network change) | `stampede` again on the Mac, enter Duo |
| `rsync: [sender] change_dir "/home1/12029/smartinez627/Documents/..." failed: No such file or directory`, after a password/token prompt | the `rsync` (or `scp`) was typed in the **Stampede3** terminal (prompt `login2.stampede3…$`). There `~` is the Stampede3 home folder, and `stampede3:` makes Stampede3 log in to itself. Nothing is copied | open a **Mac** terminal tab (⌘T; prompt shows your Mac's name) and run it there. Commands marked [Mac] always go there |
| `CANCELLED by 0` about 2 minutes after start, **no output file at all** | system-side cancellation, cause unknown (Problem 5 in `05_runs/README.md`). Seen on 7 jobs in Nov 2026, of all sizes; a ticket is open with TACC | resubmit the same command; nothing on disk was changed. If it keeps happening, add the job numbers to the TACC ticket |
| A dependent job stays pending with `DependencyNeverSatisfied` | the job it waited for didn't finish successfully | `scancel <jobid>`, then resubmit without `-d` |
| `WARNING: submitted from $HOME` in the output | you forgot `cd $SCRATCH/ozone_detonation/logs` | not harmful once, but submit from `$SCRATCH` next time |
| `ERROR: … is not initialized (run 04_znd_init/init.slurm)` | new run, but `init_case` is missing (purged) | run Part 7, then resubmit |
| A run unexpectedly starts at t = 0 | the run folder had no `.decomposed_ok`, so `smoke.slurm` rebuilt it | cancel it; restore the folder from a snapshot (Part 13) |
| `solver exit code 124`, `KILLED BY SIGNAL: 15` | normal: our time guard stopped the solver | resubmit to continue |
| `KILLED BY SIGNAL` with a number other than 15 (e.g. 9, 11), or `FOAM FATAL`, `nan`, `Floating point exception` beyond the startup line | a real crash | look at the solver log just before the error: `grep -n -B20 "FATAL" <log> \| head -60`. Don't change the physics to hide it; record it and ask |
| `keyword version is undefined in dictionary …/Cx` (or `Ccx`, `Ccy`) | an OpenFOAM 8 tool read a file written by OpenFOAM 12 | the scripts already handle this. If you write a new script, move those files out of the time folder first |
| `cannot find … pointProcAddressing` in `reconstructPar` | the AMR mesh changed, so the pieces can't be mapped back | run `reconstructParMesh -time <t> -mergeTol 1e-6` first, as `analyze.slurm` does |
| ParaView: "No proxy that matches…" and an empty window | file passed with `open -a` | use the command in 12.3, or File → Open |
| ParaView: "Ranges not valid for log-space" | log scale applied while the range started at 0 | set a positive custom range |
| `rsync` from Stampede3 to the Mac hangs | seen once | use `scp` with full paths (Parts 11, 12) |

**Writing to TACC.** Use the TACC User Portal (portal.tacc.utexas.edu) → **Tickets → Create a ticket**, system Stampede3. Include:
- the job numbers
- the full path of the submission script
- what you expected and what happened
- the `sacct` lines

---

## 16. Cheat sheet

**[Mac]**
```bash
stampede                                    # log in (password from Keychain + Duo)
ssh -O check stampede3                      # is the shared connection alive?
rsync -av --exclude .git --exclude local_data ~/Documents/Research/repos/ozone_detonation/ stampede3:ozone_detonation/
scp 'stampede3:/work2/12029/smartinez627/stampede3/ozone_detonation/runs/prop1/analysis_<t>/*' <local folder>/
```

**[Stampede3]**
```bash
cd $SCRATCH/ozone_detonation/logs                                    # ALWAYS submit from here
sbatch ~/ozone_detonation/05_runs/prop1_to_475mm.slurm               # continue prop1 to 475 mm (done)
sbatch --export=ALL,SRC_RUN=prop1,NEW_RUN=prop1_cycle1 ~/ozone_detonation/05_runs/recycle.slurm   # next cycle folder
sbatch --export=ALL,RUN_NAME=prop1_cycle1 ~/ozone_detonation/05_runs/cycle_run.slurm             # run a cycle (repeat)
sbatch --export=ALL,RUN_NAME=smoke3 ~/ozone_detonation/05_runs/smoke.slurm               # smoke test
sbatch --export=ALL,RUN_NAME=prop1,LOGJOB=<id1>:<id2>:...,KEEP_SNAPSHOT=1 ~/ozone_detonation/05_runs/analyze.slurm
sbatch --export=ALL,RUN_NAME=prop1 ~/ozone_detonation/05_runs/to_vtk.slurm
squeue -u $USER                                                      # queued / running
sacct -j <jobid> -X -o JobID,JobName%15,State%20,Elapsed,NodeList    # finished
scancel <jobid>                                                      # cancel
tail -f $SCRATCH/ozone_detonation/prop1/log.detonationFoam.<jobid>   # watch the solver
tail -40 $SCRATCH/ozone_detonation/logs/<name>_<jobid>.log           # job summary
/usr/local/etc/taccinfo                                              # SU balance
```

**Key numbers:**
- D_CJ = 1616 m/s
- about 85 s of wall time per simulated µs on 2 nodes
- about 1.6 mm of shock travel per µs
- 1 save (1 µs) ≈ 70 MB in `$SCRATCH`
- 2 nodes × 2 h = 4 SU
