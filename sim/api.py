"""sim -> renderer contract v3: snapshot(t) the web canvas just draws.

Shape:
{v:3, t, credits, campaign:{captain,difficulty,name,company}, bodies:[{id,name,parent,kind,a,period,angle,x,y}],
 ships:[{id,name,at,loc,loc_to,leg,x,y,progress,eta_d,arc_pts,cargo,cargo_cap,dv,dv_cap}],
 ports:{port_id:{asks,bids,last}}, ledger:[...],
 locations:[{id,name,body,kind,depart_dv,arrive_dv,service,x,y,orbit_a,orbit_period,orbit_angle}],
 contacts:[{id,name,port,occupation,reliability,rapport}],
 known:{port_id:[parties]},
 contracts:[{id,issuer,port,dest,comm,qty,delivered,price,deadline,status,known}],
 gates:[{id,body,status,dest_system,note,open_t,eta_d,transit}]}
Hohmann legs interpolate the transfer ellipse; fast/hop legs render straight.
Order lines carry a `known` flag (party met?) and contracts carry one too —
the renderer dims the unknown; the sim still settles everything. That is the
known-subset rule: at-port you see all, off-port only what your network knows.
`ledger` carries the last 50 entries — the morning-check payoff.
"""
from __future__ import annotations

import math

from . import orbits
from .state import Game, gate_state

SNAPSHOT_VERSION = 3

# Renderer-side local geometry for stations and terminals. These are
# deliberately tiny planetocentric offsets, not navigation radii: they make
# orbital infrastructure inspectable when the camera zooms into a world without
# changing the movement simulation. They must stay far INSIDE the innermost
# moon (Tern's Moon rides at a=0.20) or the system reads inside-out — orbital
# infrastructure would appear to sit beyond the moons. Surfaces remain
# body-anchored locations and have no ring.
LOCATION_ORBITS = {
    "terminal": (0.012, 1.8, 1.3),
    "station": (0.020, 2.6, 2.4),
}


def _location_pos(game: Game, loc: dict) -> tuple[float, float, float, float]:
    body = game.bodies[loc["body"]]
    bx, by, _ = orbits.body_pos(body, game.bodies, game.t)
    if loc["kind"] == "surface":
        return (bx, by, 0.0, 0.0)
    orbit_a, period_d, phase = LOCATION_ORBITS[loc["kind"]]
    angle = phase + math.tau * game.t / period_d
    return (bx + orbit_a * math.cos(angle),
            by + orbit_a * math.sin(angle), orbit_a, angle)


def _kepler_E(M: float, e: float) -> float:
    """Eccentric anomaly from mean anomaly (Newton; e < 1 always here)."""
    E = M + e * math.sin(M)
    for _ in range(8):
        E -= (E - e * math.sin(E) - M) / (1 - e * math.cos(E))
    return E


def _transfer_polar(leg, f: float) -> tuple[float, float]:
    """Orbital position at fraction f along a Hohmann transfer.

    Uses Kepler's equation to solve for eccentric anomaly E from mean anomaly M,
    then converts to true anomaly nu via the standard two-body formula. The orbit
    sweeps equal area in equal time: slower at aphelion (outer system), faster at
    perihelion (inner system). Correctly handles both outward and inward legs.
    """
    e_abs = abs(leg.e)
    f = min(max(f, 0.0), 1.0)
    # Outward legs run perihelion -> aphelion. Inward legs traverse the same
    # ellipse in reverse, aphelion -> perihelion, so solve Kepler backwards
    # from the next perihelion rather than starting a second forward orbit.
    M = math.pi * (f if leg.e >= 0 else 1.0 - f)
    E = M + e_abs * math.sin(M)
    for _ in range(8):
        E -= (E - e_abs * math.sin(E) - M) / (1 - e_abs * math.cos(E))
    nu = 2 * math.atan2(math.sqrt(1 + e_abs) * math.sin(E / 2),
                        math.sqrt(1 - e_abs) * math.cos(E / 2))
    r = leg.a_trans * (1 - e_abs * math.cos(E))
    return (r, leg.th0 + nu)


def transfer_pos(leg, bodies: dict, t: float) -> tuple[float, float]:
    if leg.kind != "hohmann" or abs(leg.a1 - leg.a2) < 1e-12 or leg.a_trans <= 0:
        span = max(leg.t_arrive - leg.t_depart, 1e-9)
        f = min(max((t - leg.t_depart) / span, 0.0), 1.0)
        ox, oy, _ = orbits.body_pos(bodies[leg.origin], bodies, leg.t_depart)
        dx, dy, _ = orbits.body_pos(bodies[leg.dest], bodies, leg.t_arrive)
        return (ox + (dx - ox) * f, oy + (dy - oy) * f)
    span = max(leg.t_arrive - leg.t_depart, 1e-9)
    f = min(max((t - leg.t_depart) / span, 0.0), 1.0)
    r, ang = _transfer_polar(leg, f)
    return (r * math.cos(ang), r * math.sin(ang))


