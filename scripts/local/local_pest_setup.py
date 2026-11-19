# %% [markdown]
# # Set up a LOCAL multi-core PEST++ IES run
# Local counterpart of `hovenweep_pest_setup.ipynb`. It runs the same PEST++ IES
# ensemble on **this machine**: one manager plus N workers talking over `localhost`,
# with N sized from your physical cores, logical (hyper-threaded) cores and RAM.
#
# Compared with the Hovenweep notebook it drops the Slurm scripts, Globus/scp
# transfer, VPN/Kerberos, and the Linux binary. It adds:
# 1. a **one-run benchmark** that measures forward-run wall time and peak RAM, so the
#    worker count comes from measurement and not a guess;
# 2. optional **`.pst` overrides** (e.g. `ies_num_reals` 500 -> 100) written to a COPY of
#    the control file, leaving your original untouched;
# 3. a **detached launcher** (`run_local_ies.py`) that keeps running if the notebook
#    kernel restarts, plus monitor and stop cells.
#
# The launcher lives in `scripts/local/` of the nhm-assist repo.

# %%
import json, math, os, re, shutil, socket, subprocess, sys, time
import pathlib as pl
import warnings
warnings.filterwarnings("ignore")
import psutil
from rich.console import Console
con = Console()

# %% [markdown]
# ## 1. Configure your run  <- EDIT THIS CELL
# | Key | What it is |
# |-----|------------|
# | `LOCAL_RUN_DIR` | Your model's `pestpp_ies/` directory (holds the `.pst` and inputs) |
# | `CASE_NAME` | `<CASE_NAME>.pst` control file |
# | `OUTPUT_ROOT` | Folder that holds the results packages, `<OUTPUT_ROOT>/<RUN_NAME>`. `None` = `local_pestpp_ies_output` next to `LOCAL_RUN_DIR` |
# | `RUN_NAME` | Name of the results folder, `<OUTPUT_ROOT>/<RUN_NAME>` |
# | `PST_OVERRIDES` | Options changed in a COPY of the `.pst`, e.g. `{"ies_num_reals": 100}` |
# | `USE_LOGICAL_CORES` | `True` counts hyper-threads. They add roughly 10-30%, not 2x |
# | `RESERVE_CORES` | Cores left free for the manager, the OS and you |
# | `WORKER_MEM_GB` | Per-worker RAM budget. `None` = use the benchmark (peak x `MEM_SAFETY`) |
# | `MAX_WORKERS` | Optional hard cap |

# %%
# REPO_ROOT is found from the installed `assist` package. LOCAL_RUN_DIR defaults
# to <model_dir>/pestpp_ies from the project's active model, when there is one.
import assist as _assist_pkg

_default_repo_root = pl.Path(_assist_pkg.__file__).resolve().parents[2]
try:
    from assist.common.assist_utilities import load_subdomain_config
    from assist.workspace.bridge import resolve_project_notebook_context
    from assist.workspace.service import get_active_model_root

    _ctx = resolve_project_notebook_context(cwd=os.getcwd(), env=os.environ)
    _project_config = load_subdomain_config(
        get_active_model_root(_ctx["workspace_root"], _ctx["project_root"].name) / "config"
    )
    _default_run_dir = str(pl.Path(_project_config["model_dir"]) / "pestpp_ies")
except Exception as _e:  # not inside a project, or no active model
    con.print(f"[yellow]No project config found ({_e}); set LOCAL_RUN_DIR by hand.[/yellow]")
    _default_run_dir = "<USER_PATH_HERE>"

