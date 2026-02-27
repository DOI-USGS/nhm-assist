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
import pywatershed as pws
from pprint import pprint

# %%
processes_list = [pws.PRMSCanopy, pws.PRMSChannel]

# %%
processes_list 

# %%
for pp in processes_list:
    #for rr in pp.get_parameters():
    pprint(pp.__name__)
    pprint(pws.meta.find_variables(pp.get_parameters()))

# %%

# %%
pws.PRMSGroundwater.description()


# %%
# https://github.com/DOI-USGS/pywatershed/tree/develop/examples

# %%
# https://pywatershed.readthedocs.io/en/latest/ for cool plot, version1.0.0
