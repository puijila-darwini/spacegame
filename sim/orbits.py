"""Keplerian-lite orbits: circular coplanar, real periods. No integrator.

Planets orbit Sun with MU_SUN; moons orbit their parent with that parent's
mu (Moon/Tide around Tern, Eope/Cenaedo/Cteta around Fulmaior).
Positions resolve hierarchically: pos(moon) = pos(parent) + planetocentric offset.
Transfers are heliocentric Hohmann arcs between helio radii (moons use the
parent's), plus sequential moon hop/wait legs. Leave-now premium via
fast_option(): skip the window, pay dv *= 1 + (hohmann_time/transit)^2.

Periods are MUD-literal (world/astrology.py) with Kepler-solved radii.
"""
from __future__ import annotations

import math

MU_SUN = 0.0003046174  # MUD-literal: Tern (a=1.0) -> 360d year; radii Kepler-solved below
# Planetocentric mu is tied to the moon radii below. The renderer puts the
# innermost moon ~18 planet-radii out and station rings deep inside it, so
# these mu values are large by design: n = sqrt(mu/a^3) is what actually fixes
# each moon's period, and the radii are free to look right. Scaling a moon's
# radius by k only requires scaling its parent's mu by k^3 to hold the clock.
MU_TERN = 3.509193e-04  # Moon (a=0.2000) -> 30d, Tide (a=0.2864) -> 360/7 d ≈ 51.43d
MU_FULMAIOR = 6.395504e-03  # Eope (a=0.1800) -> 6d, Cenaedo (0.3462) -> 16d, Cteta (0.6156) -> 38d
MU_BY_PARENT = {"tern": MU_TERN, "fulmaior": MU_FULMAIOR}
TAU = math.tau

# Game-tuned moon rendezvous costs (days + dv coherent with cruise ~0.01-0.03).
# Nearer moons are quicker and cheaper to leave.
HOP_TIME = {"moon": 1.0, "tide": 2.5, "eope": 1.2, "cenaedo": 1.8, "cteta": 2.5}
MOON_DV = {"moon": 0.015, "tide": 0.025, "eope": 0.018, "cenaedo": 0.022, "cteta": 0.028}


class WindowError(RuntimeError):
    pass


def _refuse_gate(o, d) -> None:
    """Gates are charted, not sailable. Inter-system transit is not wired up.

    Refusing here (rather than in the renderer) keeps the destination list
    honest: there is no dv budget or wait time that would buy a crossing.
    """
    if d.kind == "wormhole":
        raise ValueError("the gate mouth is charted but not commissioned for transit")
    if o.kind == "wormhole":
        raise ValueError("departing the gate is not possible — no crossing exists yet")


def mean_motion(a: float, mu: float) -> float:
    return math.sqrt(mu / a**3)


def period(a: float, mu: float) -> float:
    return TAU / mean_motion(a, mu)


def angle_at(a: float, angle0: float, mu: float, t: float) -> float:
    return angle0 + mean_motion(a, mu) * t


def _wrap_pi(x: float) -> float:
    return (x + math.pi) % TAU - math.pi


def _helio_pair(bodies: dict, body_id: str) -> tuple[float, float]:
    """(a, angle0) at helio level: own orbit for planets, parent's for moons."""
    b = bodies[body_id]
    if b.parent is not None:
        p = bodies[b.parent]
        return (p.a, p.angle0)
    if b.a <= 0:
        return (0.0, b.angle0)
    return (b.a, b.angle0)


def helio_angle(bodies: dict, body_id: str, t: float, mu: float = MU_SUN) -> float:
    a, th0 = _helio_pair(bodies, body_id)
    return angle_at(a, th0, mu, t)


def moon_angle(bodies: dict, moon_id: str, t: float) -> float:
    m = bodies[moon_id]
    mu = MU_BY_PARENT.get(m.parent, MU_TERN)
    return angle_at(m.a, m.angle0, mu, t)


def body_angle(body, t: float) -> float:
    mu = MU_SUN if body.parent is None else MU_BY_PARENT[body.parent]
    return angle_at(body.a, body.angle0, mu, t)


def body_pos(body, bodies: dict, t: float) -> tuple[float, float, float]:
    """(x, y, angle_at_own_level); moons add the parent's helio position."""
    if body.a <= 0:
        return (0.0, 0.0, body.angle0)  # star: fixed at origin
    th = body_angle(body, t)
    x, y = body.a * math.cos(th), body.a * math.sin(th)
    if body.parent is not None:
        px, py, _ = body_pos(bodies[body.parent], bodies, t)
        return (x + px, y + py, th)
    return (x, y, th)


