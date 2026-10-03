"""Real Lambert geometry: two-impulse transfers between coplanar circular orbits.

The sim previously offered exactly one interplanetary trajectory — the Hohmann
transfer, which sweeps precisely pi and is therefore *minimum delta-v* among all
two-impulse transfers. That made departure phase a hard gate: you could only leave
when the two bodies were half a cycle apart, and the only way to go sooner was
`fast_option`, priced by an invented `1 + (t_hohmann/t)^2` premium.

This module generalises it honestly. A transfer is set by:

  r1, r2   the two circular radii (a moon uses its parent's radius)
  theta    the transfer ANGLE -- the phase gap the departure accepts

`theta = pi` is the Hohmann transfer, reproduced exactly (see
`tests/test_lambert.py`, which pins it to 1e-9 against `orbits.hohmann`). Smaller
`theta` accepts less phase, which covers the same angle sooner and costs more
fuel. That turns "wait or go" from two separate mechanics into one dial.

Geometry
---------
An ellipse through the two radius vectors is fixed by the departure true anomaly
`nu1` and the transfer angle:

    e = (r2 - r1) / (r1 cos nu1 - r2 cos(nu1 + theta))
    p = r1 (1 + e cos nu1)          a = p / (1 - e^2)

Given r1, r2 and theta this leaves a ONE-parameter family (nu1 in [0, 2pi)). The
minimum-delta-v member is found by grid + golden-section refinement.

Delta-v is the magnitude of the velocity *vector* difference at each end, not a
difference of speeds. That distinction matters: it is only equivalent when the
arrival is at an apsis, and using speeds makes non-apsis arcs look impossibly
cheap (it briefly reported a 160-degree arc as both faster and cheaper than
Hohmann, which the minimum-dv theorem forbids).
"""
from __future__ import annotations

import math

TAU = math.tau
_CACHE: dict = {}


def _vel(p: float, e: float, mu: float, nu: float) -> tuple[float, float]:
    """(radial, transverse) velocity at true anomaly nu."""
    k = mu / math.sqrt(mu * p)
    return (k * e * math.sin(nu), k * (1.0 + e * math.cos(nu)))


def arc_from_nu1(r_lo: float, r_hi: float, theta: float, nu1: float, mu: float):
    """One transfer ellipse of the family, or None if this nu1 is not physical.

    Radii are given INNER-first: the family is solved on the canonical
    lo -> hi orientation and `outward` says which way the ship actually flies.
    """
    r1, r2 = r_lo, r_hi
    c1, c2 = math.cos(nu1), math.cos(nu1 + theta)
    den = r1 * c1 - r2 * c2
    if abs(den) < 1e-13:
        return None
    e = (r2 - r1) / den
    if not (-1e-9 <= e < 1.0):
        return None
    p = r1 * (1.0 + e * c1)
    if p <= 1e-15:
        return None
    a = p / (1.0 - e * e)
    # the arrival really is at r2 (guards against float drift)
    if abs(p / (1.0 + e * c2) - r2) > 1e-7 * max(1.0, r2):
        return None

    vr1, vt1 = _vel(p, e, mu, nu1)
    vr2, vt2 = _vel(p, e, mu, nu1 + theta)
    dv1 = math.hypot(vr1, vt1 - math.sqrt(mu / r1))
    dv2 = math.hypot(vr2, vt2 - math.sqrt(mu / r2))

    E1 = _ecc_from_true(nu1, e)
    E2 = _ecc_from_true(nu1 + theta, e)
    dM = (E2 - e * math.sin(E2)) - (E1 - e * math.sin(E1))
    dM %= TAU
    tof = dM / math.sqrt(mu / a ** 3)

    return {"e": e, "a": a, "p": p, "nu1": nu1, "theta": theta,
            "tof": tof, "dv": dv1 + dv2, "dv1": dv1, "dv2": dv2,
            "periapsis": a * (1.0 - e), "apoapsis": a * (1.0 + e),
            "m0": E1 - e * math.sin(E1), "dm": dM,
            "r_lo": r_lo, "r_hi": r_hi, "mu": mu}


def _ecc_from_true(nu: float, e: float) -> float:
    return 2.0 * math.atan2(math.sqrt(1.0 - e) * math.sin(nu / 2.0),
                            math.sqrt(1.0 + e) * math.cos(nu / 2.0))


def _ecc_from_mean(M: float, e: float) -> float:
    """Kepler's equation by Newton. M and E are NOT reduced mod 2pi.

    Reducing here breaks inward and overshoot arcs: an arc running from
    apoapsis to periapsis carries its mean anomaly through pi -> 3pi, and a
    modulo turns that into pi -> pi, so the radius dives to periapsis halfway
    and climbs back out. Keep the window: M stays in [0, 4pi) because
    m0 < 2pi and dm < 2pi, which is exactly what the half-angle tangent formulas
    can represent.
    """
    E = M if e < 0.8 else math.pi
    for _ in range(60):
        d = (E - e * math.sin(E) - M) / (1.0 - e * math.cos(E))
        E -= d
        if abs(d) < 1e-14:
            break
    return E


