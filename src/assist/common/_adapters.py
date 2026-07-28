"""Boundary adapters to normalize nhf's `poi_gage_id` to the canonical `poi_id`."""
from __future__ import annotations

import functools

import pandas as pd

try:  # xarray is a hard dep in practice, but stay import-safe
    import xarray as xr
except Exception:  # pragma: no cover
    xr = None

_POI_OLD = "poi_gage_id"
_POI_NEW = "poi_id"


def _canonicalize_poi(obj):
    if isinstance(obj, pd.DataFrame):
        if _POI_OLD in obj.columns and _POI_NEW not in obj.columns:
            return obj.rename(columns={_POI_OLD: _POI_NEW})
        return obj
    if xr is not None and isinstance(obj, (xr.Dataset, xr.DataArray)):
        names = set(map(str, getattr(obj, "dims", ()))) | set(
            map(str, getattr(obj, "coords", {}).keys())
        )
        if _POI_OLD in names:
            return obj.rename({_POI_OLD: _POI_NEW})
        return obj
    return obj


def poi_adapt(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if "poi_gage_id_sel" in kwargs and "poi_id_sel" not in kwargs:
            kwargs["poi_id_sel"] = kwargs.pop("poi_gage_id_sel")
        args = tuple(_canonicalize_poi(a) for a in args)
        kwargs = {k: _canonicalize_poi(v) for k, v in kwargs.items()}
        return fn(*args, **kwargs)

    return wrapper
