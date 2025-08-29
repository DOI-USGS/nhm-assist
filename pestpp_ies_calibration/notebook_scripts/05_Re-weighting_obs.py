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
import pywatershed
import pandas as pd
import pathlib as pl
import numpy as np
import sys
import pyemu
interrupt_notebook = False
import matplotlib.pyplot as plt
import os
plt.rcParams['pdf.fonttype'] = 42

# Find and set the "nhm-assist" root directory
root_dir = pl.Path(os.getcwd().rsplit("nhm-assist", 1)[0] + "nhm-assist")
sys.path.append(str(root_dir))
print(root_dir)
from nhm_helpers.nhm_assist_utilities import load_subdomain_config
from pestpp_ies_calibration.helpers.pest_utils import pars_to_tpl_entries

config = load_subdomain_config(root_dir)

# %%
pestpp_model_dir = config["model_dir"] / "pestpp_ies"
pestpp_dir = root_dir / "pestpp_ies_calibration"
obsdir = pestpp_model_dir / "observation_data"
ancillary_dir = pestpp_model_dir / "ancillary"
output_dir = pestpp_model_dir / "output"

if not (pestpp_model_dir / "postprocessing").exists():
    (pestpp_model_dir / "postprocessing").mkdir()

# %%
#all_models = ['01473000','05431486','09112500','14015000']# Create a list of all cutouts

# %%
#rootdir = pl.Path('../NHM_extractions/20230110_pois_haj/')# Path to location of cutouts

# %%
# cm = all_models[0] # sets cutout from list
#cm = snakemake.params['basin']
#pestdir = os.path.join(rootdir, f'{cm}')  # stes path to location of NHM output folder where output files are.

# %%
pst = pyemu.Pst(os.path.join(pestpp_model_dir,'prior_mc_loc.pst'))
num_reals=pst.pestpp_options['ies_num_reals']

# %% [markdown]
# ### changing from manual re-weighting to using the 'phi factor' approach

# %%
# Assign relative contributions to the objective function
phi_new_comps = {'actet_mean_mon':0.08,
                 'actet_mon':  .04,
                 'recharge_ann': 0.08,
                 'runoff_mon': .16,
#                  'sca_daily':.1,
                 'soil_moist_ann': 0.08,
                 'soil_moist_mon': 0.1,
                 'streamflow_mean_mon_cal': .1,
                 'streamflow_mon': .12,
                 'scnd': .14,
                 '_low': 0.1
                }

# %%
phi_new_comps_plot = phi_new_comps.copy()
phi_new_comps_plot['streamflow_high'] = phi_new_comps_plot.pop('scnd')
phi_new_comps_plot['streamflow_low'] = phi_new_comps_plot.pop('_low')


# %%
fig, ax = plt.subplot_mosaic('''
                            aaa.bbb
                            aaa.bbb
                            aaa.bbb
                            ''', figsize=(8,6))
ax['a'].pie(pst.phi_components.values(), 
            labels = [i.replace('_','\n') for i in pst.phi_components.keys()], 
            startangle=180,textprops={'fontsize': 12})
ax['b'].pie(phi_new_comps_plot.values(), 
            labels = [i.replace('_','\n') for i in phi_new_comps_plot.keys()],textprops={'fontsize': 12})
plt.savefig(pestpp_model_dir / f'postprocessing/reweighting_{config["subdomain"]}.pdf')

# %%
# #build phi factor df
# real_names = [str(i) for i in np.arange(0,num_reals)]
# real_names.append('base')
# # obs = pyemu.ObservationEnsemble.from_csv(pst=pst,filename=os.path.join(pestdir, 'prior_mc.0.obs.csv'))
# phi_fac = pd.DataFrame()
# for cid in real_names:
#     phi_fac[cid]=phi_new_comps

# np.sum(phi_fac.iloc[:,0])
# assert (1- np.sum(phi_fac.iloc[:,0]))<0.001
# # phi_fac=phi_fac.transpose()

# #save to csv
# phi_fac.to_csv(os.path.join(pestdir,'phi_factors.csv'))

#build phi factor df
phi_fac = pd.DataFrame(phi_new_comps.items())
assert (1- np.sum(phi_fac[1]))<0.001 #make sure they sum to 1

#save to csv
phi_fac.to_csv(os.path.join(pestpp_model_dir,'phi_factors.csv'),index=None,header=None)

# %%
phi_fac

# %%
#Write a new version of the PEST++ control file (.pst)
pst.pestpp_options['ies_phi_factor_file']="phi_factors.csv"
pst.pestpp_options['ies_phi_factors_by_real']=False
pst.control_data.noptmax=0
pst.write(os.path.join(pestpp_model_dir, 'prior_mc_reweight.pst'), version=2)

# %% [markdown]
# ### update the localization matrix to remove groups with only 0-weighted obs

# %%
# read in the localization matrix from the run directory
locmat = pyemu.Matrix.from_ascii(str(pestpp_model_dir / 'loc.mat')).to_dataframe()

# %%
# find zero-weighted groups (just streamflow no data)
zero_grps = ['streamflow_nodata']
zero_grps

# %%
# confirm that we can select only the rows that are not in the zero-weighted groups lines
locmat.loc[~locmat.index.isin(zero_grps)]

# %%
# write out the new matrix in PEST style
pyemu.Matrix.from_dataframe(locmat.loc[~locmat.index.isin(zero_grps)]).to_ascii(str(pestpp_model_dir/ 'loc.mat'))

# %%
pyemu.os_utils.run('pestpp-ies prior_mc_reweight.pst',cwd=pestpp_model_dir)

# %%
pst.control_data.noptmax=-1
pst.write(os.path.join(pestpp_model_dir, 'prior_mc_reweight.pst'), version=2)

# %% [markdown]
# ### spit out control file for GSA

# %%

pst.pestpp_options['gsa_morris_r']=18
pst.pestpp_options['gsa_morris_p']=4
pst.pestpp_options['tie_by_group']=True
pst.write(os.path.join(pestpp_model_dir, 'prior_mc_reweight_gsa.pst'), version=2)

# quick remap of dependent files
# Eddie and Matt think this was so Mike didn't have to move new files up to S3 for a sensativity analysis.
# Prob be deleted, not used, etc.
#
# ingsa = open(os.path.join(pestpp_model_dir, 'prior_mc_reweight_gsa.pst'), "r").readlines()
# with open(os.path.join(pestpp_model_dir, 'prior_mc_reweight_gsa.pst'), "w") as ofp:
#     [ofp.write(line.strip().replace("prior_mc_reweight_gsa", "prior_mc_reweight")+"\n") for line in ingsa]
#     print(f'rewrote({os.path.join(pestpp_model_dir, "prior_mc_reweight_gsa.pst")})')

# %%
