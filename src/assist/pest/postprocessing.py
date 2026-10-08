import pandas as pd
import sys
import numpy as np
import pathlib as pl
import zipfile
sys.path.append('../dependencies/')
import pyemu
from datetime import datetime as dt
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import calendar
datfmtmon = '%Y_%m'
datfmtdaily = '%Y_%m_%d'
plot_lw = 0.01
plot_alpha = 0.15


def setup_postproc(curr_model='01473000', curr_run_root='prior_mc_reweight', extractfiles = False):
    """function to set paths, unzip results files, and load up data from PST files for a given cutout run

    Args:
        curr_model (str, optional): _cutout name_. Defaults to '01473000'.
        curr_run_root (str, optional): _specific pst filename root_. Defaults to 'prior_mc_reweight'.
        extractfiles (bool, optional): _flag whether to unzip files or not_. Defaults to False.

    Returns:
        pathnames, observation data frame, and pst object
    """
    # set some paths
    pstdir = pl.Path(f'../NHM_extractions/20230110_pois_haj/{curr_model}/')
    results_file = pl.Path(f'../results/{curr_run_root}.{curr_model}.zip/')
    tmp_res_path = pl.Path(f'../results/{curr_model}.{curr_run_root}')
    # set up figures directory
    fig_dir = pl.Path( f'../postprocessing/figures/{curr_model}/{curr_run_root}.{curr_model}')
    if not fig_dir.exists():
        fig_dir.mkdir(parents=True)    
        
    # get the obs data from the PST file
    pst = pyemu.Pst(str(pstdir / f'{curr_run_root}.pst'))
    obs = pst.observation_data.copy()
    
    # if still need to extract the files, go for it
    if extractfiles:
        with zipfile.ZipFile(results_file, 'r') as zf:
            zf.extractall(tmp_res_path)
    return pstdir, results_file, tmp_res_path, fig_dir, obs, pst

def check_pdc(tmp_res_path, curr_run_root, pst, obs):
    """evaluate PDC in broad sense. Just reporting percent of obs. in PDC overall and by non-zero-weighted groups.

    Args:
        tmp_res_path (pathlib.Path): _path to results files
        curr_run_root (str): _PST filename root_
        pst (pyemu.Pst): PEST control file object 
        obs (pandas.DataFrame): observation dataframe from PEST file

    Returns:
        pandas.DataFrame: _counts by group and percentages of PDC observations_
    """
    pdc = pd.read_csv(tmp_res_path / f'{curr_run_root}.pdc.csv', index_col=0)
    print(f'{(len(pdc)/pst.nnz_obs)*100:.2f}% of weighted obs are in PDC')    
    pdc = pdc.merge(obs[['weight', 'obgnme']], left_index=True, right_index=True)
    pdc_counts_tmp = pdc.groupby('obgnme')['obgnme'].count().to_frame()
    pdc_counts = obs.groupby('obgnme')['obgnme'].count().to_frame()
    pdc_counts.rename(columns={'obgnme':'obs_counts'}, inplace=True)
    # only keep groups with nonzero weights
    pdc_counts = pdc_counts.loc[pst.nnz_obs_groups]
    pdc_counts_tmp.rename(columns={'obgnme':'pdc_counts'}, inplace=True)
    pdc_counts = pdc_counts.merge(pdc_counts_tmp, left_index=True,right_index=True, how='outer')
    pdc_counts['group_percent_pdc'] = [f'{i:0.2%}' for i in 
                                       (pdc_counts['pdc_counts']/pdc_counts['obs_counts'])]
    return pdc_counts

