"""M3/M4 tests: contacts, known-subset visibility, contracts. Run: python3 tests/test_contacts.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sim import api, contacts, contracts, markets, persist, ships, time
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
    contacts.seed(g)
    return g


def expect_raise(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return
    raise AssertionError(f"expected {exc.__name__}")


def test_roster_and_known():
    g = new_game()
    assert len(g.contacts) == 14
    assert g.known["tide"] == ["Tide Ice Cutters", "Tide Outpost"]
    assert "Far-Side Skimmers" not in g.known["tide"]


def test_trade_builds_rapport():
    g = new_game()
    markets.buy(g, "pc1", "water", 2)
    assert g.contacts["c-tid-mar"]["rapport"] == 2
    assert g.contacts["c-tid-oss"]["rapport"] == 2
    assert g.contacts["c-tern-voss"]["rapport"] == 0


def test_quote_strangers_then_friends():
    g = new_game()
    expect_raise(lambda: contacts.quote(g, "c-tid-mar"))
    for _ in range(3):
        markets.buy(g, "pc1", "water", 1)
    q = contacts.quote(g, "c-tid-mar", "water")
    assert q["confidence"] == "high" and q["port"] == "tide"
    best = min(a[0] for a in g.markets["tide"]["asks"]["water"])
    assert q["quotes"]["water"]["ask"] == best


def test_referral():
    g = new_game()
    g.contacts["c-tid-mar"]["rapport"] = 30
    party = contacts.refer(g, "c-tid-mar")
    assert party == "Far-Side Skimmers"
    assert party in g.known["tide"]
    assert g.contacts["c-tid-mar"]["rapport"] == 20
    assert g.ledger and g.ledger[-1]["kind"] == "contact"
    expect_raise(lambda: contacts.refer(g, "c-tid-mar"))  # spent rapport
    g.contacts["c-tid-mar"]["rapport"] = 30
    assert contacts.refer(g, "c-tid-mar") == "Outpost Store"
    g.contacts["c-tid-mar"]["rapport"] = 30
    expect_raise(lambda: contacts.refer(g, "c-tid-mar"))  # no one left


def test_shady_no_vouch():
    g = new_game()
    g.contacts["c-mon-fix"]["rapport"] = 90
    expect_raise(lambda: contacts.refer(g, "c-mon-fix"))


def test_snapshot_known_flags():
    g = new_game()
    s = api.snapshot(g)
    lines = s["ports"]["tide"]["asks"]["water"]
    assert all(len(line) == 4 for line in lines)
    extra = [line for line in lines if line[2] == "Far-Side Skimmers"][0]
    assert extra[3] is False
    g.contacts["c-tid-mar"]["rapport"] = 30
    contacts.refer(g, "c-tid-mar")
    s2 = api.snapshot(g)
    extra2 = [line for line in s2["ports"]["tide"]["asks"]["water"] if line[2] == "Far-Side Skimmers"][0]
    assert extra2[3] is True


def test_board_topup():
    g = new_game()
    first = contracts.board(g, "arax")
    assert len(first) == 3 and all(c["status"] == "open" for c in first)
    again = contracts.board(g, "arax")
    assert len([c for c in g.contracts.values() if c["port"] == "arax"]) == 3
    assert [c["id"] for c in again] == [c["id"] for c in first]


def test_contract_loop():
    g = new_game()
    start = g.credits
    c = contracts.board(g, "arax")[0]
    g.ships["pc1"].at = "arax"
    g.ships["pc1"].cargo = {c["comm"]: c["qty"]}
    contracts.accept(g, c["id"])
    half = c["qty"] / 2
    r1 = contracts.fulfill(g, "pc1", c["id"], half)
    assert r1["status"] == "accepted"
    r2 = contracts.fulfill(g, "pc1", c["id"])
    assert r2["status"] == "filled" and g.contracts[c["id"]]["status"] == "filled"
    assert abs(g.credits - start - c["qty"] * c["price"]) < 1e-6


def test_fulfill_guards():
    g = new_game()
    c = contracts.board(g, "arax")[0]
    g.ships["pc1"].at = "tide"
    g.ships["pc1"].cargo = {c["comm"]: c["qty"]}
    expect_raise(lambda: contracts.fulfill(g, "pc1", c["id"]))  # not accepted
    contracts.accept(g, c["id"])
    expect_raise(lambda: contracts.fulfill(g, "pc1", c["id"]))  # wrong port
    g.ships["pc1"].at = "arax"
    expect_raise(lambda: contracts.accept(g, c["id"]))  # already accepted


def test_contract_expiry():
    g = new_game()
    c = contracts.board(g, "arax")[0]
    contracts.accept(g, c["id"])
    g.contracts[c["id"]]["deadline"] = g.t - 1
    lapsed = contracts.sweep(g)
    assert lapsed == [c["id"]]
    assert g.contracts[c["id"]]["status"] == "lapsed"
    assert g.ledger[-1]["kind"] == "contract"


def test_expiry_on_advance():
    g = new_game()
    c = contracts.board(g, "arax")[0]
    time.advance(g, c["deadline"] + 1)
    assert g.contracts[c["id"]]["status"] == "lapsed"


def test_save_roundtrip_all():
    os.makedirs("/home/pthag/ai/tmp/spacegame", exist_ok=True)
    path = "/home/pthag/ai/tmp/spacegame/test_contacts.json"
    g = new_game()
    g.contacts["c-tid-mar"]["rapport"] = 30
    contacts.refer(g, "c-tid-mar")
    contracts.board(g, "arax")
    contracts.accept(g, sorted(g.contracts)[0])
    persist.save(g, path)
    g2 = persist.load(path)
    assert g2.contacts == g.contacts and g2.known == g.known
    assert g2.contracts == g.contracts and g2.contract_seq == g.contract_seq


def test_snapshot_v2():
    g = new_game()
    contracts.board(g, "arax")
    s = api.snapshot(g)
    assert s["v"] == 3
    assert set(s) == {"v", "t", "credits", "bodies", "ships", "ports", "ledger",
                      "locations", "contacts", "known", "contracts"}
    assert len(s["contacts"]) == 14
    assert len(s["contracts"]) == 3
    assert all(c["known"] for c in s["contracts"])  # buyer labels are known faces


if __name__ == "__main__":
    tests = [
        ("roster_and_known", test_roster_and_known),
        ("trade_builds_rapport", test_trade_builds_rapport),
        ("quote_gating", test_quote_strangers_then_friends),
        ("referral", test_referral),
        ("shady_no_vouch", test_shady_no_vouch),
        ("snapshot_known_flags", test_snapshot_known_flags),
        ("board_topup", test_board_topup),
        ("contract_loop", test_contract_loop),
        ("fulfill_guards", test_fulfill_guards),
        ("contract_expiry", test_contract_expiry),
        ("expiry_on_advance", test_expiry_on_advance),
        ("save_roundtrip_all", test_save_roundtrip_all),
        ("snapshot_v2", test_snapshot_v2),
    ]
    ok = all(check(n, f) for n, f in tests)
    print(f"\n{len(PASS)}/{len(tests)} passed")
    sys.exit(0 if ok else 1)
