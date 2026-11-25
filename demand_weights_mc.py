"""Recompute demand weights from the saved demand layer (for Monte Carlo runs).

The demand layer (data/delhi_demand_weights.gpkg) stores R and the destination
component masses (Dm_*), so weights for any lambda / theta can be rebuilt without
re-running the OSM pipeline:

    D     = th_poi * sum_k(thp_k * Dm_k) + th_land * Dm_ci_land
            + th_road * (Dm_art_density + Dm_int_density + Dm_art_prox) / 3
            + th_transit * Dm_transit_prox
    s     = lam * R / sum(R) + (1 - lam) * D / sum(D)
    w     = N * s / sum(s)

D is linear in the component masses, so summing pieces into cells first and
re-weighting afterwards gives exactly the same answer as re-weighting pieces.
"""
import numpy as np

# Team's reasoned starting values (NOT taken from literature).
THETA_D = {"poi": 0.35, "land": 0.30, "road": 0.20, "transit": 0.15}
THETA_POI = {"office": 0.25, "mall": 0.25, "hospital": 0.20, "hotel": 0.15, "parking": 0.15}
LAMBDA = 0.6
N_TOTAL = 1000.0


def destination_mass(df, theta_D=THETA_D, theta_POI=THETA_POI):
    poi = sum(theta_POI[k] * df[f"Dm_{k}"] for k in theta_POI)
    road = (df["Dm_art_density"] + df["Dm_int_density"] + df["Dm_art_prox"]) / 3
    return (theta_D["poi"] * poi + theta_D["land"] * df["Dm_ci_land"]
            + theta_D["road"] * road + theta_D["transit"] * df["Dm_transit_prox"])


def recompute_weights(df, lam=LAMBDA, theta_D=THETA_D, theta_POI=THETA_POI, N=N_TOTAL, R_col="R"):
    """Return a numpy array of weights w (sums to N). R_col picks the home-demand column:
    "R" = population (dasymetric), "R_ev" = EV registrations (population x ward EV-4W rate; main since the audit)."""
    R = df[R_col].to_numpy(float)
    D = destination_mass(df, theta_D, theta_POI).to_numpy(float)
    s = lam * R / R.sum() + (1 - lam) * D / D.sum()
    return N * s / s.sum()


def draw_params(rng, lam_range=(0.3, 0.8), dirichlet_conc=50.0, draw_theta=True):
    """One Monte Carlo draw: lambda ~ U(lam_range); theta ~ Dirichlet(conc * base)."""
    lam = rng.uniform(*lam_range)
    if not draw_theta:
        return lam, THETA_D, THETA_POI
    kd, kp = list(THETA_D), list(THETA_POI)
    td = rng.dirichlet(dirichlet_conc * np.array([THETA_D[k] for k in kd]))
    tp = rng.dirichlet(dirichlet_conc * np.array([THETA_POI[k] for k in kp]))
    return lam, dict(zip(kd, td)), dict(zip(kp, tp))


def mc_weights(df, rng, sigma=0.30, R_col="R", **draw_kw):
    """Weights for one MC run: random lambda/theta, then lognormal noise (sigma in log space)."""
    lam, td, tp = draw_params(rng, **draw_kw)
    w = recompute_weights(df, lam, td, tp, R_col=R_col)
    w = w * rng.lognormal(0.0, sigma, len(w))
    return N_TOTAL * w / w.sum(), dict(lam=lam, **{f"th_{k}": v for k, v in td.items()},
                                       **{f"thp_{k}": v for k, v in tp.items()})
