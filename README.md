# EV charger siting in Delhi

Where should public four-wheeler EV charging stations go in Delhi? This project compares three siting methods on the
same data and the same number of stations (104):

| Method | Tradition | What it optimises |
| --- | --- | --- |
| Grid (Ministry of Power 3 km rule, ICCT method) | Policy rule | Nothing beyond the rule: one station per 3 km cell with at least 1% commercial/industrial land |
| Weighted K-means | Machine learning | Shortest (squared) distance from demand to its nearest station |
| MCLP (Maximal Covering Location Problem) | Optimisation | Most demand within 2.1 km of a station |

Study area: the 250 MCD wards of Delhi (2022 boundaries, 1,393 km²), excluding NDMC and Delhi Cantonment.
All geometry is in EPSG:32643 (UTM 43N, metres).

## Main result

At 104 stations, demand-based siting puts 94–99% of estimated demand within 2.1 km of a station, against 85% for the
grid rule. Between K-means and MCLP there is no overall winner: K-means gives the shortest average distance; MCLP the
widest coverage when it has enough candidate sites.

| Layout (104 stations) | Demand within 2.1 km | Mean distance |
| --- | --- | --- |
| Grid, 3 km | 85.0% | 1,450 m |
| K-means | 95.1% | 1,141 m |
| MCLP, 3 km candidate sites | 94.3% | 1,258 m |
| MCLP, 1 km candidate sites | 98.8% | 1,335 m |
| Existing confirmed 4W chargers (98) | 65.8% | 2,148 m |

## Demand

Each 1 km cell gets a weight (all weights sum to 1,000):

- 60% **home demand**: cell population (Census 2011, spread over mapped residential land) × the ward's VAHAN EV-4W
  registrations per resident (2020–26, by RTO zone);
- 40% **destination demand**: offices, malls, hospitals, hotels, parking, commercial/industrial land, road density,
  nearness to arterials, metro and bus terminals (OpenStreetMap), as 0–1 rank scores.

A 50-run Monte Carlo test (λ ~ U(0.3, 0.8), θ ~ Dirichlet, ±30% noise) moves coverage by at most about 3 points.

## Files

| Path | What it is |
| --- | --- |
| `ev_siting_final.ipynb` | **The current pipeline.** All models, Scenario A and B, sensitivity, extensions, set cover, exports |
| `demand_weights.ipynb` | Builds the 1 km demand layer from OSM and the ward data |
| `demand_weights_mc.py` | Demand-weight formula and Monte Carlo draws |
| `siting_lib.py` | Shared functions (used by the older notebooks and the website) |
| `Final Data/` | Team data package: wards, chargers, candidate sites, VAHAN-based demand, assumptions log |
| `data/` | The 1 km (and 500 m) demand layers |
| `outputs/final/` | Tables, maps and a GeoPackage of every layout from the current pipeline |
| `website/` | Interactive explorer (`index.html` + `explorer_data.json`; `precompute_layouts.py` rebuilds the data) |
| `ev_kmeans_model_v2.ipynb`, `ev_mclp_model.ipynb`, `ev_evaluation_and_extensions.ipynb`, `ev_grid_baseline_updated.ipynb`, `ev_kmeans_model.ipynb` | Earlier versions, kept for the record (marked superseded) |

## Running it

```bash
python3 -m venv .venv
.venv/bin/pip install geopandas pyogrio scikit-learn scipy matplotlib nbformat nbclient ipykernel tabulate mapclassify
```

Open `ev_siting_final.ipynb` in VS Code (kernel: `.venv`) and run all cells, about 35 minutes. Settings are in the
first code cell: `weight="ev"` (main) or `"team"` (population in place of EV registrations), solver time limits, budgets.

**Not in this repository:** `Final Data/delhi_road_network_v1.gpkg` (220 MB, over GitHub's file limit). It is the
drivable road network from OpenStreetMap, used only for road-distance runs. Without it, set `run_road=False` in the
notebook settings; everything else runs.

## Main assumptions

No observed charging data exists, so demand is an estimate built from proxies. EV registrations are known per RTO zone
only; Census population is from 2011; OSM land use and parking are incomplete; distances are straight-line in the
main runs (road distance is a check); the 104-station budget comes from the grid rule, not from cost or need.
Every assumption and team decision is logged in `Final Data/ASSUMPTIONS.md`.
