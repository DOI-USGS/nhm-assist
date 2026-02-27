# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.17.0
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %%
import sys
import os
import pathlib as pl
import warnings


warnings.filterwarnings("ignore")
from rich.console import Console

con = Console()
from rich import pretty

pretty.install()
import jupyter_black

jupyter_black.load()
# Find and set the "nhm-assist" root directory
root_dir = pl.Path(os.getcwd().rsplit("nhm-assist", 1)[0] + "nhm-assist")
sys.path.append(str(root_dir))
from nhm_helpers.nhm_hydrofabric import make_hf_map_elements
from nhm_helpers.map_template import make_hf_map
from nhm_helpers.nhm_assist_utilities import load_subdomain_config

config = load_subdomain_config(root_dir)
# con.print(config)

# %%
import numpy as np
import pandas as pd
import geopandas as gpd
import io
from nhm_helpers.nhm_hydrofabric import make_hf_map_elements

# %%
# Read in the hru_gdf
hru_gdf = gpd.read_file(
    root_dir / f"nhm_v2_model_building/domain_data/OR_v2_domain/NHM_OR_draft.gpkg",
    layer="nhru",
)
# Convert the index from float to integer
hru_gdf.index = hru_gdf.index.astype(int)
hru_gdf.reset_index(inplace=True, drop=False)
hru_gdf.rename(columns={"index": "hru_index"}, inplace=True)

# %%
hru_gdf

# %%
# Read in the hru_gdf
seg_gdf = gpd.read_file(
    root_dir / f"nhm_v2_model_building/domain_data/OR_v2_domain/NHM_OR_draft.gpkg",
    layer="nsegment",
)
# Convert the index from float to integer
seg_gdf.index = seg_gdf.index.astype(int)
seg_gdf.reset_index(inplace=True, drop=False)
seg_gdf.rename(columns={"index": "seg_index"}, inplace=True)

# %%
seg_gdf

# %%
import glob
import os

# Define path and pattern for CSV files
path = root_dir / f"nhm_v2_model_building/domain_data/OR_v2_domain/rOR"
pattern = os.path.join(path, "*.csv")

# Get all matching CSV file names
all_files = glob.glob(pattern)

# Read each file using a list comprehension and concatenate
df = pd.concat((pd.read_csv(f) for f in all_files), ignore_index=True)

# %%
kk = pd.read_csv(
    root_dir / f"nhm_v2_model_building/domain_data/OR_v2_domain/rOR/nhm_id.csv"
)

# %%
kk

# %%
from pyPRMS.metadata.metadata import MetaData
from pyPRMS import ParameterFile
from contextlib import redirect_stdout
import io

f = io.StringIO()
with redirect_stdout(f):
    import pywatershed as pws

# %%
# pws.Parameters.get_dim_values()
pws.Parameters.dimensions.values

# get_dim_values()

# %%
pws.Parameters

# %%
from pprint import pprint
import numpy as np
import pywatershed as pws

nreach = 3
params = pws.parameters.PrmsParameters(
    dims={
        "nsegment": nreach,
    },
    coords={
        "nsegment": np.array(range(nreach)),
    },
    data_vars={
        "tosegment": np.array([2, 3, 0]),  # one-based index, 0 is outflow
        "seg_length": np.ones(nreach) * 1.0e3,
    },
    metadata={
        "nsegment": {"dims": ["nsegment"]},
        "tosegment": {"dims": ["nsegment"]},
        "seg_length": {"dims": ["nsegment"]},
    },
    validate=True,
)

# %%
params.coords

# %%

# %%
params
<pywatershed.parameters.prms_parameters.PrmsParameters object at 0x105781390>
params.dims
mappingproxy({'nsegment': 3})
params.coords
mappingproxy({'nsegment': array([0, 1, 2])})
pprint(params.data)
{'coords': mappingproxy({'nsegment': array([0, 1, 2])}),
 'data_vars': mappingproxy({'seg_length': array([1000., 1000., 1000.]),
                            'tosegment': array([2, 3, 0])}),
 'dims': mappingproxy({'nsegment': 3}),
 'encoding': mappingproxy({}),
 'metadata': mappingproxy({'global': mappingproxy({}),
                           'nsegment': mappingproxy({'dims': ['nsegment']}),
                           'seg_length': mappingproxy({'dims': ['nsegment']}),
                           'tosegment': mappingproxy({'dims': ['nsegment']})})}
pprint(params.metadata)
mappingproxy({'global': mappingproxy({}),
              'nsegment': mappingproxy({'dims': ['nsegment']}),
              'seg_length': mappingproxy({'dims': ['nsegment']}),
              'tosegment': mappingproxy({'dims': ['nsegment']})})
xrds = params.to_xr_ds()
xrds
<xarray.Dataset>
Dimensions:     (nsegment: 3)
Coordinates:
  * nsegment    (nsegment) int64 0 1 2
Data variables:
    tosegment   (nsegment) int64 2 3 0
    seg_length  (nsegment) float64 1e+03 1e+03 1e+03
