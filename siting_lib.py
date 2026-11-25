"""Shared code for the three siting models (grid, K-means, MCLP), their variants and the evaluation scorecard.

Everything is in EPSG:32643 (metres). Layouts are passed around as (n, 2) arrays of x/y station coordinates.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import shapely
from scipy.optimize import milp, linprog, LinearConstraint, Bounds
from scipy.sparse import csr_matrix, coo_matrix, hstack, vstack, eye
from scipy.sparse.csgraph import dijkstra, connected_components
from scipy.spatial import cKDTree
from sklearn.cluster import KMeans

import demand_weights_mc as dwmc

CRS = "EPSG:32643"
GIS = "Final Data/delhi_ev_gis_v1.gpkg"
DEMAND = "data/delhi_demand_weights.gpkg"
GRID_ORIGIN = (679924.5228, 3142807.6633)      # origin of the team's 3 km / 2 km grids (from candidates_v1.csv)


# ----------------------------------------------------------------------------------------------------------------
# data
# ----------------------------------------------------------------------------------------------------------------
def xy(g):
    return np.column_stack([g.geometry.x.to_numpy(), g.geometry.y.to_numpy()])


def pts(df, x="x", y="y"):
    return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df[x], df[y]), crs=CRS)


MASTER = "Final Data/delhi_ev_master_wards_v1.csv"


def load_base(weight="ev"):
    """All inputs shared by the models and the scorecard.

    weight: "ev" (main, since the audit) = 60% EV registrations + 40% destinations;
            "team" = 60% population + 40% destinations (the original 1 km weight).
    EV registrations per cell = population in the cell x its ward's VAHAN EV-4W registrations per resident
    (EV cars + e-taxis 2020-26, allocated to wards by RTO zone; Final Data A4/A5)."""
    B = {}
    d = gpd.read_file(DEMAND, layer="demand_weights").to_crs(CRS)
    B["cells"] = gpd.read_file(DEMAND, layer="cells_polygons")
    study = gpd.read_file(GIS, layer="study_area").to_crs(CRS)
    B["study"], B["study_geom"] = study, shapely.make_valid(study.union_all())

    wards = pd.read_csv(MASTER).set_index("ward_no")            # Final Data master table (audit: not ward_master_v2.csv)
    pieces = gpd.read_file(DEMAND, layer="demand_pieces")
    rate = (wards["ev_4w_demand"] / wards["population"])
    pieces["ev_reg"] = pieces["pop_alloc"] * pieces["ward_no"].map(rate)
    ev = pieces.groupby("cell_id")["ev_reg"].sum()
    d["ev_reg"] = d["cell_id"].map(ev).fillna(0).to_numpy()
    d["R_ev"] = d["ev_reg"]
    d["w_team"] = d["weight"].to_numpy(float)
    d["w_ev"] = dwmc.recompute_weights(d, R_col="R_ev")
    B["weight_name"] = weight
    B["R_col"] = "R_ev" if weight == "ev" else "R"
    B["demand"], B["X"], B["w"] = d, xy(d), d["w_" + weight].to_numpy(float)
    d["sc_share"] = d["ward_no"].map(wards["sc_share"])
    # SC quintiles weighted by population (each group ~20% of people; audit issue 5). Ward-level groups.
    o_ = wards.sort_values("sc_share"); cp_ = o_["population"].cumsum() / o_["population"].sum()
    q_pop = pd.cut(cp_, [0, .2, .4, .6, .8, 1.0001], labels=[f"Q{i}" for i in range(1, 6)]).reindex(wards.index)
    d["sc_q"] = d["ward_no"].map(q_pop)
    d["sc_q_cells"] = pd.qcut(d["sc_share"].rank(method="first"), 5, labels=[f"Q{i}" for i in range(1, 6)])

    c = pd.read_csv("Final Data/model_inputs/candidates_v1.csv")
    B["cand3"] = pts(c[c["grid_km"] == 3].reset_index(drop=True))
    B["cand2"] = pts(c[c["grid_km"] == 2].reset_index(drop=True))
    ch = pd.read_csv("Final Data/model_inputs/existing_chargers_v1.csv")
    ch = pts(ch[ch["in_study_area"] == True].reset_index(drop=True))
    B["existing_all"], B["existing_4w"] = ch, ch[ch["scenario_b_fixed"] == True].reset_index(drop=True)
    feas = pd.concat([gpd.read_file(DEMAND, layer=l)[["geometry"]].assign(kind=l.split("_")[1])
                      for l in ["feasible_parking", "feasible_fuel"]], ignore_index=True)
    feas = gpd.GeoDataFrame(feas, geometry="geometry", crs=CRS)
    B["real_sites"] = feas[feas.within(B["study_geom"])].reset_index(drop=True)
    B["landuse_ci"] = gpd.read_file(GIS, layer="landuse_ci").to_crs(CRS)
    return B


# ----------------------------------------------------------------------------------------------------------------
# model 1: policy grid (ICCT / Vansola et al. 2023; MoP 3 km x 3 km rule)
# ----------------------------------------------------------------------------------------------------------------
def grid_model(B, size_km=3.0, threshold=0.01, origin=GRID_ORIGIN):
    """One station per cell with C+I share >= threshold; station at the cell centroid if inside the study area,
    else at the centre of the cell's largest in-area part (rule M2). Returns (stations gdf, cells gdf)."""
    s = size_km * 1000
    area = B["study_geom"]
    minx, miny, maxx, maxy = area.bounds
    x0 = origin[0] + np.floor((minx - origin[0]) / s) * s
    y0 = origin[1] + np.floor((miny - origin[1]) / s) * s
    boxes = [shapely.box(x, y, x + s, y + s) for x in np.arange(x0, maxx, s) for y in np.arange(y0, maxy, s)]
    cells = gpd.GeoDataFrame(geometry=boxes, crs=CRS)
    cells = cells[cells.intersects(area)].reset_index(drop=True)
    cells["cell_id"] = np.arange(len(cells))
    inpart = cells.geometry.intersection(area)
    cells["area_in_km2"] = inpart.area / 1e6
    # merge overlapping land-use polygons first so no area is counted twice (audit issue 13)
    if "landuse_union" not in B:
        B["landuse_union"] = shapely.make_valid(B["landuse_ci"].union_all())
    cells["share_ci"] = inpart.intersection(B["landuse_union"]).area / inpart.area
    cells["station"] = cells["share_ci"] >= threshold

    def site(cellgeom, part):
        c = cellgeom.centroid
        if c.within(area):
            return c
        parts = list(getattr(part, "geoms", [part]))
        big = max(parts, key=lambda g: g.area)
        cc = big.centroid
        return cc if cc.within(area) else big.representative_point()

    cells["site"] = [site(g, p) for g, p in zip(cells.geometry, inpart)]
    st = gpd.GeoDataFrame(cells.loc[cells["station"], ["cell_id", "share_ci"]],
                          geometry=list(cells.loc[cells["station"], "site"]), crs=CRS).reset_index(drop=True)
    return st, cells.drop(columns="site")


