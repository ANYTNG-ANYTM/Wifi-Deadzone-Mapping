# Step 4: expected service, uncertainty, and priorities

Campus WiFi (IITG_CONNECT and eduroam) serves indoor building networks. WiFi is
not expected along the outdoor connecting path between hostel and academic
clusters. Missing WiFi there is normal, not a campus connectivity problem.
The approved -83 dBm cutoff and zero poor WiFi prediction cells are retained as
requested. No further WiFi model investigation or threshold adjustment is made.

## Approved classification

Apply these separately to each network, in order:

1. Uncertain if prediction SD exceeds its approved cutoff **or** distance to the
   nearest actual observation of that network exceeds 50 m.
2. Otherwise poor if the predicted mean is at or below the approved signal cutoff.
3. Otherwise OK.

| Network | Poor mean cutoff (dBm) | SD cutoff (dBm) |
|---|---:|---:|
| WiFi | -83 | 10.767799579805995 |
| Cellular | -101 | 11.763522269946332 |

The cellular SD cutoff is the full-precision value previously displayed as
11.76 dBm. Predictions remain predictions: poor meets these model/support rules,
not a direct observation of a failed call or connection. Thresholds are frozen in
the implementation and recorded in the final approved-settings section below; the executable source is
`approved_settings()` in `scripts/04_clustering_ranking.py`.

## Geographic context proxy

The coverage plot did not provide indoor/outdoor cluster labels or building
footprints. The new grouping uses proximity to manifest-labelled reference
observations:

- Hostel reference points: `route_id` is `barak` or `umiam`, from both networks.
- Academic reference points: `route_id` is `academic_complex`.
- Within 50 m of those points: the nearest building-cluster proxy.
- Otherwise: outdoor / outside the building-cluster proxy.

The mixed hostel-academic WiFi loop and cellular transit routes do not seed
building membership, because they also contain outdoor corridor observations.
This 50 m radius makes the classification reproducible with existing data. It
does not establish that a phone or predicted point is physically indoors.
The outdoor class includes the connecting corridor, as well as peripheral
points outside the reference neighbourhoods. Small fragments at the proxy edges
are retained and their cell counts shown, rather than being silently removed.

## Clustering and ranking

First, DBSCAN groups supported poor cells independently per network and context.
On the 5 m prediction grid, `eps = sqrt(2) * 5 m + 0.000001 m` and
`min_samples = 1` implement eight-neighbour connectivity. Edge- or corner-touching
poor cells belong together; uncertain or OK gaps are not bridged. No minimum
zone area is imposed. Zone areas describe the model's poor region, not surveyed
land area or independent observations.

The ranked zones partition actionable cells by context and priority category:

| Tier | Category | Reason |
|---|---|---|
| 1 | Outdoor cellular poor | Cellular is the expected service on the outdoor walk. |
| 1 | Both networks poor in a building proxy | Neither expected service meets the signal criterion. |
| 2 | WiFi poor in a building proxy | Campus WiFi is the primary expected service there. |
| 3 | Cellular poor in a building proxy | Cellular issue where WiFi service is also expected. |

Outdoor rankings depend only on cellular status, signal severity, area, and
cellular uncertainty. Outdoor WiFi status never affects eligibility or rank.
Within each tier, sort by mean dB deficit below the relevant signal cutoff
(largest first), then zone area (largest first), then mean SD (smallest first),
then stable zone ID. This explicit severity-first choice can put small poor
fragments ahead of larger, less severe regions; always read rank with cell count.

`true_dead_zone` can be true only in a building-cluster proxy with both networks
independently poor at the same cells. Outdoors it is false and
`true_dead_zone_applicable` is false; this means not applicable, not that there is
a WiFi fallback. An uncertain counterpart network remains unknown, never OK.
Mixed counterpart statuses are reported with counts in the zone CSV. Every cell
contributing to a zone's ranked service must be poor, never uncertain.

Zone marker coordinates are the member cell nearest the zone centroid, so the
marker lies within the zone even for concave shapes. `avg_uncertainty` uses the
ranked service's SD; for both-poor zones it would average the larger of the two
SDs at each cell. All current ranked zones are cellular.

## Uncertain cells and Step 5

All uncertain cells remain in `classified_cells.parquet` for a distinct grey
map layer, including outdoor WiFi. Uncertain expected service is saved separately
as unranked needs-more-data: cellular everywhere and WiFi in building proxies.
Outdoor uncertain WiFi does not trigger a survey recommendation, since that
service is not expected. Neither uncertain cells nor unknown fallback claims
inflate the poor-zone rankings.

The final interactive map is implemented in Step 5; see `docs/map_documentation.md`.

## Files and commands

