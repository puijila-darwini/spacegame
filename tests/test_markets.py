"""M2 market tests — stdlib only. Run: python3 tests/test_markets.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sim import api, markets, persist, ships, time
from sim.state import build_sol

PASS = []


def check(name, fn):
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        print(f"FAIL {name}: {type(e).__name__}: {e}")
        return False
    print(f"ok   {name}")
    PASS.append(name)
    return True


def new_game():
    g = build_sol()
    markets.seed(g)
    return g


def test_seed_specialization():
    g = new_game()
    tern_grain = g.markets["tern"]["asks"]["grain"][0][0]
    arax_grain = g.markets["arax"]["asks"]["grain"][0][0]
    assert tern_grain < arax_grain, "Tern grows, Arax strains"
    assert g.markets["tide"]["asks"]["water"][0][0] < g.markets["veluvy"]["asks"]["water"][0][0]
    assert len(g.markets) == 7


def test_buy_water_tide():
    g = new_game()
    before = g.credits
    r = markets.buy(g, "pc1", "water", 5)
    assert r["filled"] == 5 and r["unfilled"] == 0
    assert g.ships["pc1"].cargo == {"water": 5}
    assert g.credits == before - r["cost"]
    assert g.markets["tide"]["last"]["water"]["side"] == "buy"


def test_partial_fill():
    g = new_game()
    g.ships["pc1"].at = "veluvy"
    avail = sum(q for _, q, _ in g.markets["veluvy"]["asks"]["ore"])
    r = markets.buy(g, "pc1", "ore", avail + 1000)
    assert r["filled"] == avail and r["unfilled"] == 1000
    assert g.markets["veluvy"]["asks"]["ore"] == []


def test_hold_limit():
    g = new_game()
    r = markets.buy(g, "pc1", "water", 10000)
    assert r["filled"] <= 100.0, "PC-1 holds 100t"


def test_trade_run_profit():
    g = new_game()
    start = g.credits
    markets.buy(g, "pc1", "water", 5)  # cheap Tide ice
    leg = ships.commit(g, "pc1", "veluvy")
    time.advance_to(g, leg.t_arrive)
    r = markets.sell(g, "pc1", "water", 5)  # thirsty Veluvy pays up
    assert r["filled"] == 5
    assert g.credits > start, f"trade must pay: {g.credits} vs {start}"


def test_sweep_moves_market():
    g = new_game()
    g.ships["pc1"].at = "veluvy"
    base0 = g.markets["veluvy"]["flow"]["parts"]["ask"]
    markets.buy(g, "pc1", "parts", 10000)  # sweep thin outpost stock
    assert g.markets["veluvy"]["asks"]["parts"] == []
    time.advance(g, 1.0)  # no production -> shortage nudge
    assert g.markets["veluvy"]["flow"]["parts"]["ask"] > base0


def test_regen():
    g = new_game()
    markets.buy(g, "pc1", "water", 10000)  # strip Tide ice
    time.advance(g, 3.0)  # cutters keep cutting
    total = sum(q for _, q, _ in g.markets["tide"]["asks"]["water"])
    assert total >= 6.0, f"production replenishes: {total}"


def test_shock():
    g = new_game()
    bid0 = g.markets["arax"]["bids"]["grain"][0][0]
    msg = markets.apply_shock(g, "arax", "grain", "shortage", 1.0, "Blight on Arax")
    assert g.markets["arax"]["bids"]["grain"][0][0] > bid0
    assert g.ledger and g.ledger[-1]["kind"] == "event" and "Blight" in msg


def test_save_roundtrip_markets():
    os.makedirs("/home/pthag/ai/tmp/spacegame", exist_ok=True)
    path = "/home/pthag/ai/tmp/spacegame/test_markets.json"
    g = new_game()
    markets.buy(g, "pc1", "water", 5)
    persist.save(g, path)
    g2 = persist.load(path)
    assert g2.credits == g.credits
    assert g2.ships["pc1"].cargo == {"water": 5}
    assert g2.markets["tide"]["asks"]["water"] == g.markets["tide"]["asks"]["water"]


def test_snapshot_v1():
    g = new_game()
    markets.buy(g, "pc1", "water", 5)
    s = api.snapshot(g)
    assert s["v"] == 3 and set(s) == {"v", "t", "credits", "campaign", "bodies", "ships", "ports", "ledger",
                                      "locations", "contacts", "known", "contracts"}
    assert len(s["ports"]) == 7
    assert s["ships"][0]["cargo"] == {"water": 5}


if __name__ == "__main__":
    tests = [
        ("seed_specialization", test_seed_specialization),
        ("buy_water_tide", test_buy_water_tide),
        ("partial_fill", test_partial_fill),
        ("hold_limit", test_hold_limit),
        ("trade_run_profit", test_trade_run_profit),
        ("sweep_moves_market", test_sweep_moves_market),
        ("regen", test_regen),
        ("shock", test_shock),
        ("save_roundtrip_markets", test_save_roundtrip_markets),
        ("snapshot_v1", test_snapshot_v1),
    ]
    ok = all(check(n, f) for n, f in tests)
    print(f"\n{len(PASS)}/{len(tests)} passed")
    sys.exit(0 if ok else 1)
