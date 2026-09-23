"""Basic markets (M2): local order books, no global ticker.

Each port has standing asks/bids per commodity plus a last-trade tape.
Production adds asks daily; consumption lifts them; emptied books nudge base
prices (shortage up, glut down). The player trades market orders into the
book — big buys exhaust supply and move the market. Remote visibility and
real NPC counterparties come in M3; for now every port's full book is shown
and party labels are plain strings.
"""
from __future__ import annotations

from . import contacts

COMMODITIES = {
    "ore": {"name": "Ore", "kind": "bulk", "base": 40.0},
    "water": {"name": "Water", "kind": "bulk", "base": 25.0},
    "grain": {"name": "Grain", "kind": "biologic", "base": 60.0},
    "parts": {"name": "Parts", "kind": "input", "base": 220.0},
    "propellant": {"name": "Propellant", "kind": "input", "base": 120.0},
    "vaccines": {"name": "Vaccines", "kind": "biologic", "base": 900.0},
}

# port_id -> {seller, buyer, flows: {comm: (ask_base, prod_t/day, cons_t/day)}}
# Persistent differences are the point (GDD §6): Tern grows, Veluvy mines,
# Nellus builds, Arax strains, Fulmaior fuels, outposts pay premiums.
PORTS = {
    "tern": {"seller": "Tern Grain Board", "buyer": "Tern Factors", "flows": {
        "grain": (55, 12, 8), "parts": (240, 1, 3), "vaccines": (880, 1, 1),
        "ore": (44, 2, 6), "water": (28, 4, 9), "propellant": (130, 2, 4)}},
    "veluvy": {"seller": "Veluvy Smelters", "buyer": "Veluvy Combine", "flows": {
        "ore": (32, 15, 4), "water": (30, 1, 6), "parts": (250, 0, 2),
        "grain": (68, 0, 4), "propellant": (140, 1, 3)}},
    "nellus": {"seller": "Nellus Works", "buyer": "Nellus Factors", "flows": {
        "parts": (200, 6, 2), "ore": (46, 2, 8), "grain": (64, 1, 5),
        "water": (30, 2, 5), "propellant": (135, 1, 3)}},
    "arax": {"seller": "Arax Yard", "buyer": "Arax Cooperative", "flows": {
        "water": (22, 8, 5), "grain": (70, 2, 7), "ore": (36, 6, 2),
        "propellant": (110, 4, 2), "parts": (245, 0, 2)}},
    "fulmaior": {"seller": "Fulmaior Gas Guild", "buyer": "Fulmaior Factors", "flows": {
        "propellant": (95, 10, 3), "water": (26, 6, 2), "parts": (255, 1, 4),
        "grain": (72, 0, 3), "ore": (40, 1, 3)}},
    "moon": {"seller": "Moon Depot", "buyer": "Moon Depot Buyers", "flows": {
        "water": (32, 1, 2), "grain": (75, 0, 2), "parts": (260, 0, 1),
        "ore": (48, 0, 1), "propellant": (150, 0, 1)}},
    "tide": {"seller": "Tide Ice Cutters", "buyer": "Tide Outpost", "flows": {
        "water": (20, 3, 1), "grain": (74, 0, 2), "parts": (265, 0, 1),
        "ore": (50, 0, 1), "propellant": (155, 0, 1)}},
}

# (party, side, comm, price_mult_vs_base, qty): independents on the books that
# the player hasn't met — referrals (M3) reveal them.
EXTRAS = {
    "tern": [("Tern Freeholders", "ask", "grain", 1.05, 4.0),
             ("Tern Co-op Reserve", "bid", "parts", 0.95, 2.0)],
    "veluvy": [("Veluvy Free Traders", "ask", "ore", 1.05, 6.0),
               ("Helio Scrap Men", "bid", "parts", 0.97, 2.0)],
    "nellus": [("Nellus Surplus", "ask", "parts", 1.03, 3.0),
               ("Vesper Buyers", "bid", "ore", 0.95, 4.0)],
    "arax": [("Arax Prospectors", "ask", "ore", 1.04, 4.0),
             ("Ares Co-op", "bid", "grain", 0.96, 5.0)],
    "fulmaior": [("Shepherd Crews", "ask", "propellant", 1.05, 5.0),
                 ("Outer Factors", "bid", "water", 0.95, 3.0)],
    "moon": [("Earth-Luna Shuttle", "ask", "water", 1.10, 1.0),
             ("Depot Seconds", "bid", "parts", 0.90, 1.0)],
    "tide": [("Far-Side Skimmers", "ask", "water", 1.05, 2.0),
             ("Outpost Store", "bid", "grain", 0.90, 1.0)],
}


