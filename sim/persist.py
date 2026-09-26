"""Persistence: JSON save/load. Bodies are fixture-rebuilt; t/ships/ledger saved.

Saves stamp wall-clock time so loads can apply offline catch-up (the daemon's
morning-check: what happened while you were away).
"""
from __future__ import annotations

import json
import time as walltime

from . import time as simtime
from .state import Game, Leg, Ship, build_sol, seed_gate

SAVE_VERSION = 0


def to_dict(game: Game) -> dict:
    ships = []
    for s in game.ships.values():
        leg = None
        if s.leg is not None:
            leg = {
                "ship_id": s.leg.ship_id, "origin": s.leg.origin, "dest": s.leg.dest,
                "t_depart": s.leg.t_depart, "t_arrive": s.leg.t_arrive, "kind": s.leg.kind,
                "a1": s.leg.a1, "a2": s.leg.a2, "a_trans": s.leg.a_trans,
                "e": s.leg.e, "th0": s.leg.th0,
                "origin_loc": s.leg.origin_loc, "dest_loc": s.leg.dest_loc,
            }
        ships.append({"id": s.id, "name": s.name, "at": s.at, "leg": leg,
                      "cargo_cap": s.cargo_cap, "cargo": dict(s.cargo),
                      "loc": s.loc, "dv_cap": s.dv_cap, "dv": s.dv})
    return {"v": SAVE_VERSION, "t": game.t, "ships": ships,
            "ledger": list(game.ledger), "credits": game.credits,
            "markets": game.markets, "contacts": game.contacts,
            "known": game.known, "contracts": game.contracts,
            "contract_seq": game.contract_seq, "locations": game.locations,
            "meta": {"captain": game.captain, "difficulty": game.difficulty,
                     "campaign": game.campaign, "company": game.company}}


def from_dict(data: dict) -> Game:
    if data.get("v") != SAVE_VERSION:
        raise ValueError(f"unsupported save version {data.get('v')}")
    game = build_sol()
    game.t = data["t"]
    game.ships = {}
    for s in data["ships"]:
        leg = None
        if s["leg"] is not None:
            leg = Leg(s["leg"]["ship_id"], s["leg"]["origin"], s["leg"]["dest"],
                        s["leg"]["t_depart"], s["leg"]["t_arrive"], s["leg"]["kind"],
                        s["leg"].get("a1", 0.0), s["leg"].get("a2", 0.0),
                        s["leg"].get("a_trans", 0.0), s["leg"].get("e", 0.0),
                        s["leg"].get("th0", 0.0),
                        s["leg"].get("origin_loc"), s["leg"].get("dest_loc"))
        game.ships[s["id"]] = Ship(s["id"], s["name"], s["at"], leg,
                                   s.get("cargo_cap", 100.0), s.get("cargo", {}),
                                   s.get("loc"), s.get("dv_cap", 0.25), s.get("dv", 0.25))
    game.ledger = list(data.get("ledger", []))
    game.credits = data.get("credits", 10000.0)
    game.markets = data.get("markets", {})
    game.contacts = data.get("contacts", {})
    game.known = data.get("known", {})
    game.contracts = data.get("contracts", {})
    game.contract_seq = data.get("contract_seq", 0)
    game.locations = data.get("locations", {})
    meta = data.get("meta", {})
    game.captain = meta.get("captain", "Commander")
    game.difficulty = meta.get("difficulty", "balanced")
    game.campaign = meta.get("campaign", "Sol Merchant")
    game.company = meta.get("company", "") or f"{game.captain}'s Company"
    # Gates are fixture state, not player state: re-seed so saves written
    # before the gate existed still come up with the mouth on the chart.
    seed_gate(game)
    return game


def save(game: Game, path: str, wall: float | None = None) -> None:
    data = to_dict(game)
    data["wall"] = walltime.time() if wall is None else wall
    with open(path, "w") as f:
        json.dump(data, f)


def load(path: str) -> Game:
    with open(path) as f:
        return from_dict(json.load(f))


def load_with_catchup(path: str, rate: float = simtime.DAY_PER_SEC,
                       cap_days: float = simtime.CATCHUP_CAP_D,
                       now: float | None = None) -> tuple:
    """Load + apply offline progress. Returns (game, offline_days, reports).

    `rate` is game-days per real second; tests pass rate=1.0 and fake `now`.
    """
    with open(path) as f:
        data = json.load(f)
    game = from_dict(data)
    saved_wall = data.get("wall")
    if saved_wall is None:
        return (game, 0.0, [])
    now = walltime.time() if now is None else now
    advanced, reports = simtime.catch_up(
        game, simtime.offline_days(saved_wall, now, rate), cap_days)
    return (game, advanced, reports)
