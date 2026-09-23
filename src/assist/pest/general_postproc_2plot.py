import sys, os, json
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.pyplot as plt
sys.path.insert(0,'../scripts/')
from postprocessing_doublewide import setup_postproc, check_pdc, plot_phi, get_obs_and_noise, get_pars, plot_group, plot_pars_group
# try:
#     import snakemake
#     context = 'snakemake'
# except:
#     context = 'local'
plot_obs = True
unzip_dirs = True
plot_streamflow = True
cms = ['01473000',  '05431486', '09112500']


crrs = ['prior_mc_reweight','ies_hot']

# catalog of cutoffs heuristically determined
with open('../notebooks/phi_cutoffs.json', 'r') as ifp:
    phi_cutoffs = json.load(ifp)

# phi_cutoffs['01473000']['ies_hot_noloc'] = 1.9e7


# if context == 'snakemake':
curr_model = snakemake.params['basin']
# else:
# curr_model = '05431486'
modens_list = []
for curr_run_root in crrs:
    pstdir, results_file, tmp_res_path, fig_dir, obs, pst = setup_postproc(
        curr_model, curr_run_root, unzip_dirs
        )

    # ### look at PHI history
    phi = plot_phi(tmp_res_path, curr_run_root, curr_model, fig_dir)

    # ### Truncate PHI at a threshold
    best_iter = phi_cutoffs[curr_model]['best_iter']
    if 'prior' in curr_run_root:
        best_iter = 0
    print(f'Iter {best_iter} is best for {curr_model}')
    
    # ## now rejection sampling for outlier PHI values
    orgphi = phi.loc[best_iter].iloc[5:].copy()
    ax = orgphi.hist(bins=50)
    lims = ax.get_xlim()

    phi_too_high = phi_cutoffs[curr_model][curr_run_root]

    phi = orgphi.loc[orgphi<=phi_too_high]
    fig,ax = plt.subplots(1,2)
    ### --> need to indicate which reals we will carry forward <-- ###
    orgphi.hist(bins=50, ax=ax[0])
    reals = phi.index 
    phi.hist(bins=50, ax=ax[1])
    ax[0].axvline(phi_too_high, color='orange')
    ax[1].set_xlim(lims)
    ax[0].set_title(f'Original PHI: {len(orgphi)} reals')
    ax[1].set_title(f'Truncated PHI: {len(phi)} reals')
    plt.savefig(fig_dir / 'phi_histogram.pdf')


    # # Now let's start looking at the fits
    modens, obens_noise, nhm_res = get_obs_and_noise(tmp_res_path, curr_run_root, curr_model, reals, best_iter, obs, get_nhm_results=True)
    # for plotting, let's make sure we have values even for validation observations (0 weight)
    obens_noise = obens_noise.T
    for cc in obens_noise.columns:
        obens_noise.loc[obs.loc[obs.weight==0].index, cc] = obs.loc[obs.weight==0].obsval
    obens_noise = obens_noise.T        
    modens_list.append(modens)
nhm_res.index = [i.replace('l_max_','') for i in nhm_res.index]
# plot_group('sca_daily', obs, modens_list[0], obens_noise, fig_dir, curr_model, best_iter, curr_run_root, modens_list[1], nhm_res)

plot_group('actet_mean_mon', obs, modens_list[0], obens_noise, fig_dir, curr_model, best_iter, curr_run_root, modens_list[1], nhm_res)
plot_group('actet_mon', obs, modens_list[0], obens_noise, fig_dir, curr_model, best_iter, curr_run_root, modens_list[1], nhm_res)
# plot_group('runoff_mon', obs, modens_list[0], obens_noise, fig_dir, curr_model, best_iter, curr_run_root, modens_list[1], nhm_res)
# plot_group('soil_moist_mon', obs, modens_list[0], obens_noise, fig_dir, curr_model, best_iter, curr_run_root, modens_list[1], nhm_res)
# plot_group('recharge_ann', obs, modens_list[0], obens_noise, fig_dir, curr_model, best_iter, curr_run_root, modens_list[1], nhm_res)

# # streamflow_daily is a special case - all aggregated
if plot_streamflow:
    plot_group('streamflow_daily', obs, modens_list[0], obens_noise, fig_dir, curr_model, best_iter, curr_run_root, modens_list[1], nhm_res)
    plot_group('streamflow_mean_mon_val', obs, modens_list[0], obens_noise, fig_dir, curr_model, best_iter, curr_run_root, modens_list[1], nhm_res)
    plot_group('streamflow_mean_mon_cal', obs, modens_list[0], obens_noise, fig_dir, curr_model, best_iter, curr_run_root, modens_list[1], nhm_res)
    plot_group('streamflow_mon', obs, modens_list[0], obens_noise, fig_dir, curr_model, best_iter, curr_run_root, modens_list[1], nhm_res)

with open(fig_dir / 'alldone.dat', 'w') as ofp:
    ofp.write('fin\n')