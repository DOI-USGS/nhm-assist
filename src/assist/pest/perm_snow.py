"""Permanent-snow ("perm_snow") HRUs for PEST++ calibration.

Some HRUs carry glaciers or a snowpack that lasts through the summer (on the
SandyRiver model, the six highest HRUs on the flanks of Mt. Hood). The SWE
calibration targets come from gridded products (SNODAS, ERA5-Land, UA SWE) that
show no SWE there in late summer, and the model cannot hold a small summer pack
either: at those HRUs the pack never melts out and grows every year (a "snow
tower"). Those HRUs are handled differently during calibration:

- `tmax_cbh_adj` starts at +4.5 F and `tmin_cbh_adj` at 0 F in every month, and
  calibration may move them only within narrow bounds (notebook 02b).
- Notebook 03 can give their SWE observations zero weight while keeping them
  for plotting (``PERM_SNOW_ZERO_WEIGHT_SWE``, off by default).

The HRUs are listed once per project, in ``project_config/perm_snow_hrus.csv``,
with two columns: ``hru_id`` (the ``nhm_id``) and ``child_domain`` (the model in
which the HRU was identified). The list is a master list for the project, so it
can name HRUs that a given child model does not contain; those are reported and
skipped. The file lives in ``project_config`` because a model's ``pestpp_ies``
folder is routinely deleted and rebuilt.
"""

from __future__ import annotations

import json
import pathlib as pl
from dataclasses import dataclass, field
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

PERM_SNOW_FILENAME = "perm_snow_hrus.csv"
PERM_SNOW_COLUMNS = ("hru_id", "child_domain")

# Starting values (degrees F, every month) given to perm_snow HRUs. From
# forward-run tests on the SandyRiver prior (Nov 2026): with these values the
# six Mt. Hood HRUs stopped growing a snow tower and peaked at about 46 in of SWE
# against a 35-43 in target.
PERM_SNOW_START_VALUES = {"tmax_cbh_adj": 4.5, "tmin_cbh_adj": 0.0}


@dataclass
class PermSnowSelection:
    """The perm_snow HRUs that apply to one model."""

    path: pl.Path | None
    selected: list[int] = field(default_factory=list)
    not_in_model: list[int] = field(default_factory=list)
    child_domain: dict[int, str] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.selected)


def perm_snow_list_path(project_context: Mapping | None) -> pl.Path | None:
    """Path of the project's perm_snow list, or None outside a project."""
    if not project_context or not project_context.get("project_config_root"):
        return None
    return pl.Path(project_context["project_config_root"]) / PERM_SNOW_FILENAME


def read_perm_snow_list(path: str | pl.Path) -> pd.DataFrame:
    """Read and validate a perm_snow list. Returns one row per HRU id."""
    path = pl.Path(path)
    df = pd.read_csv(path, dtype={"child_domain": str}, comment="#")
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in PERM_SNOW_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"{path} is missing column(s) {missing}; expected {list(PERM_SNOW_COLUMNS)}."
        )
    df = df.dropna(subset=["hru_id"])
    ids = pd.to_numeric(df["hru_id"], errors="coerce")
    bad = df.loc[ids.isna() | (ids != ids.round()), "hru_id"].tolist()
    if bad:
        raise ValueError(f"{path}: hru_id values that are not integers: {bad}")
    df = df.assign(
        hru_id=ids.astype(int),
        child_domain=df["child_domain"].fillna("").str.strip(),
    )
    # An HRU listed from more than one child domain is kept once, with the
    # domains joined, so the report still says where each listing came from.
    return (
        df.groupby("hru_id", sort=False)["child_domain"]
        .agg(lambda s: ", ".join(sorted({d for d in s if d})))
        .reset_index()
    )


def select_perm_snow_hrus(
    path: str | pl.Path | None, model_nhm_ids: Iterable[int]
) -> PermSnowSelection:
    """Split the listed HRUs into those in this model and those that are not.

    A missing file (or ``path=None``) gives an empty selection: the model is
    calibrated without any perm_snow handling.
    """
    if path is None or not pl.Path(path).exists():
        return PermSnowSelection(path=pl.Path(path) if path is not None else None)
    listed = read_perm_snow_list(path)
    model_ids = {int(i) for i in model_nhm_ids}
    in_model = listed["hru_id"].isin(model_ids)
    return PermSnowSelection(
        path=pl.Path(path),
        selected=listed.loc[in_model, "hru_id"].tolist(),
        not_in_model=listed.loc[~in_model, "hru_id"].tolist(),
        child_domain=dict(zip(listed["hru_id"], listed["child_domain"])),
    )