config = {
    "REPO_ROOT": str(_default_repo_root),   # repo that holds scripts/local/run_local_ies.py
    "LOCAL_RUN_DIR": _default_run_dir,
    # e.g. "LOCAL_RUN_DIR": r"D:\nhm-workspace\my_project\models\SandyRiver\outputs\runtime\pestpp_ies",
    "CASE_NAME": "prior_mc_reweight_obs+noise_mod",
    # Results package: <OUTPUT_ROOT>/<RUN_NAME>. Same layout as the folder a Hovenweep run
    # copies back, so downstream plotting runs unchanged. None -> "local_pestpp_ies_output"
    # next to LOCAL_RUN_DIR (not inside it). The worker scratch folder stays beside LOCAL_RUN_DIR.
    "OUTPUT_ROOT": None,
    "RUN_NAME": "Sandy_local_1",
    "PESTPP_RELEASE": "5.2.26",       # exact tag; used only if no Windows exe is in the run dir
    "FORCE_EXE_DOWNLOAD": False,      # True = replace the Windows pestpp-ies.exe in the run dir
    # Options rewritten in a COPY of the .pst (name gets a _local suffix).
    # Leave {} to run the .pst exactly as it is.
    "PST_OVERRIDES": {"ies_num_reals": 100},              # e.g. {"ies_num_reals": 100, "ies_subset_size": 10}
    # --- sizing ---
    "USE_LOGICAL_CORES": True,
    "RESERVE_CORES": 2,
    "RESERVE_RAM_GB": 8,              # left for Windows and your other programs
    "WORKER_MEM_GB": None,            # None -> benchmark peak RSS x MEM_SAFETY
    "MEM_SAFETY": 1.5,                # margin for the synchronized start-up spike
    "MAX_WORKERS": None,
    "RUN_BENCHMARK": True,            # time ONE forward run (about 1-2 min)
    "ESTIMATE_SLOWDOWN": 1.4,         # assumed per-run slowdown with every core busy (not measured)
    # --- launch ---
    "LOW_PRIORITY": True,             # workers run below-normal so the PC stays usable
    "STAGGER_S": 1.0,                 # seconds between worker starts
    "KEEP_WORKERS": False,            # keep worker dirs after the run (for debugging)
    "PYTHON_EXE": sys.executable,     # env with pywatershed; must be the kernel's env
    "LAUNCH_NOW": True,              # True = the launch cell starts the run
}
from assist.common.user_paths import require_user_path

run_dir = require_user_path(
    config["LOCAL_RUN_DIR"], "LOCAL_RUN_DIR",
    example=r"D:\nhm-workspace\my_project\models\SandyRiver\outputs\runtime\pestpp_ies",
)
repo_root = require_user_path(config["REPO_ROOT"], "REPO_ROOT")
launcher_src = repo_root / "scripts" / "local" / "run_local_ies.py"
output_root = pl.Path(config["OUTPUT_ROOT"]) if config["OUTPUT_ROOT"] else run_dir.parent / "local_pestpp_ies_output"
worker_root = run_dir.parent / f"{run_dir.name}_workers"   # same drive -> hard links work
assert launcher_src.exists(), f"Launcher not found: {launcher_src} (fix REPO_ROOT)"
con.print(f"Run dir     : [bold]{run_dir}[/bold]")
con.print(f"Results     : [bold]{output_root / config['RUN_NAME']}[/bold]")
con.print(f"Worker root : [bold]{worker_root}[/bold]")
con.print(f"Python      : [bold]{config['PYTHON_EXE']}[/bold]")

# %% [markdown]
# ## 2. Machine resources

# %%
phys = psutil.cpu_count(logical=False) or os.cpu_count()
logi = psutil.cpu_count(logical=True) or os.cpu_count()
vm = psutil.virtual_memory()
con.print(f"Cores   : {phys} physical, {logi} logical")
con.print(f"RAM     : {vm.total/1024**3:.1f} GB total, {vm.available/1024**3:.1f} GB free now")
if vm.available / vm.total < 0.4:
    con.print("[yellow]Less than 40% of RAM is free. Close other programs before a long run.[/yellow]")

# %% [markdown]
# ## 3. Verify the run directory
# Checks the required files, plus every `.jcb` ensemble the `.pst` points to (a missing
# one kills the run at start-up).