# ----------------------------------------------------------------------------------------------------------------
# model 2: weighted K-means and variants
# ----------------------------------------------------------------------------------------------------------------
def kmeans(X, w, k, seed=42, n_init=20):
    km = KMeans(n_clusters=k, init="k-means++", n_init=n_init, max_iter=500, random_state=seed).fit(X, sample_weight=w)
    return km.cluster_centers_, km.labels_


def kmeans_fixed(X, w, fixed_xy, k_free, seed=42, n_init=5, iters=100):
    """K-means where `fixed_xy` centres stay put (existing chargers) and only k_free centres move."""
    rng = np.random.default_rng(seed)
    best = None
    for _ in range(n_init):
        d_fix = cKDTree(fixed_xy).query(X)[0] ** 2
        C = np.empty((0, 2))
        for _ in range(k_free):                      # k-means++ seeding, counting the fixed centres as already chosen
            d = d_fix if len(C) == 0 else np.minimum(d_fix, cKDTree(C).query(X)[0] ** 2)
            pr = w * d; C = np.vstack([C, X[rng.choice(len(X), p=pr / pr.sum())]])
        for _ in range(iters):
            allc = np.vstack([fixed_xy, C])
            lab = cKDTree(allc).query(X)[1]
            newC = C.copy()
            for j in range(k_free):
                m = lab == len(fixed_xy) + j
                if m.any():
                    newC[j] = np.average(X[m], axis=0, weights=w[m])
            if np.allclose(newC, C):
                break
            C = newC
        allc = np.vstack([fixed_xy, C])
        dd, lab = cKDTree(allc).query(X)
        inertia = (w * dd ** 2).sum()
        if best is None or inertia < best[0]:
            best = (inertia, C, lab)
    return best[1], best[2]


