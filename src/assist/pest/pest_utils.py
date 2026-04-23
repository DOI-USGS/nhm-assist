import pandas as pd
import numpy as np
import json
import pywatershed as pws
from pywatershed.parameters.prms_parameters import JSONParameterEncoder

def pars_to_tpl_entries(pars, parname, par_starting_vals,
                        hru_based=True, seg_based = True, month_based = True):
    # make parameter values into meaningful metadata-rich unique strings (i.e. names)
    hrus = pars["nhm_id"]
    segs = pars["nhm_seg"]
    
    tpl_pars = []
    dim_name = None
    if seg_based:
        dim_name = 'seg_'
        dim_vals = segs
    elif hru_based:
        dim_name = 'hru_'
        dim_vals = hrus
    if month_based:
        for cmonth in range(12):
            # oh hi there list comprehension - you are veeeery swanky
            tpl_pars.append(['~{0:^35}~'.format(f'{parname}:{dim_name}{cval}:mon_{cmonth+1}')
                                for cval in dim_vals])
    else:
        tpl_pars= ['~{0:^35}~'.format(f'{parname}:{dim_name}{cval}')
                                for cval in dim_vals]
    # cast into a numpy array cuz the json write will probably 💩 if given a list of lists
    tpl_pars = np.array(tpl_pars)
    # make sure we didn't mess up dimensions wrt months
    assert tpl_pars.shape == pars[parname].shape
    # grab the initial values that were in the original parameter file for starting values
    par_starting_vals = pd.concat((par_starting_vals,(pd.DataFrame(data=
                        {'parname':[v.replace('~','').strip() for v in tpl_pars.ravel()],
                                          'parval1':pars[parname].ravel()}))))
    # replace parameter values with names and delimiter for the TPL file
    pars[parname] = tpl_pars
    
    return par_starting_vals

def write_to_json_tpl(dims, pars, json_filename):
    with open(json_filename, "w") as ofp:
        ofp.write('ptf ~\n')
        json.dump(
            {**dims,
            **pars},
            ofp,
            indent=4,
            cls=JSONParameterEncoder,
        )
    # this sucks - should be a more direct way but whatevs. it verks
    inlines = open(json_filename, 'r').readlines()
    with open(json_filename, 'w') as ofp:
        [ofp.write(i.replace('"~','~').replace('~"','~')) for i in inlines]

def pars_to_tpl_entries_2(pars, parnames, par_starting_vals):
    # make parameter values into meaningful metadata-rich unique strings (i.e. names)
    hrus = pars["nhm_id"]
    segs = pars["nhm_seg"]

    for parname in parnames:
        print(parname)
        dims = list(pws.meta.find_variables(parname)[parname]["dims"])
        print(dims)
        hru_based, seg_based, month_based = False, False, False
        if "nhru" in dims:
            hru_based = True
        if "nsegment" in dims:
            seg_based = True
        if "nmonth" in dims:
            month_based = True
    
        tpl_pars = []
        dim_name = None
        if seg_based:
            dim_name = 'seg_'
            dim_vals = segs
        elif hru_based:
            dim_name = 'hru_'
            dim_vals = hrus
        if month_based:
            for cmonth in range(12):
                # oh hi there list comprehension - you are veeeery swanky
                tpl_pars.append(['~{0:^35}~'.format(f'{parname}:{dim_name}{cval}:mon_{cmonth+1}')
                                    for cval in dim_vals])
        else:
            tpl_pars= ['~{0:^35}~'.format(f'{parname}:{dim_name}{cval}')
                                    for cval in dim_vals]
        # cast into a numpy array cuz the json write will probably 💩 if given a list of lists
        tpl_pars = np.array(tpl_pars)
        # make sure we didn't mess up dimensions wrt months
        assert tpl_pars.shape == pars[parname].shape
        # grab the initial values that were in the original parameter file for starting values
        par_starting_vals = pd.concat((par_starting_vals,(pd.DataFrame(data=
                            {'parname':[v.replace('~','').strip() for v in tpl_pars.ravel()],
                                              'parval1':pars[parname].ravel()}))))
        # replace parameter values with names and delimiter for the TPL file
        pars[parname] = tpl_pars
        
    return par_starting_vals

def check_par_bounds(par_starting_vals, bnds, bnds_path):
    """
    Check consistency between par_starting_vals and bnds.

    - All parameter groups in par_starting_vals must appear in bnds.parameter_name.
    - Optionally warn if bnds has parameters not present in par_starting_vals.
    """

    # Basic column checks
    required_par_cols = {"parname"}
    required_bnd_cols = {"parameter_name"}

    missing_par_cols = required_par_cols - set(par_starting_vals.columns)
    missing_bnd_cols = required_bnd_cols - set(bnds.columns)

    if missing_par_cols:
        print(
            f"[FAIL] par_starting_vals is missing required columns: {sorted(missing_par_cols)}"
        )
        return False

    if missing_bnd_cols:
        print(
            f"[FAIL] {bnds_path} is missing required columns: {sorted(missing_bnd_cols)}"
        )
        return False

    # Pull parameter "groups" from par_starting_vals (split on ':')
    bnds_params = bnds["parameter_name"].astype(str).unique()
    par_starting_vals_params_groups = (
        par_starting_vals["parname"].astype(str).str.split(":").str[0].unique()
    )

    missing_bounds = set(par_starting_vals_params_groups) - set(bnds_params)
    extra_bounds = set(bnds_params) - set(par_starting_vals_params_groups)

    all_passed = True

    if missing_bounds:
        print(
            f"[FAIL] The following parameter groups need bounds added to {bnds_path}: "
            f"{sorted(missing_bounds)}"
        )
        all_passed = False
    else:
        print(
            f"[PASS] All parameter groups in `par_starting_vals` have bounds defined in {bnds_path}."
        )

    if extra_bounds:
        print(
            f"[WARNING] The following parameters have bounds listed in {bnds_path}, "
            f"but are not present in `par_starting_vals`: {sorted(extra_bounds)}"
        )
    else:
        print(
            f"[PASS] No extra parameters in {bnds_path} without corresponding entries in `par_starting_vals`."
        )

    if all_passed:
        print("[PASS] par/bounds consistency check completed successfully.")
    else:
        print("[FAIL] par/bounds consistency check found issues (see messages above).")

    # return all_passed