def set_perm_snow_start_values(
    pars: dict,
    hrus: Iterable[int],
    start_values: Mapping[str, float] = PERM_SNOW_START_VALUES,
) -> pd.DataFrame:
    """Set the perm_snow starting values in ``pars`` (edited in place).

    ``pars`` is the parameter dict notebook 02b builds the template from
    (``pardat.parameters``); each parameter is an (nmonth, nhru) array, and
    ``pars["nhm_id"]`` gives the HRU order. The arrays pywatershed returns are
    read-only, so each changed parameter is replaced with an edited copy.

    Returns one row per parameter and HRU whose value was changed, with the
    old values (min and max over months) and the new value. An empty frame
    means every value was already at its perm_snow starting value.
    """
    nhm_id = np.asarray(pars["nhm_id"]).astype(int)
    hrus = [int(h) for h in hrus]
    idx = {h: int(np.where(nhm_id == h)[0][0]) for h in hrus if h in set(nhm_id)}
    rows = []
    for name, value in start_values.items():
        arr = np.array(pars[name], dtype=float, copy=True)
        if arr.shape[-1] != len(nhm_id):
            raise ValueError(
                f"{name} has shape {arr.shape}; expected the last axis to be nhru "
                f"({len(nhm_id)})."
            )
        for h, i in idx.items():
            old = arr[..., i]
            if not np.allclose(old, value):
                rows.append(
                    {
                        "parameter": name,
                        "hru_id": h,
                        "old_min": float(old.min()),
                        "old_max": float(old.max()),
                        "new_value": float(value),
                    }
                )
            arr[..., i] = value
        pars[name] = arr
    return pd.DataFrame(
        rows, columns=["parameter", "hru_id", "old_min", "old_max", "new_value"]
    )


def update_parameters_json(
    json_path: str | pl.Path,
    hrus: Iterable[int],
    start_values: Mapping[str, float] = PERM_SNOW_START_VALUES,
) -> None:
    """Write the perm_snow starting values into a ``parameters.json`` file.

    Keeps ``parameters.json`` (what the forward run reads) consistent with the
    starting values in the PEST++ template.
    """
    json_path = pl.Path(json_path)
    data = json.loads(json_path.read_text())
    nhm_id = np.asarray(data["nhm_id"]).astype(int)
    cols = [int(np.where(nhm_id == int(h))[0][0]) for h in hrus if int(h) in set(nhm_id)]
    for name, value in start_values.items():
        arr = np.asarray(data[name], dtype=float)
        if arr.shape[-1] != len(nhm_id):
            raise ValueError(
                f"{json_path}: {name} has shape {arr.shape}; expected the last axis "
                f"to be nhru ({len(nhm_id)})."
            )
        arr[..., cols] = value
        data[name] = arr.tolist()
    json_path.write_text(json.dumps(data))


def hru_of_parameter(parnames: pd.Series) -> pd.Series:
    """HRU id (int, or <NA>) from PEST parameter names like ``tmax_cbh_adj:hru_7305:mon_1``."""
    token = parnames.astype(str).str.split(":").str[1]
    return pd.to_numeric(
        token.where(token.str.startswith("hru_", na=False)).str[len("hru_") :],
        errors="coerce",
    ).astype("Int64")


def swe_obs_mask(obs: pd.DataFrame, hrus: Iterable[int]) -> pd.Series:
    """True for SWE observations at the given HRUs.

    SWE observation names end in the HRU id, e.g. ``swe_monthly:2010_10_31:7305``.
    """
    hrus = {int(h) for h in hrus}
    is_swe = obs["obgnme"].astype(str).str.startswith("swe")
    hru = pd.to_numeric(obs["obsnme"].astype(str).str.split(":").str[-1], errors="coerce")
    return is_swe & hru.isin(hrus)
