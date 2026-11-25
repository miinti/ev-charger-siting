# EV Go Brrr: project context for anyone (or any Claude) working with this folder

Read this first, then `README.md` (file list), `data_dictionary_v1.csv` (every column) and `ASSUMPTIONS.md` (every decision; codes like A4 or D3 used throughout point there).

## The project

The project compares three ways of siting **public 4-wheeler EV charging stations** in **NCT Delhi**, run on one shared ward-level dataset and scored on common metrics:
1. **Grid-based zoning.** 3 km × 3 km cells; one station per cell with ≥1% commercial/industrial land (ICCT Haryana method; Vansola et al. 2023). Sensitivity: 2 km cells; thresholds 1–30%.
2. **Demand-weighted K-means.** Ward demand points weighted by EV demand.
3. **MCLP (Maximal Covering Location Problem).** An integer program that places p stations to maximise the demand covered within a radius.

This folder is the **finished data stage**. The models are still to be built or rebuilt on top of it.

## Agreed settings (do not change silently: they are team decisions)

| Setting | Value | Ref |
|---|---|---|
| Study area | 250 MCD wards (2022 delimitation), 1,393 km². **NDMC + Delhi Cantonment excluded** | A2, A3 |
| CRS | **EPSG:32643** (UTM 43N, metres) for all geometry work | |
| Demand points | one per ward: `cx_utm`, `cy_utm` in `delhi_ev_master_wards_v1.csv` | M1 |
| Demand weight | `demand_w` (= `ev_4w_demand`: VAHAN EV cars + e-taxis). `population` is kept for a later check | D2 |
| Station budget | **104** for all three methods (= grid stations on this study area). Sensitivity 50 / 104 / 157 | D1 |
| K-means k | 104. The silhouette sweep is a **diagnostic only** (it favours a few big clusters) | D1 |
| MCLP p / radius | p = 104, radius **2,100 m straight-line**. Radius sensitivity proposed: 1,500 / 2,100 / 3,000 m (**not yet agreed**) | D1 |
| MCLP candidate sites | `model_inputs/candidates_v1.csv`, `grid_km == 3` (206 sites). The 2 km set (428) is for sensitivity and **for all road-distance runs** | M1, M2 |
| Road distances | Precomputed ward → site matrices in `model_inputs/`. A 2.1 km straight line ≈ 3 km by road (median detour 1.42) | R1 |
| Equity indicator | `sc_share` (Scheduled Caste share). **Income is flat** in every ward (`income_pci_is_flat`), so don't use it for equity | A6, A7 |
| Scenario A (greenfield) | Place 104 stations from scratch. Existing chargers are used only for scoring | D3 |
| Scenario B (existing) | The 149 chargers with `scenario_b_fixed == True` count as already open, and each method adds up to 104 new stations | D3 |

### Scenario B, per method
- **Grid:** drop cells with `n_existing_4w > 0` (in `grid_cells_3km`).
- **MCLP:** add the 149 sites as facilities fixed open. Their distances are in `dist_road_ward_exist4w_v1.csv`; straight-line distances come from x/y.
- **K-means:** the 149 sites are fixed centres; only the free centres move. Exact method not yet chosen.

## How each method reads the data

- **Grid:**
  - Layers `study_area`, `grid_cells_3km` (`share_ci`, `grid_candidate_1pct`, `n_existing_4w`) and `candidates_3km` from `delhi_ev_gis_v1.gpkg`.
  - Station location = the cell's candidate point. Candidates are moved inside the study area where the cell centre falls outside (`moved_in_area`).
  - The rule gives 104 stations at 3 km and 1%; reproduce that as a sanity check.
- **K-means:**
  - Use `cx_utm`, `cy_utm`, weighted by `demand_w` (`sample_weight` in scikit-learn).
  - Centres can land anywhere, including the excluded NDMC hole or outside Delhi. Move any such centre to the nearest point inside `study_area`, and record that as an assumption.
- **MCLP:**
  - Use PuLP or OR-Tools.
  - Coverage sets: ward i is covered by site j if d_ij ≤ R. Use straight-line distance from the x/y columns, or the road matrices.
  - Maximise Σ demand_w × covered, subject to Σ open = p.

## Evaluation metrics (step 4, shared)

Measure each of these for every method and scenario:
- % of `demand_w` (and of population) within R of a station;
- mean and max distance from ward point to nearest station;
- number of stations;
- overlap with existing chargers, both all chargers and confirmed 4W;
- spatial agreement between methods (e.g. distance from each station to the nearest station of another method);
- equity: coverage and distance compared across `sc_share` groups (e.g. quintiles).

Baselines before any new stations are already in the master table: `covered_4w_euclid_2100m` covers 68.5% of demand and `covered_4w_road_2100m` covers 37.1%.

## Working conventions

- **Notebook style** (copy the existing grid notebook `ev_grid_baseline_updated.ipynb`): config cell → data contract table → loading → model → sensitivity → export.
- **Station output format:** export stations as CSV + GeoJSON, one row per station. Proposed common columns: `method`, `scenario`, `budget`, `station_id`, `x`, `y`, `lon`, `lat`, `cand_id` (if from a candidate), `is_existing_fixed`. Agree on this with the team before step 4.
- **Never overwrite** data or results; write a new version (`_v2`, ...).
- **Record every new assumption** so it can go into the report's limitations section. Use the same style and codes as `ASSUMPTIONS.md`, and add new ones with new codes.
- Explain findings before changing anything; decisions are the team's.

## Pitfalls

- **Join key:** `ward_no` (1–250). Ward names aren't guaranteed unique-safe.
- **`is_4w` values:** 1 = 4W, 0 = 2W/3W, NULL = unknown. It reads back as float with NaN in geopandas.
- **Road matrix NaN** means more than 25 km apart. Treat it as "not covered", not as zero.
- **Matrix ids:** road matrix columns are `cand_id` (e.g. `g3_57`) or `c<charger_id>`; rows are indexed by `ward_no`.
- **Demand follows RTO zones, not population** (correlation 0.26). The 9 Burari (DL12) wards get very high demand. This is an accepted limitation (A4); watch for methods clustering there, and compare with a population-weighted run.
- **Only 149 of 1,404 chargers are confirmed 4W.** "Already served" counts that use all chargers overstate 4W coverage (A1).
- **Census 2011 population; patchy OSM land use** (median 47% of a ward's area has any land-use tag, F1). `osm_lu_*` columns are reference only; the models use `ci_share`.
- **Road distances to arbitrary points** (e.g. K-means centres) need the network in `delhi_road_network_v1.gpkg`. Build a directed graph u→v (plus v→u unless `oneway` is yes/true/1; reverse only if -1), weighted by `length_m`. Don't use pyrosm's `to_graph()`, which dropped ~65% of edge endpoints (R1).
- **Libraries:** geopandas, pandas, numpy, scipy, scikit-learn, networkx; PuLP for MCLP (`pip install pulp`).

## Still open (needs a team decision)

- MCLP radius sensitivity values (proposed 1,500 / 2,100 / 3,000 m).
- K-means Scenario B method (how centres are held fixed).
- Common station output schema (proposal above).
- The grid notebook must be re-pointed to this folder. Its current version uses the old 272-ward boundary and fills the NDMC hole.
