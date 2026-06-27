# ---
# jupyter:
#   jupytext:
#     formats: nhf_assist/notebooks///ipynb,src/workflow_templates/nhf///py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.3
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %%
import geopandas as gpd

# %%
v2_gdf = gpd.read_file(r"C:\users\ahaj\nhm-assist\nhgf_v2_fabric_modification\domain_data\NHM_OR_domain\NHM_OR_draft_12_2025.gpkg", layer = "nhru")

# %%
import numpy as np
from shapely import get_coordinates

def has_nonfinite_coords(geom) -> bool:
    """
    True if geometry is None/empty or any coordinate (X/Y/Z) is NaN or ±Inf.
    """
    if geom is None or geom.is_empty:
        return True
    # include_z=True ensures we catch NaN/Inf in Z as well
    coords = get_coordinates(geom, include_z=False)  # returns (N,2) or (N,3) ndarray
    return not np.isfinite(coords).all()

# Example usage:
mask_bad = v2_gdf.geometry.apply(has_nonfinite_coords)
bad_rows = v2_gdf.loc[mask_bad]          # rows with non-finite coords
bad_idx  = v2_gdf.index[mask_bad].tolist()

print(f"Bad rows: {mask_bad.sum()} of {len(v2_gdf)}")
print("First few bad indices:", bad_idx[:10])

# %%
from shapely import make_valid

v2_gdf["geometry"] = v2_gdf.geometry.apply(
    lambda g: make_valid(g, method="structure", keep_collapsed=True)
)

# %%
v2_gdf.iloc[41181].geometry

# %%

# %%