def kmeans_capacitated(X, w, k, cap, seed=42, iters=30, n_near=15):
    """Balanced K-means: each centre may serve at most `cap` weight. Assignment = LP (fractional allowed),
    restricted to each point's n_near nearest centres; centres = weighted mean of what they serve."""
    C, _ = kmeans(X, w, k, seed, n_init=10)
    n = len(X)
    for _ in range(iters):
        dist, idx = cKDTree(C).query(X, k=min(n_near, k))
        rows = np.repeat(np.arange(n), idx.shape[1]); cols = idx.ravel()
        cost = (dist.ravel() ** 2) * w[rows]
        m = len(rows)
        A_eq = csr_matrix((np.ones(m), (rows, np.arange(m))), shape=(n, m))
        A_ub = csr_matrix((w[rows], (cols, np.arange(m))), shape=(k, m))
        # slack per point (huge cost) keeps the LP feasible when the nearest centres are all full
        A_eq = hstack([A_eq, eye(n)]); A_ub = hstack([A_ub, csr_matrix((k, n))])
        r = linprog(np.r_[cost, np.full(n, cost.max() * 100)], A_ub=A_ub, b_ub=np.full(k, cap), A_eq=A_eq,
                    b_eq=np.ones(n), bounds=(0, 1), method="highs")
        z = r.x[:m]
        W = coo_matrix((z * w[rows], (cols, rows)), shape=(k, n)).tocsr()
        tot = np.asarray(W.sum(1)).ravel()
        newC = np.where(tot[:, None] > 0, (W @ X) / np.maximum(tot, 1e-12)[:, None], C)
        if np.allclose(newC, C, atol=1.0):
            C = newC; break
        C = newC
    load = tot
    return C, load


# ----------------------------------------------------------------------------------------------------------------
# model 3: MCLP and variants (HiGHS via scipy.optimize.milp)
# ----------------------------------------------------------------------------------------------------------------
def within_pairs(X, S, R):
    """Sparse 0/1 matrix A[i, j] = 1 if site j is within R of point i (Euclidean)."""
    nb = cKDTree(S).query_ball_point(X, R)
    r = np.repeat(np.arange(len(X)), [len(a) for a in nb])
    c = np.concatenate([np.asarray(a, int) for a in nb]) if len(r) else np.array([], int)
    return csr_matrix((np.ones(len(r)), (r, c)), shape=(len(X), len(S)))


