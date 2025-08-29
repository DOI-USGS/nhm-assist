import pathlib as pl
import shutil, os

all_extractions = ['05431486','09112500','01473000']
#all_extractions = ['09112500']
#rootnm = 'prior_mc_reweight'#'ies_hot'
rootnm = 'ies_hot'
hotstart =True
first_time=False
senrun=False
if senrun:
    # add gsa to the rootname
    rootnm += '_gsa'

for cex in all_extractions:
    frompath = pl.Path(f'../NHM_extractions/20230110_pois_haj/{cex}/')
    topath = pl.Path(f'../CONDOR/{cex}')
    genpath = pl.Path('../CONDOR/GENERAL')
    tofolder = ['MASTER','data']
    if first_time:
        if not topath.exists():
            topath.mkdir()
        if not (topath / 'log').exists():
            (topath / 'log').mkdir()
        [shutil.copy2(f, topath / f.name) for f in genpath.glob('*')]
        for tf in tofolder:
            print(f'copying {frompath} to CONDOR rundir')
            shutil.copytree(frompath, topath/tf, dirs_exist_ok=True)
            shutil.copy2(topath/'pestpp-ies', topath/tf/'pestpp-ies')
    else:
        files = [i for i in list(frompath.glob(f'{rootnm}*') ) if 'phi' not in i.name]
        files.extend([i for i in list(frompath.glob(f'*.tpl') ) ]) 
        files.extend([i for i in list(frompath.glob(f'*.py') ) ])
        files.extend([i for i in list(frompath.glob(f'*.ins') ) ])
        if hotstart:
            files.extend([i for i in list(frompath.glob(f'*hot*'))])
        files.append(frompath / 'loc.mat')

        for tf in tofolder:
            [shutil.copy2(f, topath / tf / f.name) for f in files]

        if senrun:
            for tf in tofolder:
                # supporting files
                supfiles = [i for i in list(frompath.glob(f'{rootnm.replace("_gsa","")}*') ) if 'phi' not in i.name]
                [shutil.copy2(f, topath / tf / f.name) for f in supfiles]
                shutil.copy2(topath/'pestpp-sen', topath/tf/'pestpp-sen')
                
    cdir = os.getcwd()
    os.chdir(topath)
    print('tarring up data.tar')
    os.system('tar --use-compress-program="pigz" -cf  data.tar data')
    os.chdir(cdir)
