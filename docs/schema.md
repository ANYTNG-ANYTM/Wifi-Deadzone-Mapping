# Dataset Schema — merged_readings.parquet

## Summary

- **Total rows:** 3,081 (after cleaning; 7 campus-SSID rows dropped for WiFi GPS accuracy >30 m; 13,733 non-campus SSID rows filtered separately)
- **WiFi readings:** 2,087 (from WiGLE, filtered to `IITG_CONNECT` and `eduroam` only)
- **Cellular readings:** 994 (from Network Cell Info Lite, Jio)
- **Collection window:** 2026-09-26, two passes (afternoon ~1-1:30pm, evening ~6-6:30pm local IST)
- **Timestamps are stored in UTC** (device system time as logged by both apps). Local IST = UTC + 5:30 — subtract 5:30 when displaying human-readable local times in any report or slide.

## Columns

| Column | Type | Description |
|---|---|---|
| `timestamp` | datetime (UTC) | When the reading was captured |
| `lat`, `lon` | float | GPS coordinates |
| `route_id` | string | Which walked route/segment — see route list below |
| `session` | string | Time-of-day label, e.g. `afternoon`, `evening`, `evening_to`, `evening_fro` |
| `network_type` | string | `wifi` or `cellular` |
| `carrier_or_ssid` | string | `IITG_CONNECT`, `eduroam`, or `Jio` |
| `signal_strength_dbm` | float | Signal strength. **Note: WiFi and cellular dBm scales are NOT directly comparable** — see below |
| `latency_ms` | float | Currently all null — no manual Speedtest checkpoints were merged in this round |
| `method` | string | `wardrive_continuous` for all rows in this dataset |
| `data_status` | string | `observed` for all rows — no synthetic data used anywhere in this dataset |
| `accuracy_m` | float | GPS accuracy in meters (WiFi rows only; null for cellular — Network Cell Info Lite export has no accuracy field) |
| `source_file` | string | Original raw filename, for traceability |

## Signal strength reference ranges (IMPORTANT — different scales per network)

| network_type | min | 25th pct | median | 75th pct | max | mean |
|---|---|---|---|---|---|---|
| wifi | -90 | -83 | -77 | -69 | -22 | -74.5 |
| cellular | -118 | -101 | -92 | -83 | -58 | -91.5 |

WiFi RSSI and cellular (5G) signal dBm are on different practical scales — a WiFi reading 
of -85 is quite poor, while a cellular reading of -85 is roughly average for this dataset. 
**Any "poor signal" threshold must be defined separately per network_type** — do not apply 
one universal dBm cutoff across both.

## Route / session / network_type breakdown

| route_id | session | network_type | rows |
|---|---|---|---|
| academic_complex | evening | cellular | 116 |
| barak | afternoon | cellular | 200 |
| barak | afternoon | wifi | 231 |
| hostel_academic_loop | evening | wifi | 1,702 |
| route1 (hostel→academic) | evening_to | cellular | 110 |
| route2 (academic→hostel) | evening_fro | cellular | 200 |
| umiam | afternoon | cellular | 200 |
| umiam | afternoon | wifi | 103 |
| umiam | evening | cellular | 168 |
| umiam | evening | wifi | 51 |

## Known gaps (see docs/collection_log.md for full narrative)

- No Barak evening session — time-of-day contrast only available for Umiam and the hostel-academic loop.
- Academic complex has a single evening snapshot only (weekend/holiday, no weekday comparison).
- Academic complex has no dedicated WiFi file — its WiFi points are embedded in `hostel_academic_loop`.
- `latency_ms` is entirely null in this dataset — no manual checkpoint speed tests were merged.

## Cleaning audit

The ten exports contain 16,821 rows. Sequential filtering removes 13,733
non-campus SSID rows and seven WiFi rows with GPS accuracy greater than 30 m;
zero retained-campus/cellular rows have invalid latitude, longitude, or signal.
The resulting 3,081 observations retain the route/session breakdown above.

Per-file counts (sequential filters):

```text
                      source_file  loaded  other_ssid  accuracy_over_30m  invalid_values  kept
        Barak_1_30pmWigleWifi.csv    2779        2541                  7               0   231
hostel_and_academic_WigleWifi.csv    7989        6287                  0               0  1702
           Umiam_1pmWigleWifi.csv    3123        3020                  0               0   103
      Umiam_evening_WigleWifi.csv    1936        1885                  0               0    51
             Academic_Complex.csv     116           0                  0               0   116
           Academic_to_Hostel.csv     200           0                  0               0   200
                 Barak_1_30pm.csv     200           0                  0               0   200
           Hostel_to_Academic.csv     110           0                  0               0   110
                 Umaim_6_30pm.csv     168           0                  0               0   168
                    Umiam_1pm.csv     200           0                  0               0   200
```

## Observed grid statistics

The grid is 135 columns by 71 rows at 10 m spacing, with southwest origin
(latitude, longitude) = (26.18381300, 91.68948224). Empty cells are omitted;
routes and sessions are pooled while networks remain separate. There are 774
cell/network rows, including 150 geographic cells containing both networks.

```text
              occupied_cells  readings  min_readings_per_cell  median_readings_per_cell  max_readings_per_cell  weakest_cell_dbm  strongest_cell_dbm
network_type                                                                                                                                        
cellular                 556       994                      1                      1.00                      9           -118.00              -58.00
wifi                     218      2087                      1                      5.00                     79            -89.00              -30.00
```

The first-ten-row preview is recoverable from `data/processed/gridded_readings.parquet`;
the coverage plot is `outputs/plots/grid_coverage.png`.

`classified_cells.parquet` contains 76,680 rows (one per network per 5 m prediction cell) read by the map; `classified_grid.parquet` contains 38,340 paired-network rows used to verify joint statuses, context, and ranked-zone membership independently. Both are protected outputs.
