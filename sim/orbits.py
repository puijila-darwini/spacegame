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

from . import lambert

MU_SUN = 0.0003046174  # MUD-literal: Tern (a=1.0) -> 360d year; radii Kepler-solved below
# Planetocentric mu is tied to the moon radii below. The radii are real
# fractions of the heliocentric chart (Moon 0.26% of Tern's orbit, like Earth's
# at 0.257%), so these mu values are correspondingly tiny. n = sqrt(mu/a^3) is
# what actually fixes each moon's period, and the radii are free to be honest:
# scaling a moon's radius by k only requires scaling its parent's mu by k^3 to
# hold the clock.
MU_TERN = 7.709696e-10  # Moon (a=0.00260) -> 30d, Tide (a=0.003726) -> 360/7 d ≈ 51.43d
MU_FULMAIOR = 2.368705e-07  # Eope (a=0.0060) -> 6d, Cenaedo (0.011534) -> 16d, Cteta (0.02054) -> 38d
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


def _scan_depart(a1, th1, a2, th2, transit, t, theta, mu=MU_SUN,
                 tol=0.01, step=0.5, horizon=12000.0) -> float:
    """First departure >= t at which the pair's phase gap equals `theta`.

    `theta = pi` is the original Hohmann gate: the arc sweeps exactly half a
    revolution, so it only launches when the bodies are half a cycle apart.
    A smaller theta accepts less phase, which the pair reaches sooner AND which
    covers the distance in less time -- at higher delta-v (see sim/lambert.py).

    Departures stay phase-gated at EVERY theta; a smaller theta only shortens
    the cycle. It does not let you leave immediately.
    """
    n1 = mean_motion(a1, mu)
    n2 = mean_motion(a2, mu)
    rel = n2 - n1
    td = float(t)
    end = t + horizon
    while td <= end:
        miss = _wrap_pi((th2 + n2 * (td + transit)) - (th1 + n1 * td) - theta)
        if abs(miss) < tol:
            if abs(rel) > 1e-12:
                for _ in range(4):  # Newton refine on unwrapped miss
                    td -= miss / rel
                    miss = _wrap_pi((th2 + n2 * (td + transit)) - (th1 + n1 * td) - theta)
            return td
        if abs(rel) > 1e-12:
            td += min(max(abs(miss / rel) * 0.5, step), 20.0)
        else:
            td += step
    raise WindowError("no launch window within horizon")


def arc_for(a1: float, a2: float, theta: float):
    """The minimum-delta-v Lambert transfer between two helio radii.

    Solved inner-radius-first and cached, so an outward and an inward transfer
    over the same pair SHARE one ellipse. The direction therefore lives on the
    Leg (as a1 < a2), never on the cached arc.
    """
    if abs(a1 - a2) < 1e-12:
        return None
    return lambert.best_arc(min(a1, a2), max(a1, a2), theta, MU_SUN)


def _plan(bodies: dict, origin_id: str, dest_id: str, t_now: float, theta: float) -> dict:
    """One real transfer option: moon legs, Lambert arc, departure, arrival."""
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
    arc = None
    if abs(a1 - a2) < 1e-12:
        kind, depart = "hop", t1
        h = {"transit_d": 0.0, "dv": 0.0, "a_trans": a1, "e": 0.0}
    else:
        kind = "hohmann"
        arc = arc_for(a1, a2, theta)
        if arc is None:
            raise WindowError("no valid transfer arc at theta=%.0f" % math.degrees(theta))
        h = {"transit_d": arc["tof"], "dv": arc["dv"],
             "a_trans": arc["a"], "e": arc["e"]}
        depart = _scan_depart(a1, th1, a2, th2, arc["tof"], t1, theta)

    helio_arrival = depart + h["transit_d"]
    t_arr = helio_arrival
    if d.kind == "moon":
        wd, burn = _moon_capture_wait(bodies, d, t_arr)
        t_arr += wd + burn
        waits["moon_arrive"] = wd
        dv += MOON_DV[d.id]

    out = {
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
        "theta": theta,
        "arc": arc,
    }
    if arc is not None:
        out.update({"nu1": arc["nu1"], "p": arc["p"], "dm": arc["dm"],
                    "m0": arc["m0"],
                    "periapsis": arc["periapsis"], "apoapsis": arc["apoapsis"],
                    "cruise_dv": arc["dv"]})
    return out