def mclp(w, A, p, A_tie=None, fixed=None, time_limit=300, return_info=False):
    """Max covered weight with p (new) sites. A: coverage matrix (n x J). fixed: indices of sites forced open
    (they do not count towards p). A_tie: optional second-stage coverage (e.g. within 1 km) maximised at the
    optimal first-stage coverage. Returns (open site indices, covered weight), plus solver info
    {status: 0 optimal / 1 time limit, gap} when return_info=True (audit issue 6)."""
    n, J = A.shape
    lo = np.zeros(J)
    if fixed is not None and len(fixed):
        lo[np.asarray(fixed)] = 1
    newsel = np.ones(J)
    if fixed is not None and len(fixed):
        newsel[np.asarray(fixed)] = 0
    nfix = int(lo.sum())
    sel = hstack([csr_matrix(newsel.reshape(1, -1)), csr_matrix((1, n))])
    cons = [LinearConstraint(hstack([-A, eye(n)]), -np.inf, 0), LinearConstraint(sel, p, p)]
    integ = np.r_[np.ones(J), np.zeros(n)]
    bnd = Bounds(np.r_[lo, np.zeros(n)], np.ones(J + n))
    r = milp(np.r_[np.zeros(J), -w], constraints=cons, integrality=integ, bounds=bnd, options=dict(time_limit=time_limit))
    best = -r.fun
    r1 = r                                         # first-stage solve (coverage); its status is what we report
    if A_tie is not None:
        Z = csr_matrix((n, n))
        cons2 =[LinearConstraint(hstack([-A, eye(n), Z]), -np.inf, 0),
                 LinearConstraint(hstack([-A_tie, Z, eye(n)]), -np.inf, 0),
                 LinearConstraint(hstack([sel, csr_matrix((1, n))]), p, p),
                 LinearConstraint(hstack([csr_matrix((1, J)), csr_matrix(w.reshape(1, -1)), csr_matrix((1, n))]),
                                  best * (1 - 1e-9), np.inf)]
        bnd2 = Bounds(np.r_[lo, np.zeros(2 * n)], np.ones(J + 2 * n))
        r2 = milp(np.r_[np.zeros(J + n), -w], constraints=cons2, integrality=np.r_[np.ones(J), np.zeros(2 * n)],
                  bounds=bnd2, options=dict(time_limit=time_limit))
        if r2.status in (0, 1) and r2.x is not None:
            r = r2
    info = {"status": r1.status, "gap": getattr(r1, "mip_gap", np.nan)}
    if r1.status != 0:
        import warnings
        warnings.warn(f"MCLP stopped before proving optimality (status {r1.status}, gap {info['gap']})")
    out = (np.flatnonzero(np.round(r.x[:J]) == 1), best)
    return out + (info,) if return_info else out


def _assignment_problem(w, rows, cols, J, p, obj, cap=None, time_limit=300, maximise=True, must_assign=False):
    """Generic facility problem on sparse (point, site) pairs: x_j binary, z_ij in [0,1].
    sum_j z_ij <= 1 (or == 1), z_ij <= x_j (or capacity sum_i w_i z_ij <= cap x_j), sum_j x_j = p."""
    n, m = len(w), len(rows)
    nv = J + m
    c = np.r_[np.zeros(J), (-obj if maximise else obj)]
    A1 = hstack([csr_matrix((n, J)), csr_matrix((np.ones(m), (rows, np.arange(m))), shape=(n, m))])
    cons = [LinearConstraint(A1, 1 if must_assign else 0, 1)]
    if cap is None:
        A2 = hstack([csr_matrix((-np.ones(m), (np.arange(m), cols)), shape=(m, J)), eye(m)])
        cons.append(LinearConstraint(A2, -np.inf, 0))
    else:
        A2 = hstack([csr_matrix(-cap * eye(J)), csr_matrix((w[rows], (cols, np.arange(m))), shape=(J, m))])
        cons.append(LinearConstraint(A2, -np.inf, 0))
    cons.append(LinearConstraint(hstack([csr_matrix(np.ones((1, J))), csr_matrix((1, m))]), p, p))
    r = milp(c, constraints=cons, integrality=np.r_[np.ones(J), np.zeros(m)], bounds=Bounds(0, 1),
             options=dict(time_limit=time_limit))
    x, z = r.x[:J], r.x[J:]
    return np.flatnonzero(np.round(x) == 1), z, r


def mclp_capacitated(w, X, S, p, R, cap, time_limit=300):
    """MCLP where each open site can serve at most `cap` weight (demand within R may be split between sites)."""
    A = within_pairs(X, S, R).tocoo()
    o, z, r = _assignment_problem(w, A.row, A.col, len(S), p, w[A.row], cap=cap, time_limit=time_limit)
    load = np.bincount(A.col, weights=z * w[A.row], minlength=len(S))
    return o, (z * w[A.row]).sum(), load


def mclp_gradual(w, X, S, p, r_full=1000, r_zero=3000, time_limit=300):
    """Gradual-coverage MCLP: full credit within r_full, falling linearly to 0 at r_zero (no hard cut-off)."""
    D = cKDTree(S).sparse_distance_matrix(cKDTree(X), r_zero, output_type="coo_matrix")   # (J x n)
    rows, cols, d = D.col, D.row, D.data
    score = np.clip((r_zero - d) / (r_zero - r_full), 0, 1)
    o, z, r = _assignment_problem(w, rows, cols, len(S), p, w[rows] * score, time_limit=time_limit)
    return o, -r.fun


