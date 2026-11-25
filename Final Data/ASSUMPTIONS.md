# Assumptions and limitations log

Running list of decisions and data caveats, for the report's limitations section. Newest at the bottom.

## Decisions

### A1. Existing chargers: keep all 1,404, flag 4W capability (decided 2026-11-21)
- **Decision:** use all 1,404 points in `Data/delhi_ev_chargers_master.geojson` as "existing chargers". Add a flag for whether each one is a 4W site, and report results both ways.
- **Why it matters:** the project's scope is public 4W charging. Matching the master points to `Data/ev_chargers_kaggle_ds.xlsx` (the SwitchDelhi source) within 30 m gives:
  - 149 of 1,322 SwitchDelhi points are 4W sites (`vehicle_type` includes 4W);
  - 1,170 are 2W/3W only (mostly REVOS);
  - 3 have no match;
  - 82 OSM points have no vehicle-type information.
- **Effect:** "already served" and "overlap with existing chargers" metrics overstate 4W coverage when all points are used. For example, the grid baseline's figure of 89 of 102 candidate cells "already served" is an upper bound.
- **Flag definition (to apply in step 2):** `is_4w = True` if within 30 m of a Kaggle row whose `vehicle_type` contains "4W"; `None` (unknown) for OSM points; otherwise `False`.

### A2. Ward layout: 2022 MCD delimitation, 250 wards (decided 2026-11-21)
- **Source:** `Data/delhi_wards_2022.kml` (251 polygons). This supersedes the 272-ward geojson for all ward-level work (C1, C2 no longer apply).
- **Ward 0 dropped:** an unnamed, zero-population 7.4 km² polygon inside the Cantonment.
- **Geometry fixes:** 4 invalid geometries were repaired with `make_valid`.
- **Overlaps:** 117 neighbouring ward pairs overlap, but by a negligible area (<0.01 km²).
- **Population:** `TotalPop` and `SC_Pop` come from the SEC 2022 delimitation, which uses **Census 2011** counts (total 16.42 M). Population is 15 years old and does not reflect growth since 2011, especially in peripheral wards.
- **Still on the old layout:** the grid notebook still builds its boundary from the old 272-ward file. Switch it to the 2022 wards before the final comparison so all three models share one study area.

### A3. NDMC and Delhi Cantonment excluded (decided 2026-11-21)
- The study area is the 250 MCD wards only (1,393 km²). The 84 km² NDMC + Cantonment hole is left out.
- 81 of the 1,404 chargers fall outside the wards (in the hole or beyond the border) and are dropped from ward counts. They are still present in `chargers_flagged_v1.gpkg` for distance metrics.
- **Reason:** no usable ward-level data for these areas.

### A4. VAHAN cars to wards: nearest RTO office, then population share (decided 2026-11-21)
- **Office locations:** `Claude Data/rto_offices_v1.csv`. Each ward is assigned to the RTO whose office is nearest to the ward's interior point.
  - 6 offices are OSM-tagged.
  - 5 are locality centroids from OSM (Lado Sarai, Hari Nagar, Wazirpur, Raja Garden, Burari).
  - DL2 Jam Nagar House is a manual estimate.
- **Rohini merged:** DL11 (Rohini-I) and DL13 (Rohini-II) are merged into one zone because only one Rohini office is in OSM. Merged cars: 5,993.
- **Allocation:** within each zone, the zone's "Cars (LMV)" are split across its wards in proportion to ward population. All 68,322 cars are allocated.
- **Known artefact: demand jumps at zone borders.** Cars per 1,000 people range from 1.3 (DL5, North East) to 12.0 (DL12, Burari) depending only on the zone.
  - DL12's 6,906 cars land on just 9 wards. This likely reflects where dealers register vehicles and how far each RTO's jurisdiction really extends, not where cars actually are.
  - Nearest-office zones are not real RTO jurisdictions.
  - The correlation between ward 4W demand and population is only 0.26, so demand mostly follows RTO zones, not population.
- **DL2 cars:** DL2's 1,301 cars go to the 8 wards nearest its estimated office, because NDMC itself is excluded.
- **Decision (2026-11-21): the artefact is accepted as is; no smoothing.** `ev_4w_demand` is used unchanged in ward_master_v2.
  - Report it as a limitation: the demand surface has step changes at nearest-office zone borders, and the DL12 (Burari) wards are probably over-weighted.
  - Expect K-means and MCLP to place more stations in those wards than population alone would suggest.
  - When interpreting results, compare against a population-weighted run, since `population` is in the same dataset.

### A5. DL52 e-taxis spread in proportion to cars (decided 2026-11-21, provisional)
- The 14,016 DL52 LIGHT PASSENGER VEHICLE registrations are added to each ward in proportion to its allocated cars.
- `ev_4w_demand = ev_cars + ev_taxis` (total 82,338).
- This scales every ward by the same factor (×1.205), so it changes demand totals but not any ward's relative share.

