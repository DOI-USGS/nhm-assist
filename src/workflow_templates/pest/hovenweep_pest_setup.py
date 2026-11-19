# %% [markdown]
# # Set up a PEST++ IES run on Hovenweep
#
# This notebook prepares a **parallel PEST++ IES** calibration to run on the
# **Hovenweep** HPC, using the reusable templates in `scripts/hovenweep/`.
#
# > **This is an EXAMPLE remote-execution workflow set up around USGS-specific
# > resources** (the Hovenweep HPC, Globus, DOI VPN + Kerberos). USGS users can
# > run it as-is; others can use it as a reference and tailor the transfer,
# > scheduler, and auth pieces to their own HTC/HPC resource (another Slurm
# > cluster, AWS, or a local multi-core run). The optional tooling it needs
# > (the Globus CLI) is NOT in the base install — install it with
# > `pixi run remote-setup` (the opt-in `remote-run` environment).
#
# What it does:
# 1. You fill in a small config block (username, center, paths, case name, etc.).
# 2. It reads the generic templates from `scripts/hovenweep/`, substitutes your
#    values for the `<PLACEHOLDER>` tokens, and writes the customized
#    `run_pestpp_ies.slurm`, `setup_worker.sh`, and `transfer_to_hpc.ps1` into
#    your local PEST++ run directory.
# 3. It verifies the required run files are present.
# 4. It prints the exact transfer / smoke-test / submit / monitor / cancel
#    commands for you to run.
#
# **What it does NOT do:** it does not SSH to Hovenweep or transfer files. Those
# steps require VPN + a Kerberos ticket and are run from your own terminal /
# PowerShell (the notebook prints the commands). See
# `scripts/hovenweep/README_hovenweep_run.md` for the full reference.

# %%
import math as _math
import pathlib as pl
import warnings

warnings.filterwarnings("ignore")
from rich.console import Console

con = Console()
from rich import pretty

pretty.install()

# %% [markdown]
# ## Locate the repo and the Hovenweep templates
# Finds the `nhm-assist` repo root via the installed `assist` package so the
# template directory resolves regardless of where the notebook is launched.

# %%
try:
    import assist as _assist_pkg

    repo_root = pl.Path(_assist_pkg.__file__).resolve().parents[2]
except Exception:
    # Fallback: walk up until we find scripts/hovenweep
    here = pl.Path.cwd()
    repo_root = here
    for parent in [here, *here.parents]:
        if (parent / "scripts" / "hovenweep").is_dir():
            repo_root = parent
            break

template_dir = repo_root / "scripts" / "hovenweep"
con.print(f"Repo root:      [bold]{repo_root}[/bold]")
con.print(f"Template dir:   [bold]{template_dir}[/bold]")
assert template_dir.is_dir(), (
    f"Could not find {template_dir}. Set `template_dir` manually to the "
    "scripts/hovenweep directory."
)

# %% [markdown]
# ## 1. Configure your run  ⟵ EDIT THIS CELL
#
# These values replace the `<PLACEHOLDER>` tokens in the templates.
#
# | Key | What it is |
# |-----|------------|
# | `HPC_USER` | Your Hovenweep username |
# | `CENTER` | Your SLURM allocation / center (e.g. `wawsc`) |
# | `PYWATERSHED_ENV` | conda env on Hovenweep with pywatershed (runs `forward_run.py`) |
# | `CONDA_DIR` | Base of your conda/miniforge install on Hovenweep |
# | `CASE_NAME` | The `<CASE_NAME>.pst` control file (e.g. `prior_mc_reweight`) |
# | `JOB_NAME` | SLURM job name / scratch tag |
# | `RUN_NAME` | Remote run-directory name under your caldera project space |
# | `LOCAL_RUN_DIR` | Local path to your model's `pestpp_ies/` directory |
# | `WALLTIME` | Walltime `HH:MM:SS` (48h max) |
# | `TRANSFER_METHOD` | `"globus"` (preferred) or `"scp"` |
# | `NODE_RAM_GB` / `WORKER_MEM_GB` / `NODE_CORES` / `NUM_REALS` | Inputs to the computed `NTASKS` (see sizing cell) |
#
# `NTASKS` is **computed** from the memory/core/reals budget below — not set by
# hand. Use `NTASKS_OVERRIDE` only to force a specific value.

# %%
# Defaults for LOCAL_RUN_DIR and the run name come from the project's active
# model (subdomain_config.yaml), when the notebook runs inside a project.
import datetime as _dt
import os as _os

try:
    from assist.common.assist_utilities import load_subdomain_config
    from assist.workspace.bridge import resolve_project_notebook_context
    from assist.workspace.service import get_active_model_root

    _ctx = resolve_project_notebook_context(cwd=_os.getcwd(), env=_os.environ)
    project_config = load_subdomain_config(
        get_active_model_root(_ctx["workspace_root"], _ctx["project_root"].name) / "config"
    )
except Exception as _e:  # not inside a project, or no active model
    project_config = None
    con.print(f"[yellow]No project config found ({_e}); set LOCAL_RUN_DIR and the run names by hand.[/yellow]")

if project_config:
    _default_run_dir = str(pl.Path(project_config["model_dir"]) / "pestpp_ies")
    _default_run_name = (
        f"{project_config['subdomain']}_pestcal_{_dt.datetime.now():%Y%m%d_%H%M}"
    )
