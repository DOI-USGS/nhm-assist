# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.3
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %%
import warnings
import pandas as pd
import numpy as np
import pathlib as pl
import xarray as xr
from contextlib import redirect_stdout
import io
import sys
import os

f = io.StringIO()
with redirect_stdout(f):
    import pywatershed as pws

from rich.console import Console
from rich import pretty

warnings.filterwarnings("ignore")
pretty.install()
con = Console()

root_folder = "nhm-assist"
root_dir = pl.Path(os.getcwd().rsplit(root_folder, 1)[0] + root_folder)
sys.path.append(str(root_dir))

from nhm_helpers.nhm_assist_utilities import load_subdomain_config
config = load_subdomain_config(root_dir)

import dataretrieval.nwis as nwis
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

# %%
from nhm_helpers.nhm_hydrofabric import (
    create_hru_gdf,
    create_segment_gdf,
    create_poi_df,
    create_default_gages_file,
    read_gages_file,
)

hru_gdf, hru_txt, hru_cal_level_txt = create_hru_gdf(
    root_dir=root_dir,
    model_dir=config["model_dir"],
    GIS_format=config["GIS_format"],
    param_filename=config["param_filename"],
    nhru_params=config["nhru_params"],
    nhru_nmonths_params=config["nhru_nmonths_params"],
)

seg_gdf, seg_txt = create_segment_gdf(
    model_dir=config["model_dir"],
    GIS_format=config["GIS_format"],
    param_filename=config["param_filename"],
)

poi_df = create_poi_df(
    root_dir=root_dir,
    model_dir=config["model_dir"],
    param_filename=config["param_filename"],
    control_file_name=config["control_file_name"],
    hru_gdf=hru_gdf,
    gages_file=config["gages_file"],
    default_gages_file=config["default_gages_file"],
    nwis_gage_nobs_min=config["nwis_gage_nobs_min"],
    seg_gdf=seg_gdf,
)


# %%
poi_df

# %%
start_date = config[
    "start_date"
]  # pd.to_datetime(str(control.start_time)).strftime("%m/%d/%Y")
end_date = config[
    "end_date"
]  # pd.to_datetime(str(control.end_time)).strftime("%m/%d/%Y")

# %%
temp_config = {
    "usgs_site": "14159500",
    "nwis_service": "iv",
    "parameter_code": "00010",
    "start_date": "start_date",
    "end_date": "end_date",

    # Set one of these:
    "target_nhm_seg_index": 6,
    "target_poi_gage_id": None,

    "air_temp_rolling_days": 7,

    "obs_temp_csv": config["out_dir"] / "obs_stream_temp_daily.csv",
    "regression_dataset_csv": config["out_dir"] / "stream_temp_regression_dataset.csv",
    "predicted_temp_csv": config["out_dir"] / "predicted_stream_temp.csv",
    "predicted_temp_nc": config["out_dir"] / "predicted_stream_temp.nc",
}

# %%
pws_prcp_input_file = config["model_dir"] / "prcp.nc"
pws_tmin_input_file = config["model_dir"] / "tmin.nc"
pws_tmax_input_file = config["model_dir"] / "tmax.nc"
nhmx_input_file = config["model_dir"] / "cbh.nc"
input_file_path_list = [pws_prcp_input_file, pws_tmin_input_file, pws_tmax_input_file]

rewrite_inputs = any([not ff.exists() for ff in input_file_path_list])

if rewrite_inputs:
    con.print(
        "One or more pywatershed forcing files is missing. "
        "Rewriting prcp.nc, tmin.nc, and tmax.nc from cbh.nc."
    )
    with xr.open_dataset(nhmx_input_file) as ds:
        model_input = ds.swap_dims({"nhru": "nhm_id"}).drop("nhru")
        model_input["prcp"].to_netcdf(pws_prcp_input_file)
        model_input["tmin"].to_netcdf(pws_tmin_input_file)
        model_input["tmax"].to_netcdf(pws_tmax_input_file)

    con.print(f"Created forcing files in {config['model_dir']}")
else:
    con.print(
        f"Optional: delete prcp.nc, tmin.nc, and tmax.nc in {config['model_dir']} to recreate them."
    )

# %%
params = pws.parameters.PrmsParameters.load(config["param_filename"])