def seed(game) -> None:
    """Build starting books: ~3 days of production on offer, ~2 days bid wanted.

    The big seller/buyer labels are known faces; EXTRAS sit on the books as
    strangers until a contact introduces them.
    """
    game.markets = {}
    game.known = {}
    for pid, spec in PORTS.items():
        asks, bids, last, flow = {}, {}, {}, {}
        for comm, (ask_base, prod, cons) in spec["flows"].items():
            bid_base = round(0.9 * ask_base, 1)
            ask_qty = 3 * prod if prod > 0 else 1.0
            bid_qty = 2 * cons if cons > 0 else 1.0
            asks[comm] = [[float(ask_base), float(ask_qty), spec["seller"]]]
            bids[comm] = [[bid_base, float(bid_qty), spec["buyer"]]]
            last[comm] = None
            flow[comm] = {"prod": prod, "cons": cons, "ask": float(ask_base),
                          "bid": bid_base, "ask0": float(ask_base), "bid0": bid_base}
        for party, side, comm, mult, qty in EXTRAS.get(pid, []):
            base = flow[comm]["ask"] if side == "ask" else flow[comm]["bid"]
            line = [round(base * mult, 1), float(qty), party]
            if side == "ask":
                asks[comm].append(line)
                asks[comm].sort(key=lambda a: a[0])
            else:
                bids[comm].append(line)
        game.markets[pid] = {"body": pid, "asks": asks, "bids": bids,
                             "last": last, "flow": flow,
                             "seller": spec["seller"], "buyer": spec["buyer"]}
        game.known[pid] = [spec["seller"], spec["buyer"]]


def _add_ask(asks: list, price: float, qty: float, party: str) -> None:
    for a in asks:
        if a[0] == price:
            a[1] += qty
            break
    else:
        asks.append([price, qty, party])
    asks.sort(key=lambda a: a[0])


def _take_asks(asks: list, qty: float) -> None:
    left = qty
    for a in asks:
        if left <= 0:
            break
        take = min(a[1], left)
        a[1] -= take
        left -= take
    asks[:] = [a for a in asks if a[1] > 1e-9]


def tick(game) -> None:
    """One day of local life: produce onto asks, consume off them, nudge bases."""
    for port in game.markets.values():
        for comm, f in port["flow"].items():
            asks = port["asks"].setdefault(comm, [])
            if f["prod"] > 0:
                _add_ask(asks, f["ask"], f["prod"], port["seller"])
            if f["cons"] > 0:
                _take_asks(asks, f["cons"])
            total = sum(q for _, q, _ in asks)
            if total <= 1e-9:
                f["ask"] = round(min(f["ask"] * 1.1, 8 * f["ask0"]), 2)  # shortage
            elif f["cons"] > 0 and total > 4 * f["cons"]:
                f["ask"] = round(max(f["ask"] * 0.99, 0.25 * f["ask0"]), 2)  # glut
            bids = port["bids"].setdefault(comm, [])
            if not bids and f["cons"] > 0:
                f["bid"] = round(min(f["bid"] * 1.05, 8 * f["bid0"]), 2)
                bids.append([f["bid"], float(f["cons"]), port["buyer"]])


def _port_for(game, ship_id: str):
    ship = game.ships[ship_id]
    if ship.leg is not None:
        raise ValueError("ship is in transit")
    port = game.markets.get(ship.at or "")
    if port is None:
        raise ValueError("no market here")
    return ship, port


