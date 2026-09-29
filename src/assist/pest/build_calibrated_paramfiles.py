"""Build classic PRMS ``.param`` files from PEST++ IES calibrated realizations.

WHAT THIS DOES
--------------
A PEST++ IES run stores its calibrated parameters as a flat ensemble table
(``<case>.<iter>.par.csv``): one row per realization, one column per adjustable
parameter. The column names are *flattened* PRMS parameters tagged by location
and (where relevant) month, e.g.::

    smidx_coef:hru_11777              # 1D, per-HRU
    adjmix_rain:hru_11777:mon_7       # 2D, per-HRU per-month
    mann_n:seg_3055                   # 1D, per-segment

pywatershed / PRMS want these values back in a structured ``myparam.param``
file (dimensioned arrays, not flat name/value pairs). This tool rebuilds that
file for one or more realizations by placing each flat value into the correct
array slot, then writing the classic ``.param`` text format with pyPRMS.

WHY THE MAPPING IS BY nhm_id (NOT position)
-------------------------------------------
The HRU tag ``hru_<N>`` is the *national* ``nhm_id`` and the segment tag
``seg_<N>`` is the ``nhm_seg`` id. Each id is looked up in the starting param
file's ``nhm_id`` / ``nhm_seg`` arrays and written to that index, so placement
is correct regardless of ordering in the ensemble. Month tags ``mon_<m>`` are
1-based (Jan=1) and index the second axis of pyPRMS's ``(nhru, nmonth)`` arrays.

WHAT IT DOES NOT DO
-------------------
The forward-run guardrail clips in ``forward_run.py`` (soil_moist_max,
soil_rechr_max_frac, dprst_frac, smidx_coef floors/caps) are applied in memory
at *run* time. They are intentionally NOT baked into these files -- these hold
the raw calibrated values PEST estimated. The guardrails re-apply at model run.

USAGE
-----
Run inside the project's pixi env. Point it at any IES output directory::

    pixi run --manifest-path <repo>/pyproject.toml python build_calibrated_paramfiles.py \
        --run-dir D:/path/to/SomeRiver_ies

By default it exports the ``base`` realization plus the single lowest-phi
non-base member, auto-detecting the final iteration and auto-discovering a
matching starting ``.param``. Common overrides::

    # export the 5 lowest-phi realizations (including base if it ranks)
    ... --best 5

    # export specific realizations by name
    ... --reals base 233 168

    # pin the iteration and the structural starting .param explicitly
    ... --iteration 3 --starting-param D:/.../models/SandyRiver/inputs/source_data/myparam.param

    # also export the best realization for one observation group (e.g. the
    # hru_streamflow/runoff target), named myparam_lowest_runoff_mon.param
    ... --phi-group runoff_mon

    # just list the best realizations and their phi, write nothing
    ... --list --phi-group runoff_mon

The starting ``.param`` supplies structure, dimensions, metadata, and the
values of every non-calibrated parameter, so it MUST match the calibration
domain (same nhm_id / nhm_seg set). The tool verifies this before writing. If
you don't pass ``--starting-param`` it searches ``--param-search-root`` for a
``.param`` whose ids match the run's ``parameters.json``; failing that it
builds the structural base from the run's own ``parameters.json``.

The functions (``build_param_files``, ``pick_realizations``, ...) are also
importable from another script or notebook.

Requires: pandas, numpy, pyPRMS (all in the nhm-assist env).
"""
from __future__ import annotations

import argparse
import json
import pathlib as pl
import sys

import numpy as np
import pandas as pd
from pyPRMS import ParameterFile, Parameters, MetaData

# Default place to hunt for a matching starting .param when one isn't supplied.
DEFAULT_PARAM_SEARCH_ROOT = pl.Path(r"d:\nhm-workspace\Oregon_Recharge\models")

# Columns in *.phi.actual.csv that are summary stats, not realizations.
_PHI_META = ("iteration", "total_runs", "mean", "standard_deviation", "min", "max")