def arc_points(leg, n: int = 25) -> list:
    if leg.kind != "hohmann" or abs(leg.a1 - leg.a2) < 1e-12 or leg.a_trans <= 0:
        return []
    pts = []
    for i in range(n + 1):
        r, ang = _transfer_polar(leg, i / n)  # time-uniform: dots bunch at aphelion
        pts.append([round(r * math.cos(ang), 4), round(r * math.sin(ang), 4)])
    return pts


def _book_side(orders: dict, known: set) -> dict:
    return {c: [[round(p, 2), round(q, 2), party, party in known]
                for p, q, party in lines]
            for c, lines in orders.items()}


def snapshot(game: Game) -> dict:
    bodies = []
    for b in game.bodies.values():
        x, y, th = orbits.body_pos(b, game.bodies, game.t)
        mu = orbits.MU_BY_PARENT.get(b.parent, orbits.MU_SUN) if b.parent else orbits.MU_SUN
        period = orbits.period(b.a, mu) if b.a > 0 else 0.0
        bodies.append({
            "id": b.id, "name": b.name, "parent": b.parent, "kind": b.kind,
            "a": b.a, "period": period,
            "angle": round(th, 4), "x": round(x, 4), "y": round(y, 4),
        })
    ships = []
    for s in game.ships.values():
        entry_name = s.name
        if s.leg is not None:
            x, y = transfer_pos(s.leg, game.bodies, game.t)
            span = max(s.leg.t_arrive - s.leg.t_depart, 1e-9)
            raw = (game.t - s.leg.t_depart) / span
            entry = {
                "id": s.id, "at": None, "loc": None, "loc_to": s.leg.dest_loc,
                "leg": {"from": s.leg.origin, "to": s.leg.dest},
                "x": round(x, 4), "y": round(y, 4),
                "progress": round(min(max(raw, 0.0), 1.0), 4),
                "eta_d": round(s.leg.t_arrive - game.t, 2),
                "arc_pts": arc_points(s.leg),
            }
        else:
            x, y, _ = orbits.body_pos(game.bodies[s.at], game.bodies, game.t)
            entry = {
                "id": s.id, "at": s.at, "loc": s.loc, "loc_to": None, "leg": None,
                "x": round(x, 4), "y": round(y, 4),
                "progress": 1.0, "eta_d": 0.0, "arc_pts": [],
            }
        entry["cargo"] = dict(s.cargo)
        entry["name"] = entry_name
        entry["cargo_cap"] = s.cargo_cap
        entry["dv"] = round(s.dv, 4)
        entry["dv_cap"] = s.dv_cap
        ships.append(entry)
    ports = {}
    for pid, port in game.markets.items():
        known = set(game.known.get(pid, []))
        ports[pid] = {"asks": _book_side(port["asks"], known),
                      "bids": _book_side(port["bids"], known),
                      "last": port["last"]}
    ledger = list(game.ledger[-50:])
    contact_list = [{"id": n["id"], "name": n["name"], "port": n["port"],
                     "occupation": n["occupation"], "reliability": n["reliability"],
                     "rapport": n["rapport"]} for n in game.contacts.values()]
    contract_list = []
    for c in game.contracts.values():
        known = c["issuer"] in game.known.get(c["port"], [])
        contract_list.append({**c, "known": known})
    locations = []
    for loc in game.locations.values():
        lx, ly, orbit_a, orbit_angle = _location_pos(game, loc)
        orbit_period = 0.0 if loc["kind"] == "surface" else LOCATION_ORBITS[loc["kind"]][1]
        locations.append({"id": loc["id"], "name": loc["name"], "body": loc["body"],
                          "kind": loc["kind"], "depart_dv": loc["depart_dv"],
                          "arrive_dv": loc["arrive_dv"], "service": loc["service"],
                          "x": round(lx, 6), "y": round(ly, 6),
                          "orbit_a": orbit_a, "orbit_period": orbit_period,
                          "orbit_angle": round(orbit_angle, 6)})
    return {"v": SNAPSHOT_VERSION, "t": round(game.t, 2), "credits": round(game.credits, 2),
            "campaign": {"captain": game.captain, "difficulty": game.difficulty,
                         "name": game.campaign, "company": game.company},
            "bodies": bodies, "ships": ships, "ports": ports, "ledger": ledger,
            "locations": locations, "gates": gate_state(game),
            "contacts": contact_list, "known": {k: list(v) for k, v in game.known.items()},
            "contracts": contract_list}