def buy(game, ship_id: str, comm: str, qty: float) -> dict:
    """Lift cheapest asks first. Partial fills allowed; empty fills raise."""
    if comm not in COMMODITIES:
        raise KeyError(comm)
    if qty <= 0:
        raise ValueError("qty must be positive")
    ship, port = _port_for(game, ship_id)
    asks = [a for a in port["asks"].get(comm, []) if a[1] > 1e-9]
    if not asks:
        raise ValueError("no sellers")
    space = ship.cargo_cap - sum(ship.cargo.values())
    if space <= 0:
        raise ValueError("hold full")
    want = min(float(qty), space)
    filled, cost = 0.0, 0.0
    for a in asks:
        if filled >= want or game.credits - cost <= 1e-9:
            break
        take = min(a[1], want - filled, (game.credits - cost) / a[0])
        if take <= 1e-9:
            break
        a[1] -= take
        filled += take
        cost += take * a[0]
    port["asks"][comm] = [a for a in asks if a[1] > 1e-9]
    if filled <= 1e-9:
        raise ValueError("no fill (funds or stock)")
    game.credits -= cost
    ship.cargo[comm] = ship.cargo.get(comm, 0.0) + filled
    contacts.credit_trade(game, port["body"])
    avg = cost / filled
    port["last"][comm] = {"price": round(avg, 2), "qty": round(filled, 2),
                          "t": round(game.t, 2), "side": "buy"}
    return {"filled": filled, "cost": cost, "avg": avg, "unfilled": float(qty) - filled}


def sell(game, ship_id: str, comm: str, qty: float) -> dict:
    """Hit highest bids first. Partial fills allowed; empty fills raise."""
    if comm not in COMMODITIES:
        raise KeyError(comm)
    if qty <= 0:
        raise ValueError("qty must be positive")
    ship, port = _port_for(game, ship_id)
    held = ship.cargo.get(comm, 0.0)
    if held <= 0:
        raise ValueError("no cargo to sell")
    bids = sorted([b for b in port["bids"].get(comm, []) if b[1] > 1e-9],
                  key=lambda b: -b[0])
    if not bids:
        raise ValueError("no buyers")
    want = min(float(qty), held)
    filled, proceeds = 0.0, 0.0
    for b in bids:
        if filled >= want:
            break
        take = min(b[1], want - filled)
        b[1] -= take
        filled += take
        proceeds += take * b[0]
    port["bids"][comm] = [b for b in port["bids"][comm] if b[1] > 1e-9]
    if filled <= 1e-9:
        raise ValueError("no fill (no demand)")
    ship.cargo[comm] = held - filled
    if ship.cargo[comm] <= 1e-9:
        del ship.cargo[comm]
    game.credits += proceeds
    contacts.credit_trade(game, port["body"])
    avg = proceeds / filled
    port["last"][comm] = {"price": round(avg, 2), "qty": round(filled, 2),
                          "t": round(game.t, 2), "side": "sell"}
    return {"filled": filled, "proceeds": proceeds, "avg": avg, "unfilled": float(qty) - filled}


def apply_shock(game, body_id: str, comm: str, kind: str = "shortage",
                severity: float = 1.0, note: str | None = None) -> str:
    """Minimal event-driven repricing (full event bus comes later).

    Shortage wipes most asks and bids up; glut wipes most bids and asks down.
    Always leaves a ledger fragment — the player only ever sees fragments.
    """
    port = game.markets.get(body_id)
    if port is None:
        raise ValueError("no market here")
    if comm not in COMMODITIES:
        raise KeyError(comm)
    name = game.bodies[body_id].name if body_id in game.bodies else body_id
    if kind == "shortage":
        for a in port["asks"].get(comm, []):
            a[1] *= max(0.0, 1 - 0.8 * severity)
        port["asks"][comm] = [a for a in port["asks"][comm] if a[1] > 1e-9]
        for b in port["bids"].get(comm, []):
            b[0] = round(b[0] * (1 + 0.5 * severity), 2)
        msg = note or f"{COMMODITIES[comm]['name']} shortage on {name}: bids spike"
    elif kind == "glut":
        for b in port["bids"].get(comm, []):
            b[1] *= max(0.0, 1 - 0.8 * severity)
        port["bids"][comm] = [b for b in port["bids"][comm] if b[1] > 1e-9]
        for a in port["asks"].get(comm, []):
            a[0] = round(a[0] * (1 - 0.3 * severity), 2)
        msg = note or f"{COMMODITIES[comm]['name']} glut on {name}: offers collapse"
    else:
        raise ValueError("kind must be 'shortage' or 'glut'")
    game.ledger.append({"t": round(game.t, 2), "kind": "event", "msg": msg})
    return msg
