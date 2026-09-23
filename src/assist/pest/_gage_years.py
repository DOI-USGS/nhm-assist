import pathlib as pl
import pandas as pd
import numpy as np
import xarray as xr

model_dir = pl.Path(r"D:\nhm-workspace\Oregon_Recharge\models\SandyRiver\outputs\runtime")

# calibration gages + names
xlsx = model_dir / "metadata" / "npoigages_cal_list_SandyRiver.xlsx"
df = pd.read_excel(xlsx)
cal = df[df["ohm_cal"].astype(str).str.strip().str.lower() == "yes"].copy()
cal["poi_gage_id"] = cal["poi_gage_id"].astype(int).astype(str)
names = dict(zip(cal["poi_gage_id"], cal["poi_name"]))
gages = list(cal["poi_gage_id"])

# observations
efc = model_dir / "notebook_output_files" / "nc_files" / "sf_efc.nc"
ds = xr.open_dataset(efc)

def odd_years_with_obs(gage):
    if gage not in [str(x) for x in ds["poi_gage_id"].values]:
        return None  # gage not in obs file at all
    q = ds["discharge"].sel(poi_gage_id=gage).to_series()
    q = q.dropna()
    if q.empty:
        return []  # in file but no observations
    years = pd.Index(q.index).year
    odd = sorted({int(y) for y in years if y % 2 == 1})
    return odd

rows = []
for g in gages:
    oy = odd_years_with_obs(g)
    if oy is None:
        yrs_str = "(gage not in obs file)"
    elif len(oy) == 0:
        yrs_str = "(no observations)"
    else:
        yrs_str = ", ".join(str(y) for y in oy)
    rows.append({"poi_gage_id": g, "poi_name": names[g], "odd_cal_years_with_obs": yrs_str})

out = pd.DataFrame(rows)
pd.set_option("display.max_colwidth", None)
pd.set_option("display.width", 200)
print(out.to_string(index=False))

# also save a CSV next to the model metadata for convenience
csv_path = model_dir / "metadata" / "cal_gage_odd_years_SandyRiver.csv"
out.to_csv(csv_path, index=False)
print(f"\nsaved: {csv_path}")