### A6. Income / equity (provisional)
- `income_proxy` is left empty until the proxy data arrives.
- `income_total_flat_inr` (population × ₹4,93,024) is kept for reference only. It has no equity signal.
- `sc_share` (Scheduled Caste share of population, from the ward file) is available now as an interim equity indicator, ranging from 0.00 to 0.69.

### A7. Income proxy: flat Delhi per-capita income (applied in ward_master_v2, 2026-11-21)
- **Source:** `Data/delhi_ward_population_with_proxy_income.xlsx`. It joins 1:1 on ward number with the 2022 KML: all 250 wards, with identical names, population and SC population.
- **No per-ward variation:** `PCI` is ₹4,93,024 for every ward (Delhi state per-capita income). `income_total_inr = population × PCI` is therefore just population multiplied by a constant.
  - **It carries no equity signal.** Any income-based equity metric will show perfect equality by construction.
  - Kept as instructed and labelled a limitation; `income_pci_is_flat = True` in the data marks this.
- **Equity indicator in use:** `sc_share` (Scheduled Caste share of ward population, Census 2011) is the only ward-varying equity indicator available.
- **Redundant file:** `Data/ward_wise_population.csv` is actually an Excel workbook with a `.csv` extension. It is the population table the income file was built from, so it adds nothing.

### R1. Road network (built 2026-11-21, `Claude Data/build_road_network_v1.py`)
- **Source:** the OSM extract (`Data/delhi_osm_chargers.pbf`) read with pyrosm, keeping roads tagged as "driving" and clipped to the study area plus 2 km.
- **Graph:** a directed graph built directly from the edge table.
  - Direction comes from OSM `oneway` tags (yes/true/1 = forward only, -1 = reverse only, otherwise both). Missing or wrong oneway tags in OSM carry through.
  - Weight = segment length in metres. There are no speeds or travel times, so this is distance, not time.
  - pyrosm's own `to_graph()` was not used because it dropped ~65% of edge endpoints in testing.
- **Size:** the largest strongly connected component keeps 700 k of 710 k nodes (98.6%), 26,857 km in total. Inside the study area it keeps 17,677 of 17,766 km (99.5%).
- **Snapping:** ward demand points snap to the nearest network node with a median of 32 m (max 875 m). 3 km grid centroids snap with a median of 82 m (max 1.97 km, an edge cell).
- **Detour factor:** road distance / straight-line distance, measured on 118 ward pairs 1.5–5 km apart: median **1.42** (p10 1.19, p90 1.93).
  - A 2.1 km straight-line radius therefore corresponds to roughly 3 km by road.
  - A 2.1 km road radius corresponds to roughly 1.5 km straight-line.

## Modelling decisions (2026-11-21)

