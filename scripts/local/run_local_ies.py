"""run_local_ies.py -- run a PEST++ IES ensemble on THIS machine (Windows/Linux/macOS).

Local counterpart of scripts/hovenweep/run_pestpp_ies.slurm + setup_worker.sh.
One PEST++ manager listens on a TCP port and N workers connect to it over
localhost, exactly as under Slurm, but with no scheduler, transfer, or VPN.

Normally the local_pest_setup notebook copies this file into the PEST++ run
directory, writes `run_local_config.json` next to it, and launches it. It can
also be run by hand from the run directory:

    python run_local_ies.py              # run the ensemble
    python run_local_ies.py --benchmark  # time ONE forward run, report peak RAM

Config keys (run_local_config.json):
    case            .pst basename (no extension) that PEST++ is started with
    source_case     basename the external *_data.csv files carry (differs from
                    `case` only when the notebook wrote an edited .pst copy)
    exe             pestpp-ies executable (absolute path)
    port            manager TCP port
    n_workers       number of workers (the manager is one extra process)
    worker_root     directory that holds the per-worker run directories
    python_exe      python whose environment has pywatershed (run by the .pst
                    model command line, `python forward_run.py`)
    low_priority    run workers at below-normal priority (keeps the PC usable)
    stagger_s       seconds between worker starts (avoids a synchronized
                    numba-JIT / NetCDF-load memory spike)
    keep_workers    keep worker directories after the run
    output_root     (optional) folder that holds the results packages. Results go
                    to <output_root>/<run_name>. Absent = <run_dir>/results, the
                    older layout. worker_root must be a folder of its own: it is
                    deleted at the end of a run, so it may not be, or contain,
                    run_dir or output_root.
    run_name        results folder name: <output_root>/<run_name>. When the
                    run ends, the same package a Hovenweep run copies back is
                    written there (see collect_results). Also: --collect.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
IS_WIN = os.name == "nt"

# Small per-worker files, copied. Mirrors COPY_FILES in setup_worker.sh.
COPY_FILES = [
    "parameters.json",
    "parameters.json.tpl",
    "modelobs.dat",
    "modelobs.dat.ins",
    "control.default.bandit",
    "forward_run.py",
    "loc.mat",
    "phi_factors.csv",
    "starting_par_vals.dat",
]
# External data tables, named <source_case>.<suffix>.
CASE_SUFFIXES = [
    "pargp_data.csv",
    "par_data.csv",
    "obs_data.csv",
    "tplfile_data.csv",
    "insfile_data.csv",
]
# Large read-only inputs: linked, not copied. Mirrors SYMLINK_FILES.
LINK_DIRS = ["observation_data", "ancillary"]


def _link_file(src: Path, dst: Path) -> None:
    """Hard link (no admin needed on the same NTFS volume); copy if that fails."""
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _link_dir(src: Path, dst: Path) -> None:
    """Directory junction on Windows (no admin), symlink elsewhere; copy on failure."""
    if dst.exists() or dst.is_symlink():
        return
    try:
        if IS_WIN:
            res = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(dst), str(src)],
                capture_output=True,
            )
            if res.returncode != 0:
                raise OSError(res.stderr.decode(errors="replace"))
        else:
            os.symlink(src, dst, target_is_directory=True)
    except OSError:
        shutil.copytree(src, dst)


def build_worker_dir(cfg: dict, wdir: Path) -> None:
    run_dir = Path(cfg["run_dir"])
    wdir.mkdir(parents=True, exist_ok=True)
    (wdir / "output").mkdir(exist_ok=True)
    names = [f"{cfg['case']}.pst"]
    names += [f"{cfg['source_case']}.{s}" for s in CASE_SUFFIXES]
    names += COPY_FILES
    for name in names:
        if (run_dir / name).exists():
            shutil.copy2(run_dir / name, wdir / name)
    for nc in run_dir.glob("*.nc"):
        _link_file(nc, wdir / nc.name)
    for d in LINK_DIRS:
        if (run_dir / d).is_dir():
            _link_dir(run_dir / d, wdir / d)


def worker_env(cfg: dict) -> dict:
    """Environment for the model: pywatershed's python first on PATH, 1 thread each."""
    env = os.environ.copy()
    py_dir = Path(cfg["python_exe"]).resolve().parent
    extra = [py_dir, py_dir / "Scripts", py_dir / "Library" / "bin", py_dir / "bin"]
    env["PATH"] = os.pathsep.join(
        [str(p) for p in extra if p.is_dir()] + [env.get("PATH", "")]
    )
    for var in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMBA_NUM_THREADS",
    ):
        env[var] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    return env


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        import psutil

        parent = psutil.Process(proc.pid)
        for child in parent.children(recursive=True):
            child.kill()
        parent.kill()
    except Exception:
        proc.kill()


