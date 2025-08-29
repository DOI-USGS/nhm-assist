import pathlib as pl
import zipfile
import os

#all_extractions = ['01473000', '05431486','09112500']
all_extractions = ['05431486']
#rootnm = 'prior_mc_reweight' # 'ies_hot'
senflag = False
rootnm = 'ies_hot_noloc'
priorflag = False
results_dir = pl.Path('../results')

if senflag:
    # add gsa to the rootname
    rootnm += '_gsa'


for cex in all_extractions:
    cpath = pl.Path(f'../CONDOR/{cex}/MASTER')
    if senflag:
        files = []
        files.extend([i for i in cpath.glob(f'{rootnm}.*') if (
            ('rec' not in i.name) & ('rmr' not in i.name))])
    else:
        files = []
        files.extend(cpath.glob(f'{rootnm}*pdc*'))
        files.extend(cpath.glob(f'{rootnm}*phi*'))
        files.extend(cpath.glob(f'{rootnm}.0*'))
        if not priorflag:
            for i in range(1,4):
                files.extend(cpath.glob(f'{rootnm}.{i}*'))
        files.extend(cpath.glob(f'{rootnm}.*noise*'))
    with zipfile.ZipFile(results_dir / f'{rootnm}.{cex}.zip', 'w', zipfile.ZIP_DEFLATED) as zipf:
        [zipf.write(i, i.name) for i in files]
    pt = str(results_dir / f'{rootnm}.{cex}.zip')
    os.system(f"aws s3 cp {pt} s3://hytest-workspace/mnfienen/{rootnm}.{cex}.zip --endpoint-url https://usgs.osn.mghpcc.org/ --profile osn-hytest-workspace")