else:
    _default_run_dir = "<USER_PATH_HERE>"
    _default_run_name = "<RUN_NAME_HERE>"

config = {
    "HPC_USER": "<HPC_USER_HERE>",      # << your Hovenweep login (e.g. jdoe)
    "CENTER": "wawsc",                      # << your allocation/center (e.g. wawsc)
    "HPC_HOST": "hw-login1.gs.doi.net",
    "PARTITION": "cpu",
    # The version the run ACTUALLY uses: this EXACT release is downloaded
    # (pyemu get_pestpp, linux build) and shipped in the run dir, and the slurm
    # script runs that shipped binary by path. Use an EXACT tag, NOT "latest":
    # GitHub's "latest" excludes PRE-RELEASES, so it returns the newest STABLE
    # (currently 5.2.16) and would silently downgrade you. Pinning a tag also
    # gives reproducibility. 5.2.27 is a pre-release (2026-06-29).
    "PESTPP_RELEASE": "5.2.26",
    # INDEPENDENT fallback, NOT derived from PESTPP_RELEASE. Only used by the
    # commented-out `module load` line in the slurm scripts, for the rare case
    # where the shipped binary is missing. It must be a version ARC actually
    # has INSTALLED (`module avail pestpp`) -- pre-release tags like 5.2.27 are
    # downloaded+shipped precisely because they are NOT available as modules, so
    # this is deliberately a different, installed, stable version.
    "PESTPP_MODULE": "pestpp/5.2.19",
    "PYWATERSHED_ENV": "nhm",    # << conda env with pywatershed
    # Conda base; derived from HPC_USER by default. Override only if elsewhere.
    "CONDA_DIR": "",                           # "" -> /home/<HPC_USER>/miniforge3
    "CASE_NAME": "prior_mc_reweight_obs+noise_mod",          # << basename of your <CASE_NAME>.pst
    # Default: <subdomain>_pestcal_<YYYYmmdd_HHMM>. Change it if you like.
    "JOB_NAME": _default_run_name,       # << short run label (e.g. SandyRiver_pestcal_20261119_0930)
    "RUN_NAME": _default_run_name,       # << remote run-dir name under your scratch/project space
    # Local path to the run directory that holds the .pst and inputs.
    # Default: <model_dir>/pestpp_ies from the project config.
    "LOCAL_RUN_DIR": _default_run_dir,
    # e.g. "LOCAL_RUN_DIR": r"D:\nhm-workspace\my_project\models\SandyRiver\outputs\runtime\pestpp_ies",
    "WALLTIME": "03:00:00",
    # --- Transfer method ----------------------------------------------------
    # "globus" (preferred — DTN-backed, parallel, resumable, checksummed) or
    # "scp" (simple, but discouraged for multi-GB over a login node).
    "TRANSFER_METHOD": "scp",
    # Globus settings (only used when TRANSFER_METHOD == "globus"). Find the
    # endpoint UUIDs with `globus endpoint search "Hovenweep"` and from your
    # Globus Connect Personal collection on this workstation.
    "GLOBUS_SRC_ENDPOINT": "<SRC_ENDPOINT_ID>",   # this workstation (GCP)
    "GLOBUS_DST_ENDPOINT": "<DST_ENDPOINT_ID>",   # Hovenweep Disk Storage
    # How the local run dir is exposed THROUGH Globus Connect Personal. On
    # Windows GCP, D:\Projects\... is typically /D/Projects/...  (check your
    # GCP "Access" mapping). Leave "" to auto-derive from LOCAL_RUN_DIR.
    "GLOBUS_LOCAL_RUN_DIR": "",
    # --- Worker sizing (NODES x TASKS_PER_NODE are COMPUTED below) ----------
    # PER NODE, workers are capped by RAM (not cores): too many -> OOM kill
    # (learned the hard way: 100 workers x ~5.3 GB > 378 GB usable on a
    # Hovenweep cpu node). We then request ENOUGH NODES (up to MAX_NODES) to
    # cover the ensemble in fewer sequential waves. Cross-node works because the
    # slurm script advertises the manager by FQDN (hostname -f) over the IB
    # fabric — the short name can resolve to unroutable fe80:: link-local.
    "NODE_RAM_GB": 378,       # usable RAM on one node (sacct ReqMem, NOT the 512 GB sticker)
    "NODE_CORES": 128,        # physical cores/node (Hovenweep cpu = 128-core AMD)
    # WORKER_MEM_GB = per-worker RSS + a margin for the SYNCHRONIZED first-run
    # spike. CrookedRiver: sacct MaxRSS ~5.9 GB, but 47 workers ALL numba-jit +
    # load NetCDFs at t=0 simultaneously — that transient spike (which sacct
    # undersamples) OOM-killed the node even though 47 x 5.9 = 279 GB < 378 GB.
    # So budget ~1.5x the measured RSS. 9 GB -> ~35 workers here. Confirm from a
    # COMPLETED run's `sacct -j <id> --format=MaxRSS` and tune.
    "WORKER_MEM_GB": 9,
    "MEM_HEADROOM": 0.85,     # fraction of node RAM to actually use (leave slack for OS/manager)
    "NUM_REALS": 500,         # realizations in the .pst (ies_num_reals); sizes how many nodes to request
    "MAX_NODES": 4,           # cap on nodes to request (be a good scheduler citizen; raise if the queue allows)
    # Optional hard overrides — set to ints to bypass the computed values.
    "NTASKS_OVERRIDE": None,   # total tasks (mgr + workers)
    "NODES_OVERRIDE": None,    # nodes; only used with NTASKS_OVERRIDE
}