def benchmark(cfg: dict) -> dict:
    """Run ONE forward run in a scratch worker dir; report wall time + peak RAM."""
    import psutil

    wdir = Path(cfg["worker_root"]) / "bench"
    if wdir.exists():
        shutil.rmtree(wdir, ignore_errors=True)
    build_worker_dir(cfg, wdir)
    t0 = time.time()
    proc = subprocess.Popen(
        [cfg["python_exe"], "forward_run.py"],
        cwd=wdir,
        env=worker_env(cfg),
        stdout=open(wdir / "bench.out", "w"),
        stderr=subprocess.STDOUT,
    )
    peak = 0
    try:
        ps = psutil.Process(proc.pid)
        while proc.poll() is None:
            try:
                procs = [ps, *ps.children(recursive=True)]
                peak = max(peak, sum(p.memory_info().rss for p in procs))
            except psutil.Error:
                pass
            time.sleep(0.2)
    finally:
        wall = time.time() - t0
    result = {
        "returncode": proc.returncode,
        "wall_s": round(wall, 1),
        "peak_rss_gb": round(peak / 1024**3, 2),
        "log": str(wdir / "bench.out"),
    }
    if not cfg.get("keep_workers"):
        shutil.rmtree(wdir, ignore_errors=True)
    return result


STATE_FILE = "run_local_state.json"
# A file is a PEST++ INPUT if it ends with one of these; any other file that
# starts with "<case>." is a PEST++ OUTPUT.
INPUT_SUFFIXES = tuple("." + s for s in CASE_SUFFIXES) + (".pst",)


def _unique_dir(base: Path) -> Path:
    if not base.exists():
        return base
    i = 2
    while (base.parent / f"{base.name}_{i}").exists():
        i += 1
    return base.parent / f"{base.name}_{i}"


def results_base(cfg: dict) -> Path:
    """Folder that holds results packages: cfg["output_root"], else <run_dir>/results."""
    if cfg.get("output_root"):
        return Path(cfg["output_root"])
    return Path(cfg["run_dir"]) / "results"


def check_roots(cfg: dict) -> None:
    """Refuse a worker_root that the end-of-run cleanup would turn into data loss.

    worker_root is deleted when the run ends (unless keep_workers), so it must not
    be run_dir or output_root, nor contain either of them.
    """
    root = Path(cfg["worker_root"]).resolve()
    for label, p in (("run_dir", cfg.get("run_dir")), ("output_root", cfg.get("output_root"))):
        if not p:
            continue
        p = Path(p).resolve()
        if p == root or root in p.parents:
            raise ValueError(
                f"worker_root ({root}) is, or contains, {label} ({p}). It is deleted "
                "after the run; give the workers a folder of their own."
            )


