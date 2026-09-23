"""M6 location tests: stations/elevators, climb dv, fuel budgets. Run: python3 tests/test_infra.py"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sim import api, contacts, infra, markets, orbits, persist, ships, time
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
    infra.seed(g)
    return g


def expect_raise(fn, exc=(ValueError, KeyError)):
    try:
        fn()
    except exc:
        return
    raise AssertionError(f"expected {exc}")


V3_KEYS = {"v", "t", "credits", "bodies", "ships", "ports", "ledger",
           "locations", "contacts", "known", "contracts"}


def test_seed_locations():
    g = new_game()
    assert len(g.locations) == 18  # 10 surface + 3 terminals + 5 stations
    assert g.locations["tern-terminal"]["kind"] == "terminal"
    assert "tide-terminal" not in g.locations and "tide-station" not in g.locations
    assert "eope-station" not in g.locations  # bare outpost dirt, no services
    assert g.ships["pc1"].loc == "tide-surface"


def test_elevator_undercuts_rockets():
    g = new_game()
    assert g.locations["tern-terminal"]["depart_dv"] < g.locations["tern-surface"]["depart_dv"]
    assert g.locations["arax-station"]["depart_dv"] < g.locations["arax-surface"]["depart_dv"]


def test_commit_spends_dv():
    g = new_game()
    ship = g.ships["pc1"]
    w = ships.plot(g, "pc1", "arax")
    assert w["dest_loc"] == "arax-station"  # stations are the default come-down
    assert abs(w["total_dv"] - (w["dv"] + w["climb_dv"] + w["descent_dv"])) < 1e-9
    ships.commit(g, "pc1", "arax")
    assert abs(ship.dv - (ship.dv_cap - w["total_dv"])) < 1e-9


def test_dv_binds():
    g = new_game()
    g.ships["pc1"].dv = 0.001
    expect_raise(lambda: ships.commit(g, "pc1", "arax"))


def test_dest_choice_changes_price():
    g = new_game()
    g.ships["pc1"].at = "tern"
    g.ships["pc1"].loc = "tern-station"
    w_station = ships.plot(g, "pc1", "arax", "arax-station")
    w_surface = ships.plot(g, "pc1", "arax", "arax-surface")
    assert w_surface["total_dv"] > w_station["total_dv"]
    assert abs((w_surface["total_dv"] - w_station["total_dv"]) - (0.021 - 0.008)) < 1e-9


def test_arrival_sets_loc():
    g = new_game()
    leg = ships.commit(g, "pc1", "arax", "arax-surface")
    time.advance_to(g, leg.t_arrive)
    assert g.ships["pc1"].at == "arax"
    assert g.ships["pc1"].loc == "arax-surface"


def test_transfer_local():
    g = new_game()
    g.ships["pc1"].at = "tern"
    g.ships["pc1"].loc = "tern-surface"
    t0 = g.t
    r = infra.transfer_local(g, "pc1", "tern-terminal")
    assert r == {"loc": "tern-terminal", "days": 2.0, "dv": 0.002}
    assert g.t == t0 + 2.0
    r2 = infra.transfer_local(g, "pc1", "tern-station")
    assert r2["loc"] == "tern-station"
    expect_raise(lambda: infra.transfer_local(g, "pc1", "tern-station"))  # already here
    expect_raise(lambda: infra.transfer_local(g, "pc1", "arax-station"))  # wrong body


def test_refuel():
    g = new_game()
    g.ships["pc1"].at = "tern"
    g.ships["pc1"].loc = "tern-station"
    g.ships["pc1"].dv = 0.05
    credits0 = g.credits
    r = infra.refuel(g, "pc1")
    assert g.ships["pc1"].dv == g.ships["pc1"].dv_cap
    assert abs(r["cost"] - (0.20 * 130.0)) < 1e-6  # Tern propellant ask
    assert abs(g.credits - (credits0 - r["cost"])) < 1e-6
    assert g.ledger[-1]["kind"] == "service"


def test_refuel_denied_on_dirt():
    g = new_game()  # PC-1 sits on Tide surface: no services
    expect_raise(lambda: infra.refuel(g, "pc1"))


def test_save_roundtrip_infra():
    os.makedirs("/home/pthag/ai/tmp/spacegame", exist_ok=True)
    path = "/home/pthag/ai/tmp/spacegame/test_infra.json"
    g = new_game()
    g.ships["pc1"].at = "tern"
    g.ships["pc1"].loc = "tern-station"
    ships.commit(g, "pc1", "arax")
    persist.save(g, path)
    g2 = persist.load(path)
    assert g2.locations == g.locations
    assert g2.ships["pc1"].loc is None and g2.ships["pc1"].leg.dest_loc == "arax-station"
    assert g2.ships["pc1"].dv == g.ships["pc1"].dv


def test_snapshot_v3():
    g = new_game()
    s = api.snapshot(g)
    assert s["v"] == 3 and set(s) == V3_KEYS
    assert len(s["locations"]) == 18
    assert len(s["bodies"]) == 11
    ship = s["ships"][0]
    assert ship["loc"] == "tide-surface" and ship["dv"] == ship["dv_cap"] == 0.25


def test_fulmaior_moon_departure():
    g = new_game()
    g.ships["pc1"].at = "eope"
    g.ships["pc1"].loc = "eope-surface"
    w = ships.plot(g, "pc1", "arax")
    assert "moon_depart" in w["waits"]
    assert w["climb_dv"] == 0.010
    assert w["kind"] == "hohmann"


def test_fulmaior_moon_capture():
    g = new_game()
    g.ships["pc1"].at = "tern"
    g.ships["pc1"].loc = "tern-station"
    w = ships.plot(g, "pc1", "cteta")
    assert "moon_arrive" in w["waits"]
    o_ang = orbits.helio_angle(g.bodies, "tern", w["depart_t"])
    d_ang = orbits.helio_angle(g.bodies, "fulmaior", w["helio_arrival_t"])
    assert abs(((d_ang - o_ang - math.pi + math.pi) % (2 * math.pi)) - math.pi) < 0.03


def test_eope_offset_geometry():
    import math as _m
    g = new_game()
    mx, my, _ = orbits.body_pos(g.bodies["eope"], g.bodies, 10.0)
    fx, fy, _ = orbits.body_pos(g.bodies["fulmaior"], g.bodies, 10.0)
    assert abs(_m.hypot(mx - fx, my - fy) - 0.03) < 1e-9


def test_bare_moon_services():
    g = new_game()
    g.ships["pc1"].at = "eope"
    g.ships["pc1"].loc = "eope-surface"
    expect_raise(lambda: infra.refuel(g, "pc1"))
    expect_raise(lambda: infra.transfer_local(g, "pc1", "eope-station"))


if __name__ == "__main__":
    tests = [
        ("seed_locations", test_seed_locations),
        ("elevator_undercuts", test_elevator_undercuts_rockets),
        ("commit_spends_dv", test_commit_spends_dv),
        ("dv_binds", test_dv_binds),
        ("dest_choice_price", test_dest_choice_changes_price),
        ("arrival_sets_loc", test_arrival_sets_loc),
        ("transfer_local", test_transfer_local),
        ("refuel", test_refuel),
        ("refuel_denied_on_dirt", test_refuel_denied_on_dirt),
        ("save_roundtrip_infra", test_save_roundtrip_infra),
        ("snapshot_v3", test_snapshot_v3),
        ("fulmaior_departure", test_fulmaior_moon_departure),
        ("fulmaior_capture", test_fulmaior_moon_capture),
        ("eope_offset", test_eope_offset_geometry),
        ("bare_moon_services", test_bare_moon_services),
    ]
    ok = all(check(n, f) for n, f in tests)
    print(f"\n{len(PASS)}/{len(tests)} passed")
    sys.exit(0 if ok else 1)
