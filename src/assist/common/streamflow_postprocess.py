from __future__ import annotations

import numpy as np
import xarray as xr


def subset_seg_outflow_to_poi_gages(
    seg_outflow: xr.DataArray,
    *,
    poi_gage_segment: np.ndarray,
    poi_gage_id: np.ndarray,
    nhm_seg: np.ndarray,
) -> xr.DataArray:
    """Subset seg_outflow to POI gage segments in a rerun-safe way.

    `poi_gage_segment` stores 1-based positions into the full `nhm_seg` parameter
    array. The output file itself is labeled by `nhm_seg`, and may already be
    filtered from a previous run, so selection must happen by label rather than
    by positional index.
    """

    if "nhm_seg" not in seg_outflow.dims:
        raise KeyError("Expected seg_outflow to include an `nhm_seg` dimension.")

    gage_nhm_seg = np.asarray(nhm_seg)[np.asarray(poi_gage_segment) - 1]
    return seg_outflow.sel(nhm_seg=gage_nhm_seg).assign_coords(
        npoi_gages=("nhm_seg", np.asarray(poi_gage_id))
    )
