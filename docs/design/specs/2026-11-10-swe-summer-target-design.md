# Design: an end-of-summer SWE calibration target (`swe_summer`)

Status: proposed, not started. Open decisions are listed in section 7.

## 1. Problem

In the Sandy River PEST++ IES runs, many ensemble members develop **snow
towers**: HRUs where simulated SWE (`pkwater_equiv`) never melts out and grows
year after year. Findings from `Sandy_beta1_n` and `Sandy_beta1_1`
(2026-11-10, read-only analysis of the runs' archives and ensemble files):

- Towers are present in the **prior**: at HRU 7328, 14 % of the 499 prior
  realizations already hold more than 50 in of SWE in November 2010. The
  saturated state is the same 3,838 in in every iteration of both runs.
- They persist and spread through calibration: in the final ensembles, 81 %
  (`_n`) and 98 % (`_1`) of members have a tower at one or more HRUs, and the
  `base` realization has towers in both runs (`_n`: HRUs 7320, 7333; `_1`:
  7328, 7346). At HRU 7328, `_1` went 14 % → 2.5 % → 9 % → 22 % over the four
  iterations.
- The **targets have no towers**: the November SWE target is at most 5.45 in
  anywhere, and in the daily target file (`SWE.nc`, ensemble mean) the
  August-September SWE is 0.0-0.1 in at every towered HRU except 7346
  (2.0 in), and October-1 SWE is at most 0.16 in anywhere.
- `pkwater_equiv` is the correct model variable (snowpack water equivalent,
  a storage, inches), and the forward run aggregates it the same way as the
  target (monthly mean of daily values).
- The gap is the target's **season**: notebook 01 and the forward run drop
  June-October from `swe_monthly`. Summer is exactly when a tower is obvious,
  so IES only sees a tower as an excess in November-May. Inside a tower SWE is
  insensitive to the parameters, so the ensemble gives IES no direction out.
- Towers lock water in the snowpack, so a towered member's runoff, ET and
  recharge are wrong; this biases the posterior recharge range.

## 2. Goal

Give IES an observation that is large for towered members and near zero for
realistic ones, and that responds smoothly as a member approaches the tower
state, so IES can steer members away from it. Keep the existing `swe_monthly`
target unchanged.

Out of scope here: narrowing the `tmax_allsnow` prior (bounds −10 to 40 °F;
high December values are associated with prior towers), screening towered
members out of reported results, and diagnosing the melt mechanism with a
forward run. Each is worth doing; they are separate changes.

## 3. Proposed target

A new observation group, **`swe_summer`**: one value per HRU per calibration
year, the **mean SWE over August and September** (inches) of that water year.

- **Model side:** mean of daily `pkwater_equiv` over Aug 1-Sep 30.
- **Observed side:** mean of the daily SWE ensemble (`snodas`, `era5_land`,
  `ua_swe`; `margulis_wus_sr` stays excluded) over the same days, from the
  same `swe_targets.nc` baseline used for `swe_monthly`.
- **Years:** the calibration (odd) years only, by the `water_years` flag in
  `ancillary/cal_year_config.csv`, as for every other target. Aug-Sep is the
  end of a water year, so it pairs with the preceding winter.
- **Names:** `swe_summer:<year>:<nhm_id>`, following the `recharge_ann` and
  `soil_moist_ann` pattern. 164 HRUs × 6 calibration years ≈ 984 observations
  for Sandy.

Why Aug-Sep mean rather than a single date: a two-month mean is less noisy than
one day, still near zero wherever snow melts out, and close to the annual SWE
minimum, which is what distinguishes a tower.

## 4. Files and steps that change

Each step must keep `allobs.dat` and `modelobs.dat` in the same order and count
(the instruction file pairs them by position).

| Where | Change |
|---|---|
| `00_Subset_NHM_baselines_gfv2.py` | Write `SWE_summer.nc`: the Aug-Sep mean of the daily ensemble (mean, std, bounds) per HRU, calibration years only, built after `_rebuild_swe_ensemble`. |
| `01_Prepare_observations_gfv2.py` | Append `swe_summer` values to `allobs.dat` and its std to `allobs_std.dat`, right after the `swe_monthly` block. |
| `forward_run_gfv2.py` | After the `swe_monthly` block, write the matching Aug-Sep mean of `pkwater_equiv` for the same years, HRUs and order. Uses the existing `swe_start`/`swe_end` window (2009-10-01 to 2021-09-30). |
| `02_Create_pest_instruction_file_gfv2.py` | No code change (it reads names from `allobs.dat`); its `check_ins_and_outs` run confirms the alignment. |
| `03_set_up_PEST++_gfv2.py` | Assign `obgnme = "swe_summer"` (or the inequality name, section 7.2); add an `SD_FLOORS` entry (section 7.4). Weights follow the existing non-streamflow rule, `1 / wt_percent` from the SD table. |
| `ancillary_template/Observation_standard_deviation.csv` | New row for the group: `noise_percent`, units `inches`, bounds, `wt_percent`. Notebook 06 asserts every modifiable group has a row. |
| `ancillary_template/localization_groups.csv` | New row for the group. **Required:** PEST++ IES treats a non-zero-weighted observation that is missing from the localizer as zero-weighted. Proposed: the same parameter types as `swe_monthly`. |
| `05_Re-weighting_obs.py` | New entry in `phi_new_comps`, and lower another entry so the fractions still sum to 1 (section 7.5). The pattern `swe_monthly` does not match `swe_summer`, so the two stay separate. |
| `assist/pest/calibration_evaluation.py`, `calibration_target_comparison.py` | Add the group to the plotted HRU groups, X/Y titles and the target comparison. Statistic: **mean error in inches** (sim − obs). PBIAS is unusable when the observed sum is near zero. |

Notebook 04 builds `loc.mat` from `localization_groups.csv`, and notebook 06
reads the SD table, so neither needs code changes once those files have the new
row.

## 5. How it is weighted against towers

- A towered member's `swe_summer` residual is hundreds to thousands of inches
  at that HRU, so its phi from this group is large, and IES tends to drop or
  move it (`ies_bad_phi_sigma` is 2.5).
- A member *approaching* a tower carries a few inches of SWE into late summer.
  That residual responds smoothly to the snow parameters, which is the
  gradient IES lacks today.
- The group's share of the objective function is set by its phi factor, so a
  single towered HRU cannot dominate the whole calibration.

## 6. Verification

1. Rebuild notebooks 00-06 for Sandy and confirm `check_ins_and_outs` in 02
   passes (same count, names and order in `allobs.dat`, `modelobs.dat`,
   `modelobs.dat.ins`).
2. `noptmax = 0` run: the `swe_summer` simulated values for `base` are near
   the observed values at HRUs without towers, and the group appears in the
   phi summary with the intended share.
3. Prior check, before a full run: compute the `swe_summer` residuals of the
   existing prior ensemble (iteration 0 of `Sandy_beta1_1`) and confirm the
   towered realizations are the ones with large residuals. This needs the
   prior's Aug-Sep SWE, so it needs one prior forward run or the existing
   prior outputs if they hold daily `pkwater_equiv`.
4. After a calibration: the share of final members with a tower (the
   November > 100 in / observed < 10 in rule used in the analysis) should drop
   well below the 81-98 % seen in `_n` and `_1`. Compare with the
   `compare_calibration_evaluation_plots` workflow against `Sandy_beta1_1`.
   Note that a new observation group changes the objective function, so the
   two runs' changes in KGE are not like-for-like.

## 7. Open decisions

### 7.1 Months

Aug-Sep mean (proposed), September only, or a single date (Sep 30). A later
window catches towers more cleanly. An earlier one penalizes slow-melting but
realistic high-elevation snow more.

### 7.2 Equality or inequality target

- **Equality** (proposed to start): `obsval` = observed Aug-Sep mean,
  ordinary residual.
- **Inequality** ("less than"): penalize only simulated values above a
  threshold, so a member with slightly less snow than observed is not
  penalized. PEST++ marks inequality observations by group-name prefix
  (believed to be `l_`/`less_` for less-than; **verify against the PEST++
  manual before implementing**). It would rename the group, e.g.
  `less_swe_summer`, which then has to match in the SD table, localizer and
  phi factors.

### 7.3 High-elevation HRUs with real late snow

A few HRUs keep snow into late summer in the targets (HRU 7346: 2.0 in on the
ensemble mean, SNODAS up to 6.1 in; across the domain, 10 of 164 HRUs exceed
1 in in Aug-Sep). With an equality target they get their observed value, which
handles them naturally. With an inequality target the threshold has to be per
HRU (e.g. observed + margin), not one number.

### 7.4 Noise standard deviation

The ensemble std of the three sources is near zero in summer at most HRUs, so
the noise ensemble would be almost exact. Proposed: an `SD_FLOORS` entry with
an absolute floor, e.g. `{"abs": 0.5}` inches (plus `rel` 0.2 for the
high-elevation HRUs). The value is open.

### 7.5 Phi share

`swe_monthly` has 0.08 today. Proposed: 0.04 for `swe_summer`, taken from
`swe_monthly` (0.08 → 0.04) so total snow weight is unchanged. Alternatives:
take it from another group, or start smaller (0.02) and raise it if towers
persist.

### 7.6 Validation years

Proposed: calibration (odd) years only, like the other targets, with the even
years kept for evaluation. The evaluation workflow can then report the tower
share on the validation years too, once posterior forward runs exist.

## 8. Risks

- **Alignment.** The forward run writes values by position. A mismatch in
  years, HRU order or month selection between 01 and the forward run silently
  pairs wrong values. Mitigated by verification step 1.
- **Phi budget.** A new group takes share from others. With the
  fixed-fraction phi factors, every other group's effective weight changes a
  little.
- **Masking the cause.** The target penalizes towers but does not explain why
  melt stops. The prior-bound and mechanism checks in section 2 remain
  worthwhile.
- **Comparability.** Runs with and without this group have different
  objective functions, so their changes in KGE compare different
  calibrations.