def helio_a(body, bodies: dict) -> float:
    if body.parent is not None:
        return bodies[body.parent].a
    return body.a


def hohmann(a1: float, a2: float, mu: float = MU_SUN) -> dict:
    a_t = (a1 + a2) / 2.0
    transit = math.pi * math.sqrt(a_t**3 / mu)
    v1 = math.sqrt(mu / a1)
    v2 = math.sqrt(mu / a2)
    vt1 = math.sqrt(mu * (2.0 / a1 - 1.0 / a_t))
    vt2 = math.sqrt(mu * (2.0 / a2 - 1.0 / a_t))
    return {
        "transit_d": transit,
        "dv": abs(vt1 - v1) + abs(vt2 - v2),
        "a_trans": a_t,
        "e": (a2 - a1) / (a1 + a2),  # signed; ellipse r(0)=a1, r(pi)=a2
    }


def align_wait(moon_a: float, moon_angle0: float, t: float, aspect: float, mu: float) -> float:
    """Days until the moon reaches planetocentric longitude `aspect`."""
    n = mean_motion(moon_a, mu)
    return ((aspect - angle_at(moon_a, moon_angle0, mu, t)) % TAU) / n


def _moon_departure(bodies: dict, moon, t1: float) -> tuple[float, dict, float]:
    """Sequential hop off a moon: phase wait + burn. Returns (t_ready, waits, dv)."""
    mu = MU_BY_PARENT[moon.parent]
    aspect = helio_angle(bodies, moon.parent, t1) + math.pi / 2  # prograde side
    wm = align_wait(moon.a, moon.angle0, t1, aspect, mu)
    return (t1 + wm + HOP_TIME[moon.id], {"moon_depart": wm}, MOON_DV[moon.id])


def _moon_capture_wait(bodies: dict, moon, t_arr: float) -> tuple[float, float]:
    """(phase_wait_days, burn_days) to come down on a moon from the parent's vicinity."""
    mu = MU_BY_PARENT[moon.parent]
    aspect = helio_angle(bodies, moon.parent, t_arr) + math.pi / 2
    return (align_wait(moon.a, moon.angle0, t_arr, aspect, mu), HOP_TIME[moon.id])


def _scan_depart(a1, th1, a2, th2, transit, t, mu=MU_SUN,
                 tol=0.01, step=0.5, horizon=12000.0) -> float:
    """First departure >= t where a Hohmann arc intercepts the target.

    Arrival longitude = departure longitude + pi (prograde half-ellipse), so
    solve wrap(dest_angle(td+transit) - origin_angle(td) - pi) == 0.
    Horizon covers outer-outer synodics (Fulmaior↔Arax: ~20yr).
    """
    n1 = mean_motion(a1, mu)
    n2 = mean_motion(a2, mu)
    rel = n2 - n1
    td = float(t)
    end = t + horizon
    while td <= end:
        miss = _wrap_pi((th2 + n2 * (td + transit)) - (th1 + n1 * td) - math.pi)
        if abs(miss) < tol:
            if abs(rel) > 1e-12:
                for _ in range(4):  # Newton refine on unwrapped miss
                    td -= miss / rel
                    miss = _wrap_pi((th2 + n2 * (td + transit)) - (th1 + n1 * td) - math.pi)
            return td
        if abs(rel) > 1e-12:
            td += min(max(abs(miss / rel) * 0.5, step), 20.0)
        else:
            td += step
    raise WindowError("no launch window within horizon")


def next_window(bodies: dict, origin_id: str, dest_id: str, t_now: float) -> dict:
    """Phase-gated departure preview: moon hop, then helio window, then capture.

    Returns wait/depart/transit/arrival/dv plus transfer geometry for the Leg.
    `helio_arrival_t` is the exact Hohmann intercept (pre moon-capture addon).
    """
    if origin_id not in bodies or dest_id not in bodies:
        raise KeyError("unknown body")
    if origin_id == dest_id:
        raise ValueError("already there")
    o = bodies[origin_id]
    d = bodies[dest_id]
    if o.kind == "star" or d.kind == "star":
        raise ValueError("the star is not a port")
    _refuse_gate(o, d)
    t1 = float(t_now)
    waits: dict = {}
    dv = 0.0

    if o.kind == "moon":
        t1, w, mvd = _moon_departure(bodies, o, t1)
        waits.update(w)
        dv += mvd

    a1, th1 = _helio_pair(bodies, origin_id)
    a2, th2 = _helio_pair(bodies, dest_id)
    if abs(a1 - a2) < 1e-12:
        kind, depart = "hop", t1
        h = {"transit_d": 0.0, "dv": 0.0, "a_trans": a1, "e": 0.0}
    else:
        kind = "hohmann"
        h = hohmann(a1, a2)
        depart = _scan_depart(a1, th1, a2, th2, h["transit_d"], t1)

    helio_arrival = depart + h["transit_d"]
    t_arr = helio_arrival
    if d.kind == "moon":
        wd, burn = _moon_capture_wait(bodies, d, t_arr)
        t_arr += wd + burn
        waits["moon_arrive"] = wd
        dv += MOON_DV[d.id]

    return {
        "kind": kind,
        "wait_d": depart - float(t_now),
        "waits": waits,
        "depart_t": depart,
        "transit_d": t_arr - depart,
        "arrival_t": t_arr,
        "helio_arrival_t": helio_arrival,
        "dv": dv + h["dv"],
        "a1": a1,
        "a2": a2,
        "a_trans": h["a_trans"],
        "e": h["e"],
        "th0": th1 + mean_motion(a1, MU_SUN) * depart,
    }