def plot_phi(tmp_res_path, curr_run_root, curr_model, fig_dir):
    """just a quick plot of the phi history (ensemble-wise) over iterations. also reads and returns PHI

    Args:
        tmp_res_path (pathlib.Path): location of results files
        curr_run_root (str, optional): _specific pst filename root_.
        curr_model (str, optional): _cutout name_. 
        fig_dir (oathlib.Path): path to save figures in 

    Returns:
        DataFrame: list of phi values indexed by realizations
    """
    phi = pd.read_csv(tmp_res_path / f'{curr_run_root}.phi.actual.csv', index_col=0)
    plt.figure(figsize=(6,4))
    ax = phi['base'].apply(np.log10).plot(legend=False, lw=1.5, color='r', label='base')
    phi.iloc[:,6:7].apply(np.log10).plot(legend=False,lw=0.5,color='k',alpha=0.15,label='realizations', ax = ax)
    plt.legend(['base','realizations'])
    phi.iloc[:,6:].apply(np.log10).plot(legend=False,lw=0.5,alpha=0.15,color='k', ax = ax)
    phi['base'].apply(np.log10).plot(legend=False, lw=1.5, color='r', ax=ax)
    plt.ylabel('log Phi')
    plt.xlabel('iES iteration')
    plt.xticks(ticks=np.arange(4))
    ax.axes.tick_params(length=7, direction='in', right=True, top=True)
    plt.title(f'PHI History for {curr_model}')
    plt.legend(['base','realizations'], title='EXPLANATION', frameon=False, bbox_to_anchor =(0.97, 0.95))
    plt.savefig(fig_dir / 'phi_history.pdf')
    return phi

def get_obs_and_noise(tmp_res_path, curr_run_root, reals, best_iter):
    """_summary_

    Args:
        tmp_res_path (pathlib.Path): location of results files
        curr_run_root (str, optional): _specific pst filename root_.
        reals (list): list of realizations to retain
        best_iter (int): iteration to retain as "best"

    Returns:
        modens (DataFrame): modelled results for retained realizations of best iteration
        obens_noise (DataFrame): sampled noise-adjusted observation values for retained realizations
        
    """
    modens = pd.read_csv(tmp_res_path / f'{curr_run_root}.{best_iter}.obs.csv', 
                        low_memory=False, index_col=0).loc[reals].T
    obens_noise = pd.read_csv(tmp_res_path / f'{curr_run_root}.obs+noise.csv', 
                              low_memory=False, index_col=0).loc[reals].T
    modens['mod_min'] = modens.min(axis=1)
    modens['mod_max'] = modens.max(axis=1)
    modens = modens.T
    obens_noise['obs_min'] = obens_noise.min(axis=1)
    obens_noise['obs_max'] = obens_noise.max(axis=1)
    obens_noise = obens_noise.T
    return modens, obens_noise

def get_pars(tmp_res_path, curr_run_root, reals, best_iter, pst):
    """_summary_

    Args:
        tmp_res_path (pathlib.Path): location of results files
        curr_run_root (str, optional): _specific pst filename root_.
        reals (list): list of realizations to retain
        best_iter (int): iteration to retain as "best"
        pst (pyemu.Pst): Pst object containing information for the runs

    Returns:
        parens (DataFrame): parameter ensemble trimmed to retained realizations and at best iteration
    """
    parens = pd.read_csv(tmp_res_path / f'{curr_run_root}.{best_iter}.par.csv',
                         index_col=0, low_memory=False).loc[reals].T
    pars = pst.parameter_data.copy()
    parens['par_min'] = parens.min(axis=1)
    parens['par_max'] = parens.max(axis=1)
    parens['pargroup'] = [i.split(':')[0] for i in parens.index]
    parens['location'] = [i.split(':')[1] for i in parens.index]
    parens['low_bound'] = pars.loc[parens.index,'parlbnd']
    parens['upper_bound'] = pars.loc[parens.index,'parubnd']
    parens['starting'] = pars.loc[parens.index,'parval1']
    return parens

