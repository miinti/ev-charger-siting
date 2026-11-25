# Final Data (v1, 2026-11-21)

This is everything the grid, K-means and MCLP models read, plus a GIS file for maps.
- **Coordinate system:** EPSG:32643 (UTM 43N, metres) everywhere, except `lon`/`lat`.
- **Data dictionary:** every column is described in `data_dictionary_v1.csv`.
- **Decisions and assumptions:** codes like A4 or D3 refer to `ASSUMPTIONS.md` in this folder.
- **Start with `CLAUDE.md`:** the project context, agreed settings, pitfalls and open items. If you use Claude, it reads this file automatically.

## Contents

| File | What it is |
|---|---|
| **`CLAUDE.md`** | **Read first.** Project context: the three methods, agreed settings, scenarios, evaluation metrics, conventions, pitfalls, open decisions |
| `ASSUMPTIONS.md` | Every data and modelling decision with its reasoning (a snapshot of the project's master log) |
| **`delhi_ev_master_wards_v1.csv`** | **The master dataset.** One row per ward (250 rows, 58 columns, no missing values): population, SC share, EV demand, existing chargers and their coverage, land use, income, and the model demand point |
| **`delhi_ev_gis_v1.gpkg`** | **The GIS file.** 14 layers, all described below. Open it in QGIS by dragging it in, or via *Layer → Add Vector Layer* |
| `delhi_road_network_v1.gpkg` | The full drivable road network (803 k road segments, 700 k junction points; 230 MB) used for road distances |
| `model_inputs/candidates_v1.csv` | MCLP candidate sites and grid-model station points: 206 on the 3 km grid, 428 on the 2 km grid |
| `model_inputs/existing_chargers_v1.csv` | All 1,404 chargers; `scenario_b_fixed` marks the 149 confirmed 4W sites |
| `model_inputs/dist_road_ward_cand3_v1.csv` | Road distance in metres, ward (rows) → 3 km candidate (columns) |
| `model_inputs/dist_road_ward_cand2_v1.csv` | Road distance in metres, ward → 2 km candidate |
| `model_inputs/dist_road_ward_exist4w_v1.csv` | Road distance in metres, ward → confirmed 4W site |
| `model_inputs/model_parameters_v1.json` | Budget, radius, scenarios, demand weight and other agreed settings |
| `data_dictionary_v1.csv` | Every column of every table and layer: description, unit, source and decision code |
| `overview_v1.png` | A quick visual check of the main layers |

## Layers in `delhi_ev_gis_v1.gpkg`

| Layer | Count | Use |
|---|---|---|
| `wards` | 250 polygons | Every master column; use it for choropleth maps (shading wards by a value) |
| `ward_demand_points` | 250 points | Where each ward's demand sits for K-means and MCLP |
| `study_area` | 1 | The 250 MCD wards (1,393 km²); grid-model boundary |
| `excluded_ndmc_cantonment` | 1 | The 84 km² area left out of the study |
| `rto_zones` / `rto_offices` | 12 / 12 | How VAHAN cars were split across wards |
| `existing_chargers` | 1,404 points | `is_4w` (1/0/NULL) and `scenario_b_fixed` |
| `candidates_3km` / `candidates_2km` | 206 / 428 points | Candidate sites. Orange in the overview = moved inside the study area |
| `grid_cells_3km` / `grid_cells_2km` | 206 / 428 polygons | Grid-model inputs: `share_ci`, `grid_candidate_1pct`, `n_existing_4w` |
| `landuse_ci` | 725 polygons | Commercial, retail and industrial land, **the land use the models use** |
| `landuse_osm_all` | 7,342 polygons | **All OSM land-use zones** (53 classes in 12 groups, `landuse` + `lu_group`). Reference only |
| `roads_major` | 125 k lines | Tertiary roads and above, for display |

## How each model uses it

- **Grid model:**
  - Study area from `study_area`.
  - Cells and their `share_ci` from `grid_cells_3km`.
  - A cell gets a station when `grid_candidate_1pct` is true (share_ci ≥ 1%), placed at the cell's point in `candidates_3km`.
  - Scenario B: drop cells with `n_existing_4w > 0`.
- **K-means:**
  - Points: `cx_utm`, `cy_utm`. Weights: `demand_w`. k = 104.
  - Scenario B: the 149 `scenario_b_fixed` chargers act as fixed centres.
- **MCLP:**
  - Demand: `cx_utm`, `cy_utm` weighted by `demand_w`.
  - Sites: `candidates_v1.csv` with `grid_km == 3`. p = 104, radius 2,100 m, straight-line distance.
  - Road-distance run: use `grid_km == 2` and `dist_road_ward_cand2_v1.csv`.
  - Scenario B: add the `scenario_b_fixed` sites as facilities that are always open (`dist_road_ward_exist4w_v1.csv`).
- **Evaluation:** coverage, distance, overlap with existing chargers, and equity (`sc_share`). The starting point before any new stations is in `covered_4w_euclid_2100m` / `covered_4w_road_2100m`.

## Rebuild

You don't need to rebuild to use this folder. It is complete on its own. Rebuilding needs the full project (the `Parent Data/` and `Claude Data/` folders, which aren't included here). Run these in order from `IMP CS/`. Inputs come from `Parent Data/`, intermediate files go to `Claude Data/`, and the last two scripts write this folder. `CLAUDE.md` is maintained by hand and isn't regenerated.

```
python3 "Claude Data/compile_master_v1.py"
python3 "Claude Data/compile_master_v2.py"
python3 "Claude Data/build_road_network_v1.py"
python3 "Claude Data/compile_model_inputs_v3.py"
python3 "Claude Data/compile_model_inputs_v4.py"
python3 "Claude Data/compile_final_v1.py"
python3 "Claude Data/write_data_dictionary_v1.py"
```
`compile_final_v1.py` refuses to run if `delhi_ev_gis_v1.gpkg` already exists. Bump the version number rather than overwriting.