if "pref_flow_infil_frac" not in params.parameters.keys():
    params_ds = params.to_xr_ds()
    params_ds["pref_flow_infil_frac"] = params_ds["pref_flow_den"][:] * 0.0
    params = pws.parameters.PrmsParameters.from_ds(params_ds)

params_ds = params.to_xr_ds()
params_ds["pref_flow_infil_frac"] = params_ds["pref_flow_infil_frac"].where(
    (params_ds["pref_flow_infil_frac"] >= 0.0) &
    (params_ds["pref_flow_infil_frac"] <= 1.0),
    0.0,
)
params = pws.parameters.PrmsParameters.from_ds(params_ds)

# %%
control = pws.Control.load_prms(
    config["model_dir"] / config["control_file_name"],
    warn_unused_options=False,
)

control.options = control.options | {
    "input_dir": config["model_dir"],
    "budget_type": None,
    "verbosity": 0,
    "calc_method": "numba",
    "netcdf_output_var_names": config["selected_output_variables"],
    "netcdf_output_dir": config["out_dir"],
}

model = pws.Model(
    [
        pws.PRMSSolarGeometry,
        pws.PRMSAtmosphere,
        pws.PRMSCanopy,
        pws.PRMSSnow,
        pws.PRMSRunoff,
        pws.PRMSSoilzone,
        pws.PRMSGroundwater,
        pws.PRMSChannel,
    ],
    control=control,
    parameters=params,
)

model.run()

# %%
hru_streamflow_out = sum(
    xr.load_dataarray(config["out_dir"] / f"{ff}.nc")
    for ff in ["sroff_vol", "ssres_flow_vol", "gwres_flow_vol"]
)
hru_streamflow_out.name = "hru_streamflow_out"
hru_streamflow_out.to_netcdf(config["out_dir"] / "hru_streamflow_out.nc")
del hru_streamflow_out

# %%
# full_seg_outflow = xr.load_dataarray(config["out_dir"] / "seg_outflow.nc")
# full_seg_outflow.to_netcdf(config["out_dir"] / "seg_outflow_full.nc")

# wh_gages = (params.parameters["poi_gage_segment"] - 1,)
# poi_seg_outflow = full_seg_outflow[:, wh_gages[0]]
# poi_seg_outflow = poi_seg_outflow.assign_coords(
#     npoi_gages=("nhm_seg", params.parameters["poi_gage_id"])
# )
# poi_seg_outflow.to_netcdf(config["out_dir"] / "seg_outflow_poi.nc")

# del full_seg_outflow
# del poi_seg_outflow

# %%
# For streamflow, just keep output on the POIs.
# - 1 is related to the indexing in fortran; made a a tuple see above
wh_gages = (params.parameters["poi_gage_segment"] - 1,)
for var in ["seg_outflow"]:
    data = xr.load_dataarray(f"{config['out_dir'] / var}.nc")[:, wh_gages[0]]
    data = data.assign_coords(npoi_gages=("nhm_seg", params.parameters["poi_gage_id"]))
    out_file = f"{config['out_dir'] / var}.nc"
    data.to_netcdf(out_file)
    del data


# %%
def get_target_segment_index(params, temp_config):
    if temp_config["target_nhm_seg_index"] is not None:
        return int(temp_config["target_nhm_seg_index"])

    if temp_config["target_poi_gage_id"] is not None:
        poi_ids = np.array(params.parameters["poi_gage_id"]).astype(str)
        poi_segs = np.array(params.parameters["poi_gage_segment"]) - 1
        match = np.where(poi_ids == str(temp_config["target_poi_gage_id"]))[0]
        if len(match) == 0:
            raise ValueError("target_poi_gage_id not found in parameter file.")
        return int(poi_segs[match[0]])

    raise ValueError("Set either target_nhm_seg_index or target_poi_gage_id in temp_config.")


def load_segment_flow_series(seg_outflow_file, target_seg_idx):
    da = xr.load_dataarray(seg_outflow_file)

    seg_dim_candidates = [dd for dd in da.dims if dd.lower() in ["nhm_seg", "nsegment", "segment"]]
    if len(seg_dim_candidates) == 0:
        raise ValueError(f"Could not identify segment dimension in {da.dims}")

    seg_dim = seg_dim_candidates[0]
    time_dim = [dd for dd in da.dims if "time" in dd.lower()][0]

    series = da.isel({seg_dim: target_seg_idx}).to_series()
    series.index.name = "date"
    series.name = "seg_outflow"
    series = series.reset_index()

    if time_dim != "time":
        series = series.rename(columns={time_dim: "time"})
    if "time" in series.columns:
        series = series.rename(columns={"time": "date"})

    series["date"] = pd.to_datetime(series["date"]).dt.floor("D")
    return series[["date", "seg_outflow"]]