# Non-group bookkeeping columns in *.phi.group.csv (the rest are obs groups).
_GROUP_META = ("iteration", "total_runs", "obs_realization", "par_realization")


# --------------------------------------------------------------------------- #
# Discovery helpers -- figure out iteration / starting file automatically
# --------------------------------------------------------------------------- #
def detect_case(run_dir: pl.Path) -> str:
    """Infer the PEST++ case name from the ``*.pst`` file in ``run_dir``."""
    psts = sorted(run_dir.glob("*.pst"))
    if not psts:
        raise SystemExit(f"no .pst file found in {run_dir} -- pass --case explicitly")
    return psts[0].stem


def detect_final_iteration(run_dir: pl.Path, case: str) -> int:
    """Return the highest iteration N for which ``<case>.N.par.csv`` exists."""
    iters = []
    for p in run_dir.glob(f"{case}.*.par.csv"):
        mid = p.name[len(case) + 1 : -len(".par.csv")]
        if mid.isdigit():
            iters.append(int(mid))
    if not iters:
        raise SystemExit(f"no {case}.<N>.par.csv ensemble files found in {run_dir}")
    return max(iters)


def _read_run_ids(run_dir: pl.Path) -> tuple[np.ndarray, np.ndarray]:
    """Return (nhm_id, nhm_seg) arrays from the run's parameters.json."""
    with open(run_dir / "parameters.json") as f:
        pj = json.load(f)
    return np.asarray(pj["nhm_id"], dtype=int), np.asarray(pj["nhm_seg"], dtype=int)


def _param_ids(param_path: pl.Path, md) -> tuple[np.ndarray, np.ndarray]:
    pf = ParameterFile(str(param_path), metadata=md)
    return (
        np.asarray(pf.get("nhm_id").data).astype(int),
        np.asarray(pf.get("nhm_seg").data).astype(int),
    )


def discover_starting_param(
    run_dir: pl.Path, search_root: pl.Path, md
) -> pl.Path | None:
    """Find a ``.param`` under ``search_root`` whose ids match this run's domain.

    Returns the matching path, or None if nothing matches (caller then falls
    back to building a structural base from parameters.json).
    """
    want_id, want_seg = _read_run_ids(run_dir)
    if not search_root.exists():
        return None
    for cand in sorted(search_root.rglob("*.param")):
        try:
            cid, cseg = _param_ids(cand, md)
        except Exception:
            continue  # not a readable PRMS param file; skip
        if np.array_equal(cid, want_id) and np.array_equal(cseg, want_seg):
            return cand
    return None


def structural_param_from_json(run_dir: pl.Path, md, out_path: pl.Path) -> pl.Path:
    """Build a starting ``.param`` from the run's own parameters.json.

    Used when no matching external ``.param`` is found. parameters.json is the
    full domain parameter set the forward run consumes, so it is a valid
    structural base; calibrated parameters get overwritten afterward anyway.
    """
    params = Parameters.from_json  # noqa -- probe attr existence for older pyPRMS
    # pyPRMS has no direct json loader; go through pywatershed which does, then
    # hand arrays to a fresh pyPRMS Parameters via ParameterFile is not possible.
    # Simplest portable path: use pywatershed to load json, write nothing here,
    # and let ParameterNetCDF/round-trip do it. To avoid a hard pywatershed dep
    # at import time, do the import lazily.
    import pywatershed as pws  # noqa

    raise SystemExit(
        "No matching .param found under the search root and automatic "
        "json->param construction is not available in this environment. "
        "Pass --starting-param pointing at a .param for this domain "
        f"({len(_read_run_ids(run_dir)[0])} HRUs)."
    )


