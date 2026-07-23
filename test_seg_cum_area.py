"""Build a table of seg_idx, nhm_seg, seg_cum_area, seg_inc_area, and computed_cum_area.

seg_inc_area = sum of hru_area for all HRUs that drain directly to the segment.
seg_cum_area = value from the param file (cumulative contributing area).
computed_cum_area = incremental area + all upstream incremental areas (routed via tosegment).
"""
from pyPRMS import ParameterFile
from pyPRMS.metadata.metadata import MetaData
import numpy as np
import pandas as pd

param_file = r"d:\nhm-assist\domain_data\20250502_v1.1_gm_ngwos_ucb\myparam.param"
pf = ParameterFile(param_file, metadata=MetaData().metadata, verbose=False)

# Get the parameters
hru_area = pf.get("hru_area").data
hru_segment = pf.get("hru_segment").data
nhm_seg = pf.get("nhm_seg").data
seg_cum_area = pf.get("seg_cum_area").data
tosegment = pf.get("tosegment").data

nseg = len(seg_cum_area)

# Compute incremental (local) area per segment
hru_df = pd.DataFrame({
    "hru_area": hru_area,
    "hru_segment": hru_segment,
})

local_area_series = hru_df.groupby("hru_segment")["hru_area"].sum()
local_area = np.zeros(nseg)
for seg_idx in range(1, nseg + 1):
    if seg_idx in local_area_series.index:
        local_area[seg_idx - 1] = local_area_series[seg_idx]

# Compute cumulative area by routing upstream via tosegment
upstream = {i: [] for i in range(1, nseg + 1)}
for seg_idx in range(1, nseg + 1):
    downstream = tosegment[seg_idx - 1]
    if downstream > 0:
        upstream[downstream].append(seg_idx)


def compute_cum_area(seg_idx, local_areas, upstream_map, cache):
    if seg_idx in cache:
        return cache[seg_idx]
    cum = local_areas[seg_idx - 1]
    for us_seg in upstream_map[seg_idx]:
        cum += compute_cum_area(us_seg, local_areas, upstream_map, cache)
    cache[seg_idx] = cum
    return cum


cache = {}
computed_cum_area = np.zeros(nseg)
for seg_idx in range(1, nseg + 1):
    computed_cum_area[seg_idx - 1] = compute_cum_area(seg_idx, local_area, upstream, cache)

# Build output table
seg_df = pd.DataFrame({
    "seg_idx": np.arange(1, nseg + 1),
    "nhm_seg": nhm_seg,
    "seg_cum_area": seg_cum_area,
    "computed_cum_area": computed_cum_area,
    "seg_inc_area": local_area,
})

seg_df["cum_area_diff"] = seg_df["seg_cum_area"] - seg_df["computed_cum_area"]

# Save
out_path = r"d:\nhm-assist\domain_data\20250502_v1.1_gm_ngwos_ucb\seg_area_comparison.csv"
seg_df.to_csv(out_path, index=False)

# Report
mismatches = seg_df[seg_df["cum_area_diff"].abs() > 0.01]
print(f"Saved {len(seg_df)} rows to {out_path}")
print()
print(seg_df.head(15).to_string(index=False))
print()
print(f"Segments matching (diff <= 0.01): {len(seg_df) - len(mismatches)}")
print(f"Segments mismatched: {len(mismatches)}")
if len(mismatches) > 0:
    print(f"Max cum_area_diff: {mismatches['cum_area_diff'].abs().max():.4f}")
else:
    print("[PASS]: computed_cum_area matches seg_cum_area for all segments.")