```powershell
.\.venv\Scripts\python.exe scripts/04_clustering_ranking.py
.\.venv\Scripts\python.exe scripts/dev/verify_step4.py
```

- `data/processed/ranked_dead_zones.parquet` (canonical) and
  `outputs/ranked_dead_zones.csv` (independent judge-readable export): ranked table plus context, extent,
  signal, support, and counterpart-status details.
- `data/processed/classified_cells.parquet`: separate network statuses, context,
  uncertainty reasons, expected service, and per-network/ranked zone memberships.
- `data/processed/classified_grid.parquet`: paired network statuses and
  building-only true-dead-zone logic at each shared prediction cell.
- `data/processed/needs_more_data.parquet`: unranked uncertain expected service.
- Status counts, survey needs, and final verification are consolidated below;
  the full zone review table remains in the ranked CSV.
- `outputs/plots/zone_status_map.png`: separate status panels and the
  geographic context proxy, with priority numbers marking the zones.

## Threshold derivation and historical preview

The following historical records preserve the complete pre-approval proposal and
preview. Their pending status describes that earlier checkpoint only; the approved
classification above supersedes it. The original both-poor proposal was subsequently
restricted to building proxies. The diagnostic band is x=400?1150 m, inclusive.

### Historical step4_threshold_proposal.json

```json
{
  "approval_status": "pending_user_confirmation",
  "signal_quantile": 0.25,
  "signal_source": "All cleaned observed readings, separately per network; not cell means or predictions",
  "uncertainty_quantile": 0.75,
  "uncertainty_source": "All 38,340 prediction_std_dbm values per network on the full Step 3 grid, before distance filtering",
  "quantile_interpolation": "linear",
  "distance_limit_m": 50.0,
  "proposed_rule_order": [
    "uncertain if prediction_std_dbm > network SD cutoff OR nearest_observation_m > 50",
    "otherwise poor if predicted_mean_dbm <= network signal cutoff",
    "otherwise ok"
  ],
  "true_dead_zone_rule": "Both networks independently have status poor at the same shared grid cell",
  "uncertain_handling": {
    "map": "Keep visible as a distinct grey/hatched category, with network-specific toggles",
    "ranking": "Exclude uncertain cells from poor-zone clustering and priority ranking; retain separately as needs more data",
    "fallback": "An uncertain counterpart network is unknown, never an assumed ok fallback"
  },
  "terminology": "Poor means supported by the agreed model rules, not independently verified connectivity failure",
  "networks": {
    "wifi": {
      "poor_signal_cutoff_dbm": -83.0,
      "uncertainty_sd_cutoff_dbm": 10.767799579805995
    },
    "cellular": {
      "poor_signal_cutoff_dbm": -101.0,
      "uncertainty_sd_cutoff_dbm": 11.763522269946332
    }
  },
  "true_dead_zone_cells_preview": 0
}
```

### Historical step4_threshold_preview.csv

```csv
network_type,observed_signal_p25_dbm,prediction_sd_p75_dbm,distance_limit_m,prediction_cells,sd_flagged,distance_flagged,both_flags,uncertain_preview,uncertain_pct,poor_preview,ok_preview,below_signal_before_uncertainty,poor_mean_but_uncertain,gap_uncertain_cells,gap_cells,gap_uncertain_pct,minimum_predicted_mean_dbm
wifi,-83.0,10.767799579805995,50.0,38340,9585,26035,9585,26035,67.90558163797601,0,12305,0,0,19080,21300,89.5774647887324,-82.89735784948653
cellular,-101.0,11.763522269946332,50.0,38340,9585,20227,9585,20227,52.756911841418884,6068,12045,7198,1130,13625,21300,63.96713615023474,-118.11678787929708
```

### Historical step4_threshold_preview.txt

```text
STEP 4 THRESHOLD PROPOSAL - NOT APPROVED OR APPLIED
Signal cutoff: 25th percentile of cleaned actual readings, per network.
SD cutoff: 75th percentile of all prediction_std_dbm values, per network, before distance filtering.
Quantiles use linear interpolation. Full precision is retained in the proposal JSON.
Uncertain: SD > cutoff OR distance to nearest actual same-network observation > 50 m.
Otherwise poor: predicted mean <= signal cutoff. Otherwise ok.
Uncertain cells remain visible but are excluded from ranked poor zones.

network_type                            wifi     cellular
observed_signal_p25_dbm           -83.000000  -101.000000
prediction_sd_p75_dbm              10.767800    11.763522
distance_limit_m                   50.000000    50.000000
prediction_cells                38340.000000 38340.000000
sd_flagged                       9585.000000  9585.000000
distance_flagged                26035.000000 20227.000000
both_flags                       9585.000000  9585.000000
uncertain_preview               26035.000000 20227.000000
uncertain_pct                      67.905582    52.756912
poor_preview                        0.000000  6068.000000
ok_preview                      12305.000000 12045.000000
below_signal_before_uncertainty     0.000000  7198.000000
poor_mean_but_uncertain             0.000000  1130.000000
gap_uncertain_cells             19080.000000 13625.000000
gap_cells                       21300.000000 21300.000000
gap_uncertain_pct                  89.577465    63.967136
minimum_predicted_mean_dbm        -82.897358  -118.116788

Both-networks-poor cell preview: 0
wifi: minimum predicted mean is -82.897358 dBm, above its -83 dBm signal cutoff; no poor cells would result.
Smooth model means can suppress observed extremes; absence of poor cells is not evidence of reliable coverage.
Poor/ok are model classifications, not independently verified connectivity outcomes.

No classified-cell outputs, clustering, ranking, or final-map changes have been made.
```