def plot_group(cgroup, obs, modens, obens_noise, fig_dir, curr_model, citer, curr_root):

    # set up the legend properties
    lh_obens = Patch(color='orange', alpha=0.2, label='Obs Bounds')
    lh_modens = Patch(color='blue', alpha=0.2, label='Mod Ens Bounds')
    lh_linemod = Line2D([0], [0], color='blue', label='modeled base realization')
    lh_lineobs = Line2D([0], [0], color='orange', label='obs base realization')
    lh_realmod = Line2D([0], [0], color='blue', linewidth=plot_lw*5, label='modeled realization')
    lh_realobs = Line2D([0], [0], color='orange',linewidth=plot_lw*5, label='obs realization')
    # set some flags based on group names
    mean_mon=False
    monthly=False
    annual = False 
    daily = False
    # first special case for streamflow_daily where all the subgroups for daily streamflow are gathered
    streamflow = False
    if 'streamflow' in cgroup:
        streamflow=True
    if (streamflow is True) and ('daily' not in cgroup):
        currobs = obs.loc[obs.obgnme==cgroup,'obsnme'].to_list() 
    elif 'streamflow_daily' not in cgroup:
        currobs = obs.loc[(obs.obgnme==f'g_min_{cgroup}') | (obs.obgnme==f'l_max_{cgroup}'),'obsnme'].to_list() 
    else:
        currobs = obs.loc[obs.obgnme.str.contains('streamflow_daily'),'obsnme'].to_list()
    
  
    # parse the data 
    currmod = modens[currobs].copy().T
    currobs_noise = obens_noise[currobs].copy().T
    currmod['obs_location'] = [i.split(':')[-1] for i in currmod.index]
    currobs_noise['obs_location'] = [i.split(':')[-1] for i in currobs_noise.index]
    
    # get after the date information, which differs based on groups
    if 'mean_mon' in cgroup:
        mean_mon=True
        currmod['month'] = [int(i.split(':')[1]) for i in currmod.index]
        currobs_noise['month'] = [int(i.split(':')[1]) for i in currobs_noise.index]
    elif ('mon' in cgroup) & ('mean' not in cgroup):
        monthly = True
        currmod['datestring'] = [i.split(':')[1] for i in currmod.index]
        currobs_noise['datestring'] = [i.split(':')[1] for i in currobs_noise.index]  
        currmod['datestring'] = [f'{int(i.split("_")[0]):4d}_{int(i.split("_")[1]):02d}' 
                    for i in currmod['datestring']]   
        currmod['datetime'] = [dt.strptime(i, datfmtmon) for i in currmod['datestring']]
        currobs_noise['datestring'] = [f'{int(i.split("_")[0]):4d}_{int(i.split("_")[1]):02d}' 
                    for i in currobs_noise['datestring']]   
        currobs_noise['datetime'] = [dt.strptime(i, datfmtmon) for i in currobs_noise['datestring']]
        currmod['year'] = [i.year for i in currmod.datetime]    
        currobs_noise['year'] = [i.year for i in currobs_noise.datetime]
    elif 'ann' in cgroup:
        annual = True
        currmod['year'] = [int(i.split(':')[1]) for i in currmod.index]
        currobs_noise['year'] = [int(i.split(':')[1]) for i in currobs_noise.index]
    elif 'daily' in cgroup:
        daily=True
        currmod['datestring'] = [i.split(':')[1] for i in currmod.index]
        currobs_noise['datestring'] = [i.split(':')[1] for i in currobs_noise.index]  
        currmod['datestring'] = [f'{int(i.split("_")[0]):4d}_{int(i.split("_")[1]):02d}_{int(i.split("_")[2]):02d}' 
                    for i in currmod['datestring']]   
        currmod['datetime'] = [dt.strptime(i, datfmtdaily) for i in currmod['datestring']]
        currobs_noise['datestring'] = [f'{int(i.split("_")[0]):4d}_{int(i.split("_")[1]):02d}_{int(i.split("_")[2]):02d}' 
                    for i in currobs_noise['datestring']]   
        currobs_noise['datetime'] = [dt.strptime(i, datfmtdaily) for i in currobs_noise['datestring']]
        currmod['year'] = [i.year for i in currmod.datetime]    
        currobs_noise['year'] = [i.year for i in currobs_noise.datetime]    
        currmod['month'] = [i.month for i in currmod.datetime]    
        currobs_noise['month'] = [i.month for i in currobs_noise.datetime]    



    # now get plotting!
    with PdfPages(fig_dir / f'{cgroup}.pdf') as outpdf:
        # by default, we will make a plot for each location (usually that's an HRU)
        for cn,cgmod in currmod.groupby('obs_location'):
            # first handle mean_monthly or annual cases, which results in one plot per location
            if (mean_mon == True) | (annual == True):
                plt.figure()
                if mean_mon:
                    cgmod.sort_values(by='month', inplace=True)
                    cgobs = currobs_noise.loc[cgmod.index].sort_values(by='month')
                    cgmod.set_index('month', inplace=True)
                    if streamflow:
                        cgobs.set_index('month', inplace=True)
                    else:
                        cgobs_upper = cgobs.loc[cgobs.index.str.startswith('l_')].set_index('month')
                        cgobs_lower = cgobs.loc[cgobs.index.str.startswith('g_')].set_index('month')
                        
                elif annual:
                    cgmod.sort_values(by='year', inplace=True)
                    cgobs = currobs_noise.loc[cgmod.index].sort_values(by='year')
                    cgmod.set_index('year', inplace=True)
                    if streamflow:
                        cgobs.set_index('year', inplace=True)
                    else:
                        cgobs_upper = cgobs.loc[cgobs.index.str.startswith('l_')].set_index('year')
                        cgobs_lower = cgobs.loc[cgobs.index.str.startswith('g_')].set_index('year')   
                                                         
                ax = cgmod[np.random.choice(cgmod.columns[:-4],20)].plot(legend=None, linewidth=plot_lw, 
                                            color='blue', alpha = plot_alpha)
                if streamflow:
                    ax.fill_between(cgobs.index, cgobs.obs_min,cgobs.obs_max, color='orange',alpha=.2, zorder=0)
                    cgobs[np.random.choice(cgobs.columns[:-4],20)].plot(ax=ax,color='orange',  linewidth=plot_lw,
                                                    legend=None,alpha=plot_alpha, zorder=1e6)
                    cgobs.base.plot(ax=ax, color='orange')
                else:
                    ax.fill_between(cgobs_upper.index, cgobs_upper.obs_min,cgobs_upper.obs_max, color='orange',alpha=.2, zorder=0)
                    cgobs_upper[np.random.choice(cgobs_upper.columns[:-4],20)].plot(ax=ax,color='orange',  linewidth=plot_lw,
                                                    legend=None,alpha=plot_alpha, zorder=1e6)
                    ax.fill_between(cgobs_lower.index, cgobs_lower.obs_min,cgobs_lower.obs_max, color='orange',alpha=.2, zorder=0)
                    cgobs_lower[np.random.choice(cgobs_lower.columns[:-4],20)].plot(ax=ax,color='orange',  linewidth=plot_lw,
                                                    legend=None,alpha=plot_alpha, zorder=1e6)
                    cgobs_upper.base.plot(ax=ax, color='orange')
                    cgobs_lower.base.plot(ax=ax, color='orange')
                    
                ax.fill_between(cgmod.index, cgmod.mod_min,cgmod.mod_max, color='blue',alpha=.2, zorder=0)
                ax.plot(cgmod.index, cgmod[cgmod.columns[:-4]].quantile(0.05, axis=1), 'b:')
                ax.plot(cgmod.index, cgmod[cgmod.columns[:-4]].quantile(0.95, axis=1), 'b:')
                
                cgmod.base.plot(ax=ax, color='blue')
                
                # ax.fill_between(cgobs.index, cgobs.obs_min,cgobs.obs_max, color='orange',alpha=.4)
                
                ax.set_title(f'cutout={curr_model},  mod = {curr_root}, iter={citer}, group={cgroup}, location = {cn}')
                print(cn)   
                plt.legend(handles=[lh_obens,lh_modens, lh_lineobs, lh_linemod, lh_realobs, lh_realmod])                
                outpdf.savefig()
                plt.close('all')
            elif monthly:
                # for monthly time sequence cases, we will make a plot for each page
                for cny, cgmody in cgmod.groupby('year'):
                    cgmody.sort_values(by='datetime', inplace=True)
                    cgobsy = currobs_noise.loc[cgmody.index].sort_values(by='datetime')
                    cgmody.set_index('datetime', inplace=True)
                    if streamflow:
                        cgobsy.set_index('datetime', inplace=True)
                    else:
                        cgobsy_upper = cgobsy.loc[cgobsy.index.str.startswith('l_')].set_index('datetime')
                        cgobsy_lower = cgobsy.loc[cgobsy.index.str.startswith('g_')].set_index('datetime')
                    ax = cgmody[np.random.choice(cgmody.columns[:-4],20)].plot(legend=None, linewidth=plot_lw, 
                        color='blue', alpha = plot_alpha)
                    if streamflow:
                        ax.fill_between(cgobsy.index, cgobsy.obs_min,cgobsy.obs_max, color='orange',alpha=.2, zorder=0)
                        cgobsy[np.random.choice(cgobsy.columns[:-4],20)].plot(ax=ax,color='orange',  linewidth=plot_lw,
                                                        legend=None,alpha=plot_alpha, zorder=1e6)
                        cgobsy.base.plot(ax=ax, color='orange')
                    else:
                        ax.fill_between(cgobsy_upper.index, cgobsy_upper.obs_min,cgobsy_upper.obs_max, color='orange',alpha=.2, zorder=0)
                        cgobsy_upper[np.random.choice(cgobsy_upper.columns[:-4],20)].plot(ax=ax,color='orange',  linewidth=plot_lw,
                                                        legend=None,alpha=plot_alpha, zorder=1e6)
                        ax.fill_between(cgobsy_lower.index, cgobsy_lower.obs_min,cgobsy_lower.obs_max, color='orange',alpha=.2, zorder=0)
                        cgobsy_lower[np.random.choice(cgobsy_lower.columns[:-4],20)].plot(ax=ax,color='orange',  linewidth=plot_lw,
                                                        legend=None,alpha=plot_alpha, zorder=1e6)
                        cgobsy_upper.base.plot(ax=ax, color='orange')
                        cgobsy_lower.base.plot(ax=ax, color='orange')
                    ax.fill_between(cgmody.index, cgmody.mod_min,cgmody.mod_max, color='blue',alpha=.2, zorder=0)
                    cgmody[cgmody.columns[:-4]].quantile(0.05, axis=1).plot(color='b',ls=':', ax=ax)
                    cgmody[cgmody.columns[:-4]].quantile(0.95, axis=1).plot(color='b',ls=':', ax=ax)

                    cgmody.base.plot(ax=ax, color='blue')
                    
                    ax.set_title(f'cutout={curr_model},  mod = {curr_root}, iter={citer}, group={cgroup}, location = {cn}, year = {cny}')
                    print(cny, cn)  
                    plt.legend(handles=[lh_obens,lh_modens, lh_lineobs, lh_linemod, lh_realobs, lh_realmod])                  
                    outpdf.savefig()
            
                    plt.close('all')
            elif daily:
                 # for daily time sequence cases, we will make a plot for month/year, so many more pages
                for cny, cgmody in cgmod.groupby('year'):
                    for cnm, cgmodm in cgmody.groupby('month'):
                        cgmodm.sort_values(by='datetime', inplace=True)
                        cgobsm = currobs_noise.loc[cgmodm.index].sort_values(by='datetime')
                        cgmodm.set_index('datetime', inplace=True)
                        cgobsm.set_index('datetime', inplace=True)
                        ax = cgmodm[np.random.choice(cgmodm.columns[:-7],25)].plot(legend=None, linewidth=plot_lw, 
                                                        color='blue', alpha = plot_alpha)
                        ax.fill_between(cgmodm.index, cgmodm.mod_min,cgmodm.mod_max, color='blue',alpha=.2, zorder=0)
                        ax.plot(cgmodm.index, cgmodm[cgmodm.columns[:-7]].quantile(0.05, axis=1), 'b:')
                        ax.plot(cgmodm.index, cgmodm[cgmodm.columns[:-7]].quantile(0.95, axis=1), 'b:')
                        if 'sca' not in cgroup:
                            ax.fill_between(cgobsm.index, cgobsm.obs_min,cgobsm.obs_max, color='orange',alpha=.2, zorder=0)
                            cgobsm[np.random.choice(cgobsm.columns[:-7],25)].plot(ax=ax,color='orange',  linewidth=plot_lw,
                                                                                legend=None,alpha=plot_alpha)
                        cgobsm.base.plot(ax=ax, color='orange')
                        cgmodm.base.plot(ax=ax, color='blue')
                        
                        ax.set_title(f'cutout={curr_model}, mod = {curr_root}, iter={citer}, group={cgroup}, location = {cn}, date = {calendar.month_name[cnm]} {cny}')
                        if 'sca' in cgroup:
                            ax.set_ylim(0,1)
                        print(cny, cn)  
                        plt.legend(handles=[lh_obens,lh_modens, lh_lineobs, lh_linemod, lh_realobs, lh_realmod])                  
                        outpdf.savefig()
                
                        plt.close('all')