def fast_option(bodies: dict, origin_id: str, dest_id: str,
                t_now: float, arrive_by: float) -> dict:
    """Leave-now premium: depart at the earliest hop-ready time, arrive by deadline.

    No window wait; cost is hohmann_dv * (1 + (hohmann_time/transit)^2), so a
    deadline near the Hohmann time still costs ~2x (wrong-phase burn), tighter
    deadlines scale steeply. Moon hops stay sequential. Deadlines generous
    enough for a windowed sailing are refused — take the window instead.
    Same dict shape as next_window, kind='fast' (renderer draws it straight).
    """
    if origin_id not in bodies or dest_id not in bodies:
        raise KeyError("unknown body")
    if origin_id == dest_id:
        raise ValueError("already there")
    o = bodies[origin_id]
    d = bodies[dest_id]
    if o.kind == "star" or d.kind == "star":
        raise ValueError("the star is not a port")
    _refuse_gate(o, d)
    t = float(t_now)
    if not arrive_by > t:
        raise ValueError("deadline is in the past")

    t1 = t
    waits: dict = {}
    dv = 0.0
    if o.kind == "moon":
        t1, w, mvd = _moon_departure(bodies, o, t1)
        waits.update(w)
        dv += mvd

    a1, th1 = _helio_pair(bodies, origin_id)
    a2, th2 = _helio_pair(bodies, dest_id)
    same = abs(a1 - a2) < 1e-12
    h = {"transit_d": 0.0, "dv": 0.0, "a_trans": a1, "e": 0.0} if same else hohmann(a1, a2)

    if not same:
        try:
            slow = next_window(bodies, origin_id, dest_id, t)
        except WindowError:
            slow = None
        if slow is not None and arrive_by >= slow["arrival_t"]:
            raise ValueError("deadline allows a windowed sailing; take it")

    hop_burn = HOP_TIME[d.id] if d.kind == "moon" else 0.0
    wd = 0.0
    if d.kind == "moon":
        guess = arrive_by - hop_burn  # fixed-point on arrival moon phase
        for _ in range(4):
            wd, _ = _moon_capture_wait(bodies, d, guess)
            guess = arrive_by - wd - hop_burn
    helio_transit = (arrive_by - wd - hop_burn) - t1
    if not same and helio_transit < 0.1 * h["transit_d"]:
        raise ValueError("deadline unreachable (below minimum-energy transit)")
    if helio_transit < 0:
        raise ValueError("deadline unreachable")

    depart = t1
    helio_arrival = depart + helio_transit
    t_arr = helio_arrival
    if d.kind == "moon":
        t_arr += wd + hop_burn
        waits["moon_arrive"] = wd
        dv += MOON_DV[d.id]
    if t_arr > arrive_by + 0.25:
        raise ValueError("deadline unreachable (moon phase slips it)")

    premium = 1.0 if same or h["transit_d"] <= 0 else 1.0 + (h["transit_d"] / helio_transit) ** 2
    return {
        "kind": "fast" if not same else "hop",
        "wait_d": depart - t,
        "waits": waits,
        "depart_t": depart,
        "transit_d": t_arr - depart,
        "arrival_t": t_arr,
        "helio_arrival_t": helio_arrival,
        "dv": dv + h["dv"] * premium,
        "premium": premium,
        "a1": a1,
        "a2": a2,
        "a_trans": h["a_trans"],
        "e": 0.0,  # fast arcs render straight; no ellipse geometry
        "th0": th1 + mean_motion(a1, MU_SUN) * depart,
    }
