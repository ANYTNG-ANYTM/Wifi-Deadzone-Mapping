# Step 3: count-aware interpolation and uncertainty

Run with the existing project environment:

```powershell
.\.venv\Scripts\python.exe scripts/03_interpolation.py
.\.venv\Scripts\python.exe scripts/dev/verify_step3.py
```

## Inputs and geometry

Fit separate scikit-learn GaussianProcessRegressor models to the 218 observed
WiFi cell means and 556 cellular cell means from Step 2. Transform their latitude
and longitude to the same local metre coordinates used for the 10 m grid. This
makes a learned spatial length scale interpretable in metres.

Predict on a shared 5 m grid covering the full Step 2 rectangle: 270 columns by
142 rows, or 38,340 prediction locations per network. Its small outer padding is
inherited from Step 2. All routes and sessions remain pooled. No raw readings are
replaced and no interpolated values are labelled observed.

## How counts affect the fit

For each network, pool the within-cell sample variances using their degrees of
freedom:

`pooled_variance = sum((n_i - 1) * sample_variance_i) / sum(n_i - 1)`

A singleton has no sample variance. Its contribution to this pooled estimate is
zero degrees of freedom, but its assigned noise is the full pooled variance,
not zero. The variance assigned to each observed cell mean is:

`mean_noise_variance_i = pooled_variance / reading_count_i`

Pass that per-cell variance to GPR through `alpha`, with a tiny numerical jitter.
The kernel is a fitted amplitude times a Matern spatial kernel (nu=1.5), plus a
fitted WhiteKernel residual variance. Thus effective training noise is:

`pooled_variance / reading_count_i + fitted_residual_variance`

Both targets and noise variances are standardized consistently before fitting,
then all predictions and standard deviations are returned to dBm. Noise variance
is in dBm squared. The API supports an alpha value per observation; see the
[scikit-learn Gaussian process guide](https://scikit-learn.org/stable/modules/gaussian_process.html).

The spatial kernel length scale, amplitude, and residual noise are learned by
maximum marginal likelihood, with two additional optimizer starts and seed 42.
The starting length scale is 50 m, with broad numerical bounds of 5–3000 m.
These are model settings, not poor-signal or coverage thresholds.

Repeated wardrive samples, observations of multiple access points, and sessions
can be correlated. Dividing by count assumes independent errors and may overstate
the benefit of repeats. The residual noise and separate sampling panels help
expose this limitation, but do not calibrate the uncertainty. No independent
held-out-route calibration has been performed.

## Interpreting the four panels

1. **Predicted mean:** black dots locate observed cell centres. Colours fade toward
   grey as the GP loses spatial support. The opacity is the fractional reduction
   of spatial variance from its prior: `1 - latent_variance / prior_variance`.
   This is a visualization of model support, not a probability. Full means are
   retained in the prediction table even when visually faded.
2. **Prediction standard deviation:** includes spatial posterior variance and the
   fitted residual noise. It excludes extra measurement noise for a future raw
   reading, whose count is unknown. Brighter areas are less certain.
3. **Actual sampling:** marker size and colour show observed reading_count. Small
   dark dots indicate singletons. This is evidence about sampling, not a second
   prediction map.
4. **Distance to observations:** distance to the nearest original GPS observation,
   computed separately for each network. This does not depend on the GP kernel.

The uncertainty, count, and distance panels use common scales across networks.
Signal-mean colour scales remain separate. Dashed lines mark the user-requested
x=400–1150 m diagnostic band. The entire band is not empty: WiFi has 11 cells/33
readings there, and cellular has 142 cells/152 readings.

The report compares median SD within 10 m of observations versus at least 100 m
away. These are diagnostic distance bins, not quality thresholds or masks.

## Outputs

- `data/processed/gpr_predictions.parquet`: predicted mean, prediction SD,
  latent spatial SD, nearest-observation distance, actual reading count in the
  parent 10 m cell, coordinates, display opacity, and `data_status=predicted`.
  Parent-cell counts repeat across four 5 m children; do not sum them as samples.
- `data/processed/gpr_training_cells.parquet`: every observed cell's
  mean and count, within-cell variance (null for singletons), assigned mean-noise
  variance, and fitted residual/effective training-noise variance.
- `outputs/models/gpr_wifi.joblib` and `gpr_cellular.joblib`: fitted estimators,
  target normalization, and grid geometry, for reproducing predictions.
- `outputs/models/gpr_metadata.json`: kernel settings, fitted values, optimizer
  warnings, and uncertainty definitions.
- `outputs/plots/wifi_signal_uncertainty.png` and
  `cellular_signal_uncertainty.png`: the four-panel diagnostics.
- Fitted statistics and numerical verification results are consolidated below.

No poor-signal thresholds, clusters, or dead-zone classifications are applied in
Step 3. Smooth posterior means can suppress extreme observed values; absence of
a low posterior mean is not proof of reliable connectivity.

## Final fitted statistics

Full-precision statistics from the final observed-data fit:

| Metric | WiFi | Cellular |
|---|---:|---:|
| `training_cells` | 218 | 556 |
| `readings` | 2087 | 994 |
| `single_reading_cells` | 25 | 338 |
| `mean_readings_per_cell` | 9.573394495412844 | 1.7877697841726619 |
| `gap_observed_cells` | 11 | 142 |
| `gap_readings` | 33 | 152 |
| `length_scale_m` | 58.45859601165546 | 85.86022793684266 |
| `pooled_within_cell_sd_dbm` | 8.344721523020443 | 4.452137693598764 |
| `fitted_residual_sd_dbm` | 6.325771448625755 | 2.025542333036973 |
| `prior_prediction_sd_dbm` | 10.768972336816688 | 12.61920077027385 |
| `prediction_points` | 38340 | 38340 |
| `predicted_min_dbm` | -82.89735784948653 | -118.11678787929708 |
| `predicted_max_dbm` | -51.48733454808486 | -63.65537439126177 |
| `near_10m_median_sd_dbm` | 7.334416681574201 | 3.234171426360641 |
| `far_100m_median_sd_dbm` | 10.767643853836422 | 12.29334205308934 |
| `gap_median_sd_dbm` | 10.757634162415465 | 10.008807552649033 |
| `gap_median_nearest_observation_m` | 146.7989903272059 | 72.03518928292573 |

The fitted kernels, target offsets/scales, seed, optimizer restarts, warnings,
and log marginal likelihoods remain in `outputs/models/gpr_metadata.json`.
Both models used seed 42 and two restarts, with no optimizer warnings.
The prediction rectangle retains less than 10 m of Step 2 padding. Cells pool
access points and sessions; they do not measure throughput or guarantee connectivity.

## Final numerical verification

- PASS wifi: count weights, posterior equations/units, support distances, and increasing uncertainty away from data.
- PASS cellular: count weights, posterior equations/units, support distances, and increasing uncertainty away from data.
- PASS: original Step 2 means/counts retained; shared complete 5 m grid; all 76,680 predictions finite and labelled predicted.
