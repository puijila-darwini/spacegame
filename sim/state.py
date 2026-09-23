"""Sim state: Sol fixture, bodies, ships. Movement-only v0 (no cargo/markets)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Body:
    id: str  # 'sun','veluvy','nellus','tern','arax','fulmaior','moon','tide'
    name: str
    kind: str  # 'star' | 'planet' | 'moon'
    parent: str | None  # moons -> 'tern', else None
    a: float  # orbital radius at own level: helio for planets, planetocentric for moons
    angle0: float  # phase at t=0, radians


@dataclass
class Leg:
    ship_id: str
    origin: str
    dest: str
    t_depart: float
    t_arrive: float
    kind: str  # 'hohmann' | 'hop' (same-helio moon hop) | 'fast' (leave-now premium)
    a1: float = 0.0
    a2: float = 0.0
    a_trans: float = 0.0
    e: float = 0.0  # signed: (a2-a1)/(a1+a2)
    th0: float = 0.0  # helio departure longitude, radians
    origin_loc: str | None = None
    dest_loc: str | None = None


@dataclass
class Ship:
    id: str
    name: str
    at: str | None  # body id when parked, else None
    leg: Leg | None = None
    cargo_cap: float = 100.0  # tonnes of hold
    cargo: dict = field(default_factory=dict)  # {commodity: tonnes}
    loc: str | None = None  # location id when parked; None in transit/unseeded games
    dv_cap: float = 0.25  # delta-v budget, coherent units with cruise (~0.01-0.03)
    dv: float = 0.25  # current tank


@dataclass
class Game:
    t: float = 0.0  # game time, days
    bodies: dict = field(default_factory=dict)
    ships: dict = field(default_factory=dict)
    ledger: list = field(default_factory=list)  # [{t, kind, msg}] — arrival reports live here
    credits: float = 10000.0  # player capital
    markets: dict = field(default_factory=dict)  # {port_id: book}; empty until markets.seed()
    contacts: dict = field(default_factory=dict)  # {npc_id: npc}; empty until contacts.seed()
    known: dict = field(default_factory=dict)  # {port_id: [party labels met]}
    contracts: dict = field(default_factory=dict)  # {cid: contract}
    contract_seq: int = 0
    locations: dict = field(default_factory=dict)  # {loc_id: location}; empty until infra.seed()


def build_sol() -> Game:
    """Sol system: star Sun, 5 planets in solar order, 2 moons of Tern.

    Periods are MUD-literal (world/astrology.py: Moon 30d, Tide 360/7d,
    Veluvy 72d, Nellus 108d, Tern 360d, Arax 12yr, Fulmaior 29yr); radii are
    Kepler-solved for a single mu, so the sky matches the MUD's clock.
    Tern's moons are Moon (close) + Tide (distant); Fulmaior's are Eope
    (volcanic ocean), Cenaedo (Galilean) + Cteta (Titan analogue, outer).
    """
    bodies = {
        "sun": Body("sun", "Sun", "star", None, 0.0, 0.0),
        "veluvy": Body("veluvy", "Veluvy", "planet", None, 0.3420, 0.0),
        "nellus": Body("nellus", "Nellus", "planet", None, 0.4481, 1.3),
        "tern": Body("tern", "Tern", "planet", None, 1.0, 2.6),
        "arax": Body("arax", "Arax", "planet", None, 5.2415, 4.0),
        "fulmaior": Body("fulmaior", "Fulmaior", "planet", None, 9.4346, 5.2),
        "moon": Body("moon", "Moon", "moon", "tern", 0.025, 0.5),
        "tide": Body("tide", "Tide", "moon", "tern", 0.0358, 2.0),
        "eope": Body("eope", "Eope", "moon", "fulmaior", 0.03, 1.0),
        "cenaedo": Body("cenaedo", "Cenaedo", "moon", "fulmaior", 0.0577, 3.3),
        "cteta": Body("cteta", "Cteta", "moon", "fulmaior", 0.1026, 5.0),
    }
    ships = {"pc1": Ship("pc1", "PC-1", "tide", loc="tide-surface")}
    return Game(t=0.0, bodies=bodies, ships=ships)
