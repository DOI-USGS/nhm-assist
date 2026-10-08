import sys, json
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.pyplot as plt
sys.path.insert(0,'../scripts/')
sys.path.insert(0,'../dependencies/')
from postprocessing_doublewide import setup_postproc, check_pdc, parse_groups, plot_phi, get_obs_and_noise, get_pars, plot_group, plot_pars_group
import pyemu

plot_obs = True
unzip_dirs = False
plot_streamflow = True
calval = 'cal'
cms = ['05431486', '01473000', '09112500']
# cms = ['05431486', '09112500']
# cms = ['01473000']
curr_run_root = 'prior_mc_reweight'
# curr_run_root = 'ies_hot'
# catalog of cutoffs heuristically determined
with open('../notebooks/phi_cutoffs.json', 'r') as ifp:
    phi_cutoffs = json.load(ifp)

def _abbreviate_index(inds):
    newindex=[]
    for i in inds:
        if 'streamflow_daily' not in i:
            newindex.append(i)
        else:
            tmp = i.split(':')
            tmp[0]='streamflow_daily'
            newindex.append((':').join(tmp))
    return newindex

for curr_model in cms:
    for calval in ['cal','val']:
        print(f'Calculating metrics for {curr_model}:{curr_run_root} --> {calval}')
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


        phi_too_high = phi_cutoffs[curr_model][curr_run_root]

        phi = orgphi.loc[orgphi<=phi_too_high]
        reals = phi.index 



        # # Now let's focus only on streamflow first
        # read in the observation data
        modens, obens_noise, nhm_res = get_obs_and_noise(tmp_res_path, curr_run_root, 
                            curr_model, reals, best_iter, obs, get_nhm_results=True)
        # read in the PST file
        pst = pyemu.Pst(str(pstdir / f"{curr_run_root}.pst"))
        pst.observation_data.index = _abbreviate_index(pst.observation_data.index)
        pst.observation_data['obsnme'] = pst.observation_data.index
        obs = pst.observation_data.copy()  
        obs.obsnme=obs.index
        _,_,_,_,_,cm, cob = parse_groups('streamflow_daily', modens, obs, obens_noise, calval)
        obs = obs.loc[cm.index]
        obs.obgnme = cm.obs_location
        pst.observation_data = obs
        cm = cm.T.iloc[:-7]
        
        all_metrics = pyemu.metrics.calc_metric_ensemble(cm,pst, drop_zero_weight=False)
        all_metrics.to_csv(f'../results/metrics_{curr_model}.{curr_run_root}.{calval}.csv.zip')
        
        nhm_res = nhm_res.loc[[i for i in nhm_res.index if i in obs.index]].rename(columns={'obsval':'modelled'})
        nhm_res['measured'] = obs.loc[nhm_res.index,'obsval']
        nhm_res['group'] = obs.loc[nhm_res.index,'obgnme']
        nhm_res['weight'] = obs.loc[nhm_res.index,'weight']
        res_met = pyemu.metrics.calc_metric_res(nhm_res, drop_zero_weight=False)
        res_met.index=['NHM_cal']    
        res_met.to_csv(f'../results/metrics_{curr_model}.nhm_cal.{calval}.csv.zip')
        
        