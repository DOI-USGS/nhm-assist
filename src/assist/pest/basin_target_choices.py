"""Per-basin choices about the calibration targets, learned during calibration.

Some choices about how a basin's calibration targets are built only become
clear once that basin has been calibrated. On the SandyRiver model (Nov 2026),
for example, the monthly HRU runoff ensemble fit the gage flows better without
the GLDAS-2.1 Noah member. Those choices are recorded once per project, in
``project_config/basin_target_choices.yaml``, so every notebook that builds or
checks a target applies the same choice, and the reason travels with it.

Each entry is keyed by the domain name (``subdomain`` in the model's config).
A domain with no entry, or no file, uses the targets as delivered.

.. code-block:: yaml

    SandyRiver:
      runoff:
        drop_members: [gldas_noah_v21_monthly]
        reason: >-
          It was discovered during calibration that this creates a better value
          for the mean.
        evidence: >-
          ...
        date: "2026-11-23"

Only ``runoff.drop_members`` changes anything today. ``reason``, ``evidence``
and ``date`` are printed and written into the target file's attributes.

The runoff ensemble is rebuilt with the same definitions the delivered file
uses (checked against ``runoff_targets.nc``, ``range_method =
multi_source_minmax``): ``ensemble_mean`` is the NaN-aware mean of the members,
``lower_bound`` / ``upper_bound`` their NaN-aware min / max, ``ensemble_std``
their population standard deviation (ddof = 0, NaN where fewer than two
members have a value) and ``n_sources`` the number of members with a value.
"""
from __future__ import annotations

import pathlib as pl
from dataclasses import dataclass, field
from typing import Mapping

import numpy as np
import xarray as xr
import yaml

BASIN_CHOICES_FILENAME = "basin_target_choices.yaml"

# Member variables in the OHM runoff target file (``runoff_targets.nc``).
RUNOFF_MEMBERS = ("era5_land", "gldas_noah_v21_monthly", "mwbm_climgrid")
# Variables rebuilt from the members.
RUNOFF_ENSEMBLE_VARS = ("ensemble_mean", "lower_bound", "upper_bound", "ensemble_std", "n_sources")


@dataclass
class RunoffChoice:
    """The runoff members to use for one domain, and why."""

    domain: str | None
    members: list
    dropped: list = field(default_factory=list)
    reason: str = ""
    evidence: str = ""
    date: str = ""
    source: str | None = None  # the YAML file the choice came from

    @property
    def changed(self) -> bool:
        return bool(self.dropped)

    def describe(self) -> str:
        if not self.changed:
            return f"runoff: all members used ({', '.join(self.members)})"
        txt = (f"runoff ({self.domain}): dropped {', '.join(self.dropped)}; "
               f"ensemble rebuilt from {', '.join(self.members)}")
        if self.reason:
            txt += f". Reason: {self.reason}"
        return txt


def basin_choices_path(project_context: Mapping | None) -> pl.Path | None:
    """Path of the project's basin choices file, or None outside a project."""
    if not project_context or not project_context.get("project_config_root"):
        return None
    return pl.Path(project_context["project_config_root"]) / BASIN_CHOICES_FILENAME


def read_basin_choices(path) -> dict:
    """The whole file as a dict (``{}`` if ``path`` is None or missing)."""
    if path is None:
        return {}
    path = pl.Path(path)
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping of domain name to choices, got {type(data).__name__}.")
    return data


def runoff_choice(path, domain, available=RUNOFF_MEMBERS) -> RunoffChoice:
    """The runoff members to use for ``domain``.

    ``available`` is the member variables present in the target file. A member
    named in ``drop_members`` that is not one of them is an error (most likely a
    typo), so a wrong name can never silently leave the member in. Dropping
    every member is also an error.
    """
    available = list(available)
    data = read_basin_choices(path)
    entry = {}
    if domain is not None:
        entry = (data.get(str(domain)) or {}).get("runoff") or {}
    drop = [str(m).strip() for m in (entry.get("drop_members") or [])]
    unknown = [m for m in drop if m not in available]
    if unknown:
        raise ValueError(
            f"{path}: {domain}.runoff.drop_members names {unknown}, which are not "
            f"runoff members of the target file (available: {available})."
        )
    members = [m for m in available if m not in drop]
    if not members:
        raise ValueError(f"{path}: {domain}.runoff.drop_members drops every runoff member.")
    clean = lambda v: " ".join(str(v).split()) if v else ""  # noqa: E731
    return RunoffChoice(domain=None if domain is None else str(domain), members=members,
                        dropped=[m for m in available if m in drop],
                        reason=clean(entry.get("reason")), evidence=clean(entry.get("evidence")),
                        date=clean(entry.get("date")),
                        source=str(path) if (path is not None and drop) else None)


def available_runoff_members(ds: xr.Dataset) -> list:
    """The runoff member variables present in ``ds``, in the standard order."""
    return [m for m in RUNOFF_MEMBERS if m in ds.data_vars]


def rebuild_runoff_ensemble(ds: xr.Dataset, choice: RunoffChoice) -> xr.Dataset:
    """``ds`` with the ensemble variables rebuilt from ``choice.members``.

    Returns ``ds`` unchanged when nothing is dropped. Otherwise the ensemble
    variables are recomputed (see the module docstring for the definitions),
    keep their attributes and dtype, and are stamped with the members used and
    the reason. The member variables themselves, including dropped ones, are
    left in the file for reference.
    """
    if not choice.changed:
        return ds
    missing = [m for m in choice.members if m not in ds]
    if missing:
        raise KeyError(f"runoff members {missing} are not in the dataset.")
    stack = xr.concat([ds[m] for m in choice.members], dim="_member")
    count = stack.notnull().sum("_member")
    new = {
        "ensemble_mean": stack.mean("_member", skipna=True),
        "lower_bound": stack.min("_member", skipna=True),
        "upper_bound": stack.max("_member", skipna=True),
        "ensemble_std": stack.std("_member", ddof=0, skipna=True).where(count >= 2),
        "n_sources": count,
    }
    out = ds.copy()
    stamp = {
        "members_used": ",".join(choice.members),
        "members_dropped": ",".join(choice.dropped),
        "members_dropped_reason": choice.reason,
        "members_dropped_evidence": choice.evidence,
        "members_dropped_date": choice.date,
        "members_dropped_source": choice.source or "",
    }
    for name, da in new.items():
        if name not in ds:
            continue
        da = da.where(count > 0) if name != "n_sources" else da
        out[name] = da.astype(ds[name].dtype).transpose(*ds[name].dims)
        out[name].attrs = {**ds[name].attrs, **stamp}
    out.attrs = {**ds.attrs, "member_keys": ",".join(choice.members), **stamp}
    if "source_keys" in ds.attrs:
        out.attrs["source_keys"] = ",".join(choice.members)
    return out