def pmedian(w, X, S, p, n_near=40, dist=None, time_limit=300):
    """p-median: minimise demand-weighted distance to the assigned open site (each point assigned to one of its
    n_near nearest candidates). `dist`, if given, is an (n x J) dense matrix (e.g. road distance) used instead."""
    n, J = len(X), len(S)
    if dist is None:
        dd, idx = cKDTree(S).query(X, k=min(n_near, J))
    else:
        idx = np.argsort(dist, axis=1)[:, :n_near]
        dd = np.take_along_axis(dist, idx, axis=1)
    rows = np.repeat(np.arange(n), idx.shape[1]); cols = idx.ravel(); d = dd.ravel()
    ok = np.isfinite(d)
    rows, cols, d = rows[ok], cols[ok], d[ok]
    o, z, r = _assignment_problem(w, rows, cols, J, p, w[rows] * d, time_limit=time_limit, maximise=False, must_assign=True)
    return o


# ----------------------------------------------------------------------------------------------------------------
# road network distances (directed, oneway respected)
# ----------------------------------------------------------------------------------------------------------------
class RoadNet:
    """Directed road graph from delhi_road_network_v1.gpkg. dist_to(points, sites) gives road metres from each
    point to each site (point -> site direction), with straight-line snap distances to the network added."""

    def __init__(self, path="Final Data/delhi_road_network_v1.gpkg"):
        e = gpd.read_file(path, layer="road_edges_v1", columns=["u", "v", "oneway", "length_m"], ignore_geometry=True)
        nodes = gpd.read_file(path, layer="road_nodes")
        nid = pd.Index(nodes["id"].to_numpy())
        u, v = nid.get_indexer(e["u"]), nid.get_indexer(e["v"])
        ok = (u >= 0) & (v >= 0)
        e, u, v = e[ok], u[ok], v[ok]
        ow = e["oneway"].astype(str).str.lower()
        fwd = ~ow.isin(["-1"]); bwd = ~ow.isin(["yes", "true", "1"])
        src = np.r_[u[fwd.to_numpy()], v[bwd.to_numpy()]]
        dst = np.r_[v[fwd.to_numpy()], u[bwd.to_numpy()]]
        L = np.r_[e["length_m"].to_numpy()[fwd.to_numpy()], e["length_m"].to_numpy()[bwd.to_numpy()]]
        N = len(nid)
        G = csr_matrix((L, (src, dst)), shape=(N, N))
        _, comp = connected_components(G, directed=True, connection="strong")
        big = comp == np.bincount(comp).argmax()
        self.G, self.GT = G, G.T.tocsr()
        self.nxy = xy(nodes)
        self.keep = np.flatnonzero(big)
        self.tree = cKDTree(self.nxy[self.keep])

    def snap(self, P):
        d, i = self.tree.query(P)
        return self.keep[i], d

    def dist_to(self, P, S, limit=15000, batch=25):
        """(len(P) x len(S)) road distance point -> site in metres (inf beyond `limit`)."""
        pn, pd_ = self.snap(P)
        sn, sd = self.snap(S)
        out = np.full((len(P), len(S)), np.inf)
        for b in range(0, len(S), batch):
            idx = sn[b:b + batch]
            D = dijkstra(self.GT, directed=True, indices=idx, limit=limit)    # reversed graph: node -> site
            out[:, b:b + batch] = D[:, pn].T
        return out + pd_[:, None] + sd[None, :]


# ----------------------------------------------------------------------------------------------------------------
# evaluation scorecard
# ----------------------------------------------------------------------------------------------------------------
def gini(x, wts):
    o = np.argsort(x); x, wts = x[o], wts[o]
    cw = np.cumsum(wts) / wts.sum(); cx = np.cumsum(x * wts) / (x * wts).sum()
    return 1 - np.sum((cx[1:] + cx[:-1]) * np.diff(cw)) - cx[0] * cw[0]