def _plotpars(cn, cg, outpdf, curr_model, citer, curr_root, cgroup):
    # general hidden function covering all the parameter plotting details
    # set up the legend properties
    lh_parens = Patch(color='blue', alpha=0.1, label='Parameter Bounds')
    lh_linebase = Line2D([0], [0], color='blue', label='base realization')
    lh_linebounds = Line2D([0], [0], color='red', label='upper/lower par bounds')
    lh_linestart = Line2D([0], [0], color='grey', label='par starting value', linestyle='dashed')
    lh_realpar = Line2D([0], [0], color='blue', linewidth=plot_lw*5, label='modeled realization')
    plt.figure()
    ax=cg[np.random.choice(cg.columns[:-8],25)].plot(legend=None, linewidth=.01, alpha=plot_alpha,
                                                        color='blue')
    cg['low_bound'].plot(ax=ax,color='red')
    cg['upper_bound'].plot(ax=ax,color='red')
    cg['starting'].plot(ax=ax,color='grey', linestyle='dashed', zorder=1e6)
    cg.base.plot(ax=ax, color='blue')
    plt.fill_between(cg.index, cg.par_min, cg.par_max, color='blue', alpha=.1, zorder=0)
    plt.title(f'{curr_model} {curr_root}.iter_{citer} {cgroup} {cn}')
    plt.legend(handles=[lh_parens,lh_linebase, lh_linebounds, lh_linestart, lh_realpar])                  

    outpdf.savefig()
    plt.close('all')
    