## Final approved settings

This approved record supersedes the historical pending proposal above. Step 5
and the verifier use the same frozen `approved_settings()` function directly.

```json
{
  "approval_status": "approved_by_user",
  "networks": {
    "wifi": {
      "poor_signal_cutoff_dbm": -83.0,
      "uncertainty_sd_cutoff_dbm": 10.767799579805995
    },
    "cellular": {
      "poor_signal_cutoff_dbm": -101.0,
      "uncertainty_sd_cutoff_dbm": 11.763522269946332
    }
  },
  "distance_limit_m": 50.0,
  "precision_note": "Retain original percentile precision; cellular 11.76 dBm was the rounded approved display value.",
  "status_order": "uncertain if SD > cutoff or distance > 50; otherwise poor if mean <= signal cutoff; otherwise ok",
  "building_proxy": {
    "reference_routes": {
      "hostel_cluster": [
        "barak",
        "umiam"
      ],
      "academic_cluster": [
        "academic_complex"
      ]
    },
    "radius_m": 50.0,
    "interpretation": "Proximity to observed building-cluster routes, not measured indoor location"
  },
  "dbscan": {
    "eps_m": 7.071068811865476,
    "min_samples": 1,
    "connectivity": "8-neighbour 5 m grid; no minimum-area exclusion"
  },
  "priority_tiers": {
    "building_both_poor": 1,
    "outdoor_cellular_poor": 1,
    "building_wifi_poor": 2,
    "building_cellular_poor": 3
  },
  "within_tier_order": "Mean deficit below relevant signal cutoff descending, area descending, relevant mean SD ascending, stable zone ID",
  "true_dead_zone_rule": "Both networks poor AND within a building-cluster proxy; not applicable outdoors",
  "uncertain_handling": "Exclude uncertain network cells from poor clusters; retain visibly and list uncertain expected service as needs more data without rank",
  "wifi_context": "IITG_CONNECT and eduroam are indoor building networks. Outdoor corridor WiFi absence is expected and is not a problem to investigate.",
  "source_prediction_file": "data/processed/gpr_predictions.parquet"
}
```

## Final status counts

| area_context | network_type | ok | poor | uncertain |
|---|---|---|---|---|
| academic_cluster | cellular | 942 | 3116 | 0 |
| academic_cluster | wifi | 3943 | 0 | 115 |
| hostel_cluster | cellular | 2116 | 159 | 0 |
| hostel_cluster | wifi | 2229 | 0 | 46 |
| outdoor | cellular | 8987 | 2793 | 20227 |
| outdoor | wifi | 6133 | 0 | 25874 |

## Unranked needs-more-data counts

| area_context | network_type | needs_more_data_cells |
|---|---|---|
| academic_cluster | wifi | 115 |
| hostel_cluster | wifi | 46 |
| outdoor | cellular | 20227 |

There are 20,388 uncertain expected-service cells in total. All 6,068 supported
cellular-poor cells form the seven ranked zones; the zone coordinates, priorities,
counts, means, uncertainties, and counterpart statuses from the final review
remain in `outputs/ranked_dead_zones.csv`.

## Final ranking verification

- PASS: all 76,680 predictions preserved and statuses exactly follow approved cutoffs.
- PASS: uncertain network cells excluded from ranked and per-network poor memberships.
- PASS: independent eight-neighbour raster components agree with all DBSCAN zones.
- PASS: all 6,068 cellular-poor cells partitioned into 7 zones; no poor pixels discarded.
- PASS: outdoor rank depends on cellular; true-dead-zone logic is building-only.
- PASS: 20,388 uncertain expected-service cells saved unranked; outdoor WiFi excluded from survey needs.
- PASS: ranking order, zone counts, areas, uncertainty averages, and in-zone marker coordinates verified.