from assist.common.user_paths import require_user_path, require_user_value

config["HPC_USER"] = require_user_value(config["HPC_USER"], "HPC_USER", example="jdoe")
config["JOB_NAME"] = require_user_value(config["JOB_NAME"], "JOB_NAME", example="SandyRiver_pestcal_20261119_0930")
config["RUN_NAME"] = require_user_value(config["RUN_NAME"], "RUN_NAME", example="SandyRiver_pestcal_20261119_0930")
config["LOCAL_RUN_DIR"] = str(
    require_user_path(
        config["LOCAL_RUN_DIR"], "LOCAL_RUN_DIR",
        example=r"D:\nhm-workspace\my_project\models\SandyRiver\outputs\runtime\pestpp_ies",
    )
)

# Derived remote paths (usually no need to edit).
config["MAIL_USER"] = f"{config['HPC_USER']}@usgs.gov"
# Default conda base to the user's home if not explicitly set.
if not config.get("CONDA_DIR"):
    config["CONDA_DIR"] = f"/home/{config['HPC_USER']}/miniforge3"
config["REMOTE_RUN_DIR"] = (
    f"/caldera/hovenweep/projects/usgs/water/{config['CENTER']}"
    f"/{config['HPC_USER']}/{config['RUN_NAME']}"
)
config["SCRATCH_BASE"] = (
    f"/caldera/hovenweep/projects/usgs/water/{config['CENTER']}"
    f"/{config['HPC_USER']}/scratch"
)


def _globus_local_path(win_path: str) -> str:
    """Best-effort map a Windows path to its Globus Connect Personal path.

    Windows GCP typically exposes a drive as /<DRIVE>/rest/of/path, e.g.
    D:\\Projects\\x  ->  /D/Projects/x. This is a CONVENIENCE default; verify
    against your GCP "Access" configuration and override GLOBUS_LOCAL_RUN_DIR
    if your mapping differs.
    """
    p = str(win_path).replace("\\", "/")
    if len(p) >= 2 and p[1] == ":":  # drive-letter path like D:/...
        return f"/{p[0]}{p[2:]}"
    return p


if not config.get("GLOBUS_LOCAL_RUN_DIR"):
    config["GLOBUS_LOCAL_RUN_DIR"] = _globus_local_path(config["LOCAL_RUN_DIR"])

local_run_dir = pl.Path(config["LOCAL_RUN_DIR"])


# %% [markdown]
# ## Compute how many workers to request (memory-aware)
#
# On one node the number of concurrent pywatershed workers is limited by **RAM**,
# not cores. This picks the largest `NTASKS` (1 manager + workers) that fits:
#
# ```
# workers = floor(NODE_RAM_GB * MEM_HEADROOM / WORKER_MEM_GB)
# ```
#
# then caps it by cores (no point oversubscribing) and by the number of
# realizations (more workers than reals just idle). `NTASKS = workers + 1`.
#
# To size `WORKER_MEM_GB` accurately, run one forward run or a small ensemble,
# then `sacct -j <jobid> --format=JobID,MaxRSS,ReqMem` and use the `.1` step's
# `MaxRSS` (round up for headroom — sampled MaxRSS misses instantaneous peaks).