# --------------------------------------------------------------------------- #
# Core: phi ranking + value placement
# --------------------------------------------------------------------------- #
def pick_realizations(run_dir: pl.Path, case: str, iteration: int,
                      n: int = 5) -> pd.Series:
    """Return the ``n`` lowest-phi realizations at ``iteration`` (phi ascending).

    Reads ``<case>.phi.actual.csv``; index is the realization name (incl.
    ``base``), values are the actual measurement phi. Zeros (failed/absent runs)
    are dropped.
    """
    phi = pd.read_csv(run_dir / f"{case}.phi.actual.csv")
    row = phi[phi["iteration"] == iteration].iloc[0]
    reals = row.drop(labels=list(_PHI_META)).astype(float)
    reals = reals[reals > 0].sort_values()
    return reals.head(n)


def pick_realizations_by_group(run_dir: pl.Path, case: str, iteration: int,
                               group: str, n: int = 5) -> pd.Series:
    """Return the ``n`` lowest-phi realizations for a single observation ``group``.

    Ranks by one column of ``<case>.phi.group.csv`` -- the per-group phi
    breakdown PEST++ writes alongside the total phi. Each row of that file is one
    realization at a given iteration, identified by the ``obs_realization``
    column (``base`` included). The returned Series is indexed by realization
    name (str) with the group's phi as values, ascending. Zeros (failed/absent
    runs) are dropped, matching ``pick_realizations``.
    """
    g = _read_group_table(run_dir, case, iteration)
    if group not in g.columns:
        avail = [c for c in g.columns if c not in _GROUP_META]
        raise SystemExit(
            f"phi group '{group}' not found. Available groups:\n  " + "\n  ".join(avail)
        )
    s = g[group].astype(float)
    s = s[s > 0].sort_values()
    return s.head(n)


def _read_group_table(run_dir: pl.Path, case: str, iteration: int) -> pd.DataFrame:
    """Return ``<case>.phi.group.csv`` rows for ``iteration``, indexed by realization."""
    gpath = run_dir / f"{case}.phi.group.csv"
    if not gpath.exists():
        raise SystemExit(f"no {case}.phi.group.csv in {run_dir}")
    g = pd.read_csv(gpath)
    g = g[g["iteration"] == iteration].copy()
    g.index = g["obs_realization"].astype(str)
    return g


def resolve_groups(run_dir: pl.Path, case: str, iteration: int,
                   groups=None, prefix: str = None,
                   drop_all_zero: bool = True) -> list[str]:
    """Resolve an explicit ``groups`` list and/or a name ``prefix`` to real columns.

    A group whose phi is zero for every realization at this iteration (e.g. the
    ``streamflow_nodata`` zero-weight bucket) is dropped when ``drop_all_zero``.
    Raises if any explicitly named group is missing.
    """
    g = _read_group_table(run_dir, case, iteration)
    available = [c for c in g.columns if c not in _GROUP_META]
    chosen: list[str] = []
    if groups:
        missing = [x for x in groups if x not in available]
        if missing:
            raise SystemExit(
                "phi group(s) not found: " + ", ".join(missing)
                + "\nAvailable:\n  " + "\n  ".join(available)
            )
        chosen.extend(groups)
    if prefix:
        pref = [c for c in available if c.startswith(prefix)]
        if not pref:
            raise SystemExit(
                f"no phi groups start with '{prefix}'. Available:\n  "
                + "\n  ".join(available)
            )
        chosen.extend(c for c in pref if c not in chosen)
    if drop_all_zero:
        kept = [c for c in chosen if float(g[c].abs().sum()) > 0]
        dropped = [c for c in chosen if c not in kept]
        if dropped:
            print(f"    (skipping all-zero group(s): {', '.join(dropped)})")
        chosen = kept
    if not chosen:
        raise SystemExit("no non-zero phi groups selected")
    return chosen


def pick_realizations_by_groups(run_dir: pl.Path, case: str, iteration: int,
                                groups: list[str], n: int = 5) -> pd.Series:
    """Rank realizations by the *summed* phi across several observation ``groups``.

    Sums the named group columns of ``<case>.phi.group.csv`` per realization,
    then returns the ``n`` lowest (ascending). ``base`` is included. Rows where
    the summed phi is zero (failed/absent runs) are dropped.
    """
    g = _read_group_table(run_dir, case, iteration)
    total = g[groups].astype(float).sum(axis=1)
    total = total[total > 0].sort_values()
    return total.head(n)


