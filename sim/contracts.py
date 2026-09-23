"""Contracts (M4): demand you can finance (GDD §12).

Ports post delivery contracts (comm, qty, fixed price, deadline) drawn from
local consumption. Accept one, haul the goods, fulfill for the payout —
partial deliveries allowed, so a small ship can work a big contract across
trips. Lapsed contracts die quietly in the ledger. Issuers you haven't met
stay faceless off-port (known-subset rule, same as books).
"""
from __future__ import annotations

from . import markets

OPEN_PER_PORT = 3
PRICE_PREMIUM = 1.15


def _port_index(port_id: str) -> int:
    return list(markets.PORTS).index(port_id)


def post(game, port_id: str) -> dict:
    """Post one demand contract at a port. Deterministic rotation of needs."""
    if port_id not in game.markets:
        raise ValueError("no market here")
    port = game.markets[port_id]
    comms = [c for c, f in port["flow"].items() if f["cons"] > 0]
    if not comms:
        raise ValueError("no demand here")
    comm = comms[(game.contract_seq + _port_index(port_id)) % len(comms)]
    f = port["flow"][comm]
    qty = max(5.0, 3 * f["cons"])
    cid = f"C-{game.contract_seq:03d}"
    game.contract_seq += 1
    contract = {
        "id": cid, "issuer": port["buyer"], "port": port_id, "dest": port_id,
        "comm": comm, "qty": float(qty), "delivered": 0.0,
        "price": round(f["bid"] * PRICE_PREMIUM, 1),
        "deadline": round(game.t + 360 + (game.contract_seq * 17 % 120), 1),
        "status": "open", "created": round(game.t, 2),
    }
    game.contracts[cid] = contract
    return contract


def sweep(game) -> list:
    """Lapse expired open/accepted contracts. Returns lapsed ids."""
    lapsed = []
    for c in game.contracts.values():
        if c["status"] in ("open", "accepted") and game.t > c["deadline"]:
            c["status"] = "lapsed"
            lapsed.append(c["id"])
            game.ledger.append({"t": round(game.t, 2), "kind": "contract",
                                "msg": f"{c['id']} lapsed: {c['qty']}t {c['comm']} for {c['issuer']} undelivered"})
    return lapsed


def board(game, port_id: str) -> list:
    """Contract board at a port: sweep, top up to cap, return open+accepted by deadline."""
    sweep(game)
    have = sum(1 for c in game.contracts.values()
               if c["port"] == port_id and c["status"] == "open")
    while have < OPEN_PER_PORT:
        try:
            post(game, port_id)
        except ValueError:
            break
        have += 1
    return sorted((c for c in game.contracts.values()
                   if c["port"] == port_id and c["status"] in ("open", "accepted")),
                  key=lambda c: c["deadline"])


def accept(game, cid: str) -> dict:
    c = game.contracts[cid]
    if c["status"] != "open":
        raise ValueError(f"{cid} is {c['status']}")
    c["status"] = "accepted"
    game.ledger.append({"t": round(game.t, 2), "kind": "contract",
                        "msg": f"accepted {cid}: {c['qty']}t {c['comm']} to {c['dest']} by t={c['deadline']}"})
    return c


def fulfill(game, ship_id: str, cid: str, qty: float | None = None) -> dict:
    """Deliver cargo against an accepted contract for the fixed price."""
    c = game.contracts[cid]
    sweep(game)
    if c["status"] != "accepted":
        raise ValueError(f"{cid} is {c['status']} (accept it first)")
    ship = game.ships[ship_id]
    if ship.leg is not None:
        raise ValueError("ship is in transit")
    if ship.at != c["dest"]:
        raise ValueError(f"cargo must reach {c['dest']}")
    held = ship.cargo.get(c["comm"], 0.0)
    if held <= 0:
        raise ValueError("no matching cargo aboard")
    remaining = c["qty"] - c["delivered"]
    give = min(remaining, held if qty is None else min(qty, held))
    if give <= 0:
        raise ValueError("nothing left to deliver")
    ship.cargo[c["comm"]] = held - give
    if ship.cargo[c["comm"]] <= 1e-9:
        del ship.cargo[c["comm"]]
    c["delivered"] += give
    paid = give * c["price"]
    game.credits += paid
    if c["delivered"] >= c["qty"] - 1e-9:
        c["status"] = "filled"
        game.ledger.append({"t": round(game.t, 2), "kind": "contract",
                            "msg": f"{cid} filled: {c['qty']}t {c['comm']} delivered, {paid:.0f}cr earned"})
    else:
        game.ledger.append({"t": round(game.t, 2), "kind": "contract",
                            "msg": f"{cid} partial: {c['delivered']:.0f}/{c['qty']:.0f}t delivered"})
    return {"delivered": give, "paid": paid, "status": c["status"]}
