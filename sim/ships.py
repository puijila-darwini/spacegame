"""Ships: plot / commit / update. Movement only (no cargo yet)."""
from __future__ import annotations

import math

from . import infra, orbits
from .state import Game, Leg


def _price(w: dict, game: Game, ship, dest_id: str, dest_loc: str | None,
           arrive_by) -> dict:
    """Attach location costs and a summary line to a raw transfer plan.

    Every option gets its own summary -- the planner shows the selected arc's
    line, so a missing key here renders as the literal string "undefined".
    """
    origin_loc = game.locations.get(ship.loc or "")
    climb = origin_loc["depart_dv"] if origin_loc else 0.0
    if dest_loc is None:
        dest_loc = infra.default_dest(game, dest_id)
    dest_entry = game.locations.get(dest_loc or "")
    descent = dest_entry["arrive_dv"] if dest_entry else 0.0
    w.update({"origin_loc": ship.loc, "dest_loc": dest_loc,
              "climb_dv": climb, "descent_dv": descent,
              "total_dv": w["dv"] + climb + descent})
    ang = math.degrees(w.get("theta", math.pi))
    w["summary"] = (
        f"{ship.name}: {ship.loc or ship.at} -> {w['dest_loc'] or dest_id} "
        f"{'DEADLINE ' if arrive_by is not None else f'{ang:.0f}deg '}| "
        f"wait {w['wait_d']:.1f}d transit {w['transit_d']:.1f}d "
        f"arrive t={w['arrival_t']:.1f} cruise {w['dv']:.3f} "
        f"climb {climb:.3f} descent {descent:.3f} "
        f"total {w['total_dv']:.3f}"
    )
    return w


def plot(game: Game, ship_id: str, dest_id: str, dest_loc: str | None = None,
         t_now: float | None = None, arrive_by: float | None = None,
         theta: float | None = None, with_options: bool = False) -> dict:
    """Commit preview: mass x dv x time shape that markets will later price.

    `theta` picks a transfer angle in RADIANS (see sim/lambert.py): pi is the
    classic Hohmann window, smaller angles cover the same distance sooner and
    cost more fuel. `arrive_by` instead asks for the cheapest arc that still
    makes a deadline.

    `with_options` attaches `options`: every arc on the ladder with its own
    wait, transit, fuel price and arrival -- the flight planner's menu.
    """
    t = game.t if t_now is None else t_now
    ship = game.ships[ship_id]
    if ship.leg is not None:
        raise ValueError("ship is in transit")
    if ship.at is None:
        raise ValueError("ship has no position")
    if dest_id not in game.bodies:
        raise KeyError(dest_id)
    if dest_id == ship.at:
        raise ValueError("already there")

    if arrive_by is not None:
        w = orbits.fast_option(game.bodies, ship.at, dest_id, t, arrive_by)
    elif theta is not None:
        w = orbits._plan(game.bodies, ship.at, dest_id, t, theta)
    else:
        w = orbits.next_window(game.bodies, ship.at, dest_id, t)
    _price(w, game, ship, dest_id, dest_loc, arrive_by)

    if with_options:
        w["options"] = []
        try:
            raw = orbits.transfer_options(game.bodies, ship.at, dest_id, t)
        except (ValueError, KeyError):
            raw = []
        for opt in raw:
            o = _price(dict(opt), game, ship, dest_id, dest_loc, arrive_by)
            w["options"].append(o)

    return w


def commit(game: Game, ship_id: str, dest_id: str, dest_loc: str | None = None,
           t_now: float | None = None, arrive_by: float | None = None,
           theta: float | None = None) -> Leg:
    t = game.t if t_now is None else t_now
    ship = game.ships[ship_id]
    w = plot(game, ship_id, dest_id, dest_loc, t, arrive_by, theta)
    if w["total_dv"] > ship.dv:
        raise ValueError(f"needs {w['total_dv']:.3f} dv, have {ship.dv:.3f} — refuel at a station")
    ship.dv -= w["total_dv"]
    leg = Leg(
        ship_id=ship_id, origin=ship.at or "", dest=dest_id,
        t_depart=w["depart_t"], t_arrive=w["arrival_t"], kind=w["kind"],
        a1=w["a1"], a2=w["a2"], a_trans=w["a_trans"], e=w["e"], th0=w["th0"],
        origin_loc=w["origin_loc"], dest_loc=w["dest_loc"],
        theta=w.get("theta", 0.0), nu1=w.get("nu1", 0.0), p=w.get("p", 0.0),
        dm=w.get("dm", 0.0), m0=w.get("m0", 0.0),
        periapsis=w.get("periapsis", 0.0), apoapsis=w.get("apoapsis", 0.0),
    )
    ship.leg = leg
    ship.at = None
    ship.loc = None
    return leg


def update(game: Game) -> list:
    """Settle arrived legs. Appends arrival reports to the ledger (the payoff).

    Returns arrival reports [(ship_id, dest, t_arrive)].
    """
    arrived = []
    for ship in game.ships.values():
        leg = ship.leg
        if leg is not None and game.t >= leg.t_arrive:
            ship.at = leg.dest
            ship.leg = None
            if leg.dest_loc:
                ship.loc = leg.dest_loc
            arrived.append((ship.id, leg.dest, leg.t_arrive))
            dest_name = game.bodies[leg.dest].name if leg.dest in game.bodies else leg.dest
            loc_name = ""
            if leg.dest_loc and leg.dest_loc in game.locations:
                loc_name = f" ({game.locations[leg.dest_loc]['name']})"
            game.ledger.append({
                "t": round(leg.t_arrive, 2),
                "kind": "arrival",
                "msg": f"{ship.name} arrived at {dest_name}{loc_name}",
            })
    return arrived