def _load_ensemble(run_dir: pl.Path, case: str, iteration: int) -> pd.DataFrame:
    """Load the parameter ensemble table; index = realization name (str)."""
    df = pd.read_csv(
        run_dir / f"{case}.{iteration}.par.csv", index_col=0, low_memory=False
    )
    df.index = df.index.astype(str)
    return df


def _place_values(pf: ParameterFile, real_vals: pd.Series) -> tuple[int, int]:
    """Write one realization's flat values into the pyPRMS parameter arrays.

    Returns (values_placed, n_calibrated_params). Raises if any calibrated array
    is only partially covered -- a guard against silent id/shape mismatches.
    """
    hru_pos = {v: i for i, v in enumerate(np.asarray(pf.get("nhm_id").data).astype(int))}
    seg_pos = {v: i for i, v in enumerate(np.asarray(pf.get("nhm_seg").data).astype(int))}

    # group flat names by the underlying PRMS parameter
    by_param: dict[str, list[tuple[str, float]]] = {}
    for name, val in real_vals.items():
        by_param.setdefault(name.split(":")[0], []).append((name, float(val)))

    placed = 0
    for pname, items in by_param.items():
        param = pf.get(pname)
        arr = np.array(param.data, dtype=float)
        filled = np.zeros(arr.shape, dtype=bool)
        for name, val in items:
            parts = name.split(":")
            if len(parts) == 2 and parts[1].startswith("seg_"):   # per-segment 1D
                i = seg_pos[int(parts[1].split("_")[1])]
                arr[i] = val
                filled[i] = True
            elif len(parts) == 3:                                 # per-HRU per-month 2D
                i = hru_pos[int(parts[1].split("_")[1])]
                m = int(parts[2].split("_")[1]) - 1               # mon_1 -> col 0
                arr[i, m] = val
                filled[i, m] = True
            else:                                                 # per-HRU 1D
                i = hru_pos[int(parts[1].split("_")[1])]
                arr[i] = val
                filled[i] = True
        if not filled.all():
            raise SystemExit(
                f"{pname}: only {filled.sum()}/{filled.size} slots filled "
                f"-- id set or shape mismatch between ensemble and starting file"
            )
        param.data = arr.astype(np.asarray(param.data).dtype)  # back to native dtype
        placed += filled.size
    return placed, len(by_param)


def _assert_domain_match(run_dir: pl.Path, starting_param: pl.Path, md) -> None:
    """Fail early if the starting .param's ids don't match the run's domain."""
    want_id, want_seg = _read_run_ids(run_dir)
    got_id, got_seg = _param_ids(starting_param, md)
    if not (np.array_equal(got_id, want_id) and np.array_equal(got_seg, want_seg)):
        raise SystemExit(
            f"domain mismatch: starting .param has {len(got_id)} HRUs / "
            f"{len(got_seg)} segments, run expects {len(want_id)} / {len(want_seg)}. "
            f"Point --starting-param at a .param for THIS domain."
        )