def plot_single_real(res, cgroup, citer, curr_root, fig_dir, curr_model):
    plot_NHM=False
    if 'NHM_modelled' in res.columns:
        plot_NHM = True
    # set up the legend properties
    lh_linemod = Line2D([0], [0], color='blue', label='modelled base realization')
    lh_lineobs = Line2D([0], [0], color='orange', label='obs base realization')
    leg_handles = [lh_linemod, lh_lineobs]
    if plot_NHM:
        lh_lineNHM = Line2D([0], [0], color='green', label='modelled NHM results')
        leg_handles.append(lh_lineNHM)
    # set some flags based on group names
    mean_mon=False
    monthly=False
    annual = False 
    daily = False
    # first special case for streamflow_daily where all the subgroups for daily streamflow are gathered
    if 'streamflow_daily' not in cgroup:
        currobs = res.loc[(res.Group==f'g_min_{cgroup}') | (res.Group==f'l_max_{cgroup}')].index.to_list() 
    else:
        currobs = res.loc[res.Group.str.contains('streamflow_daily')].index.to_list()
    streamflow = False
    if 'streamflow' in cgroup:
        streamflow=True
    # parse the data
    res = res.loc[currobs]
    res['obs_location'] = [i.split(':')[-1] for i in res.index]
    # get after the date information, which differs based on groups
    if 'mean_mon' in cgroup:
        mean_mon=True
        res['month'] = [int(i.split(':')[1]) for i in res.index]
    elif ('mon' in cgroup) & ('mean' not in cgroup):
        monthly = True
        res['datestring'] = [i.split(':')[1] for i in res.index]
        res['datestring'] = [f'{int(i.split("_")[0]):4d}_{int(i.split("_")[1]):02d}' 
            for i in res['datestring']]   
        res['datetime'] = [dt.strptime(i, datfmtmon) for i in res['datestring']]
        res['year'] = [i.year for i in res.datetime]    
    elif 'ann' in cgroup:
        annual = True
        res['year'] = [int(i.split(':')[1]) for i in res.index]
    elif 'daily' in cgroup:
        daily=True
        res['datestring'] = [i.split(':')[1] for i in res.index]
        res['datestring'] = [f'{int(i.split("_")[0]):4d}_{int(i.split("_")[1]):02d}_{int(i.split("_")[2]):02d}' 
                    for i in res['datestring']]   
        res['datetime'] = [dt.strptime(i, datfmtdaily) for i in res['datestring']]
        res['year'] = [i.year for i in res.datetime]    
        res['month'] = [i.month for i in res.datetime]    
    # now get plotting!
    if plot_NHM:
        fname = f'{cgroup}.base+NHM.pdf'
    with PdfPages(fig_dir / fname) as outpdf:
        # by default, we will make a plot for each location (usually that's an HRU)
        for cn,cgres in res.groupby('obs_location'):
            # first handle mean_monthly or annual cases, which results in one plot per location
            if (mean_mon == True) | (annual == True):
                plt.figure()
                if mean_mon:
                    cgres = cgres.sort_values(by='month').copy()
                    if not streamflow:
                        cgres_upper = cgres.loc[cgres.index.str.startswith('l_')].set_index('month')
                        cgres_lower = cgres.loc[cgres.index.str.startswith('g_')].set_index('month')
                    cgres.set_index('month', inplace=True)
                elif annual:
                    cgres = cgres.sort_values(by='year').copy()
                    if not streamflow:
                        cgres_upper = cgres.loc[cgres.index.str.startswith('l_')].set_index('year')
                        cgres_lower = cgres.loc[cgres.index.str.startswith('g_')].set_index('year')   
                    cgres.set_index('year', inplace=True)
                ax = cgres.Modelled.plot(color='blue') 
                if plot_NHM:
                    cgres.NHM_modelled.plot(color='green',ax=ax) 
                if streamflow:
                    cgres.Measured.plot(ax=ax, color='orange')
                else:
                    cgres_upper.Measured.plot(ax=ax, color='orange')
                    cgres_lower.Measured.plot(ax=ax, color='orange')         
                
                ax.set_title(f'cutout={curr_model},  mod = {curr_root}, iter={citer}, group={cgroup}, location = {cn}')
                print(cn)   
                plt.legend(handles=leg_handles)                
                outpdf.savefig()
                plt.close('all')
            elif monthly:
                # for monthly time sequence cases, we will make a plot for each page
                for cny, cgres in res.groupby('year'):
                    cgres = cgres.sort_values(by='datetime').copy()
                    if not streamflow:
                        cgres_upper = cgres.loc[cgres.index.str.startswith('l_')].set_index('datetime')
                        cgres_lower = cgres.loc[cgres.index.str.startswith('g_')].set_index('datetime')
                    cgres.set_index('datetime', inplace=True)                
                    ax = cgres.Modelled.plot(color='blue') 
                    if plot_NHM:
                        cgres.NHM_modelled.plot(color='green', ax=ax) 

                    if streamflow:
                        cgres.Measured.plot(ax=ax, color='orange')
                    else:
                        cgres_upper.Measured.plot(ax=ax, color='orange')
                        cgres_lower.Measured.plot(ax=ax, color='orange')   

                    
                    ax.set_title(f'cutout={curr_model},  mod = {curr_root}, iter={citer}, group={cgroup}, location = {cn}, year = {cny}')
                    print(cny, cn)  
                    plt.legend(handles=leg_handles)                
                    outpdf.savefig()
            
                    plt.close('all')
            elif daily:
                # for daily time sequence cases, we will make a plot for month/year, so many more pages
                for cny, cgresy in cgres.groupby('year'):
                    for cnm, cgresm in cgresy.groupby('month'):
                        cgresm = cgresm.sort_values(by='datetime').copy()
                        cgresm.set_index('datetime', inplace=True)
                        
                        ax = cgresm.Modelled.plot(color='blue') 
                        if plot_NHM:
                            cgresm.NHM_modelled.plot(color='green', ax=ax) 
                        
                        cgresm.Measured.plot(ax=ax, color='orange')
                        
                        ax.set_title(f'cutout={curr_model}, mod = {curr_root}, iter={citer}, group={cgroup}, location = {cn}, date = {calendar.month_name[cnm]} {cny}')
                        if 'sca' in cgroup:
                            ax.set_ylim(0,1)
                        print(cny, cn)  
                        plt.legend(handles=leg_handles)                  
                        outpdf.savefig()
                
                        plt.close('all')    


