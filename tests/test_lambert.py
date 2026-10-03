"""Lambert geometry tests. Run: python3 tests/test_lambert.py

Two jobs. First: theta = pi MUST reproduce the existing Hohmann transfer exactly,
or every movement test in the suite is quietly testing a different orbit. Second:
the speed/fuel trade has to be well-behaved and honest, because it is now the
central strategic dial.
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sim import lambert, orbits
from sim.state import build_sol

MU = orbits.MU_SUN
PASS = []

PAIRS = [(1.0, 5.2415), (1.0, 9.4346), (0.3420, 1.0), (0.4481, 1.0),
         (1.0, 0.4481), (0.3420, 0.4481), (5.2415, 9.4346)]


def check(name, fn):
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        print(f"FAIL {name}: {type(e).__name__}: {e}")
        return False
    print(f"ok   {name}")
    PASS.append(name)
    return True


def test_theta_pi_is_exactly_hohmann():
    """The backward-compatibility guarantee."""
    for r1, r2 in PAIRS:
        ref = orbits.hohmann(r1, r2)
        got = lambert.best_arc(r1, r2, math.pi, MU)
        assert got is not None, (r1, r2)
        assert abs(got["dv"] - ref["dv"]) < 1e-9, (r1, r2, got["dv"], ref["dv"])
        assert abs(got["tof"] - ref["transit_d"]) < 1e-3, (r1, r2)
        assert abs(got["e"] - abs(ref["e"])) < 1e-9, (r1, r2)
        assert abs(got["a"] - ref["a_trans"]) < 1e-9, (r1, r2)


def test_hohmann_touches_both_radii_exactly():
    for r1, r2 in PAIRS:
        arc = lambert.best_arc(r1, r2, math.pi, MU)
        r, _ = lambert.position(arc, 0.0)
        assert abs(r - min(r1, r2)) < 1e-9, (r1, r2, r)
        r, _ = lambert.position(arc, 1.0)
        assert abs(r - max(r1, r2)) < 1e-9, (r1, r2, r)


def test_arc_stays_between_the_radii():
    """A transfer must never dip below periapsis or climb past apoapsis."""
    for theta in (math.radians(d) for d in (180, 150, 120, 90)):
        arc = lambert.best_arc(1.0, 5.2415, theta, MU)
        for i in range(21):
            r, _ = lambert.position(arc, i / 20)
            assert r <= arc["apoapsis"] + 1e-9, (theta, r, arc["apoapsis"])
            assert r >= arc["periapsis"] - 1e-9, (theta, r, arc["periapsis"])


def test_swept_angle_equals_theta():
    for deg in (180, 160, 140, 120, 100, 90, 70):
        theta = math.radians(deg)
        arc = lambert.best_arc(1.0, 5.2415, theta, MU)
        r0, l0 = lambert.position(arc, 0.0)
        r1, l1 = lambert.position(arc, 1.0)
        assert abs(r0 - 1.0) < 1e-9 and abs(r1 - 5.2415) < 1e-9
        assert abs(math.degrees(l1 - l0) - deg) < 1e-6, (deg, math.degrees(l1 - l0))


def test_minimum_dv_is_at_hohmann():
    """The theorem, verified rather than assumed: theta=pi is globally cheapest."""
    h = lambert.best_arc(1.0, 5.2415, math.pi, MU)
    for deg in range(20, 180, 5):
        arc = lambert.best_arc(1.0, 5.2415, math.radians(deg), MU)
        assert arc["dv"] >= h["dv"] - 1e-9, (deg, arc["dv"], h["dv"])


def test_smaller_theta_is_never_slower():
    """The trade must be monotone in the useful range, or the dial is a lie."""
    prev = None
    for deg in range(180, 84, -10):
        arc = lambert.best_arc(1.0, 5.2415, math.radians(deg), MU)
        if prev is not None:
            assert arc["tof"] <= prev + 1e-6, (deg, arc["tof"], prev)
        prev = arc["tof"]


def test_smaller_theta_is_never_cheaper():
    prev = None
    for deg in range(180, 84, -10):
        arc = lambert.best_arc(1.0, 5.2415, math.radians(deg), MU)
        if prev is not None:
            assert arc["dv"] >= prev - 1e-12, (deg, arc["dv"], prev)
        prev = arc["dv"]


def test_inward_transfer_is_mirrored():
    """In and out cost the same and take the same time -- one ellipse, both ways."""
    out = lambert.best_arc(0.4481, 1.0, math.pi, MU)
    inn = lambert.best_arc(1.0, 0.4481, math.pi, MU)
    assert out is inn, "same pair should resolve to one cached ellipse"
    assert abs(out["tof"] - inn["tof"]) < 1e-12
    start, _ = lambert.position(inn, 0.0, outward=False)
    end, _ = lambert.position(inn, 1.0, outward=False)
    assert abs(start - 1.0) < 1e-12 and abs(end - 0.4481) < 1e-12
    assert end < start, "an inward arc must fall in radius"


def test_inward_sweeps_longitude_prograde():
    """Inward must be the arc ROTATED by pi, flown prograde -- never reversed.

    Reversing the outward arc gives a retrograde flight, whose arrival longitude
    is th0 - theta instead of th0 + theta. A Hohmann transfer between two
    circular orbits sweeps pi in the prograde sense whichever way it runs.
    """
    inn = lambert.best_arc(5.2415, 1.0, math.pi, MU)
    lons = [lambert.position(inn, i / 8, outward=False)[1] for i in range(9)]
    for i in range(8):
        assert lons[i + 1] > lons[i] - 1e-12, "inward leg must advance longitude"
    assert abs(lons[0] - 0.0) < 1e-12
    assert abs(lons[-1] - math.pi) < 1e-9, lons[-1]
    # the outward leg sweeps the same amount, the other side of the system
    out = lambert.best_arc(1.0, 5.2415, math.pi, MU)
    assert abs(lambert.position(out, 1.0)[1] - math.pi) < 1e-9


def test_inward_arc_falls_monotonically():
    inn = lambert.best_arc(5.2415, 1.0, math.pi, MU)
    rs = [lambert.position(inn, i / 20, outward=False)[0] for i in range(21)]
    assert abs(rs[0] - 5.2415) < 1e-9 and abs(rs[-1] - 1.0) < 1e-9
    for i in range(20):
        assert rs[i + 1] <= rs[i] + 1e-12, f"inward leg rose at f={i/20}"


def test_outward_and_inward_do_not_corrupt_each_other():
    """Arcs are shared and cached, so travel direction must NOT live on them.

    Two ships crossing the same radius pair in opposite directions used to fight
    over the direction flag on one cached dict.
    """
    shared = lambert.best_arc(0.4481, 1.0, math.pi, MU)
    before = dict(shared)
    lambert.position(shared, 0.3, outward=False)
    lambert.position(shared, 0.7, outward=False)
    assert shared == before, "flighting an arc inward mutated the cached geometry"
    assert "outward" not in shared


def test_trade_is_worth_it_for_the_outer_system():
    """Honest band for the minimum-FUEL member at theta = 90.

    An earlier figure of 2.7x for Tern->Fulmaior came from the minimum-TIME
    member at each theta. The minimum-DELTA-V member -- the one that is actually
    priced, and the one the planner will offer -- is 1.5x faster for 2.0x the
    cruise. Transit time bottoms out near theta = 70 and rises again below it.
    """
    h = lambert.best_arc(1.0, 9.4346, math.pi, MU)
    fast = lambert.best_arc(1.0, 9.4346, math.radians(90), MU)
    assert fast["tof"] < h["tof"] * 0.7, (fast["tof"], h["tof"])
    assert 1.5 < fast["dv"] / h["dv"] < 2.6, fast["dv"] / h["dv"]


def test_transit_time_has_an_optimum():
    """There is a floor: shrinking theta past ~70 degrees stops helping."""
    a70 = lambert.best_arc(1.0, 5.2415, math.radians(70), MU)
    a40 = lambert.best_arc(1.0, 5.2415, math.radians(40), MU)
    assert a40["tof"] > a70["tof"], (a40["tof"], a70["tof"])
    assert a40["dv"] > a70["dv"]


def test_arc_points_start_and_end_on_the_bodies():
    arc = lambert.best_arc(1.0, 5.2415, math.radians(120), MU)
    pts = lambert.arc_points(arc, 0.7, 25)
    assert len(pts) == 26
    # tolerance covers the 4-decimal rounding in the point list itself
    assert abs(math.hypot(*pts[0]) - 1.0) < 2e-4, pts[0]
    assert abs(math.hypot(*pts[-1]) - 5.2415) < 2e-4, pts[-1]
    radii = [math.hypot(*p) for p in pts]
    assert min(radii) >= arc["periapsis"] - 1e-4
    assert max(radii) <= arc["apoapsis"] + 1e-4


def test_arc_points_do_not_mutate_the_cached_arc():
    """Arcs are shared. A caller hanging th0 on one would corrupt the rest."""
    arc = lambert.best_arc(1.0, 5.2415, math.radians(120), MU)
    before = dict(arc)
    lambert.arc_points(arc, 1.234, 5)
    assert arc == before, "arc_points mutated the cached geometry"
    assert "th0" not in arc


def test_cache_returns_equal_arcs():
    a = lambert.best_arc(1.0, 5.2415, math.radians(100), MU)
    b = lambert.best_arc(1.0, 5.2415, math.radians(100), MU)
    assert a is b or (a["dv"] == b["dv"] and a["nu1"] == b["nu1"])


def test_all_fixture_routes_solve():
    """Every planetary pair the game offers must produce a usable arc set."""
    g = build_sol()
    planets = [b for b in g.bodies.values() if not b.parent and b.kind == "planet"]
    for o in planets:
        for d in planets:
            if o.id == d.id:
                continue
            for deg in (180, 150, 120, 90):
                arc = lambert.best_arc(o.a, d.a, math.radians(deg), MU)
                assert arc is not None, (o.id, d.id, deg)
                assert arc["tof"] > 0, (o.id, d.id, deg)
                assert arc["dv"] > 0, (o.id, d.id, deg)


if __name__ == "__main__":
    tests = [
        ("theta_pi_is_hohmann", test_theta_pi_is_exactly_hohmann),
        ("hohmann_touches_radii", test_hohmann_touches_both_radii_exactly),
        ("arc_within_apsides", test_arc_stays_between_the_radii),
        ("swept_angle_is_theta", test_swept_angle_equals_theta),
        ("hohmann_is_cheapest", test_minimum_dv_is_at_hohmann),
        ("faster_never_slower", test_smaller_theta_is_never_slower),
        ("faster_never_cheaper", test_smaller_theta_is_never_cheaper),
        ("inward_mirrored", test_inward_transfer_is_mirrored),
        ("inward_longitude", test_inward_sweeps_longitude_prograde),
        ("inward_falls", test_inward_arc_falls_monotonically),
        ("no_direction_crosstalk", test_outward_and_inward_do_not_corrupt_each_other),
        ("outer_trade_worth_it", test_trade_is_worth_it_for_the_outer_system),
        ("transit_has_optimum", test_transit_time_has_an_optimum),
        ("arc_points_endpoints", test_arc_points_start_and_end_on_the_bodies),
        ("arc_points_no_mutation", test_arc_points_do_not_mutate_the_cached_arc),
        ("cache_stable", test_cache_returns_equal_arcs),
        ("all_routes_solve", test_all_fixture_routes_solve),
    ]
    # NOT all(): it short-circuits and reports only the first failure.
    results = [check(n, f) for n, f in tests]
    ok = all(results)
    print(f"\n{len(PASS)}/{len(tests)} passed")
    sys.exit(0 if ok else 1)