def best_arc(r_lo: float, r_hi: float, theta: float, mu: float,
             grid: int = 240, refine: int = 60):
    """Minimum-delta-v member of the theta family, inner radius first.

    Cached per (r_lo, r_hi, theta) and therefore SHARED between an outward and
    an inward transfer over the same pair -- they are the same ellipse flown
    both ways. Travel direction is deliberately NOT stored here; it is passed to
    `position`, so a cached arc can never be corrupted by one journey's
    direction leaking into another's.
    """
    r1, r2 = min(r_lo, r_hi), max(r_lo, r_hi)
    key = (round(r1, 9), round(r2, 9), round(theta, 9), mu)
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    best = None
    for i in range(grid):
        arc = arc_from_nu1(r1, r2, theta, TAU * i / grid, mu)
        if arc and (best is None or arc["dv"] < best["dv"]):
            best = arc
    if best is None:
        _CACHE[key] = None
        return None
    step = TAU / grid
    lo, hi = best["nu1"] - step, best["nu1"] + step
    gr = (math.sqrt(5.0) - 1.0) / 2.0
    def cost(nu):
        arc = arc_from_nu1(r1, r2, theta, nu, mu)
        return arc["dv"] if arc else float("inf")
    c, d = hi - gr * (hi - lo), lo + gr * (hi - lo)
    for _ in range(refine):
        if cost(c) < cost(d):
            hi, d = d, c
            c = hi - gr * (hi - lo)
        else:
            lo, c = c, d
            d = lo + gr * (hi - lo)
    cand = arc_from_nu1(r1, r2, theta, (lo + hi) / 2.0, mu)
    out = cand if (cand and cand["dv"] <= best["dv"] + 1e-15) else best
    _CACHE[key] = out
    return out


def position(arc: dict, fraction: float, outward: bool = True) -> tuple[float, float]:
    """(radius, longitude offset from departure) at `fraction` of the transfer.

    Works for any arc: outward, inward, and overshoot. The swept longitude is
    taken as the difference between the two Kepler solutions rather than as
    `theta`, so an arc that passes through periapsis on the way in or out is
    handled without any sign cases.
    """
    frac = min(max(float(fraction), 0.0), 1.0)
    # Endpoints are exact by construction. Solving Kepler's equation for them
    # loses ~1e-10 of radius, and an arc that does not start precisely on its
    # departure body detaches the moment it is drawn.
    if frac <= 0.0:
        return (arc["r_lo"], 0.0) if outward else (arc["r_hi"], 0.0)
    if frac >= 1.0:
        return (arc["r_hi"], arc["theta"]) if outward else (arc["r_lo"], arc["theta"])
    # An inward transfer is the SAME ellipse rotated by pi and flown prograde,
    # not the outward arc reversed. Reversing it would fly retrograde -- the
    # mean anomaly would run backwards and a retrograde Hohmann is not what a
    # ship departing an outer orbit for an inner one does.
    #
    # So mean anomaly runs m0 + (1+frac)*dm: it starts one arc ahead of the
    # outward departure (which puts the ship at apoapsis) and advances by dm.
    # Range stays inside [0, 4pi) because m0 < 2pi and 2*dm < 4pi.
    M = arc["m0"] + (frac if outward else (1.0 + frac)) * arc["dm"]
    E = _ecc_from_mean(M, arc["e"])
    nu = _ecc_to_true(E, arc["e"])
    nu0 = _ecc_to_true(_ecc_from_true(arc["nu1"], arc["e"]), arc["e"])
    r = arc["p"] / (1.0 + arc["e"] * math.cos(nu))
    return r, nu - (nu0 if outward else nu0 + arc["dm"])


def _ecc_to_true(E: float, e: float) -> float:
    return 2.0 * math.atan2(math.sqrt(1.0 + e) * math.sin(E / 2.0),
                            math.sqrt(1.0 - e) * math.cos(E / 2.0))


def arc_points(arc: dict, th0: float, n: int = 25) -> list:
    """Polyline of the transfer, helio polar -> cartesian, for the renderer.

    `th0` is passed in rather than stored on the arc: arcs are CACHED and shared,
    so hanging the departure longitude off them would let one caller mutate the
    geometry that every other caller then sees.
    """
    pts = []
    for i in range(n + 1):
        r, dlon = position(arc, i / n)
        ang = th0 + dlon
        pts.append([round(r * math.cos(ang), 4), round(r * math.sin(ang), 4)])
    return pts


def arrival_time(theta: float, depart_t: float, arc: dict) -> float:
    return depart_t + (arc["tof"] if arc else 0.0)