def plot_pars_group(parens, cgroup, fig_dir, curr_model, citer, curr_root, outpdf_gen=None):
    # parsing parameters into proper groups. If the obs has 3 ":"-delimited values, that means there is 
    # both a month and an HRU, so make a separate PDF with a page per HRU with all the months on a page
    cpars = parens.loc[parens.pargroup==cgroup].copy()
    example_ob = cpars.index[0]
    print(f'evaluating parameter group: {cgroup}')
    if len(example_ob.split(':')) > 2:
        with PdfPages(fig_dir / f'parameters_monthly_{cgroup}.pdf') as outpdf:
            print(f'plotting parameter group: {cgroup}')
            cpars['month'] = [int(i.split(':')[-1].replace('mon_','')) 
                            for i in cpars.index]
            cpars = parens.loc[parens.pargroup==cgroup].copy()
            cpars['month'] = [int(i.split(':')[-1].replace('mon_','')) for i in cpars.index]
            cpars.sort_values(by=['location','month'], inplace=True)
            for cn, cg in cpars.groupby('location'):
                cg.index=[calendar.month_abbr[i] for i in cg.month]
                _plotpars(cn, cg, outpdf, curr_model, citer, curr_root, cgroup)
    # if the obs has only 2 ":"-delimited values, then there is only HRU or SEG - specific information
    # so stick that into the general PDF with a page for each parameter showing the HRUs/SEGs distinctly
    else:
        print(f'plotting parameter group: {cgroup}')
        cpars = parens.loc[parens.pargroup==cgroup].copy()
        cpars.sort_values(by=['location'], inplace=True)
        cpars.index = cpars.location
        _plotpars(cgroup, cpars, outpdf_gen, curr_model, citer, curr_root, cgroup)