# %%
def compute_ntasks(cfg: dict) -> dict:
    """Return the multi-node task layout from a memory + core + reals budget.

    Per-node worker count is capped by RAM and cores (that hasn't changed). What
    IS new: we then request ENOUGH NODES so the total worker pool covers the
    ensemble in as few sequential "waves" as possible. Cross-node PEST++ works
    because workers dial the manager's FQDN over the IB fabric (the slurm script
    now sets MANAGER_HOST via `hostname -f`, verified cn131<->cn132).

    Returns TASKS_PER_NODE and NODES for the #SBATCH directives, plus NTASKS
    (= NODES * TASKS_PER_NODE) and a breakdown for reporting.
    """
    if cfg.get("NTASKS_OVERRIDE"):
        n = int(cfg["NTASKS_OVERRIDE"])
        nodes = int(cfg.get("NODES_OVERRIDE", 1))
        per_node = max(1, n // nodes)
        return {
            "NTASKS": n,
            "NODES": nodes,
            "TASKS_PER_NODE": per_node,
            "workers": n - 1,
            "limited_by": "manual override",
            "mem_cap": None,
            "core_cap": None,
            "reals_cap": None,
        }

    usable_gb = cfg["NODE_RAM_GB"] * cfg["MEM_HEADROOM"]
    mem_cap = int(usable_gb // cfg["WORKER_MEM_GB"])          # tasks RAM allows per node
    core_cap = int(cfg["NODE_CORES"])                        # physical cores per node
    per_node = max(1, min(mem_cap, core_cap))                # tasks to pack on each node
    caps = {"memory": mem_cap, "cores": core_cap}
    limited_by = min(caps, key=caps.get)

    # How many nodes to ask for: enough workers to (ideally) cover the ensemble
    # in one wave, capped by MAX_NODES so we stay a good scheduler citizen.
    # Total tasks = NODES * per_node; workers = total tasks - 1 (rank 0 = mgr).
    reals = int(cfg["NUM_REALS"])
    max_nodes = int(cfg.get("MAX_NODES", 4))
    nodes_for_reals = max(1, _math.ceil((reals + 1) / per_node))
    nodes = min(nodes_for_reals, max_nodes)

    ntasks = nodes * per_node
    workers = ntasks - 1
    return {
        "NTASKS": ntasks,
        "NODES": nodes,
        "TASKS_PER_NODE": per_node,
        "workers": workers,
        "limited_by": limited_by,
        "mem_cap": mem_cap,
        "core_cap": core_cap,
        "reals_cap": reals,
    }


_sizing = compute_ntasks(config)
config["NTASKS"] = _sizing["NTASKS"]

# Estimated waves (how many sequential rounds of forward runs).
_waves = _math.ceil(config["NUM_REALS"] / _sizing["workers"])

config["NODES"] = _sizing["NODES"]
config["TASKS_PER_NODE"] = _sizing["TASKS_PER_NODE"]

con.print("[bold]Worker sizing[/bold]")
con.print(
    f"  Per-node   : {config['NODE_RAM_GB']} GB x {config['MEM_HEADROOM']:.0%} "
    f"= {config['NODE_RAM_GB'] * config['MEM_HEADROOM']:.0f} GB usable "
    f"/ {config['WORKER_MEM_GB']} GB -> {_sizing['mem_cap']} tasks (mem), "
    f"{_sizing['core_cap']} cores; packing [bold]{config['TASKS_PER_NODE']}[/bold]/node "
    f"(limited by {_sizing['limited_by']})"
)
con.print(
    f"  Nodes      : [bold]{config['NODES']}[/bold] "
    f"(cap MAX_NODES={config['MAX_NODES']}; {config['NUM_REALS']} realizations)"
)
con.print(
    f"  [green]=> -N {config['NODES']} --ntasks-per-node={config['TASKS_PER_NODE']} "
    f"(NTASKS = {config['NTASKS']} = 1 manager + {_sizing['workers']} workers)[/green]"
)
con.print(f"  Est. waves : ~{_waves} (ceil {config['NUM_REALS']} reals / {_sizing['workers']} workers)")
if _waves > 1 and config["NODES"] >= config["MAX_NODES"]:
    con.print(
        "  [yellow]Still multi-wave at MAX_NODES.[/yellow] Raise MAX_NODES (if the "
        "queue allows) or lower WORKER_MEM_GB (only if MaxRSS supports it) to add workers."
    )

con.print("\nConfiguration:")
for k, v in config.items():
    con.print(f"  {k:16s} = {v}")

# %% [markdown]
# ## 2. Verify the local run directory and required files
# Confirms the PEST++ inputs the run needs are present before we generate the
# launch scripts. Missing files are reported (adjust your `LOCAL_RUN_DIR` or
# regenerate them with notebooks 01–05).

# %%
case = config["CASE_NAME"]
required = [
    f"{case}.pst",
    f"{case}.pargp_data.csv",
    f"{case}.par_data.csv",
    f"{case}.obs_data.csv",
    f"{case}.tplfile_data.csv",
    f"{case}.insfile_data.csv",
    "forward_run.py",
    "parameters.json",
    "parameters.json.tpl",
    "modelobs.dat",
    "modelobs.dat.ins",
    "control.default.bandit",
    "loc.mat",
    "phi_factors.csv",
]

if not local_run_dir.is_dir():
    con.print(f"[red]LOCAL_RUN_DIR does not exist:[/red] {local_run_dir}")
else:
    con.print(f"Checking required files in [bold]{local_run_dir}[/bold] ...")
    missing = [f for f in required if not (local_run_dir / f).exists()]
    for f in required:
        ok = (local_run_dir / f).exists()
        con.print(f"  {'[green]OK  [/green]' if ok else '[red]MISS[/red]'} {f}")
    if missing:
        con.print(
            f"\n[red]{len(missing)} required file(s) missing.[/red] "
            "Fix LOCAL_RUN_DIR or regenerate via notebooks 01–05 before running."
        )
    else:
        con.print("\n[green]All required files present.[/green]")

    # Report any PEST++ binary ensembles/matrices (.jcb) found in the run dir.
    # These are NOT in `required` because not every run has one and their names
    # vary, BUT when the .pst references an obs/par ensemble (e.g. an
    # ies_observation_ensemble obs+noise file) that file MUST ship or the run
    # dies on the cluster with "error opening binary file ... .jcb". The scp
    # transfer script enumerates *.jcb at runtime, so surfacing them here lets
    # you confirm the expected ensemble is present BEFORE transferring. The
    # obs-ensemble stem often differs from CASE_NAME (e.g. case
    # "prior_mc_reweight_obs+noise_mod" with ensemble
    # "prior_reweight_obs+noise_mod.jcb"), so this does not assume a name.
    jcb_files = sorted(p.name for p in local_run_dir.glob("*.jcb"))
    if jcb_files:
        con.print(
            f"\n[cyan].jcb ensemble/matrix files found ({len(jcb_files)}) — "
            "these will be shipped by the scp transfer:[/cyan]"
        )
        for j in jcb_files:
            con.print(f"  [green]JCB [/green] {j}")
    else:
        con.print(
            "\n[yellow]No .jcb files found.[/yellow] If your .pst sets "
            "ies_observation_ensemble / ies_parameter_ensemble to a .jcb, that "
            "file must be present here or the run will fail on the cluster."
        )

# %% [markdown]
# ## 2b. Fetch the LINUX pestpp-ies binary for Hovenweep
# The Windows `.exe` files that ship in a local run dir are useless on the
# cluster (and we delete them there). Instead, pull the compiled **Linux**
# `pestpp-ies` for a SPECIFIC release straight into the run dir with pyemu's
# `get_pestpp`, so the transfer sends a binary that actually runs on Hovenweep.
#
# TWO critical arguments:
#   - `ostag="linux"`: this notebook runs on Windows, so `get_pestpp`'s OS
#     auto-detect would grab the Windows build. Force the Linux build.
#   - `release_id=config["PESTPP_RELEASE"]` (an EXACT tag, e.g. "5.2.27"), NOT
#     "latest": GitHub's "latest" EXCLUDES pre-releases, so it returns the
#     newest STABLE (5.2.16) and would silently downgrade. An exact tag pulls
#     pre-releases fine and pins the version for reproducibility.
# `subset=["pestpp-ies"]` keeps it to just the one binary we run. The resolved
# release tag is printed for provenance.

# %%
import hashlib as _hashlib
import io as _io
import tarfile as _tarfile
import urllib.request as _urlrequest

from pyemu.utils import get_pestpp

PESTPP_RELEASE = config["PESTPP_RELEASE"]   # exact tag set in the config cell; NOT "latest" (excludes pre-releases)


def _fallback_fetch_linux_ies(dest_dir, tag):
    """Direct-download fallback if pyemu get_pestpp can't fetch the (pre)release.

    Pulls pestpp-<tag>-linux.tar.gz straight from the GitHub release asset URL
    and extracts ONLY the pestpp-ies binary into dest_dir. Returns the Path to
    the extracted binary, or raises on failure. Kept independent of pyemu so a
    pyemu tag-lookup quirk on a pre-release can't block the whole workflow.
    """
    url = (
        f"https://github.com/usgs/pestpp/releases/download/"
        f"{tag}/pestpp-{tag}-linux.tar.gz"
    )
    con.print(f"  [yellow]Fallback:[/yellow] direct download {url}")
    req = _urlrequest.Request(url, headers={"User-Agent": "nhm-assist"})
    with _urlrequest.urlopen(req) as resp:      # follows the release CDN redirect
        blob = resp.read()
    # Extract just the pestpp-ies binary from the tarball (member path ends
    # with .../bin/pestpp-ies or /pestpp-ies).
    out = dest_dir / "pestpp-ies"
    with _tarfile.open(fileobj=_io.BytesIO(blob), mode="r:gz") as tf:
        member = next(
            (m for m in tf.getmembers()
             if m.isfile() and m.name.rsplit("/", 1)[-1] == "pestpp-ies"),
            None,
        )
        if member is None:
            raise RuntimeError("pestpp-ies not found inside the linux tarball")
        with tf.extractfile(member) as src, open(out, "wb") as dst:
            dst.write(src.read())
    con.print(f"  [green]Fallback extracted[/green] {out.name} ({out.stat().st_size} bytes)")
    return out


if local_run_dir.is_dir():
    con.print(
        f"Downloading LINUX pestpp-ies ({PESTPP_RELEASE}) into "
        f"[bold]{local_run_dir}[/bold] ..."
    )
    ies_bin = local_run_dir / "pestpp-ies"   # Linux build: no extension
    # Primary path: pyemu get_pestpp (pinned tag + linux ostag). If it raises OR
    # doesn't produce the binary, fall back to a direct tarball download.
    try:
        get_pestpp(
            str(local_run_dir),
            owner="usgs",
            repo="pestpp",
            release_id=PESTPP_RELEASE,
            ostag="linux",          # << force Linux build for Hovenweep, NOT the local OS
            subset=["pestpp-ies"],
            quiet=True,
        )
    except Exception as _e:  # noqa: BLE001
        con.print(f"  [yellow]get_pestpp failed ({_e}); trying direct download.[/yellow]")
    if not ies_bin.exists():
        try:
            _fallback_fetch_linux_ies(local_run_dir, PESTPP_RELEASE)
        except Exception as _e2:  # noqa: BLE001
            con.print(
                f"[red]Could not obtain pestpp-ies ({PESTPP_RELEASE}) by either method: {_e2}[/red]\n"
                "Check network access to github.com/usgs/pestpp releases, or download "
                f"pestpp-{PESTPP_RELEASE}-linux.tar.gz manually and extract pestpp-ies here."
            )

    if ies_bin.exists():
        con.print(
            f"[green]pestpp-ies (linux) ready[/green] — release "
            f"[bold]{PESTPP_RELEASE}[/bold] -> {ies_bin.name} "
            f"({ies_bin.stat().st_size} bytes)"
        )
        config["PESTPP_RELEASE_RESOLVED"] = PESTPP_RELEASE
    else:
        con.print(
            "[red]Expected pestpp-ies (linux) not found after download attempts.[/red]"
        )
else:
    con.print("[red]Skipping pestpp-ies download — LOCAL_RUN_DIR not found.[/red]")

# %% [markdown]
# ## 3. Generate customized launch scripts
# Reads each template, substitutes your config for the `<PLACEHOLDER>` tokens,
# and writes the result into your local run directory. The SLURM/shell scripts
# are written with **LF line endings** so they run on Linux without a
# `dos2unix`/`sed` fixup.


# %%
def _substitute(text: str, cfg: dict) -> str:
    """Replace <PLACEHOLDER> tokens and the plain 'e.g.' defaults in templates."""
    repl = {
        "<HPC_USER>": cfg["HPC_USER"],
        "<CENTER>": cfg["CENTER"],
        "<USER>@usgs.gov": cfg["MAIL_USER"],
        "<USER>": cfg["HPC_USER"],
        "<PYWATERSHED_ENV>": cfg["PYWATERSHED_ENV"],
        "<CASE_NAME>": cfg["CASE_NAME"],
        "<JOB_NAME>": cfg["JOB_NAME"],
        "<RUN_NAME>": cfg["RUN_NAME"],
        "<LOCAL_RUN_DIR>": cfg["LOCAL_RUN_DIR"],
        # Globus transfer tokens (only present in transfer_to_hpc_globus.ps1):
        "<SRC_ENDPOINT_ID>": cfg.get("GLOBUS_SRC_ENDPOINT", ""),
        "<DST_ENDPOINT_ID>": cfg.get("GLOBUS_DST_ENDPOINT", ""),
        "<GLOBUS_LOCAL_RUN_DIR>": cfg.get("GLOBUS_LOCAL_RUN_DIR", ""),
    }
    for token, value in repl.items():
        text = text.replace(token, str(value))
    return text


def _write_lf(path: pl.Path, text: str):
    """Write text with Unix (LF) line endings."""
    with open(path, "w", newline="\n", encoding="utf-8") as fh:
        fh.write(text)


# Pick the transfer template based on TRANSFER_METHOD. Both are written OUT as
# transfer_to_hpc.ps1 so the STEP A instructions below stay identical.
_transfer_src = (
    "transfer_to_hpc_globus.ps1"
    if config.get("TRANSFER_METHOD", "globus").lower() == "globus"
    else "transfer_to_hpc.ps1"
)
con.print(f"Transfer method: [bold]{config.get('TRANSFER_METHOD', 'globus')}[/bold] (template: {_transfer_src})")

# Scripts to customize: (template name, output name).
# The 1-node fallback ships alongside the multi-node script: known-good config
# (1 node, $(hostname), no preflight) for when you need a reliable run.
scripts = [
    ("run_pestpp_ies.slurm", "run_pestpp_ies.slurm"),
    ("run_pestpp_ies_1node.slurm", "run_pestpp_ies_1node.slurm"),
    ("setup_worker.sh", "setup_worker.sh"),
    (_transfer_src, "transfer_to_hpc.ps1"),
]

if local_run_dir.is_dir():
    for src_name, out_name in scripts:
        src = template_dir / src_name
        if not src.exists():
            con.print(f"[red]Template missing:[/red] {src}")
            continue
        out = local_run_dir / out_name
        customized = _substitute(src.read_text(encoding="utf-8"), config)
        _write_lf(out, customized)
        con.print(f"[green]Wrote[/green] {out}")

    # Apply the SBATCH node/task, --time and conda-dir edits that aren't
    # token-based. -N and --ntasks-per-node use the <NODES>/<TASKS_PER_NODE>
    # placeholders written by the multi-node template.
    slurm_path = local_run_dir / "run_pestpp_ies.slurm"
    if slurm_path.exists():
        s = slurm_path.read_text(encoding="utf-8")
        s = s.replace("#SBATCH -N <NODES>", f"#SBATCH -N {config['NODES']}")
        s = s.replace(
            "#SBATCH --ntasks-per-node=<TASKS_PER_NODE>",
            f"#SBATCH --ntasks-per-node={config['TASKS_PER_NODE']}",
        )
        s = s.replace("#SBATCH --time=04:00:00", f"#SBATCH --time={config['WALLTIME']}")
        s = s.replace(
            'CONDA_DIR="/home/${USER}/miniforge3"',
            f'CONDA_DIR="{config["CONDA_DIR"]}"',
        )
        _write_lf(slurm_path, s)
        con.print(
            f"[green]Applied[/green] NODES={config['NODES']} "
            f"TASKS_PER_NODE={config['TASKS_PER_NODE']}/WALLTIME/CONDA_DIR to {slurm_path.name}"
        )

    # Single-node fallback: 1 node, tasks = per-node RAM cap + 1 manager. Uses a
    # non-token `#SBATCH -n 27` line and its own walltime; conda-dir shared.
    onenode_path = local_run_dir / "run_pestpp_ies_1node.slurm"
    if onenode_path.exists():
        onenode_tasks = config["TASKS_PER_NODE"] + 1   # workers on one node + manager
        s = onenode_path.read_text(encoding="utf-8")
        s = s.replace("#SBATCH -n 27", f"#SBATCH -n {onenode_tasks}")
        s = s.replace("#SBATCH --time=04:00:00", f"#SBATCH --time={config['WALLTIME']}")
        s = s.replace(
            'CONDA_DIR="/home/${USER}/miniforge3"',
            f'CONDA_DIR="{config["CONDA_DIR"]}"',
        )
        _write_lf(onenode_path, s)
        con.print(
            f"[green]Applied[/green] -n {onenode_tasks}/WALLTIME/CONDA_DIR "
            f"to {onenode_path.name} (single-node fallback)"
        )
else:
    con.print("[red]Skipping script generation — LOCAL_RUN_DIR not found.[/red]")

# %% [markdown]
# ## 4. Sanity-check the generated scripts
# Confirms no `<PLACEHOLDER>` tokens remain in the written scripts.

# %%
if local_run_dir.is_dir():
    leftover = {}
    for _src_name, out_name in scripts:
        out = local_run_dir / out_name
        if out.exists():
            txt = out.read_text(encoding="utf-8")
            tokens = [t for t in ("<HPC_USER>", "<CENTER>", "<USER>", "<PYWATERSHED_ENV>",
                                  "<CASE_NAME>", "<JOB_NAME>", "<RUN_NAME>",
                                  "<LOCAL_RUN_DIR>", "<SRC_ENDPOINT_ID>",
                                  "<DST_ENDPOINT_ID>", "<GLOBUS_LOCAL_RUN_DIR>",
                                  "<NODES>", "<TASKS_PER_NODE>") if t in txt]
            if tokens:
                leftover[out_name] = tokens
    if leftover:
        con.print("[red]Unsubstituted tokens remain:[/red]")
        for name, toks in leftover.items():
            con.print(f"  {name}: {toks}")
    else:
        con.print("[green]All placeholders substituted — scripts are ready.[/green]")

# %% [markdown]
# ## 5. Next steps — run these in YOUR terminal (on VPN)
# The notebook cannot SSH/transfer for you (VPN + Kerberos required). Copy the
# commands below.
#
# First confirm Kerberos works:
# ```
# ssh -K {HPC_USER}@{HPC_HOST} "echo connected"
# ```

# %%
c = config
print("=" * 70)
print("STEP A — Transfer to Hovenweep (Windows PowerShell, on VPN):")
print("-" * 70)
if c.get("TRANSFER_METHOD", "globus").lower() == "globus":
    print("  # One-time: log in to Globus and confirm the endpoints resolve.")
    print("  globus login")
    print('  globus endpoint search "Hovenweep"   # confirm DST endpoint UUID')
    print("  # (Globus Connect Personal must be running on this workstation.)")
    print(f"  cd {c['LOCAL_RUN_DIR']}")
    print("  .\\transfer_to_hpc.ps1                 # submits a globus transfer, then ssh fixup")
else:
    print(f"  cd {c['LOCAL_RUN_DIR']}")
    print("  .\\transfer_to_hpc.ps1                 # scp over Kerberos/GSSAPI")
print()
print("=" * 70)
print("STEP B — Smoke-test on the cluster (uses the packaged LINUX pestpp-ies):")
print("-" * 70)
print(f"  ssh -K {c['HPC_USER']}@{c['HPC_HOST']}")
print(f"  cd {c['REMOTE_RUN_DIR']}")
print(f"  conda activate {c['PYWATERSHED_ENV']}   # pywatershed env for forward_run.py")
print("  # The run dir already ships the Linux pestpp-ies (from notebook cell 2b);")
print("  # no `module load pestpp` needed. Make it executable and confirm it runs:")
print("  chmod +x pestpp-ies")
print("  ./pestpp-ies --version        # confirm the packaged Linux binary works")
print("  time python forward_run.py    # expect output/model_custom_output.nc + modelobs.dat")
print()
print("=" * 70)
print("STEP C — Submit the parallel run:")
print("-" * 70)
print("  sbatch run_pestpp_ies.slurm")
print()
print("=" * 70)
print("STEP D — Monitor:")
print("-" * 70)
print(f"  squeue -u {c['HPC_USER']}                  # ST: PD=pending, R=running, CG=completing")
print(f"  squeue -u {c['HPC_USER']} --start          # estimated start time while PENDING (your place in line)")
print(f"  squeue -u {c['HPC_USER']} -o \"%.10i %.9P %.2t %.10M %.20S %.20r\"  # +reason (Priority/Resources) & start est")
print("  tail -f logs/manager.out          # Ctrl+C exits tail, NOT the job")
print(f"  cat {c['SCRATCH_BASE']}/{c['JOB_NAME']}_<jobid>/agent_1/worker.out")
print()
print("=" * 70)
print("STEP E — Cancel (if needed) + clean up scratch:")
print("-" * 70)
print("  scancel <jobid>                   # a dead manager leaves workers idling")
print(f"  rm -rf {c['SCRATCH_BASE']}/{c['JOB_NAME']}_<jobid>")
print("=" * 70)

# %% [markdown]
# ## Notes
# - `noptmax` in the `.pst`: `-1` = prior Monte Carlo (validation run); a positive
#   value = that many IES iterations. Set it in the `.pst`, not the SLURM script.
# - Parameter bounds must satisfy `parlbnd < parubnd` for every parameter, or
#   pestpp-ies aborts during control-file processing (`bounds are busted: 0 >= 0`).
# - Sizing: with N workers the ensemble runs in `ceil(num_reals / (N-1))` waves;
#   per-wave time ≈ the slowest worker's forward-run time. Time one forward run
#   (STEP B) to size `WALLTIME`.
# - Workers are RAM-limited on one node, so `NTASKS` is COMPUTED from
#   `NODE_RAM_GB`, `WORKER_MEM_GB`, cores, and realizations (see the sizing cell)
#   — NOT hardcoded. Requesting more workers than RAM allows gets them OOM-killed
#   mid-run (all realizations lost), which is worse than running fewer that
#   finish. Measure `WORKER_MEM_GB` from `sacct -j <id> --format=MaxRSS` after a
#   first run and refine.
# - Full reference: `scripts/hovenweep/README_hovenweep_run.md`.

# %% [markdown]
# ## 6. If the job sits pending: try other node layouts (`resubmit_if_faster.sh`)
#
# `scripts/hovenweep/resubmit_if_faster.sh` checks whether a **pending** job would
# start sooner with a different node / tasks-per-node layout, and can swap the job
# for that layout. Run it from your own machine (on VPN); it runs on a Hovenweep
# login node over ssh.
#
# **What it does, in one pass:**
#
# 1. Reads the pending job's script and working directory from
#    `scontrol show job <jobid>`. If the job is not `PENDING` it does nothing.
# 2. For every layout in `CANDIDATES` (for example `4x35` = 4 nodes with 35 tasks
#    each) that gives at least `TOTAL_TASKS` tasks, asks Slurm when the same script
#    would start (`sbatch --test-only`), requesting
#    `--mem = tasks_per_node x WORKER_MEM_GB + MGR_MARGIN_GB` per node and
#    `--time = TIME_LIMIT`.
# 3. Prints a table of those estimated start times against the current job's
#    estimate (a job with no estimate yet counts as 2 days out).
# 4. Takes the earliest layout. If it starts at least `MIN_GAIN_MIN` minutes
#    sooner:
#    - **dry run** (the default) only says what it would do;
#    - **`--apply`** submits the new job **first**, and cancels the old one only
#      if that submit succeeded, so a failed submit never loses the job.
#
# It makes one pass and exits; loop it yourself to repeat it (command below).
# After a swap the job has a **new job id**, so restart the loop with that id.
# The start times come from the scheduler's estimates, which change as other
# jobs finish or arrive, so a swap is a reasonable bet, not a guarantee.
#
# **Settings** (environment variables, all optional):
#
# | Variable | Meaning | Script default |
# |---|---|---|
# | `TOTAL_TASKS` | tasks wanted (1 manager + workers) | 140 |
# | `WORKER_MEM_GB` | memory per worker, GB | 9 |
# | `MGR_MARGIN_GB` | extra memory per node for the manager, GB | 7 |
# | `TIME_LIMIT` | `--time` for the new job | 01:30:00 |
# | `MIN_GAIN_MIN` | swap only if it starts at least this many minutes earlier | 60 |
# | `CANDIDATES` | layouts to test, `NODESxTASKS_PER_NODE`, space-separated | `4x35 6x24 8x18 10x14 12x12 14x10 16x9 20x7 28x5` |
#
# The cell below fills `TOTAL_TASKS`, `WORKER_MEM_GB` and `TIME_LIMIT` from this
# run's configuration (`NTASKS`, `WORKER_MEM_GB`, `WALLTIME`), so a swapped job
# asks for the same resources as the one you submitted.
#
# **One-time setup:** the script is not copied into the run directory. Copy it
# once to your project space on Hovenweep (first command below), and again
# whenever you change it.

# %%
c = config
_script_local = template_dir / "resubmit_if_faster.sh"
_script_remote = (
    f"/caldera/hovenweep/projects/usgs/water/{c['CENTER']}/{c['HPC_USER']}/resubmit_if_faster.sh"
)
_env = (
    f"TOTAL_TASKS={c.get('NTASKS', 140)} WORKER_MEM_GB={c['WORKER_MEM_GB']} "
    f"TIME_LIMIT={c['WALLTIME']}"
)
_ssh = f"ssh -K {c['HPC_USER']}@{c['HPC_HOST']}"
if not _script_local.exists():
    con.print(f"[red]Not found:[/red] {_script_local}")

print("=" * 70)
print("STEP F — If the job sits PENDING: try other node layouts")
print("         (Windows PowerShell, on VPN; <jobid> from sbatch or squeue)")
print("-" * 70)
print("  # One-time (and after editing the script): copy it to Hovenweep")
print(f'  scp "{_script_local}" {c["HPC_USER"]}@{c["HPC_HOST"]}:{_script_remote}')
print()
print("  # Dry run: print the layout table and what it would do (changes nothing)")
print(f'  {_ssh} "{_env} bash {_script_remote} <jobid>"')
print()
print("  # Apply: submit the best layout first, then cancel the old job")
print(f'  {_ssh} "{_env} bash {_script_remote} <jobid> --apply"')
print()
print("  # Repeat every 10 min until the job starts (Ctrl+C to stop).")
print("  # After a swap, stop and restart the loop with the NEW job id.")
print(
    f'  while ($true) {{ {_ssh} "{_env} bash {_script_remote} <jobid> --apply"; '
    "Start-Sleep 600 }"
)
print()
print("  # Other settings go in front of `bash` the same way, e.g.")
print(f'  {_ssh} "{_env} MIN_GAIN_MIN=30 bash {_script_remote} <jobid>"')
print("=" * 70)
