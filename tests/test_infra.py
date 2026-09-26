"""M6 location tests: stations/elevators, climb dv, fuel budgets. Run: python3 tests/test_infra.py"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sim import api, contacts, infra, markets, orbits, persist, ships, state, time
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


V3_KEYS = {"v", "t", "credits", "campaign", "bodies", "ships", "ports", "ledger",
           "locations", "gates", "contacts", "known", "contracts"}


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
    assert len(s["bodies"]) == 12  # 5 planets + sun + 5 moons + the gate
    assert all("kind" in body and "period" in body for body in s["bodies"])
    ship = s["ships"][0]
    assert ship["loc"] == "tide-surface" and ship["dv"] == ship["dv_cap"] == 0.25
    station = next(loc for loc in s["locations"] if loc["id"] == "tern-station")
    tern = next(body for body in s["bodies"] if body["id"] == "tern")
    assert station["orbit_a"] > 0 and station["orbit_period"] > 0
    assert abs(math.hypot(station["x"] - tern["x"], station["y"] - tern["y"])
               - station["orbit_a"]) < 1e-5
    surface = next(loc for loc in s["locations"] if loc["id"] == "tide-surface")
    assert surface["orbit_a"] == 0.0 and surface["orbit_period"] == 0.0


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
    assert abs(_m.hypot(mx - fx, my - fy) - g.bodies["eope"].a) < 1e-9


def test_bare_moon_services():
    g = new_game()
    g.ships["pc1"].at = "eope"
    g.ships["pc1"].loc = "eope-surface"
    expect_raise(lambda: infra.refuel(g, "pc1"))
    expect_raise(lambda: infra.transfer_local(g, "pc1", "eope-station"))


MOONED = ("tern", "fulmaior")


def test_orbital_rings_sit_inside_the_innermost_moon():
    """Stations/terminals must orbit far below the first moon.

    Regression guard: rings used to ride at a=0.042 while Tern's Moon was at
    a=0.025, so the moons rendered INSIDE the station ring and every system
    read inside-out — the moons looked like low orbit.
    """
    g = new_game()
    for parent in MOONED:
        inner = min(b.a for b in g.bodies.values() if b.parent == parent)
        for kind in ("terminal", "station"):
            for body, loc in ((b, l) for l in g.locations.values()
                              for b in [l["body"]] if l["kind"] == kind and l["body"] == parent):
                orbit_a, _period, _phase = state.orbit_geometry(loc)
                assert orbit_a < inner * 0.25, f"{body} {kind} {orbit_a} vs inner moon {inner}"


def test_terminals_are_in_synchronous_orbit():
    """A space elevator's counterweight must co-rotate with its planet.

    This is the whole reason a tether is stable and why the elevator ride
    undercuts a rocket climb: the terminal's orbital period is the host's
    sidereal rotation, exactly. Invented periods (it used to be a flat 1.8d
    for every terminal) break that link to the planet it hangs from.
    """
    g = new_game()
    terminals = [l for l in g.locations.values() if l["kind"] == "terminal"]
    assert terminals, "fixture should have at least one elevator"
    for loc in terminals:
        _a, period, _phase = state.orbit_geometry(loc)
        rot = state.rotation_period(loc["body"])
        assert abs(period - rot) < 1e-9, f"{loc['id']} period {period} != {rot} rotation"


def test_terminal_synchronous_radius_matches_the_planet():
    """The synchronous shell sits a real fraction of the way out to the moons.

    Earth's is 9.3% of the Moon's orbit; without that ratio an elevator ring
    ends up either inside the planet's drawn disc or level with the moons.
    """
    g = new_game()
    for loc in [l for l in g.locations.values() if l["kind"] == "terminal"]:
        parent = loc["body"]
        moons = [b.a for b in g.bodies.values() if b.parent == parent]
        orbit_a, _p, _ph = state.orbit_geometry(loc)
        if not moons:
            # Moonless host (Nellus): the shell is the outermost thing on the
            # planet, so only the station has to sit inside it.
            continue
        inner = min(moons)
        assert 0.05 < orbit_a / inner < 0.20, f"{parent} sync shell {orbit_a / inner:.3f} of inner moon"


def test_stations_orbit_inside_and_faster_than_the_ground():
    """Low orbit: inside the synchronous shell, and quicker than the rotation."""
    g = new_game()
    for loc in [l for l in g.locations.values() if l["kind"] == "station"]:
        body = loc["body"]
        a, period, _phase = state.orbit_geometry(loc)
        assert a < state.SYNCHRONOUS_R.get(body, state.DEFAULT_SYNCHRONOUS_R), f"{body} station outside sync shell"
        assert period < state.rotation_period(body), f"{body} station slower than its ground"


def test_moon_orbits_are_well_separated():
    """Neighbouring moons need real radial separation, not a hair's breadth."""
    g = new_game()
    for parent in MOONED:
        radii = sorted(b.a for b in g.bodies.values() if b.parent == parent)
        assert len(radii) >= 2, f"{parent} needs moons"
        for inner, outer in zip(radii, radii[1:]):
            assert outer / inner > 1.3, f"{parent}: {inner} -> {outer} too close"


def test_moon_radii_are_a_real_fraction_of_the_heliocentric_orbit():
    """A moon system is a fraction of a percent of the planet's own orbit.

    Earth's Moon is 0.257% of Earth's heliocentric radius. The moons were once
    at 20-29% of Tern's, which put a visible ring around every world in the
    heliocentric view and made the planetary orbits look wrong by comparison.
    """
    g = new_game()
    for parent in MOONED:
        helio = g.bodies[parent].a
        inner = min(b.a for b in g.bodies.values() if b.parent == parent)
        frac = inner / helio
        assert frac < 0.01, f"{parent} inner moon is {frac * 100:.1f}% of its own orbit"
        assert frac > 0.0001, f"{parent} inner moon implausibly tight"


def test_moon_periods_survive_the_radius_rescale():
    """Radii are cosmetic; the clock is fixed by the parent's mu. Guard both."""
    g = new_game()
    expect = {"moon": 30.0, "tide": 360.0 / 7.0, "eope": 6.0, "cenaedo": 16.0, "cteta": 38.0}
    for moon_id, want in expect.items():
        body = g.bodies[moon_id]
        mu = orbits.MU_BY_PARENT[body.parent]
        got = orbits.period(body.a, mu)
        assert abs(got - want) / want < 0.01, f"{moon_id} period {got} != {want}"


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
        ("rings_inside_moons", test_orbital_rings_sit_inside_the_innermost_moon),
        ("terminal_synchronous", test_terminals_are_in_synchronous_orbit),
        ("sync_shell_ratio", test_terminal_synchronous_radius_matches_the_planet),
        ("station_low_orbit", test_stations_orbit_inside_and_faster_than_the_ground),
        ("moon_separation", test_moon_orbits_are_well_separated),
        ("moon_helio_fraction", test_moon_radii_are_a_real_fraction_of_the_heliocentric_orbit),
        ("periods_after_rescale", test_moon_periods_survive_the_radius_rescale),
    ]
    ok = all(check(n, f) for n, f in tests)
    print(f"\n{len(PASS)}/{len(tests)} passed")
    sys.exit(0 if ok else 1)
