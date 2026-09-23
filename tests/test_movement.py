"""M1 movement tests — stdlib only. Run: python3 tests/test_movement.py"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sim import api, orbits, persist, ships, time
from sim.state import build_sol

TAU = math.tau
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


def wrap(x):
    return (x + math.pi) % TAU - math.pi


def test_periods():
    assert abs(orbits.period(1.0, orbits.MU_SUN) - 360.0) < 0.5, "Tern year"
    assert abs(orbits.period(0.025, orbits.MU_TERN) - 30.0) < 0.2, "Moon period"
    assert abs(orbits.period(0.0358, orbits.MU_TERN) - 360.0 / 7.0) < 0.3, "Tide period"
    g = build_sol()
    assert abs(orbits.period(g.bodies["veluvy"].a, orbits.MU_SUN) - 72.0) < 0.5, "Veluvy"
    assert abs(orbits.period(g.bodies["nellus"].a, orbits.MU_SUN) - 108.0) < 0.5, "Nellus"
    assert abs(orbits.period(g.bodies["arax"].a, orbits.MU_SUN) - 4320.0) < 5.0, "Arax"
    assert abs(orbits.period(g.bodies["fulmaior"].a, orbits.MU_SUN) - 10440.0) < 10.0, "Fulmaior"
    assert abs(orbits.period(g.bodies["eope"].a, orbits.MU_FULMAIOR) - 6.0) < 0.1, "Eope"
    assert abs(orbits.period(g.bodies["cenaedo"].a, orbits.MU_FULMAIOR) - 16.0) < 0.2, "Cenaedo"
    assert abs(orbits.period(g.bodies["cteta"].a, orbits.MU_FULMAIOR) - 38.0) < 0.5, "Cteta"


def test_orbit_closure():
    g = build_sol()
    tern = g.bodies["tern"]
    T = orbits.period(tern.a, orbits.MU_SUN)
    th0 = orbits.body_angle(tern, 0.0)
    th1 = orbits.body_angle(tern, T)
    assert abs(wrap(th1 - th0)) < 1e-9


def test_hohmann_formula():
    h = orbits.hohmann(1.1, 1.5)
    expect = math.pi * math.sqrt(((1.1 + 1.5) / 2) ** 3 / orbits.MU_SUN)
    assert abs(h["transit_d"] - expect) < 1e-9
    assert h["dv"] > 0


def test_window_intercept():
    g = build_sol()
    w = orbits.next_window(g.bodies, "tern", "arax", 0.0)
    o_ang = orbits.helio_angle(g.bodies, "tern", w["depart_t"])
    d_ang = orbits.helio_angle(g.bodies, "arax", w["helio_arrival_t"])
    assert abs(wrap(d_ang - o_ang - math.pi)) < 0.03, "Hohmann intercept geometry"
    assert w["depart_t"] >= 0.0 and w["arrival_t"] > w["depart_t"]


def test_tide_departure_has_moon_leg():
    g = build_sol()
    w = orbits.next_window(g.bodies, "tide", "arax", 0.0)
    assert "moon_depart" in w["waits"], "Tide departure pays the well"
    assert w["arrival_t"] > w["depart_t"] > 0.0


def test_moon_offset_geometry():
    g = build_sol()
    mx, my, _ = orbits.body_pos(g.bodies["moon"], g.bodies, 10.0)
    tx, ty, _ = orbits.body_pos(g.bodies["tern"], g.bodies, 10.0)
    assert abs(math.hypot(mx - tx, my - ty) - 0.025) < 1e-9


def test_ship_arrives():
    g = build_sol()
    leg = ships.commit(g, "pc1", "arax")
    assert g.ships["pc1"].at is None
    reports = time.advance_to(g, leg.t_arrive)
    assert g.ships["pc1"].at == "arax" and g.ships["pc1"].leg is None
    assert reports == [("pc1", "arax", leg.t_arrive)]


def test_step_equivalence():
    g1 = build_sol()
    ships.commit(g1, "pc1", "arax")
    leg_arr = g1.ships["pc1"].leg.t_arrive
    time.advance(g1, 7.0)
    g2 = build_sol()
    ships.commit(g2, "pc1", "arax")
    for _ in range(7):
        time.advance(g2, 1.0)
    assert g1.t == g2.t == 7.0
    assert leg_arr == g2.ships["pc1"].leg.t_arrive


def test_save_roundtrip():
    os.makedirs("/home/pthag/ai/tmp/spacegame", exist_ok=True)
    path = "/home/pthag/ai/tmp/spacegame/test_save.json"
    g = build_sol()
    ships.commit(g, "pc1", "arax")
    time.advance(g, 3.0)
    persist.save(g, path)
    g2 = persist.load(path)
    assert g2.t == g.t
    assert g2.ships["pc1"].leg.dest == "arax"
    assert g2.ships["pc1"].leg.t_arrive == g.ships["pc1"].leg.t_arrive


def test_snapshot_contract():
    g = build_sol()
    leg = ships.commit(g, "pc1", "arax")
    time.advance_to(g, leg.t_depart + 1.0)  # mid-transit (ship waits out its window first)
    s = api.snapshot(g)
    assert s["v"] == 3 and set(s) == {"v", "t", "credits", "bodies", "ships", "ports", "ledger",
                                      "locations", "contacts", "known", "contracts"}
    assert len(s["bodies"]) == 11
    ship = s["ships"][0]
    assert ship["leg"] == {"from": "tide", "to": "arax"}
    assert 0.0 < ship["progress"] < 1.0 and ship["eta_d"] > 0
    assert len(ship["arc_pts"]) == 26


def test_star_rejected():
    g = build_sol()
    for dest in ("sun",):
        try:
            ships.plot(g, "pc1", dest)
        except ValueError:
            return
        raise AssertionError(f"expected ValueError for {dest}")


def test_fast_costs_more_and_meets_deadline():
    g = build_sol()
    slow = ships.plot(g, "pc1", "arax")
    deadline = g.t + 30.0 + slow["transit_d"] * 0.5  # tighter than the window, still reachable
    assert deadline < slow["arrival_t"], "deadline must beat the windowed sailing"
    fast = ships.plot(g, "pc1", "arax", arrive_by=deadline)
    assert fast["kind"] == "fast"
    assert fast["arrival_t"] <= deadline + 1e-6
    assert fast["dv"] > slow["dv"], "leave-now must cost more than wait-cheap"


def test_fast_generous_deadline_uses_window():
    g = build_sol()
    slow = ships.plot(g, "pc1", "arax")
    try:
        ships.plot(g, "pc1", "arax", arrive_by=slow["arrival_t"] + 10.0)
    except ValueError:
        return
    raise AssertionError("expected ValueError (take the window)")


def test_fast_impossible_deadline():
    g = build_sol()
    try:
        ships.plot(g, "pc1", "arax", arrive_by=g.t + 1.0)
    except ValueError:
        return
    raise AssertionError("expected ValueError (unreachable)")


def test_fast_ship_arrives_by_deadline():
    g = build_sol()
    slow = ships.plot(g, "pc1", "arax")
    deadline = g.t + 30.0 + slow["transit_d"] * 0.5
    leg = ships.commit(g, "pc1", "arax", arrive_by=deadline)
    assert leg.kind == "fast"
    time.advance_to(g, leg.t_arrive)
    assert g.ships["pc1"].at == "arax"
    assert leg.t_arrive <= deadline + 1e-6


def test_ledger_records_arrival():
    g = build_sol()
    leg = ships.commit(g, "pc1", "arax")
    time.advance_to(g, leg.t_arrive)
    assert len(g.ledger) == 1
    assert g.ledger[0]["kind"] == "arrival" and "Arax" in g.ledger[0]["msg"]
    s = api.snapshot(g)
    assert len(s["ledger"]) == 1


def test_catchup_equivalence():
    os.makedirs("/home/pthag/ai/tmp/spacegame", exist_ok=True)
    path = "/home/pthag/ai/tmp/spacegame/test_catchup.json"
    g1 = build_sol()
    ships.commit(g1, "pc1", "arax")
    time.advance(g1, 3.0)
    persist.save(g1, path)
    with open(path) as f:
        wall = json.load(f)["wall"]
    r1 = time.advance(g1, 10.0)
    g2, off, r2 = persist.load_with_catchup(path, rate=1.0, cap_days=30.0, now=wall + 10.0)
    assert abs(off - 10.0) < 1e-9
    assert g2.t == g1.t
    assert len(r2) == len(r1)
    assert g2.ledger == g1.ledger


def test_catchup_cap():
    g = build_sol()
    ships.commit(g, "pc1", "arax")
    owed, _ = time.catch_up(g, 500.0)
    assert owed == time.CATCHUP_CAP_D


def _tpos(leg, bodies, f):
    t = leg.t_depart + f * (leg.t_arrive - leg.t_depart)
    return api.transfer_pos(leg, bodies, t)


def _tdist(p, q):
    return math.hypot(p[0] - q[0], p[1] - q[1])


def test_kepler_outward():
    g = build_sol()
    leg = ships.commit(g, "pc1", "arax")  # helio tern -> arax, outward
    B = g.bodies
    p0, p1 = _tpos(leg, B, 0.0), _tpos(leg, B, 0.1)
    p4, p5 = _tpos(leg, B, 0.45), _tpos(leg, B, 0.55)
    assert _tdist(p0, p1) > _tdist(p4, p5), "fast off perihelion, lingering at aphelion"
    assert math.hypot(*p5) > math.hypot(*p0), "outward leg climbs"
    ox, oy, _ = orbits.body_pos(B["tern"], B, leg.t_depart)
    assert _tdist(p0, (ox, oy)) < 0.05, "arc anchored at departure"


def test_kepler_inward():
    g = build_sol()
    g.ships["pc1"].at = "arax"
    leg = ships.commit(g, "pc1", "tern")
    B = g.bodies
    q0, q1 = _tpos(leg, B, 0.0), _tpos(leg, B, 0.1)
    q8, q9 = _tpos(leg, B, 0.9), _tpos(leg, B, 1.0)
    assert _tdist(q8, q9) > _tdist(q0, q1), "lingers at aphelion, dives to perihelion"
    assert math.hypot(*q9) < math.hypot(*q0), "inward leg falls"


if __name__ == "__main__":
    tests = [
        ("periods", test_periods),
        ("orbit_closure", test_orbit_closure),
        ("hohmann_formula", test_hohmann_formula),
        ("window_intercept", test_window_intercept),
        ("tide_moon_leg", test_tide_departure_has_moon_leg),
        ("moon_offset", test_moon_offset_geometry),
        ("ship_arrives", test_ship_arrives),
        ("step_equivalence", test_step_equivalence),
        ("save_roundtrip", test_save_roundtrip),
        ("snapshot_contract", test_snapshot_contract),
        ("star_rejected", test_star_rejected),
        ("fast_premium", test_fast_costs_more_and_meets_deadline),
        ("fast_window_guard", test_fast_generous_deadline_uses_window),
        ("fast_impossible", test_fast_impossible_deadline),
        ("fast_arrives", test_fast_ship_arrives_by_deadline),
        ("ledger_arrival", test_ledger_records_arrival),
        ("catchup_equivalence", test_catchup_equivalence),
        ("catchup_cap", test_catchup_cap),
        ("kepler_outward", test_kepler_outward),
        ("kepler_inward", test_kepler_inward),
    ]
    ok = all(check(n, f) for n, f in tests)
    print(f"\n{len(PASS)}/{len(tests)} passed")
    sys.exit(0 if ok else 1)