def scorecard_row(B, S, name, R=2100, road=None, road_R=3000):
    """All yardsticks for one layout S (n x 2 array). road: optional RoadNet."""
    d = B["demand"]; X = B["X"]
    dist = cKDTree(S).query(X)[0]
    cov = lambda wt: 100 * wt[dist <= R].sum() / wt.sum()
    pop = d["pop_alloc"].to_numpy()
    row = {"layout": name, "stations": len(S),
           # circular yardstick (models were built on it)
           "model_demand_cov_pct": cov(B["w"]),
           # independent / partly independent yardsticks
           "ev_registrations_cov_pct": cov(d["ev_reg"].to_numpy()),
           "population_cov_pct": cov(pop),
           "destinations_cov_pct": cov(d["D"].to_numpy()),
           "area_cov_pct": cov(d["area_km2"].to_numpy()),
           "mean_dist_m": np.average(dist, weights=B["w"]),
           "p95_dist_m": _wq(dist, B["w"], 0.95),
           "max_dist_any_cell_m": dist.max(),
           "worst_sc_quintile_pop_cov_pct": min(
               100 * pop[(dist <= R) & (d["sc_q"] == q).to_numpy()].sum() / pop[(d["sc_q"] == q).to_numpy()].sum()
               for q in d["sc_q"].cat.categories),
           "gini_access_dist_pop": gini(dist, pop + 1e-9)}
    de = cKDTree(S).query(xy(B["existing_all"]))[0]
    d4 = cKDTree(S).query(xy(B["existing_4w"]))[0]
    row["existing_all_within_1km_pct"] = 100 * (de <= 1000).mean()
    row["existing_4w_within_1km_pct"] = 100 * (d4 <= 1000).mean()
    row["sites_within_500m_of_parking_or_fuel_pct"] = 100 * (cKDTree(xy(B["real_sites"])).query(S)[0] <= 500).mean()
    if road is not None:
        rd = road.dist_to(X, S).min(axis=1)
        row["road_mean_dist_m"] = np.average(np.where(np.isfinite(rd), rd, 15000), weights=B["w"])
        row[f"road_{road_R}m_model_demand_cov_pct"] = 100 * B["w"][rd <= road_R].sum() / B["w"].sum()
        row[f"road_{road_R}m_population_cov_pct"] = 100 * pop[rd <= road_R].sum() / pop.sum()
        row["sites_within_200m_of_road_pct"] = 100 * (road.snap(S)[1] <= 200).mean()
    return row


def _wq(v, ww, q):
    o = np.argsort(v); c = np.cumsum(ww[o]) / ww.sum()
    return float(v[o][np.searchsorted(c, q)])


# higher-is-better flags for the regret table
HIGHER_BETTER = {"model_demand_cov_pct": True, "ev_registrations_cov_pct": True, "population_cov_pct": True,
                 "destinations_cov_pct": True, "area_cov_pct": True, "mean_dist_m": False, "p95_dist_m": False,
                 "max_dist_any_cell_m": False, "worst_sc_quintile_pop_cov_pct": True, "gini_access_dist_pop": False,
                 "existing_all_within_1km_pct": True, "existing_4w_within_1km_pct": True,
                 "sites_within_500m_of_parking_or_fuel_pct": True, "road_mean_dist_m": False,
                 "road_3000m_model_demand_cov_pct": True, "road_3000m_population_cov_pct": True,
                 "sites_within_200m_of_road_pct": True}


def regret_table(card):
    """Relative shortfall of each layout from the best layout on each metric (0 = best)."""
    out = pd.DataFrame(index=card.index)
    for c in card.columns:
        if c not in HIGHER_BETTER:
            continue
        v = card[c].astype(float)
        best = v.max() if HIGHER_BETTER[c] else v.min()
        out[c] = (best - v) / abs(best) if HIGHER_BETTER[c] else (v - best) / abs(best)
    return out


def agreement(A_xy, B_xy, r=1000):
    """Share of A's stations with a B station within r."""
    return 100 * (cKDTree(B_xy).query(A_xy)[0] <= r).mean()
