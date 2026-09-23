"""Locations & fuel (M6): gravity wells have structure (GDD §5, §14).

Each planet has a surface port plus a low-orbit station; Tern, Nellus and
Fulmaior also run space-side elevator terminals. Every interplanetary leg
pays climb (departure location) + cruise (helio) + descent (arrival location)
from the ship's dv budget — position in the network beats raw thrust, and
the elevator undercuts rockets exactly the way infrastructure should.

Fuel is propellant at local ask prices: refuel only where serviced
(stations/terminals), never on bare moon dirt. dv units cohere with cruise
(~0.01-0.03 per crossing); PC-1's 0.25 tank flies ~4 well-to-well trips.
"""
from __future__ import annotations

from . import time as simtime

# body -> (surface name, climb dv, descent dv). Atmosphere halves the way down.
SURFACE = {
    "tern": ("Tern Surface", 0.060, 0.030),
    "veluvy": ("Veluvy Surface", 0.045, 0.022),
    "nellus": ("Nellus Surface", 0.055, 0.027),
    "arax": ("Arax Surface", 0.030, 0.021),
    "fulmaior": ("Fulmaior Cloudtops", 0.090, 0.045),
    "moon": ("Moon Surface", 0.012, 0.011),
    "tide": ("Tide Surface", 0.008, 0.007),
    "eope": ("Eope Surface", 0.010, 0.009),
    "cenaedo": ("Cenaedo Surface", 0.008, 0.007),
    "cteta": ("Cteta Surface", 0.010, 0.004),  # thick Titan-like air: cheap down, pricey up
}

# body -> terminal name. Elevator ride replaces the rocket climb.
ELEVATORS = {
    "tern": "Tern Elevator Crown",
    "nellus": "Nellus Skyhook",
    "fulmaior": "Fulmaior Skyhook",
}
TERMINAL_DV = 0.006

# body -> station name. Staging, services, fuel — no markets yet (yards later).
STATIONS = {
    "tern": "Tern Highport",
    "veluvy": "Veluvy Halo",
    "nellus": "Nellus Halo",
    "arax": "Arax Gateway",
    "fulmaior": "Fulmaior Anchorage",
}
STATION_DV = 0.008

# local legs by location-kind pair: (days, dv). Elevator is slow and nearly free.
LOCAL = {
    ("surface", "terminal"): (2.0, 0.002),
    ("surface", "station"): (0.5, 0.020),
    ("terminal", "station"): (0.75, 0.008),
}

FALLBACK_FUEL = 120.0


def seed(game) -> None:
    """Build every location. Run after markets.seed (fuel pricing reads books)."""
    game.locations = {}
    for body, (name, up, down) in SURFACE.items():
        game.locations[f"{body}-surface"] = {
            "id": f"{body}-surface", "name": name, "body": body, "kind": "surface",
            "depart_dv": up, "arrive_dv": down, "service": False}
    for body, name in ELEVATORS.items():
        game.locations[f"{body}-terminal"] = {
            "id": f"{body}-terminal", "name": name, "body": body, "kind": "terminal",
            "depart_dv": TERMINAL_DV, "arrive_dv": TERMINAL_DV, "service": True}
    for body, name in STATIONS.items():
        game.locations[f"{body}-station"] = {
            "id": f"{body}-station", "name": name, "body": body, "kind": "station",
            "depart_dv": STATION_DV, "arrive_dv": STATION_DV, "service": True}
    for ship in game.ships.values():
        if ship.at and not ship.loc:
            ship.loc = f"{ship.at}-surface"


def default_dest(game, body_id: str) -> str | None:
    """Where arrivals come down: the station if there is one, else the surface."""
    if not game.locations:
        return None
    station = f"{body_id}-station"
    if station in game.locations:
        return station
    surface = f"{body_id}-surface"
    return surface if surface in game.locations else None


def _edge(kind_a: str, kind_b: str) -> tuple[float, float]:
    if (kind_a, kind_b) in LOCAL:
        return LOCAL[(kind_a, kind_b)]
    if (kind_b, kind_a) in LOCAL:
        return LOCAL[(kind_b, kind_a)]
    raise ValueError(f"no local leg {kind_a} <-> {kind_b}")


def transfer_local(game, ship_id: str, loc_id: str) -> dict:
    """Ride the elevator / shuttle between locations on the same body."""
    ship = game.ships[ship_id]
    if ship.leg is not None:
        raise ValueError("ship is in transit")
    dest = game.locations[loc_id]
    if dest["body"] != ship.at:
        raise ValueError(f"{dest['name']} is not at {ship.at}")
    if ship.loc == loc_id:
        raise ValueError("already here")
    origin = game.locations.get(ship.loc or "")
    if origin is None:
        raise ValueError("ship has no location")
    days, dv = _edge(origin["kind"], dest["kind"])
    if ship.dv < dv:
        raise ValueError(f"local transfer needs {dv:.3f} dv, have {ship.dv:.3f}")
    ship.dv -= dv
    ship.loc = loc_id
    simtime.advance(game, days)
    return {"loc": loc_id, "days": days, "dv": dv}


def fuel_price(game, body_id: str) -> float:
    """Propellant ask at the body, else the fallback. Stations price off the surface book."""
    port = game.markets.get(body_id, {})
    asks = (port.get("asks") or {}).get("propellant", [])
    live = [a[0] for a in asks if a[1] > 1e-9]
    return min(live) if live else FALLBACK_FUEL


def refuel(game, ship_id: str) -> dict:
    """Fill the tank where serviced. Costs propellant money + a day."""
    ship = game.ships[ship_id]
    if ship.leg is not None:
        raise ValueError("ship is in transit")
    loc = game.locations.get(ship.loc or "")
    if loc is None or not loc["service"]:
        raise ValueError("no fuel services here — dock at a station or terminal")
    need = ship.dv_cap - ship.dv
    if need <= 1e-9:
        return {"taken": 0.0, "cost": 0.0}
    price = fuel_price(game, ship.at or "")
    cost = need * price
    if game.credits < cost:
        raise ValueError(f"fuel costs {cost:.0f}cr, have {game.credits:.0f}cr")
    game.credits -= cost
    ship.dv = ship.dv_cap
    simtime.advance(game, 1.0)
    game.ledger.append({"t": round(game.t, 2), "kind": "service",
                        "msg": f"{ship.name} refueled {need:.3f} dv at {loc['name']} ({cost:.0f}cr)"})
    return {"taken": need, "cost": cost}