def load_air_temp_series_from_cbh(cbh_file):
    with xr.open_dataset(cbh_file) as ds:
        if "nhru" in ds.dims and "nhm_id" not in ds.dims:
            tmin = ds["tmin"].mean(dim="nhru")
            tmax = ds["tmax"].mean(dim="nhru")
        elif "nhm_id" in ds.dims:
            tmin = ds["tmin"].mean(dim="nhm_id")
            tmax = ds["tmax"].mean(dim="nhm_id")
        else:
            raise ValueError("Could not identify HRU dimension in cbh.nc")

        tair = (tmin + tmax) / 2.0
        df = tair.to_series().reset_index()
        df.columns = ["date", "tair_mean"]
        df["date"] = pd.to_datetime(df["date"]).dt.floor("D")
    return df


def fetch_nwis_temp_daily(site, start_date, end_date, parameter_code="00010", service="iv"):
    df = nwis.get_record(
        sites=site,
        service=service,
        start=start_date,
        end=end_date,
        parameterCd=parameter_code,
    )

    if df is None or len(df) == 0:
        raise ValueError("No NWIS stream temperature data returned.")

    df = df.copy()

    if isinstance(df.index, pd.DatetimeIndex):
        df = df.reset_index()

    dt_col = None
    for cc in df.columns:
        if "datetime" in cc.lower() or cc.lower() in ["date", "time", "datetime"]:
            dt_col = cc
            break
    if dt_col is None:
        raise ValueError("Could not identify datetime column in NWIS result.")

    value_cols = [cc for cc in df.columns if parameter_code in cc and "_cd" not in cc.lower()]
    if len(value_cols) == 0:
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        if len(numeric_cols) == 0:
            raise ValueError("Could not identify water temperature value column.")
        value_col = numeric_cols[0]
    else:
        value_col = value_cols[0]

    out = df[[dt_col, value_col]].copy()
    out.columns = ["datetime", "obs_stream_temp"]
    out["datetime"] = pd.to_datetime(out["datetime"])
    out["date"] = out["datetime"].dt.floor("D")

    daily = out.groupby("date", as_index=False)["obs_stream_temp"].mean()
    return daily


def add_time_features(df, rolling_days=7):
    df = df.sort_values("date").copy()
    doy = df["date"].dt.dayofyear
    df["sin_doy"] = np.sin(2 * np.pi * doy / 365.25)
    df["cos_doy"] = np.cos(2 * np.pi * doy / 365.25)
    df["log_flow"] = np.log1p(df["seg_outflow"].clip(lower=0.0))
    df["tair_mean_lag1"] = df["tair_mean"].shift(1)
    df["tair_mean_roll"] = df["tair_mean"].rolling(rolling_days, min_periods=1).mean()
    return df


# %%
if temp_config["target_poi_gage_id"] is not None:
    poi_ids = np.array(params.parameters["poi_gage_id"]).astype(str)
    match = np.where(poi_ids == str(temp_config["target_poi_gage_id"]))[0]
    if len(match) == 0:
        raise ValueError("target_poi_gage_id not found in poi_gage_id.")
    target_idx_for_file = int(match[0])
    seg_file = config["out_dir"] / "seg_outflow_poi.nc"
else:
    target_idx_for_file = int(get_target_segment_index(params, temp_config))
    seg_file = config["out_dir"] / "seg_outflow_full.nc"

flow_df = load_segment_flow_series(seg_file, target_idx_for_file)
air_df = load_air_temp_series_from_cbh(config["model_dir"] / "cbh.nc")

obs_temp_df = fetch_nwis_temp_daily(
    site=temp_config["usgs_site"],
    start_date=temp_config["start_date"],
    end_date=temp_config["end_date"],
    parameter_code=temp_config["parameter_code"],
    service=temp_config["nwis_service"],
)

obs_temp_df.to_csv(temp_config["obs_temp_csv"], index=False)