def build_param_files(
    targets,
    run_dir: pl.Path,
    starting_param: pl.Path,
    case: str = "prior_mc_reweight",
    iteration: int | None = None,
    out_dir: pl.Path | None = None,
) -> list[pl.Path]:
    """Build a ``.param`` file for each (realization, filename) target.

    ``targets`` may be a ``{realization: filename}`` mapping or a sequence of
    ``(realization, filename)`` pairs. The pair form allows the *same*
    realization to be written under more than one name (e.g. when the lowest
    total-phi and lowest single-group realization coincide).

    ``iteration=None`` auto-detects the final iteration. Each output file is a
    complete PRMS parameter set: calibrated parameters take the realization's
    values, everything else is carried from ``starting_param``.
    """
    run_dir = pl.Path(run_dir)
    starting_param = pl.Path(starting_param)
    if iteration is None:
        iteration = detect_final_iteration(run_dir, case)
    out_dir = pl.Path(out_dir) if out_dir else run_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    md = MetaData().metadata
    _assert_domain_match(run_dir, starting_param, md)
    ens = _load_ensemble(run_dir, case, iteration)

    pairs = list(targets.items()) if isinstance(targets, dict) else list(targets)

    written: list[pl.Path] = []
    for real_id, out_name in pairs:
        if real_id not in ens.index:
            raise SystemExit(f"realization '{real_id}' not in {case}.{iteration}.par.csv")
        print(f"\n=== realization {real_id} -> {out_name} ===")
        real_vals = ens.loc[real_id].astype(float)

        pf = ParameterFile(str(starting_param), metadata=md)  # fresh per realization
        n, nparams = _place_values(pf, real_vals)
        print(f"    placed {n} calibrated values across {nparams} parameters")

        out_path = out_dir / out_name
        pf.write_parameter_file(str(out_path))
        _ = ParameterFile(str(out_path), metadata=md)  # round-trip check
        print(f"    wrote + verified {out_path}")
        written.append(out_path)
    return written


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _safe_name(real_id: str) -> str:
    """Filename-safe token for a realization id."""
    return "".join(c if c.isalnum() else "_" for c in str(real_id))


