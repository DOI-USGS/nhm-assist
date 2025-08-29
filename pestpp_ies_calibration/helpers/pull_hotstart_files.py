import pathlib as pl
import zipfile
import os

all_extractions = ['01473000']
#all_extractions = ['05431486']
#all_extractions =['09112500']
pstdir = pl.Path('../NHM_extractions/20230110_pois_haj')

for cex in all_extractions:
    fname = str(pstdir / cex / f'{cex}.hotstart.zip')
    os.system(f"aws s3 cp s3://hytest-workspace/mnfienen/{cex}.hotstart.zip {fname} --endpoint-url https://usgs.osn.mghpcc.org/ --profile osn-hytest-workspace")
