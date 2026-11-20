# Step 1 — Connecting to Stampede3 and the computing environment

## 1. Signing in (SSH + Duo)
- **Host:** `stampede3.tacc.utexas.edu`. You land on one of the login nodes, e.g. `login2`.
- **Username:** `smartinez627`
- **Authentication:** TACC portal password, then a **Duo/TACC token code**. MFA is mandatory on all TACC systems.

Your Mac's `~/.ssh/config` defines a shortcut so you only do Duo **once per working session**:
```
Host stampede3 stampede3.tacc.utexas.edu
    HostName stampede3.tacc.utexas.edu
    User smartinez627
    ControlMaster auto                      # first login becomes the "master" connection
    ControlPath ~/.ssh/cm-%r@%h:%p          # socket file that later ssh/scp calls reuse
    ControlPersist 12h                      # keep the master alive 12 h after its terminal closes
    ServerAliveInterval 60                  # keepalive pings so the connection isn't dropped
    ServerAliveCountMax 5
```
**Each session:**
1. In your own terminal, run `~/.ssh/scripts/stampede.exp` (fills the password from Keychain), or run `ssh stampede3`.
2. Type the Duo code.
3. After that, `ssh stampede3 ...`, `scp`, and `rsync` (yours or Claude's) reuse the connection with no prompts.

**Checking or closing the connection:**
- `ssh -O check stampede3` shows whether the shared connection is alive.
- `ssh -O exit stampede3` closes it.

The connection also drops if your laptop sleeps or loses network. Then just log in again.

Rules: never put the password or Duo codes in files or scripts. The password lives in macOS Keychain, and you type the codes yourself. Do **not** run `ssh-keygen` on Stampede3 (TACC docs: it breaks batch jobs).

## 2. TACC rules that shape our workflow
From the [Stampede3 user guide](https://docs.tacc.utexas.edu/hpc/stampede3/) and the [TACC Good Conduct guide](https://docs.tacc.utexas.edu/basics/conduct/):
- **"All AI-assisted workloads must be executed on compute nodes only."** You are responsible for, and charged for, anything an AI tool launches.
- **Login nodes are shared.** No jobs or heavy computation there, including intensive Python. Compiling is allowed but shouldn't use many cores at once.
- **VS Code** "consumes significant resources"; TACC asks users to run it on a compute node, not a login node.
- Jobs should do their I/O in **`$SCRATCH`**, not `$HOME` or `$WORK`.

**How we comply:**
- Claude only does light things on the login node: copying files, git clone, `sbatch`/`squeue`, reading logs.
- Every compile, mesh generation, Python ZND script and solver run is a **Slurm batch job** on a compute node.
- Jobs are charged to **TG-MCH260175**.

## 3. VS Code
**Recommended (no remote server):** edit this repository **locally** in VS Code on your Mac, as you are now. Files are copied to Stampede3 with `rsync`/`scp`, and work runs as batch jobs. This needs no VS Code server on TACC machines, so it fully respects the login-node rule.

**Optional — VS Code directly on a compute node.** Use this if you want to browse remote files or results in VS Code. It is *not set up or tested yet*, because it needs a few extra pieces:
1. Install the **Remote - SSH** extension (`ms-vscode-remote.remote-ssh`). It is not currently installed.
2. In a terminal on Stampede3, start an interactive allocation, e.g. `idev -p skx-dev -N 1 -t 01:00:00 -A TG-MCH260175`. It prints a node name such as `c454-012`. **SUs are charged for the whole time it is open.**
3. Add a jump-host entry to `~/.ssh/config` on the Mac:
   ```
   Host c4* c5*
       User smartinez627
       ProxyJump stampede3
   ```
4. In VS Code, run "Remote-SSH: Connect to Host…" and enter `c454-012`. Logging in to a compute node through the jump host may need your public key in `~/.ssh/authorized_keys` on Stampede3. We'll set that up together if you decide you want this.

## 4. What is on Stampede3 (inspected 2026-11-16)
**Your directories**
| Variable | Path | Quota | Use |
|---|---|---|---|
| `$HOME` | `/home1/12029/smartinez627` | 15 GB, backed up | scripts, small text (copy of this repo: `~/ozone_detonation`) |
| `$WORK` | `/work2/12029/smartinez627/stampede3` | 1 TB, not backed up | source code, compiled solver, results to keep |
| `$SCRATCH` | `/scratch/12029/smartinez627` | no quota, **purged after 10 days of no access** | where jobs actually run |

**Allocations** (`/usr/local/etc/taccinfo`)
| Project | Available SUs | Expires |
|---|---|---|
| **TG-MCH260175** (used for this project) | 3130 | 2027-09-21 |
| TG-PHY260370 | 1100 | 2027-08-18 |

1 SU = 1 node-hour on `skx`. Other queues charge more per node-hour; see below.

**CPU queues** (partitions)
| Queue | Cores/node | Max nodes | Max time | SUs per node-hour | Use for |
|---|---|---|---|---|---|
| `skx-dev` | 48 | 16 | 2 h | 1 | debugging, builds, smoke tests |
| `skx` | 48 | 256 | 48 h | 1 | production |
| `icx` | 80 | 32 | 48 h | 1.5 | production |
| `spr` | 112 | 32 | 48 h | 2 | production |

**Compilers and MPI** (`module avail`)
- Intel: 23.1, 24.0 (default), 25.1, 26.0
- GCC: 13.2, 14.2, 15.1, 16.1
- MPI: Intel MPI 21.9 / 21.11 (default), MVAPICH 3.0, MVAPICH-Plus 4.0b

**OpenFOAM** (`module spider openfoam`)
- Foundation versions 8 and 12; ESI versions v2112, v2312, v2412.
- **`openfoam/8` exists**, built with `intel/23.1` + `impi/21.9`. So **we don't need to compile OpenFOAM 8 ourselves**, only detonationFoam on top of it.

**Other:** `python/3.12.11` (default), `cantera/3.1.0`, `cmake`, `boost`.

## 5. `env.sh` — loading the environment
`source ~/ozone_detonation/01_environment/env.sh` sets up everything. It is used in every job script. It does three things:
1. **Swaps compilers.** It switches to `intel/23.1` + `impi/21.9`, which OpenFOAM 8 was built with, then loads `openfoam/8`. Mixing compiler or MPI versions with prebuilt libraries causes crashes or link errors.
2. **Moves your compiled code to `$WORK`.** The TACC module hard-codes the user build directory to `$SCRATCH/OpenFOAM/...`, which would be purged. `env.sh` resets it to `$WORK/OpenFOAM/smartinez627-8/platforms/linux64IccDPInt32Opt/{bin,lib}`.
3. **Fixes a module bug.** The module sets `FOAM_LIBBIN` (OpenFOAM's core library folder) to the ThirdParty folder. `env.sh` sets it back to `$WM_PROJECT_DIR/platforms/linux64IccDPInt32Opt/lib`, matching OpenFOAM's own `etc/config.sh/settings`. That folder contains `libfiniteVolume.so`, `libchemistryModel.so`, etc.

Verified output after sourcing:
```
intel/23.1 impi/21.9 openfoam/8
WM_OPTIONS=linux64IccDPInt32Opt          # Linux 64-bit, Intel compiler, double precision, 32-bit labels, optimized
FOAM_USER_APPBIN=/work2/12029/smartinez627/stampede3/OpenFOAM/smartinez627-8/platforms/linux64IccDPInt32Opt/bin
FOAM_LIBBIN=/home1/apps/intel23/impi21/OpenFOAM/OpenFOAM-8/platforms/linux64IccDPInt32Opt/lib
FOAM_RUN=/scratch/12029/smartinez627/ozone_detonation
```

## 6. Keeping the Stampede3 copy in sync
The git repository lives on your Mac and is pushed to GitHub from there. Scripts are copied to Stampede3 with:
```
rsync -av --exclude .git ~/Documents/Research/repos/ozone_detonation/ stampede3:ozone_detonation/
```

## Personal shell aliases on Stampede3 (added 2026-11-20)
- **The file:** `stampede_aliases.sh` holds the user's Mac aliases, translated to bash, which is Stampede3's login shell. A `~/.zshrc` there is not read.
- **Where it is loaded:** one line in `~/.bashrc` on Stampede3 sources the file. The backup is `~/.bashrc.bak-2026-11-20`.
- **Interactive shells only,** so batch jobs and scripted `ssh` commands are unchanged.
- **The aliases:**
  - `log` goes to `$SCRATCH/ozone_detonation/logs`. It replaces the Mac's `home`.
  - `ll`, `clc`, `..` … `......`, `jot`, `p` work as on the Mac.
  - `sdtoolbox` activates the `$WORK/venvs/znd` Python environment.
  - `cd` lists the folder after changing into it.
- **Left out:**
  - `stampede`, `transfer` and the `transfer()` function: they log in to or copy to Stampede3 from the Mac.
  - `dircolors=gdircolors`: Linux has `dircolors` itself.
  - `mamba` and the conda setup: not installed on Stampede3.