def collect_results(cfg: dict, started: float | None = None, finished: float | None = None) -> Path:
    """Package a run into <output_root>/<run_name>, laid out like the folder a
    Hovenweep run copies back (the run directory, without worker scratch):

        <case>.*  inputs + PEST++ outputs (.rec, .N.par.csv, .N.obs.csv, .phi.*, ...)
        forward_run.py, parameters.json(.tpl), modelobs.dat(.ins), loc.mat, ...
        prcp.nc, tmax.nc, tmin.nc, *.jcb, pestpp-ies.exe
        ancillary/  observation_data/  output/model_custom_output.nc  logs/manager.out

    Outputs are taken only if written at or after the run started, so leftovers
    from an earlier run in the same directory are not mixed in. If the run used
    an edited .pst copy (case "<source>_local"), its files are renamed back to
    the source case name so plotting code finds the usual file names.
    Never overwrites: a name clash gets a _2, _3 ... suffix.
    """
    run_dir = Path(cfg["run_dir"])
    state_path = run_dir / STATE_FILE
    if started is None and state_path.exists():
        started = json.loads(state_path.read_text(encoding="utf-8-sig")).get("started")
    if started is None:
        raise RuntimeError("No recorded run start time; cannot tell this run's outputs from old ones.")
    case, src = cfg["case"], cfg["source_case"]
    dest = _unique_dir(results_base(cfg) / (cfg.get("run_name") or f"{src}_local"))
    dest.mkdir(parents=True)
    slack = 2.0  # seconds of filesystem timestamp granularity
    keep = set(COPY_FILES)
    copied, stale = 0, []

    def rename(n: str) -> str:
        return src + n[len(case):] if n.startswith(case + ".") else n

    for f in sorted(run_dir.iterdir()):
        if not f.is_file():
            continue
        n = f.name
        if n.startswith(case + "."):
            if not n.endswith(INPUT_SUFFIXES) and f.stat().st_mtime < started - slack:
                stale.append(n)
                continue
        elif case != src and n.startswith(src + "."):
            if not n.endswith(INPUT_SUFFIXES) or n == f"{src}.pst":
                continue  # old outputs, and the original .pst the edited copy replaces
        elif n in keep or n.endswith((".nc", ".jcb")) or n in ("pestpp-ies.exe", "pestpp-ies"):
            pass
        else:
            continue  # other cases' files, other pestpp tools, Hovenweep/launcher scripts
        shutil.copy2(f, dest / rename(n))
        copied += 1

    for d in LINK_DIRS:
        if (run_dir / d).is_dir():
            shutil.copytree(run_dir / d, dest / d)
    mco = run_dir / "output" / "model_custom_output.nc"
    if mco.exists():
        (dest / "output").mkdir()
        shutil.copy2(mco, dest / "output" / mco.name)
    (dest / "logs").mkdir()
    for a, b in (("manager_local.out", "manager.out"), ("launcher_local.out", "launcher_local.out")):
        if (run_dir / "logs" / a).exists():
            shutil.copy2(run_dir / "logs" / a, dest / "logs" / b)
    end = finished or time.time()
    info = {
        "run_name": dest.name,
        "case": case,
        "source_case": src,
        "n_workers": cfg.get("n_workers"),
        "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)),
        "finished": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(end)),
        "elapsed_h": round((end - started) / 3600, 2),
        "stale_outputs_skipped": stale,
    }
    (dest / "logs" / "local_run_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(f"Packaged {copied} files + directories into {dest}", flush=True)
    return dest


def run(cfg: dict) -> int:
    run_dir = Path(cfg["run_dir"])
    root = Path(cfg["worker_root"])
    check_roots(cfg)
    (run_dir / "logs").mkdir(exist_ok=True)
    started = time.time()
    (run_dir / STATE_FILE).write_text(json.dumps({"started": started}), encoding="utf-8")
    root.mkdir(parents=True, exist_ok=True)
    n = int(cfg["n_workers"])

    print(f"Building {n} worker directories in {root} ...", flush=True)
    wdirs = []
    for i in range(1, n + 1):
        wd = root / f"agent_{i}"
        if wd.exists():
            shutil.rmtree(wd, ignore_errors=True)
        build_worker_dir(cfg, wd)
        wdirs.append(wd)

    exe, case, port = cfg["exe"], cfg["case"], int(cfg["port"])
    env = worker_env(cfg)
    flags_mgr = 0
    flags_wrk = 0
    if IS_WIN:
        flags_mgr = subprocess.CREATE_NO_WINDOW
        flags_wrk = subprocess.CREATE_NO_WINDOW
        if cfg.get("low_priority", True):
            flags_wrk |= subprocess.BELOW_NORMAL_PRIORITY_CLASS

    print(f"Manager: {exe} {case}.pst /h :{port}", flush=True)
    mgr_log = open(run_dir / "logs" / "manager_local.out", "w", buffering=1)
    mgr = subprocess.Popen(
        [exe, f"{case}.pst", "/h", f":{port}"],
        cwd=run_dir,
        env=env,
        stdout=mgr_log,
        stderr=subprocess.STDOUT,
        creationflags=flags_mgr,
    )
    time.sleep(5)
    if mgr.poll() is not None:
        print(f"Manager exited immediately (code {mgr.returncode}); see logs/manager_local.out")
        return 1

    workers = []
    for i, wd in enumerate(wdirs, start=1):
        wlog = open(wd / "worker.out", "w", buffering=1)
        workers.append(
            subprocess.Popen(
                [exe, f"{case}.pst", "/h", f"localhost:{port}"],
                cwd=wd,
                env=env,
                stdout=wlog,
                stderr=subprocess.STDOUT,
                creationflags=flags_wrk,
            )
        )
        time.sleep(float(cfg.get("stagger_s", 1.0)))
    print(f"Started {len(workers)} workers; waiting for the manager ...", flush=True)

    try:
        rc = mgr.wait()
    except KeyboardInterrupt:
        print("Interrupted: stopping everything.", flush=True)
        rc = 130
        _kill_tree(mgr)
    # Workers normally exit on their own when the manager finishes.
    deadline = time.time() + 30
    for w in workers:
        try:
            w.wait(timeout=max(0.1, deadline - time.time()))
        except subprocess.TimeoutExpired:
            _kill_tree(w)
    if not cfg.get("keep_workers"):
        shutil.rmtree(root, ignore_errors=True)
    print(f"Manager finished with exit code {rc}.", flush=True)
    try:
        collect_results(cfg, started, time.time())
    except Exception as e:  # a finished run must not be lost to a packaging error
        print(f"Packaging failed ({e}). Re-run with --collect after fixing.", flush=True)
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", default=str(HERE / "run_local_config.json"))
    ap.add_argument("--benchmark", action="store_true")
    ap.add_argument("--collect", action="store_true", help="package the last run into <output_root>/<run_name> and exit")
    args = ap.parse_args()
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8-sig"))
    cfg.setdefault("run_dir", str(HERE))
    if args.collect:
        print(collect_results(cfg))
        return 0
    if args.benchmark:
        print(json.dumps(benchmark(cfg)))
        return 0
    return run(cfg)


if __name__ == "__main__":
    sys.exit(main())