def next_window(bodies: dict, origin_id: str, dest_id: str, t_now: float) -> dict:
    """The cheapest option: the classic Hohmann window (theta = pi).

    This is the default so every existing route, contract and test keeps its
    meaning. `transfer_options` exposes the faster, dearer arcs.
    """
    if origin_id not in bodies or dest_id not in bodies:
        raise KeyError("unknown body")
    if origin_id == dest_id:
        raise ValueError("already there")
    return _plan(bodies, origin_id, dest_id, t_now, math.pi)


# The ladder the flight planner offers. 180 is the window: cheapest fuel, and
# the longest wait and transit. 90 sits near the knee of the speed curve. Below
# about 70 the transit stops improving while the fuel keeps climbing.
ARC_ANGLES = (180.0, 165.0, 150.0, 135.0, 120.0, 105.0, 90.0, 75.0)

# Below ~45 deg the ellipse goes hyperbolic or the speed curve has already
# turned back on itself, so that is the floor for anything we will price.
FULL_ARC_DEG = 45.0

# The deadline path searches a finer ladder than the planner shows, so a tight
# deadline still finds the cheapest arc that fits rather than being refused for
# want of a near-enough candidate.
DEADLINE_ARC_DEGREES = tuple(range(180, 44, -5))


def transfer_options(bodies: dict, origin_id: str, dest_id: str, t_now: float,
                     angles=None) -> list:
    """Every real arc available, each with its own wait, transit and price.

    All of them are phase-gated. A smaller theta shortens the wait AND the
    transit and raises the fuel price; it never removes the window.
    """
    if origin_id not in bodies or dest_id not in bodies:
        raise KeyError("unknown body")
    if origin_id == dest_id:
        raise ValueError("already there")
    out = []
    for deg in (angles or ARC_ANGLES):
        try:
            opt = _plan(bodies, origin_id, dest_id, t_now, math.radians(deg))
            opt["angle_deg"] = deg
            out.append(opt)
        except (WindowError, ValueError):
            continue
    # A same-helio-radius hop (moon to moon, or a world to its own moon) has no
    # transfer angle: every theta yields the identical plan. Collapse those, or
    # the planner shows the player eight copies of one choice.
    seen = set()
    uniq = []
    for o in out:
        key = (round(o["depart_t"], 6), round(o["arrival_t"], 6), round(o["dv"], 9))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(o)
    # Soonest arrival first: because the wait is phase-dependent, theta order is
    # not arrival order, and the player's question is "when do I get there".
    uniq.sort(key=lambda o: o["arrival_t"])
    return uniq


def fast_option(bodies: dict, origin_id: str, dest_id: str,
                t_now: float, arrive_by: float) -> dict:
    """The cheapest arc that still makes `arrive_by`. Real geometry, no premium.

    Replaces an invented `1 + (t_hohmann/t)^2` surcharge. Scans the theta ladder
    rather than bisecting it, because ARRIVAL IS NOT MONOTONIC IN THETA: the
    wait depends on where the pair currently sits in its cycle, so a smaller
    theta can be both faster and slower to catch. From Tide at t=0 the 90-degree
    departure waits 46 days while the 120-degree one waits 412 -- the phase gap
    is simply near 90 right now. A bisection on arrival time is therefore wrong
    and was replaced by an exhaustive pick of the cheapest arrival that fits.
    """
    if origin_id not in bodies or dest_id not in bodies:
        raise KeyError("unknown body")
    if origin_id == dest_id:
        raise ValueError("already there")
    if not arrive_by > t_now:
        raise ValueError("deadline is in the past")

    slow = next_window(bodies, origin_id, dest_id, t_now)
    if slow["arrival_t"] <= arrive_by:
        raise ValueError("deadline allows a windowed sailing; take it")

    best = None
    for deg in DEADLINE_ARC_DEGREES:
        try:
            opt = _plan(bodies, origin_id, dest_id, t_now, math.radians(deg))
        except (WindowError, ValueError):
            continue
        if opt["arrival_t"] > arrive_by:
            continue
        if best is None or opt["dv"] < best["dv"]:
            best = opt
    if best is None:
        raise ValueError("deadline unreachable on any arc in the ladder")
    best["kind"] = "hohmann"
    return best
