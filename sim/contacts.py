"""Contacts (M3): the network IS price discovery (GDD §§9-10).

NPCs live at ports with occupation, reliability, rapport. Trading at a port
builds rapport with its people. Rapport unlocks:
- quotes: a contact reports their port's book remotely (stamped with time);
- referrals: a trusted contact introduces an unknown counterparty, whose
  orders become visible to you off-port (known-subset filtering).

Agents acting on your behalf (tier 3) are deferred; reliability is already
load-bearing: shady contacts (reliability < 0.5) never vouch for anyone.
"""
from __future__ import annotations

QUOTE_RAPPORT = 5
REFER_RAPPORT = 25
REFER_COST = 10
MIN_VOUCH = 0.5

# id, name, port, occupation, reliability. Two per port; one shady (Rook).
ROSTER = [
    ("c-tern-voss", "Sarella Voss", "tern", "factor", 0.90),
    ("c-tern-ibe", "Dano Ibe", "tern", "broker", 0.70),
    ("c-vel-karn", "Karn Sollec", "veluvy", "smelter boss", 0.80),
    ("c-vel-pry", "Prya Venn", "veluvy", "combine clerk", 0.75),
    ("c-nel-ose", "Osei March", "nellus", "works manager", 0.85),
    ("c-nel-luz", "Luz Amari", "nellus", "factor", 0.65),
    ("c-arx-holt", "Holt Baraka", "arax", "yard boss", 0.80),
    ("c-arx-senn", "Senna Rho", "arax", "co-op rep", 0.90),
    ("c-ful-ik", "Ikari Nox", "fulmaior", "guild officer", 0.70),
    ("c-ful-pet", "Petra Voll", "fulmaior", "outer factor", 0.60),
    ("c-mon-quill", "Quill Anders", "moon", "depot chief", 0.85),
    ("c-mon-fix", "Rook", "moon", "fixer", 0.30),
    ("c-tid-mar", "Mara Skye", "tide", "ice cutter", 0.80),
    ("c-tid-oss", "Ossian Bell", "tide", "outpost keeper", 0.75),
]


def seed(game) -> None:
    """Register the roster. Run after markets.seed (known parties come from there)."""
    game.contacts = {}
    for cid, name, port, occ, rel in ROSTER:
        game.contacts[cid] = {"id": cid, "name": name, "port": port,
                              "occupation": occ, "reliability": rel, "rapport": 0}


def credit_trade(game, port_id: str, amount: int = 2) -> None:
    """A completed trade at a port warms every local contact a little."""
    for npc in game.contacts.values():
        if npc["port"] == port_id:
            npc["rapport"] = min(100, npc["rapport"] + amount)


def _confidence(reliability: float) -> str:
    if reliability >= 0.8:
        return "high"
    if reliability >= 0.5:
        return "fair"
    return "low"


def quote(game, npc_id: str, comm: str | None = None) -> dict:
    """A contact reports their port's book. Strangers get nothing."""
    npc = game.contacts[npc_id]
    if npc["rapport"] < QUOTE_RAPPORT:
        raise ValueError(f"{npc['name']} won't talk to strangers — trade at {npc['port']} first")
    port = game.markets[npc["port"]]
    comms = [comm] if comm is not None else sorted(port["asks"])
    quotes = {}
    for c in comms:
        asks = port["asks"].get(c, [])
        bids = port["bids"].get(c, [])
        quotes[c] = {
            "ask": min((a[0] for a in asks), default=None),
            "bid": max((b[0] for b in bids), default=None),
            "last": port["last"].get(c),
        }
    return {"by": npc["name"], "port": npc["port"], "t": round(game.t, 2),
            "confidence": _confidence(npc["reliability"]), "quotes": quotes}


def unknown_parties(game, port_id: str) -> list:
    """Parties with orders on a port's books that you haven't met."""
    port = game.markets[port_id]
    known = set(game.known.get(port_id, []))
    found = set()
    for side in ("asks", "bids"):
        for lines in port[side].values():
            for _, q, party in lines:
                if q > 1e-9 and party not in known:
                    found.add(party)
    return sorted(found)


def refer(game, npc_id: str) -> str:
    """A trusted contact introduces an unknown counterparty (costs rapport)."""
    npc = game.contacts[npc_id]
    if npc["reliability"] < MIN_VOUCH:
        raise ValueError(f"{npc['name']} doesn't vouch for anyone")
    if npc["rapport"] < REFER_RAPPORT:
        raise ValueError(f"not close enough to {npc['name']} (need {REFER_RAPPORT} rapport)")
    pool = unknown_parties(game, npc["port"])
    if not pool:
        raise ValueError("no one left to meet here")
    party = pool[0]
    game.known.setdefault(npc["port"], []).append(party)
    npc["rapport"] -= REFER_COST
    pname = game.bodies[npc["port"]].name if npc["port"] in game.bodies else npc["port"]
    game.ledger.append({"t": round(game.t, 2), "kind": "contact",
                        "msg": f"{npc['name']} introduced you to {party} ({pname})"})
    return party
