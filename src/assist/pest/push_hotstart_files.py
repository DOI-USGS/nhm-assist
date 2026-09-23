import pathlib as pl
import zipfile
import os

all_extractions = ['01473000','05431486','09112500']
# all_extractions = ['05431486','09112500']
pstdir = pl.Path('../NHM_extractions/20230110_pois_haj')

for cex in all_extractions:
    fname = str(pstdir / cex / f'{cex}.hotstart.zip')
    os.system(f"aws s3 cp {fname} s3://hytest-workspace/mnfienen/{cex}.hotstart.zip --endpoint-url https://usgs.osn.mghpcc.org/ --profile osn-hytest-workspace")