flow_df["date"] = pd.to_datetime(flow_df["date"]).dt.tz_localize(None)
air_df["date"] = pd.to_datetime(air_df["date"]).dt.tz_localize(None)
obs_temp_df["date"] = pd.to_datetime(obs_temp_df["date"]).dt.tz_localize(None)

reg_df = (
    flow_df.merge(air_df, on="date", how="inner")
           .merge(obs_temp_df, on="date", how="inner")
)

reg_df = add_time_features(
    reg_df,
    rolling_days=temp_config["air_temp_rolling_days"],
)
reg_df = reg_df.dropna().reset_index(drop=True)
reg_df.to_csv(temp_config["regression_dataset_csv"], index=False)

con.print(f"Regression dataset written to {temp_config['regression_dataset_csv']}")
reg_df.head()


# %%
def kling_gupta_efficiency(obs, sim):
    obs = np.asarray(obs, dtype=float)
    sim = np.asarray(sim, dtype=float)

    mask = np.isfinite(obs) & np.isfinite(sim)
    obs = obs[mask]
    sim = sim[mask]

    if len(obs) < 2:
        return np.nan

    obs_mean = np.mean(obs)
    sim_mean = np.mean(sim)
    obs_std = np.std(obs, ddof=1)
    sim_std = np.std(sim, ddof=1)

    if obs_mean == 0 or obs_std == 0:
        return np.nan

    r = np.corrcoef(obs, sim)[0, 1]
    alpha = sim_std / obs_std
    beta = sim_mean / obs_mean

    kge = 1 - np.sqrt((r - 1)**2 + (alpha - 1)**2 + (beta - 1)**2)
    return kge


# %%
predictor_cols = [
    "tair_mean",
    "tair_mean_lag1",
    "tair_mean_roll",
    "log_flow",
    "sin_doy",
    "cos_doy",
]

X = reg_df[predictor_cols].copy()
y = reg_df["obs_stream_temp"].copy()

split_date = pd.to_datetime(reg_df["date"]).quantile(0.7)

train_mask = pd.to_datetime(reg_df["date"]) <= split_date
test_mask = ~train_mask

X_train = X.loc[train_mask]
y_train = y.loc[train_mask]
X_test = X.loc[test_mask]
y_test = y.loc[test_mask]

reg_model = LinearRegression()
reg_model.fit(X_train, y_train)

reg_df["pred_stream_temp"] = reg_model.predict(X)

train_pred = reg_model.predict(X_train)
test_pred = reg_model.predict(X_test)

metrics = pd.DataFrame({
    "dataset": ["train", "test"],
    "rmse": [
        np.sqrt(mean_squared_error(y_train, train_pred)),
        np.sqrt(mean_squared_error(y_test, test_pred)),
    ],
    "mae": [
        mean_absolute_error(y_train, train_pred),
        mean_absolute_error(y_test, test_pred),
    ],
    "r2": [
        r2_score(y_train, train_pred),
        r2_score(y_test, test_pred),
    ],
    "kge": [
        kling_gupta_efficiency(y_train, train_pred),
        kling_gupta_efficiency(y_test, test_pred),
    ],
})

metrics

# %%
coef_df = pd.DataFrame({
    "predictor": predictor_cols,
    "coefficient": reg_model.coef_,
})
coef_df.loc[len(coef_df)] = ["intercept", reg_model.intercept_]

coef_df.to_csv(config["out_dir"] / "stream_temp_regression_coefficients.csv", index=False)

pred_df = reg_df[["date", "obs_stream_temp", "pred_stream_temp", "seg_outflow", "tair_mean"]].copy()
pred_df.to_csv(temp_config["predicted_temp_csv"], index=False)

pred_da = xr.DataArray(
    data=pred_df["pred_stream_temp"].values,
    dims=["time"],
    coords={"time": pd.to_datetime(pred_df["date"]).values},
    name="pred_stream_temp",
    attrs={
        "long_name": "Predicted stream temperature",
        "units": "degC",
        "usgs_site": temp_config["usgs_site"],
    },
)
pred_da.to_netcdf(temp_config["predicted_temp_nc"])

con.print(f"Predicted stream temperature written to {temp_config['predicted_temp_csv']}")
con.print(f"Predicted stream temperature netcdf written to {temp_config['predicted_temp_nc']}")

# %%
pred_df.head()

# %%
