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
sys.path.append('../dependencies/')
import pandas as pd
import pyemu
import numpy as np
import pathlib as pl

# %% [markdown]
# ### choose a cutout from {01473000, 05431486, 09112500}

# %%
all_models = ['01473000','05431486','09112500','14015000']# Create a list of all cutouts

wkdir = pl.Path(f'../NHM_extractions/20230110_pois_haj/{snakemake.params["basin"]}/')

#wkdir = pl.Path('../NHM_extractions/20230110_pois_haj/09112500/')

# %%
wkdir

# %% [markdown]
# ### get the PST object 

# %%
pst = pyemu.Pst(str(wkdir / 'prior_mc.pst'))

# %%
pars = pst.parameter_data
obs = pst.observation_data

# %%
pst.obs_groups

# %% [markdown]
# ### Read in the base localization matrix

# %%
base_loc = pd.read_csv('../Supporting_information/localization_groups.csv', index_col=0)

# %%
# Trim out obs groups that aren't present in the PST file nut are in the base localization matrix

# %%
base_loc=base_loc.loc[~base_loc.index.str.contains("g_min_"),:]
base_loc.index = base_loc.index.str.replace('l_max_', '', regex=True)
#also in order to do phi factor, had to change this group name
base_loc.index=base_loc.index.str.replace('exlow', 'ex_low', regex=True)
base_loc.index=base_loc.index.str.replace('asc', 'ascnd', regex=True)
base_loc.index=base_loc.index.str.replace('dsc', 'dscnd', regex=True)
base_loc

# %%
base_loc.columns

# %%
base_loc = base_loc.loc[[i for i in pst.obs_groups if '_val' not in i and "sca_daily" not in i]]
base_loc

# %% [markdown]
# ### find the unique combinations of observations

# %%
# get a little squirrelly with transposes and add a row with the combos of obs

# %%
base_loc=base_loc.T
base_loc['par_obs_combo'] = [set(base_loc.T.loc[base_loc.T[i]==1].index) for i in base_loc.T.columns]
base_loc.par_obs_combo

# %%
# we need to find the unique sets of observation super-groups from the localization matrix
all_combos = []
for i in base_loc.par_obs_combo.values:
    if i not in all_combos:
        all_combos.append(i)

# %% [markdown]
# ### now just make par group names according to combinations of obs

# %%
group_lookup = {f'obs_combo_{i+1}':j for i,j in enumerate(all_combos)}

# %% [markdown]
# ### assign the group names to the parameter base types according to the cols of the base localization matrix

# %%
base_loc['par_obs_group'] = [[k for k,v in group_lookup.items() if v==i][0] for i in base_loc.par_obs_combo]

# %% [markdown]
# ### now we have a list of groups for parameters

# %%
new_par_groups = dict(zip(base_loc.index,base_loc.par_obs_group))# mapping a new group name for each par type.

# %% [markdown]
# ### set up mapping for localization groups

# %%
# assign meaningful descriptive names to the parameter supergroups
group_name_lookup = dict(zip([f'obs_combo_{i+1}' for i in range(7)],['Daily, all',
'Daily;\nLand Surface',
'Daily, low',
'Daily, low;\nLand Surface',
'Land Surface',
'Monthly;\nMean Monthly;\nLand Surface',
'Daily, high;\nLand Surface']))
group_name_lookup

# %%
locgroup, datatype, currval, groupname = [],[],[], []

# %%
for cg in sorted(base_loc['par_obs_group'].unique()):
    for obs_name in group_lookup[cg]:
        locgroup.append(cg),
        datatype.append('obs')
        currval.append(obs_name)
        groupname.append(group_name_lookup[cg])
    for par_name in base_loc.loc[base_loc.par_obs_group==cg].index.values:
        locgroup.append(cg),
        datatype.append('par')
        currval.append(par_name)
        groupname.append(group_name_lookup[cg])
loc_mapping = pd.DataFrame(data={'loc_group':locgroup,
                                'datatype': datatype,
                                'currval': currval,
                                'groupname': groupname})
loc_mapping.to_csv(
                                wkdir / 'localization_group_lookup.csv'
                                )

# %% [markdown]
# ### and we can cast the base_loc matrix back to original orientation and drop these names

# %%
base_loc = base_loc.drop(columns=['par_obs_combo', 'par_obs_group']).T

# %% [markdown]
# ### so, update the parameter groupnames

# %%
for k,v in new_par_groups.items():
    pars.loc[pars.parnme.str.startswith(k), 'pargp'] = v

# %%
pars.pargp.unique()


# %% [markdown]
# ### make sure we didn't miss any parameters in the groupings

# %%
assert 'pargp' not in pars.pargp.unique()

# %%
base_loc.columns

# %% [markdown]
# ### make the final localization matrix

# %%
locmat = pd.DataFrame(0, base_loc.index, group_lookup.keys())

# %% [markdown]
# ### loop over the groups and assign 1s where obs line up with par groups

# %%
for k,v in group_lookup.items():
    for cob in v:
        locmat.loc[cob,k] = 1.0

# %%
locmat

# %% [markdown]
# ### finally save it out to a text format

# %%
pyemu.Matrix.from_dataframe(locmat).to_ascii(str(wkdir / 'loc.mat'))

# %% [markdown]
# ### and refer to it in the PST file (TODO: add writing out the PST file)

# %%
pst.pestpp_options["ies_localizer"] = "loc.mat"
pst.control_data.noptmax = 0

# %%
#Write a new version of the PEST++ control file (.pst)
pst.write(str(wkdir / 'prior_mc_loc.pst'), version=2)

#will have to track this file and may need to add a bunch of files to be tracked

# %%
pyemu.os_utils.run('pestpp-ies prior_mc_loc.pst',cwd=wkdir)
