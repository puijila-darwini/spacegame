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

# Sidereal rotation periods, in game-days. Needed because a space elevator's
# counterweight must hang in a SYNCHRONOUS orbit: the tether is fixed to the
# ground, so the terminal's orbital period IS the host's sidereal rotation.
# Without this the elevator had an invented 1.8d period and nothing tied it to
# the planet it hangs from. Slow rotators (0.9-1.8d) keep the tether stable
# and the 0.006dv elevator ride honest against a ~0.01-0.03 cruise.
ROTATION = {
    "tern": 0.90, "veluvy": 1.40, "nellus": 1.10, "arax": 1.80,
    "fulmaior": 1.25, "moon": 4.20, "tide": 2.00,
    "eope": 1.20, "cenaedo": 1.60, "cteta": 2.50,
}

# Radius of the SYNCHRONOUS (geostationary) orbit per body, in the same AU-ish
# units as the heliocentric chart. Renderer geometry, not a navigation radius:
# real Earth's synchronous orbit is 35,786 km = 0.000239 AU, and 0.000239 /
# 0.00257 = 9.3% of the Moon's orbit, which is the ratio that makes an
# elevator read correctly next to a moon. Bigger worlds get bigger geos.
SYNCHRONOUS_R = {
    "tern": 0.000240, "veluvy": 0.000240, "nellus": 0.000255,
    "arax": 0.000205, "fulmaior": 0.000720,
}
DEFAULT_SYNCHRONOUS_R = 0.000240
# A station is ordinary low orbit, well inside the synchronous shell, and
# therefore much faster than the ground turns. At 0.55 of the synchronous
# radius a co-rotating frame would need ~0.16x the rotation period.
STATION_ORBIT_FRAC = 0.55
STATION_PERIOD_FRAC = 0.16
# Phases are arbitrary chart offsets, chosen so rings do not line up.
PHASE_TERMINAL = 1.3
PHASE_STATION = 2.4


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
        # Planetocentric radii are real: Moon 0.26% of Tern's heliocentric
        # radius (Earth/Moon is 0.257%), Cteta 0.22% of Fulmaior's (Jupiter's
        # Callisto is 0.24%). Periods are fixed by the parent's mu, not by
        # these numbers -- see sim/orbits.py. The renderer fits a system view
        # to the outermost ring, so absolute scale is invisible there; what
        # these numbers control is the HELIOCENTRIC view, where a moon system
        # correctly collapses to a speck. Cranking them up to look good in a
        # zoomed system view is what put Tern's moons at 20% of its own orbit.
        "moon": Body("moon", "Moon", "moon", "tern", 0.00260, 0.5),
        "tide": Body("tide", "Tide", "moon", "tern", 0.003726, 2.0),
        "eope": Body("eope", "Eope", "moon", "fulmaior", 0.00600, 1.0),
        "cenaedo": Body("cenaedo", "Cenaedo", "moon", "fulmaior", 0.011534, 3.3),
        "cteta": Body("cteta", "Cteta", "moon", "fulmaior", 0.020540, 5.0),
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


def rotation_period(body_id: str) -> float:
    """Sidereal rotation in days. The synchronous orbit's period, by definition."""
    return ROTATION.get(body_id, 1.0)


def orbit_geometry(loc: dict) -> tuple[float, float, float]:
    """(orbit_a, period_d, phase) for a non-surface location.

    A terminal is in a SYNCHRONOUS orbit, so its period is exactly the host
    world's sidereal rotation -- that is what makes a tether stable and why the
    elevator undercuts a rocket. A station is ordinary low orbit: inside the
    synchronous shell and correspondingly faster.
    """
    body = loc["body"]
    rot = rotation_period(body)
    if loc["kind"] == "terminal":
        return (SYNCHRONOUS_R.get(body, DEFAULT_SYNCHRONOUS_R), rot, PHASE_TERMINAL)
    a = STATION_ORBIT_FRAC * SYNCHRONOUS_R.get(body, DEFAULT_SYNCHRONOUS_R)
    return (a, rot * STATION_PERIOD_FRAC, PHASE_STATION)


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