# %%
case = config["CASE_NAME"]
required = [
    f"{case}.pst", f"{case}.pargp_data.csv", f"{case}.par_data.csv",
    f"{case}.obs_data.csv", f"{case}.tplfile_data.csv", f"{case}.insfile_data.csv",
    "forward_run.py", "parameters.json", "parameters.json.tpl",
    "modelobs.dat", "modelobs.dat.ins", "control.default.bandit",
    "loc.mat", "phi_factors.csv", "prcp.nc", "tmax.nc", "tmin.nc",
]
pst_text = (run_dir / f"{case}.pst").read_text(encoding="utf-8")
for key in ("ies_parameter_ensemble", "ies_observation_ensemble", "ies_localizer",
            "ies_phi_factor_file"):
    m = re.search(rf"(?m)^{key}\s+(\S+)", pst_text)
    if m and m.group(1) not in required:
        required.append(m.group(1))
missing = [f for f in required if not (run_dir / f).exists()]
for f in required:
    ok = (run_dir / f).exists()
    con.print(f"  {'[green]OK  [/green]' if ok else '[red]MISS[/red]'} {f}")
for d in ("observation_data", "ancillary"):
    ok = (run_dir / d).is_dir()
    con.print(f"  {'[green]OK  [/green]' if ok else '[yellow]none[/yellow]'} {d}/")
if missing:
    con.print(f"\n[red]{len(missing)} required file(s) missing.[/red] Fix before running.")
else:
    con.print("\n[green]All required files present.[/green]")

# %% [markdown]
# ## 4. Windows `pestpp-ies.exe`
# Uses the `pestpp-ies.exe` already in the run dir. If it is missing (or
# `FORCE_EXE_DOWNLOAD`), downloads the **Windows** build of `PESTPP_RELEASE`.

# %%
import io, urllib.request, zipfile
exe_name = "pestpp-ies.exe" if os.name == "nt" else "pestpp-ies"
exe_path = run_dir / exe_name
if config["FORCE_EXE_DOWNLOAD"] or not exe_path.exists():
    tag = config["PESTPP_RELEASE"]
    ostag = {"nt": "win"}.get(os.name, "mac" if sys.platform == "darwin" else "linux")
    try:
        from pyemu.utils import get_pestpp
        get_pestpp(str(run_dir), owner="usgs", repo="pestpp", release_id=tag,
                   ostag=ostag, subset=["pestpp-ies"], quiet=True)
    except Exception as e:
        con.print(f"[yellow]get_pestpp failed ({e}); trying direct download.[/yellow]")
    if not exe_path.exists() and ostag == "win":
        url = f"https://github.com/usgs/pestpp/releases/download/{tag}/pestpp-{tag}-win.zip"
        req = urllib.request.Request(url, headers={"User-Agent": "nhm-assist"})
        with urllib.request.urlopen(req) as r, zipfile.ZipFile(io.BytesIO(r.read())) as zf:
            member = next(n for n in zf.namelist() if n.rsplit("/", 1)[-1] == exe_name)
            exe_path.write_bytes(zf.read(member))
assert exe_path.exists(), f"{exe_path} not found; download pestpp {config['PESTPP_RELEASE']} manually."
out = subprocess.run([str(exe_path), "--version"], capture_output=True, text=True, timeout=30)
con.print(f"[green]Using[/green] {exe_path}  ({exe_path.stat().st_size/1e6:.1f} MB)")
con.print((out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr) else "")

# %% [markdown]
# ## 5. Control-file copy with overrides (optional)
# When `PST_OVERRIDES` is non-empty, writes `<CASE>_local.pst` with those options
# changed and runs that. The original `.pst` is not modified. The external `*_data.csv`
# tables keep the original case name, which the copy still references.

# %%
local_case = case
overrides = config["PST_OVERRIDES"]
if overrides:
    new_text = pst_text
    for key, val in overrides.items():
        pat = re.compile(rf"(?m)^({re.escape(key)}\s+)\S+")
        if not pat.search(new_text):
            raise KeyError(f"'{key}' not found in {case}.pst control-data keyword block")
        new_text = pat.sub(lambda m: f"{m.group(1)}{val}", new_text, count=1)
    local_case = f"{case}_local"
    (run_dir / f"{local_case}.pst").write_text(new_text, encoding="utf-8", newline="\n")
    con.print(f"[green]Wrote[/green] {local_case}.pst with overrides {overrides}")
    pst_text_run = new_text
