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
import glob
from dataretrieval import nldi
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
import pandas as pd
import io



# Find and set the "nhm-assist" root directory
# Find the repo root via the editable-installed `assist` package — robust
# against sibling clones, cwd quirks, and arbitrary checkout directory names.
import assist as _assist_pkg
root_dir = pl.Path(_assist_pkg.__file__).resolve().parents[2] / "nhf_assist"

from dotenv import load_dotenv

load_dotenv(
    dotenv_path=root_dir / ".env"
)  # this will load the environment variables from the .env file


from assist.nhf.nhm_hydrofabric_v2 import (
    create_hru_gdf,
    create_segment_gdf,
    create_poi_df,
    create_default_gages_file,
    read_gages_file,
)

from assist.nhf.nhm_assist_utilities_v2 import (
    load_subdomain_config,
)

config = load_subdomain_config(root_dir)

# %%
root_dir

# %%
folders_path = root_dir / "data_dependencies/stats_pois_2018"
data_folders = [f for f in pl.Path(folders_path).glob("region*/") if f.is_dir()]

# %%
data_folders

# %%
results = [
    f.stem.split("_", 1)[1]  # Get everything after first _
    for folder in data_folders  # Loop through each folder object
    for f in folder.glob("*")  # Glob files in that folder
    if f.is_file() and "_" in f.stem  # Ensure it's a file with an underscore
]

# %%
print(len(results))

# %%
# feat_source = "huc12pp"

# feat_id = results[0]  # your HUC12 (12-digit string)

# pp_gdf = nldi.get_features(feature_source=feat_source, feature_id=feat_id)
# pp_gdf

# %%
# chunk_size = 200
# list = results
# chunks = [list[i : i + chunk_size] for i in range(0, len(list), chunk_size)]
# pp_locations = pd.DataFrame()
# for feat_id in chunks:
#     feat_source = "huc12pp"
#     try:
#         pp_data = nldi.get_features(feature_source=feat_source, feature_id=feat_id)

#         if not pp_data.empty:
#             pp_locations = pd.concat([pp_locations, pp_data])
#     except Exception as e:
#         print(f"Chunk failed: {e}")


# list = results
# feat_source = "huc12pp"
# pp_locations = pd.DataFrame()

# for feat_id in list:
#     try:
#         pp_data = nldi.get_features(feature_source=feat_source, feature_id=feat_id)

#         if not pp_data.empty:
#             pp_locations = pd.concat([pp_locations, pp_data])
#     except Exception as e:
#         print(f"Chunk failed: {e}")

# %%
hu8_list = [
    16040201,
    16040205,
    17050103,
    17050105,
    17050106,
    17050107,
    17050108,
    17050109,
    17050110,
    17050115,
    17050116,
    17050117,
    17050118,
    17050119,
    17050201,
    17050202,
    17050203,
    17060101,
    17060102,
    17060103,
    17060104,
    17060105,
    17060106,
    17070101,
    17070102,
    17070103,
    17070104,
    17070105,
    17070201,
    17070202,
    17070203,
    17070204,
    17070301,
    17070302,
    17070303,
    17070304,
    17070305,
    17070306,
    17070307,
    17080001,
    17080003,
    17080006,
    17090001,
    17090002,
    17090003,
    17090004,
    17090005,
    17090006,
    17090007,
    17090008,
    17090009,
    17090010,
    17090011,
    17090012,
    17100201,
    17100202,
    17100203,
    17100204,
    17100205,
    17100206,
    17100207,
    17100301,
    17100302,
    17100303,
    17100304,
    17100305,
    17100306,
    17100307,
    17100308,
    17100309,
    17100310,
    17100311,
    17100312,
    17120001,
    17120002,
    17120003,
    17120004,
    17120005,
    17120006,
    17120007,
    17120008,
    17120009,
    18010101,
    18010201,
    18010202,
    18010203,
    18010204,
    18010205,
    18010206,
    18010209,
    18020001,
]

# %%
hu8_list_str = hu8_list
hu8_list_str = [str(x) for x in hu8_list]
hu8_list_str

# %%
# Your example lists
integers_8 = hu8_list
text_12 = results

# 1. Convert integers to a set of strings for fast matching
match_set = {str(i) for i in integers_8}

# 2. Filter the second list
filtered_list = [t for t in text_12 if t[:8] in match_set]

print(len(filtered_list))
# Output: ['12345678ABCD', '87654321WXYZ']

# %%
list = filtered_list
feat_source = "huc12pp"
pp_locations = pd.DataFrame()

for feat_id in list:
    try:
        pp_data = nldi.get_features(feature_source=feat_source, feature_id=feat_id)

        if not pp_data.empty:
            pp_locations = pd.concat([pp_locations, pp_data])
    except Exception as e:
        print(f"Chunk failed: {e}")

# %%
