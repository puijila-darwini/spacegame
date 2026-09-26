"""Sim state: Sol fixture, bodies, ships. Movement-only v0 (no cargo/markets)."""
from __future__ import annotations

from dataclasses import dataclass, field

# --- Inter-system groundwork -------------------------------------------------
# The Fulmaior Gate is the first anchor outside Sol. It is a real body on the
# real map with a real time-driven lifecycle, so the far side is something the
# player watches approach rather than a surprise. Transit is deliberately NOT
# wired up yet: `orbits` refuses the gate and the far system fixture below is
# data only. See gdd/gdd.md §22.
GATE_ID = "fulmaior-gate"
GATE_BODY = "gate"
GATE_OPEN_T = 400.0  # game-days before the mouth stabilises (~1.1 Tern years)
GATE_DEST_SYSTEM = "Alpha Phocae"


@dataclass
class Body:
    id: str  # 'sun','veluvy','nellus','tern','arax','fulmaior','moon','tide','gate'
    name: str
    kind: str  # 'star' | 'planet' | 'moon' | 'wormhole'
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
    captain: str = "Commander"  # campaign identity, set by NEW GAME
    company: str = ""  # trading company, set by NEW GAME
    difficulty: str = "balanced"  # campaign difficulty label
    campaign: str = "Sol Merchant"
    gates: dict = field(default_factory=dict)  # {gate_id: gate}; see gate_state()


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
        # Planetocentric radii are sized for the renderer: the innermost moon
        # sits well outside the planet's drawn disc, and station/terminal rings
        # sit far inside the innermost moon. Periods are fixed by the parent's
        # mu (see sim/orbits.py), not by these numbers.
        "moon": Body("moon", "Moon", "moon", "tern", 0.2000, 0.5),
        "tide": Body("tide", "Tide", "moon", "tern", 0.2864, 2.0),
        "eope": Body("eope", "Eope", "moon", "fulmaior", 0.1800, 1.0),
        "cenaedo": Body("cenaedo", "Cenaedo", "moon", "fulmaior", 0.3462, 3.3),
        "cteta": Body("cteta", "Cteta", "moon", "fulmaior", 0.6156, 5.0),
        # The gate rides beyond Fulmaior's 9.43 so it reads as the edge of the
        # charted system, not as another planet in it. The renderer fits the
        # overview to the outermost charted body, so it stays on screen.
        "gate": Body("gate", "Fulmaior Gate", "wormhole", None, 15.0, 3.1),
    }
    ships = {"pc1": Ship("pc1", "PC-1", "tide", loc="tide-surface")}
    return Game(t=0.0, bodies=bodies, ships=ships)


def gate_state(game: Game) -> list:
    """Live gate readings for the renderer.

    Derived from game time so the mouth is something the player watches
    approach: sealed -> stabilising -> open. The far side is not surveyed yet,
    so `transit` stays false however long you wait.
    """
    out = []
    for gate_id, gate in game.gates.items():
        left = gate["open_t"] - game.t
        if left <= 0.0:
            status, note = "open", (
                f"The mouth is stable. {gate['dest_system']} is visible on the far side, "
                "but no transit is commissioned — the crossing needs a hull rated for it.")
        elif left < 120.0:
            status = "stabilising"
            note = (f"Stabilising — the mouth opens in {left:.0f}d "
                    f"(t={gate['open_t']:.0f}). {gate['dest_system']} lies beyond.")
        else:
            status = "sealed"
            note = (f"Sealed. Charts put the mouth open in {left:.0f}d "
                    f"(t={gate['open_t']:.0f}). {gate['dest_system']} lies beyond.")
        out.append({"id": gate_id, "body": gate["body"], "status": status,
                    "dest_system": gate["dest_system"], "note": note,
                    "open_t": gate["open_t"], "eta_d": max(0.0, left),
                    "transit": False})
    return out


def seed_gate(game: Game) -> None:
    """Install the Sol-side gate. Run from the same place as the other seeds."""
    game.gates = {GATE_ID: {"id": GATE_ID, "body": GATE_BODY,
                            "open_t": GATE_OPEN_T, "dest_system": GATE_DEST_SYSTEM}}


def build_alpha_phocae() -> dict:
    """Far-side fixture — data only; not loaded into a Game yet.

    Exists so the gate's promise is concrete and so the shape of a second
    system is already decided: a hot inner world, a temperate middle, a cold
    outer, and one moon. Heliocentric periods use MU_SOL_FAR, chosen so the
    outer planet rides a ~40 year clock like Fulmaior does at home.
    """
    mu = 0.0003046174  # same sol-type primary; radii re-tuned per system
    return {
        "star": Body("aph-star", "Aphaedra", "star", None, 0.0, 0.0),
        "caldris": Body("caldris", "Caldris", "planet", None, 0.61, 0.4),
        "sarrow": Body("sarrow", "Sarrow", "planet", None, 1.0, 2.2),
        "vane": Body("vane", "Vane", "planet", None, 6.05, 4.4),
        "thole": Body("thole", "Thole", "planet", None, 11.9, 5.6),
        "sarrow-b": Body("sarrow-b", "Brume", "moon", "sarrow", 0.22, 1.4),
    }