else:
    pst_text_run = pst_text
    con.print("No overrides; running the original .pst.")

def _opt(key, default, cast):
    m = re.search(rf"(?m)^{key}\s+(\S+)", pst_text_run)
    return cast(m.group(1)) if m else default
num_reals = _opt("ies_num_reals", 50, int)
subset = _opt("ies_subset_size", 4, int)
noptmax = _opt("noptmax", 3, int)
n_lambda = len(_opt("ies_lambda_mults", "1.0", str).split(","))
n_scale = len(_opt("lambda_scale_fac", "1.0", str).split(","))
con.print(f"reals={num_reals}  noptmax={noptmax}  lambda mults={n_lambda}  scale facs={n_scale}  subset={subset}")


# %% [markdown]
# ## 6. Install the launcher and write its config

# %%
def free_port():
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]

def write_config(n_workers):
    cfg = {
        "run_dir": str(run_dir),
        "case": local_case,
        "source_case": case,
        "exe": str(exe_path),
        "port": free_port(),
        "n_workers": int(n_workers),
        "worker_root": str(worker_root),
        "output_root": str(output_root),
        "python_exe": config["PYTHON_EXE"],
        "low_priority": config["LOW_PRIORITY"],
        "stagger_s": config["STAGGER_S"],
        "keep_workers": config["KEEP_WORKERS"],
        "run_name": config["RUN_NAME"],
    }
    (run_dir / "run_local_config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg

launcher = run_dir / "run_local_ies.py"
shutil.copy2(launcher_src, launcher)
write_config(1)
con.print(f"[green]Installed[/green] {launcher}")

# %% [markdown]
# ## 7. Benchmark ONE forward run
# Runs `forward_run.py` once in a scratch worker directory and records wall time and
# peak RAM (the model process plus any children). With nothing else running, the wall time is
# a best case; with every core busy, runs get slower (see `ESTIMATE_SLOWDOWN`).

# %%
bench = None
if config["RUN_BENCHMARK"]:
    con.print("Running one forward run ... (the first run includes numba JIT compile)")
    res = subprocess.run([config["PYTHON_EXE"], str(launcher), "--benchmark"],
                         cwd=run_dir, capture_output=True, text=True)
    try:
        bench = json.loads(res.stdout.strip().splitlines()[-1])
    except Exception:
        con.print(f"[red]Benchmark failed.[/red]\n{res.stdout[-1500:]}\n{res.stderr[-1500:]}")
    if bench:
        con.print(bench)
        if bench["returncode"] != 0:
            con.print(f"[red]forward_run.py exited {bench['returncode']}; see {bench['log']}[/red]")
            bench = None

# %% [markdown]
# ## 8. Size the worker pool
# ```
# core_cap = (physical or logical cores) - RESERVE_CORES
# mem_cap  = (total RAM - RESERVE_RAM_GB) / worker_mem
# workers  = min(core_cap, mem_cap, MAX_WORKERS, reals)
# ```
# `worker_mem` is `WORKER_MEM_GB` if set, else benchmark peak x `MEM_SAFETY`. More workers
# than cores adds no speed for a CPU-bound model, so RAM only binds when `worker_mem` is large.

# %%
if config["WORKER_MEM_GB"]:
    worker_mem, mem_src = float(config["WORKER_MEM_GB"]), "config"
elif bench:
    worker_mem, mem_src = max(0.5, bench["peak_rss_gb"] * config["MEM_SAFETY"]), "benchmark"
else:
    worker_mem, mem_src = 9.0, "fallback (no benchmark; the Hovenweep value)"
ncores = logi if config["USE_LOGICAL_CORES"] else phys
core_cap = max(1, ncores - config["RESERVE_CORES"])
mem_cap = max(1, int((vm.total / 1024**3 - config["RESERVE_RAM_GB"]) // worker_mem))
caps = {"cores": core_cap, "memory": mem_cap, "reals": num_reals}
if config["MAX_WORKERS"]:
    caps["MAX_WORKERS"] = int(config["MAX_WORKERS"])
n_workers = min(caps.values())
limited_by = min(caps, key=caps.get)
con.print(f"worker RAM budget : {worker_mem:.2f} GB ({mem_src})")
con.print(f"caps              : {caps}")
con.print(f"[green]=> {n_workers} workers + 1 manager[/green] (limited by {limited_by})")

# Rough forward-run count: initial ensemble + per iteration (full ensemble + one subset run per lambda x scale-factor pair).
runs_per_iter = num_reals + n_lambda * n_scale * min(subset, num_reals)
total_runs = num_reals + 1 + noptmax * runs_per_iter
con.print(f"approx forward runs: {total_runs} ({noptmax} iterations x ~{runs_per_iter} + initial {num_reals + 1})")
if bench:
    waves = math.ceil(total_runs / n_workers)
    t_run = bench["wall_s"] * config["ESTIMATE_SLOWDOWN"]
    con.print(f"estimate: {waves} waves x {t_run:.0f} s = [bold]{waves * t_run / 3600:.1f} h[/bold] "
              f"(single-run time {bench['wall_s']} s x assumed slowdown {config['ESTIMATE_SLOWDOWN']})")
cfg_run = write_config(n_workers)


# %% [markdown]
# ## 9. Launch
# The launcher runs detached, so closing or restarting the kernel does not stop the run.
# Set `LAUNCH_NOW = True` in the config cell to start it from here, or paste the command
# into a terminal. Keep the PC awake (sleep stops the run).

# %%
def pest_procs():
    out = []
    for p in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
        try:
            if p.info["exe"] and pl.Path(p.info["exe"]).resolve() == exe_path.resolve():
                out.append(p)
        except (psutil.Error, OSError):
            pass
    return out

cmd = [config["PYTHON_EXE"], str(launcher)]
con.print("Launch command (run in the run dir):")
con.print(f"  cd {run_dir}\n  " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
if config["LAUNCH_NOW"]:
    if pest_procs():
        con.print(f"[red]{len(pest_procs())} pestpp-ies process(es) already running from this run dir. Stop them first.[/red]")
    else:
        (run_dir / "logs").mkdir(exist_ok=True)
        flags = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW) if os.name == "nt" else 0
        lp = subprocess.Popen(cmd, cwd=run_dir, stdout=open(run_dir / "logs" / "launcher_local.out", "w"),
                              stderr=subprocess.STDOUT, creationflags=flags)
        (run_dir / "run_local.pid").write_text(str(lp.pid))
        con.print(f"[green]Launched[/green] pid {lp.pid}. Use the monitor cell below.")

# %% [markdown]
# ## 10. Monitor
# Re-run this cell any time. The manager log is `logs/manager_local.out`; per-iteration
# progress is in `<case>.rec`.

# %%
procs = pest_procs()
con.print(f"pestpp-ies processes: {len(procs)} (1 manager + {max(0, len(procs) - 1)} workers expected: {cfg_run['n_workers']})")
con.print(f"CPU {psutil.cpu_percent(interval=1):.0f}%   RAM used {psutil.virtual_memory().percent:.0f}%")
log = run_dir / "logs" / "manager_local.out"
if not procs and not log.exists():
    con.print("[yellow]Nothing has been launched from this run dir yet (not launched). Set LAUNCH_NOW = True in the config cell and run the launch cell.[/yellow]")
if log.exists():
    con.print("--- manager log (tail) ---")
    print("\n".join(log.read_text(errors="replace").splitlines()[-15:]))
phi = run_dir / f"{local_case}.phi.meas.csv"
if phi.exists():
    lines = phi.read_text().strip().splitlines()
    con.print("--- phi (measured) ---")
    print(lines[0]); print(lines[-1])
    import datetime as _dt
    con.print(f"(file last written {_dt.datetime.fromtimestamp(phi.stat().st_mtime):%Y-%m-%d %H:%M}; an old time means it is from a previous run)")

# %% [markdown]
# ## 11. Stop
# Kills the launcher, the manager, the workers and their `forward_run.py` processes for
# this run dir.

# %%
STOP = False   # set True and run this cell to stop the run
if STOP:
    victims = []
    for p in psutil.process_iter(["pid", "cmdline", "exe"]):
        try:
            cl = " ".join(p.info["cmdline"] or [])
            is_launcher = "run_local_ies.py" in cl and str(run_dir) in (p.cwd() or "")
            is_pest = p.info["exe"] and pl.Path(p.info["exe"]).resolve() == exe_path.resolve()
            if is_launcher or is_pest:
                victims.append(p)
        except (psutil.Error, OSError):
            pass
    for p in victims:                       # launcher first so it cannot respawn anything
        try:
            for ch in p.children(recursive=True):
                ch.kill()
            p.kill()
        except psutil.Error:
            pass
    con.print(f"Stopped {len(victims)} process(es). Worker dirs left in {worker_root} (safe to delete).")

# %% [markdown]
# ## 12. Results package
# When the run finishes, the launcher packages it automatically into
# `<OUTPUT_ROOT>/<RUN_NAME>` with the same layout as a Hovenweep results folder
# (e.g. `Sandy_beta4_n`): the `<case>.*` inputs and PEST++ outputs (`.rec`, `.rmr`, `.N.par.csv`,
# `.N.obs.csv`, `.N.pdc.csv`, `.phi.*.csv`, `.base.par/.rei`, `.obs+noise.csv`, ...), the model
# files, `ancillary/`, `observation_data/`, `output/model_custom_output.nc` and `logs/manager.out`.
#
# - Only outputs written during this run are packaged; leftovers from earlier runs in the same
#   directory are skipped (listed in `logs/local_run_info.json`).
# - If you used `PST_OVERRIDES`, the `<case>_local.*` files are renamed back to `<case>.*`.
# - Hovenweep-only files (`.slurm`, `setup_worker.sh`, `pestpp_ies_<jobid>.conf`) are not included.
# - A name clash gets `_2`, `_3`, ... so a package is never overwritten.
#
# Run the next cell to package a finished or stopped run by hand (e.g. after a stop).

# %%
COLLECT = False   # True = package the last run now (the launcher already does this when a run ends)
if COLLECT:
    res = subprocess.run([config['PYTHON_EXE'], str(launcher), '--collect'], cwd=run_dir,
                         capture_output=True, text=True)
    print(res.stdout[-800:] or res.stderr[-800:])
results_dir = output_root
if results_dir.is_dir():
    for d in sorted(results_dir.iterdir()):
        n_files = sum(1 for _ in d.rglob('*') if _.is_file())
        size_gb = sum(f.stat().st_size for f in d.rglob('*') if f.is_file()) / 1024**3
        con.print(f'  {d.name}: {n_files} files, {size_gb:.2f} GB')
else:
    con.print('No results yet.')

# %% [markdown]
# ## Notes
# - **Outputs** are packaged to `<OUTPUT_ROOT>/<RUN_NAME>` (section 12). Raw files also land in the run dir: `<case>.rec`, `.phi.*.csv`, `.<iter>.par.csv` / `.obs.csv` ensembles, as on Hovenweep.
# - **Worker disk use:** each worker copies a few small files and hard-links the `.nc` inputs
#   and junctions `observation_data/`, `ancillary/`, so 30 workers cost little disk. The
#   launcher falls back to copying if linking fails.
# - **Firewall:** the first run may trigger a Windows Firewall prompt for `pestpp-ies.exe` on its local port. Allow it.
# - **One-hour Hovenweep run, sized back:** compare the benchmark wall time and worker count with
#   `sacct -j <id> --format=JobID,Elapsed,NNodes,NTasks,MaxRSS` to calibrate `ESTIMATE_SLOWDOWN`.
# - **Fewer realizations** (`PST_OVERRIDES = {"ies_num_reals": 100, "ies_subset_size": 10}`) cuts the run count roughly 5x.
#   Check the first `.rec` to confirm PEST++ took the first 100 members of the `.jcb` ensembles.