### D1. Station budget: 104 for all three models (revised 2026-11-21, was 102)
- **Revision:** the budget was 102, the grid count on the old filled boundary. On the 2022 study area the grid rule gives 104, so all three models now use **104**.
- K-means k = 104 and MCLP p = 104, matching the grid baseline (3 km grid, 1% threshold).
- **Budget sensitivity:** 50, 104 and 157 (157 = the 2 km grid's count on the 2022 study area; was 165).
- **Scenarios:** where D3 below says 102, read 104.
- The K-means silhouette sweep is reported as a diagnostic only. Silhouette favours a few large, well-separated clusters, not good service coverage.
- Budget sensitivity: 50, 102 and 165 (165 = the 2 km grid's station count).

### D2. Demand weight: `ev_4w_demand`
- K-means and MCLP weight each ward by `ev_4w_demand` (EV cars + spread e-taxis; see A4, A5).
- `population` is held back for a later check of how much the RTO-zone artefact drives the results.

### D3. Two scenarios for comparison
- **Scenario A, greenfield:** place 102 stations from scratch. Existing chargers are not used to place stations; they are used only to score the result (overlap with existing chargers, reported for all chargers and for 4W only).
- **Scenario B, building on what exists:** the **149 confirmed 4W charger sites** count as already open, and each model places up to 102 *new* stations to fill gaps.
  - Grid: candidate cells that already contain a confirmed 4W site are dropped (`drop_covered=True` with 4W chargers only).
  - MCLP: the 149 sites are added as facilities fixed open.
  - K-means: the 149 sites are added as fixed centres, and only the free centres move.
- **Unknown-type chargers excluded from B:** the 82 OSM chargers with unknown type (A1) are not counted as existing in B. Including them is a possible sensitivity run.

### M1. Model input package v3 (built 2026-11-21, `Claude Data/compile_model_inputs_v3.py`)
- **Study area:** the 250 wards dissolved, with interior slivers under 1 km² filled. The NDMC + Cantonment hole is kept (A3). Area 1,393.3 km².
- **Demand points:** one per ward, at a point guaranteed inside the ward. Weight `demand_w = ev_4w_demand` (D2).
  - Large peripheral wards (up to 92 km²) have all their demand at a single point. This is an aggregation limitation.
- **MCLP candidate sites:** centres of the 3 km grid cells that touch the study area (206), plus 2 km cells (428) for sensitivity. These are the same cells the grid model chooses from.
  - 48 of the 206 3 km centres fall outside the study area: 8 in the NDMC hole and 40 beyond the outer border (edge cells with a median of 1.4 km² inside Delhi).
  - They are flagged `centroid_in_study_area = False`. **Open decision: how to treat them.**
- **Scenario B fixed sites:** all 149 confirmed 4W sites. **Only 98 of them are inside the study area.** The other 51 are in NDMC/Cantonment or just over the border. They are kept because they physically exist and serve nearby wards. The grid model's "already served" check only sees the 98 inside cells.
- **Road distance matrices:**
  - Distance from a ward to a site = shortest network path + the ward's snap offset + the site's snap offset.
  - Pairs more than 25 km apart by road are stored as NaN; none is needed for coverage or nearest-station metrics.
  - Check: every road distance is at least the straight-line distance, and the median detour is 1.42.
- **Road coverage is limited by candidate spacing:**
  - At a 2.1 km **road** radius, only 148 of 250 wards have *any* 3 km candidate within reach (218 with 2 km candidates).
  - At 2.1 km **straight-line**, all 250 do.
  - So the road-distance MCLP run should use the 2 km candidates, or it will under-report coverage because of candidate spacing rather than the method.
- **Budget may need revisiting:** the 102 in D1 comes from the grid model on the old filled boundary. Re-running the grid notebook on the 2022 study area may give a different count. D1 keeps 102 unless changed.

### M2. Candidate sites moved inside the study area (decided 2026-11-21, model inputs v4)
- **Rule:** a candidate site is its grid cell's centroid if that is inside the study area. Otherwise it moves to the centre of the largest part of the cell inside the study area, or a guaranteed-interior point if that centre still falls outside.
- **Applies to all three models:** the grid model places its station at the same point, so every station sits inside the 250-ward study area.
- **Sites moved:**
  - 3 km grid: 48 of 206 (median move 1.28 km, max 2.11 km).
  - 2 km grid: 79 of 428 (median 0.78 km, max 1.41 km).
  - All other sites are identical to v3.
- **Road reach after the move:** the number of wards with any candidate within 2.1 km by road rises to 159 of 250 (3 km grid) and 220 (2 km grid). The advice in M1 still holds: use the 2 km candidates for the road-distance run.
- **Far from roads:** 3 sites on the 3 km grid and 5 on the 2 km grid are more than 1 km from the nearest drivable road (e.g. in the Ridge forest or along the river). Their road distances include that straight-line snap distance.
- **Supersedes v3:** the v4 set is complete, so notebooks read `*_v4` only.

### F1. Final data package v1 (`Final Data/`, built 2026-11-21)
- **Master table:** the ward master is `ward_master_v4` plus:
  - coverage before any new stations (chargers within 2.1 km; whether each ward is covered by a confirmed 4W site, straight-line and by road);
  - `demand_density_per_km2`;
  - the full OSM land-use mix (`osm_lu_*`).
- **Full OSM land use (reference only):** 7,342 polygons in 53 classes, read from the `.pbf` with pyrosm and grouped into 12 groups (see `LU_GROUPS` in `compile_final_v1.py`).
  - **The models still use `ci_share`**, from `delhi_landuse_ci.gpkg` (OSM, Oct 2026). Across wards it correlates at 0.999 with the same classes taken from the `.pbf`, so the two sources agree.
  - Group shares can add up to slightly more than 1 (max 1.16) where polygons of different groups overlap in OSM.
  - On median, only 47% of a ward's area has any land-use tag; the rest of the ward has no OSM land-use tag, and 17 wards have none at all. Treat land-use shares as lower bounds.
- **Grid count on the new study area:** 104 stations on the 3 km grid with the 1% threshold (157 on the 2 km grid). The old boundary gave 102 and 165.
  - **Resolved:** the budget moved to 104 (see D1).

## Data caveats found in step 1 (no decision yet)

- **C1. Ward layout:** the ward file is the 272-ward pre-2022 MCD layout (104 S, 104 N, 64 E, plus Lado Sarai).
  - It does not match the 250 wards of the 2022 delimitation, so SEC 2022 ward population will not join directly.
  - NDMC and Delhi Cantonment (~91 km²) have no wards. 56 chargers fall in that gap.
- **C2. Ward names:** East-zone ward names are corrupted (11× "Maujpur (40E)", 3× "Geeta Colony (24E)"). `wardcode` repeats 13 times. Use `objectid` as the ward key.
- **C3. Unusable ward columns:** `districtname`, `ulbname`, `remark` and `id` are unusable. Geometry only.
- **C4. Charger dedup:** 105 chargers fall outside every ward polygon. 252 charger pairs remain within 100 m of each other after the 30 m dedup.
- **C5. Pipeline can't be re-run:** `compilation.py` depends on `ev_final.xlsx`, which is missing.
- **C6. Land use is incomplete:** OSM land-use coverage is patchy (15.3 km² commercial, 66.2 km² industrial).

## OSM extract `Data/delhi_osm_chargers.pbf` (scanned 2026-11-21)

- **O1. What the file is:** despite its name, it is a full OSM extract of Delhi plus NCR. It covers lat 27.0–30.2 and lon 75.7–78.1 and holds 3.66 M nodes, 720 k ways and 6.8 k relations.
  - 239 k `highway` ways, so it can serve as the **road network** for road-distance MCLP.
  - 427 k buildings and 9 k land-use ways.
- **O2. No MCD ward layer:**
  - `admin_level=10` (1,367 relations) holds colonies and housing societies.
  - `admin_level=9`/`11` hold sectors.
  - The 130 `boundary=political` relations are mostly revenue villages and Haryana assembly seats; only 26 names match our wards.
  - **The 272-ward geojson remains the only ward boundary file in the project.** There is no 2022 (250-ward) layout anywhere.
- **O3. Outlines for the ward-file gap:** `admin_level=8` includes **New Delhi** (NDMC) and **Delhi Cantonment**, which could fill the 91 km² gap in the ward file (C1) as two extra zones.

## Pending inputs

- **P1. Ward population:** resolved. It is included in `delhi_wards_2022.kml` (see A2).
- **P2. Income / equity proxy:** received. It is flat (see A7).

## VAHAN / RTO data (added 2026-11-21)

Files: `Data/Raw_v2.xlsx` (raw VAHAN export, numbers stored as text with commas) and `Data/cleaned_delhi_EV_by_RTO_2020-2026.xlsx`.
- The cleaned file's "Raw Download" sheet is identical to `Raw_v2.xlsx`.
- Its grouped sheets reconcile exactly: 476,830 EVs in total across 16 RTO codes.
- Use the cleaned file as the source and read it with `openpyxl` cached values or `pandas`; the total and share columns are formulas.

- **V1. Registration period:** active vehicles registered 2020 to 2026, and 2026 is a part year. EVs registered before 2020 are excluded, and scrapped or archived vehicles are excluded too.
- **V2. Hybrids included:** the fuel filter includes STRONG HYBRID EV and PLUG-IN HYBRID EV. Strong hybrids never plug in, so "Cars (LMV)" overstates the 4W fleet that needs charging. The VAHAN download does not split cars by fuel type, so this cannot be corrected from these files.
- **V3. What counts as 4W demand:** "Cars (LMV)" (68,322 across the 13 area RTOs) is the private 4W demand variable. Electric taxis registered at DL52 (Taxi Unit HQ, 14,016 LIGHT PASSENGER VEHICLE) are 4W and heavy public-charger users. They have no home RTO, so they are excluded from ward demand (or spread citywide if we decide so). Note: the cleaned file files DL52 under "Buses & goods & other".
- **V4. City-wide units:** DL51, DL52 and DL53 register vehicles citywide and are not mapped to any area. DL51 has no cars; DL53 has 0 cars.
- **V5. Registration address ≠ charging location:** a registration reflects the owner's address (where the car is kept overnight), not where it needs public charging.
- **V6. No RTO boundaries:** no RTO jurisdiction map exists in the project. Wards must be assigned to RTOs by hand, from published RTO jurisdiction lists or by nearest RTO office.
- **V7. DL2 New Delhi:** DL2 (Jam Nagar House) mostly covers NDMC, which has no wards in the current ward file (C1). Its 1,301 cars (1.9%) have nowhere to go until the ward layout is fixed.
- **V8. Share of cars by RTO:**

  | RTO | Share | RTO | Share |
  |---|---|---|---|
  | DL10 | 15.5% | DL13 | 4.8% |
  | DL9 | 13.4% | DL4 | 4.6% |
  | DL8 | 12.6% | DL5 | 4.3% |
  | DL3 | 11.6% | DL11 | 3.9% |
  | DL12 | 10.1% | DL6 | 3.9% |
  | DL1 | 7.9% | DL2 | 1.9% |
  | DL7 | 5.5% | | |

  West (DL4) has the most EVs overall but only 4.6% of the cars. Its EVs are mostly 2W and e-rickshaws, so the vehicle class matters a lot.