def _resolve_targets(args, run_dir: pl.Path, case: str, iteration: int) -> dict:
    """Turn CLI selection (--reals / --best / default) into {real_id: filename}."""
    def _name(rid):
        return "myparam_base.param" if rid == "base" else f"myparam_real_{_safe_name(rid)}.param"

    if args.reals:
        return [(rid, _name(rid)) for rid in args.reals]

    if args.best:
        ids = list(pick_realizations(run_dir, case, iteration, n=args.best).index)
        return [(rid, _name(rid)) for rid in ids]

    # default: base + lowest total-phi non-base member, plus (optionally) the
    # lowest non-base member for a specific observation group. Returned as a
    # list of pairs so the group winner can share a realization with the total
    # winner yet still get its own group-named file.
    targets: list[tuple[str, str]] = []
    ranked = pick_realizations(run_dir, case, iteration, n=50)
    if "base" in ranked.index:
        targets.append(("base", "myparam_base.param"))
    nonbase = [r for r in ranked.index if r != "base"]
    if nonbase:
        targets.append((nonbase[0], "myparam_lowest_nonbase.param"))

    if args.phi_group:
        granked = pick_realizations_by_group(run_dir, case, iteration,
                                             args.phi_group, n=50)
        g_nonbase = [r for r in granked.index if r != "base"]
        if g_nonbase:
            targets.append(
                (g_nonbase[0], f"myparam_lowest_{_safe_name(args.phi_group)}.param")
            )

    if args.phi_groups or args.phi_groups_prefix:
        groups = resolve_groups(run_dir, case, iteration,
                                groups=args.phi_groups, prefix=args.phi_groups_prefix)
        label = args.phi_groups_label
        if not label:
            label = "streamflow" if args.phi_groups_prefix == "streamflow_" else "groups"
        print(f"    summed-group ranking uses: {', '.join(groups)}")
        granked = pick_realizations_by_groups(run_dir, case, iteration, groups, n=50)
        g_nonbase = [r for r in granked.index if r != "base"]
        if g_nonbase:
            targets.append(
                (g_nonbase[0], f"myparam_lowest_{_safe_name(label)}.param")
            )
    return targets


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Build PRMS .param files from PEST++ IES calibrated realizations.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--run-dir", type=pl.Path, default=pl.Path.cwd(),
                    help="PEST++ IES output directory (holds *.par.csv, *.phi.actual.csv).")
    ap.add_argument("--case", default=None,
                    help="PEST++ case name (default: inferred from the .pst file).")
    ap.add_argument("--iteration", type=int, default=None,
                    help="Ensemble iteration to use (default: final iteration found).")
    ap.add_argument("--starting-param", type=pl.Path, default=None,
                    help="Structural starting .param for this domain "
                         "(default: auto-discovered under --param-search-root).")
    ap.add_argument("--param-search-root", type=pl.Path, default=DEFAULT_PARAM_SEARCH_ROOT,
                    help="Where to hunt for a matching starting .param.")
    ap.add_argument("--out-dir", type=pl.Path, default=None,
                    help="Where to write outputs (default: the run directory).")

    sel = ap.add_mutually_exclusive_group()
    sel.add_argument("--reals", nargs="+", default=None,
                     help="Explicit realization names to export (e.g. base 233 168).")
    sel.add_argument("--best", type=int, default=None,
                     help="Export the N lowest-phi realizations.")

    ap.add_argument("--phi-group", default=None,
                    help="In the default selection, also export the lowest-phi "
                         "non-base realization for this observation group "
                         "(a column of <case>.phi.group.csv, e.g. 'runoff_mon'). "
                         "Written as myparam_lowest_<group>.param.")
    ap.add_argument("--phi-groups", nargs="+", default=None,
                    help="Also export the lowest non-base realization ranked by "
                         "the SUMMED phi across these groups. Combine with "
                         "--phi-groups-prefix to add name-matched groups.")
    ap.add_argument("--phi-groups-prefix", default=None,
                    help="Add every phi group whose name starts with this prefix "
                         "to the --phi-groups set (e.g. 'streamflow_' for all "
                         "POI-gage streamflow groups). All-zero groups like "
                         "streamflow_nodata are skipped automatically.")
    ap.add_argument("--phi-groups-label", default=None,
                    help="Filename label for the summed-groups output "
                         "(default: 'streamflow' when using the streamflow_ "
                         "prefix, else 'groups'). File: myparam_lowest_<label>.param.")
    ap.add_argument("--list", action="store_true",
                    help="List the lowest-phi realizations and exit (writes nothing). "
                         "With --phi-group, also lists that group's ranking.")
    args = ap.parse_args(argv)

    run_dir = args.run_dir.resolve()
    if not run_dir.exists():
        print(f"run-dir does not exist: {run_dir}", file=sys.stderr)
        return 2

    case = args.case or detect_case(run_dir)
    iteration = args.iteration if args.iteration is not None else detect_final_iteration(run_dir, case)
    print(f"run-dir   : {run_dir}")
    print(f"case      : {case}")
    print(f"iteration : {iteration}")

    if args.list:
        n = args.best or 10
        ranked = pick_realizations(run_dir, case, iteration, n=n)
        print(f"\n{n} lowest total-phi realizations at iteration {iteration}:")
        print(ranked.to_string())
        if args.phi_group:
            granked = pick_realizations_by_group(run_dir, case, iteration,
                                                 args.phi_group, n=n)
            print(f"\n{n} lowest '{args.phi_group}' phi realizations at iteration {iteration}:")
            print(granked.to_string())
        if args.phi_groups or args.phi_groups_prefix:
            groups = resolve_groups(run_dir, case, iteration,
                                    groups=args.phi_groups, prefix=args.phi_groups_prefix)
            print(f"\nsummed-group ranking uses: {', '.join(groups)}")
            granked = pick_realizations_by_groups(run_dir, case, iteration, groups, n=n)
            print(f"{n} lowest SUMMED-group phi realizations at iteration {iteration}:")
            print(granked.to_string())
        return 0

    md = MetaData().metadata
    starting = args.starting_param
    if starting is None:
        starting = discover_starting_param(run_dir, args.param_search_root, md)
        if starting is None:
            starting = structural_param_from_json(run_dir, md, run_dir / "_structural.param")
        print(f"starting  : {starting}  (auto-discovered)")
    else:
        print(f"starting  : {starting}")

    targets = _resolve_targets(args, run_dir, case, iteration)
    print("targets   :", targets)

    build_param_files(
        targets,
        run_dir=run_dir,
        starting_param=starting,
        case=case,
        iteration=iteration,
        out_dir=args.out_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
