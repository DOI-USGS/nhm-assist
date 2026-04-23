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

import networkx as nx
import matplotlib.pyplot as plt

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
from nhf_assist.helpers.nhm_hydrofabric_v2 import make_hf_map_elements
from nhf_assist.helpers.map_template_v2 import make_hf_map
from nhf_assist.helpers.nhm_assist_utilities_v2 import load_subdomain_config

# config = load_subdomain_config(root_dir)
# con.print(config)

# %%
import glob
import os
import pydot
import networkx as nx


import numpy as np
import pandas as pd

from pathlib import Path

# from pyPRMS.base.console import get_console_instance
from pyPRMS.metadata.metadata import MetaData
from pyPRMS import Parameters
from pyPRMS import ParameterNetCDF
from pyPRMS import ParamDb
from pyPRMS import ControlFile
from pyPRMS.constants import NEW_PTYPE_TO_DTYPE
from pyPRMS.Exceptions_custom import ParameterNotValidError

# from rich.console import Console
# from rich.progress import track
from rich import pretty

# con = get_console_instance(width=200, force_jupyter=False)

pretty.install()

# %%
base_dir = root_dir / f"nhm_v2_model_building/domain_data/OR_v2_domain"
params_dir = f"{base_dir}/rOR"
pdb_dir = f"{base_dir}/paramdb_v2.0_default_oregon_init"
# plot_dir = f'{base_dir}/20220616_bad_parameters_plots'
ctl_filename = (
    root_dir / f"nhm_v2_model_building/data_dependencies/control.default.bandit"
)

# HRU polygons
# hru_geodatabase = f'{base_dir}/NHM_19.gpkg'
# hru_layer_name = 'nhru'
# hru_shape_key = 'hru_id'

# Segment lines
# seg_geodatabase = f'{base_dir}/NHM_19.gpkg'
# seg_layer_name = 'nsegments'
# seg_shape_key = 'segment_id'

# %%
prms_meta = MetaData(verbose=False).metadata

ctl = ControlFile(ctl_filename, metadata=prms_meta, verbose=True)


# %%
def check_for_disconnected_graphs(g):
    # Check for disconnected graphs within the graph object
    tot_weak_comp = 0
    node_size_cnt = Counter()

    for xx in nx.weakly_connected_components(g):
        out_node = [ii for ii in list(xx) if "Out_" in str(ii)]
        tot_weak_comp += 1
        node_size_cnt[len(xx)] += 1

        try:
            print("{}: nodes {}".format(out_node[0], len(xx)))
        except IndexError:
            # If this occurs it most likely indicates a loop or cycle
            print("WEIRD: ", xx)
    print("Total weakly connected components: {}".format(tot_weak_comp))

    print("Top 10 node sizes (size, count)")
    print(node_size_cnt.most_common(10))


def _data_it(filename):
    """Get iterator to a parameter db file.

    :returns: iterator
    """

    # Read the data
    fhdl = open(filename)
    rawdata = fhdl.read().splitlines()
    fhdl.close()
    return iter(rawdata)


def read_data(filename):
    it = _data_it(filename)
    next(it)

    data = []

    # Read the parameter values
    for rec in it:
        idx, val = rec.split(",")
        data.append(val)

    return data


# %%
# Get the list of parameter files to read
gf_files = []

file_it = glob.glob(f"{params_dir}/*.csv")
for kk in file_it:
    gf_files.append(kk)

gf_files.sort()

# %%
len(gf_files)

# %%
pdb = Parameters(metadata=prms_meta, verbose=False)
pdb.control = ctl

# Some dimensions are derived from particular parameters
derived_dimensions = {"nhru": "nhm_id", "nsegment": "nhm_seg", "npoigages": "poi_type"}
# 'ndeplval': 'snarea_curve'}

for kk, vv in derived_dimensions.items():
    tmp_data = read_data(f"{params_dir}/{vv}.csv")
    pdb.dimensions.add(kk, size=len(tmp_data))

# Add the constant-size dimensions
pdb.dimensions.add("ndays", size=366)
pdb.dimensions.add("nmonths", size=12)
pdb.dimensions.add("one", size=1)

# %%
for cfile in gf_files:
    cname = os.path.basename(os.path.splitext(cfile)[0])
    # print(cname)

    try:
        pdb.add(cname)
    except ParameterNotValidError:
        con.print(f"[red]{cname}[/] is not a valid parameter... skipping")
        continue

    try:
        cdtype = NEW_PTYPE_TO_DTYPE[pdb.get(cname).meta["datatype"]]
        tmp_data = (
            pd.read_csv(cfile, skiprows=0, usecols=[1], dtype={1: cdtype})
            .squeeze("columns")
            .to_numpy()
        )
        try:
            pdb.get(cname).data = tmp_data
        except IndexError:
            con.print(f"[red]{cname}[/] has incorrect size... skipping")
            pdb.remove(cname)
    except ValueError as err:
        con.print(f"[red]{cname}[/]: {err} - skipping")
        pdb.remove(cname)

# %%
pdb.check()

# %%
# Build the stream network
dag_ds = pdb.stream_network(tosegment="tosegment", seg_id="nhm_seg")

# %%
check_for_disconnected_graphs(dag_ds)

# %%
# import networkx as nx
# import matplotlib.pyplot as plt

# G = dag_ds
# # # G.add_edges_from([(1, 2), (2, 3), (3, 1)])  # example edges

# nx.draw(G, with_labels=True, arrows=True)
# #plt.show(G)

# %%
#len(G), G.number_of_edges()

# %%
# import networkx as nx
# import matplotlib.pyplot as plt

# G = dag_ds

import networkx as nx
import pydot

G = dag_ds
G.add_edges_from([(1, 2), (2, 3), (3, 1)])

P = nx.nx_pydot.to_pydot(G)
P.write_pdf("digraph.pdf")

# %%
pdb.parameters.keys()

# %%

# %% [markdown]
# ## Write out the parameters

# %%
#pdb.write_paramdb(base_dir)
pdb.write_parameter_file(base_dir)#, header=['blah'])
#pdb.write_parameter_netcdf(base_dir)

# %% [markdown]
# ## Add missing parameters

# %%

# %% [markdown]
# ## Remove unneeded parameters

# %%

# %%
pdb.missing_params

# %%
pdb.unneeded_parameters

# %%

# %%

# %%

# %%

# %%

# %%

# %%

# %%
con.print(pdb.dimensions)

# %%

# %%

# %%
