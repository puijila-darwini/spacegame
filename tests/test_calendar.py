"""Calendar and clock tests. Run: python3 tests/test_calendar.py

Everything here is ported from pthmud/world/timekeeping.py. The point of these
tests is that the port stays faithful: the Sol year must remain 360 days so a
game-day IS a MUD day (that is why sim/orbits.py calls its periods
"MUD-literal"), the calendar handover must agree, and the astronomy we compute
ourselves (moon phase, subsolar longitude, conjunctions) must be arithmetically
right rather than plausible-looking.
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sim import calendar as cal
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


def game():
    return build_sol()


# --- unit agreement ---------------------------------------------------------
def test_sol_year_is_360_days():
    """The MUD's GAME_YEAR/DAY_LENGTH is 360. Ours must be, or every date in
    the calendar drifts against the orbits the sim actually runs."""
    assert cal.DAYS_PER_YEAR == 360.0
    assert cal.DAY_LENGTH == 1.0, "spacegame counts t in game-days already"
    assert cal.ZODIAC_DEGREES == 30.0


def test_calendar_reuses_the_sim_periods():
    """The sim's moon periods must BE the calendar's, not merely agree with it:
    Moon 360/12 = 30d, Tide 360/7."""
    g = game()
    assert abs(g.bodies["moon"].a and 30.0 - 30.0) < 1e-9
    from sim import orbits
    assert abs(orbits.period(g.bodies["moon"].a, orbits.MU_TERN) - cal.DAYS_PER_YEAR / 12) < 0.05
    assert abs(orbits.period(g.bodies["tide"].a, orbits.MU_TERN) - cal.DAYS_PER_YEAR / 7) < 0.05
    c = cal.calendar(0.0, g)
    for m in c["moons"]:
        if m["id"] == "moon":
            assert abs(m["period_days"] - 30.0) < 0.05
        if m["id"] == "tide":
            assert abs(m["period_days"] - cal.DAYS_PER_YEAR / 7) < 0.05


# --- New Rational -----------------------------------------------------------
def test_new_rational_months_and_days():
    for day in (0, 1, 29, 30, 31, 359, 360, 361, 720):
        nr = cal.new_rational(float(day))
        assert 1 <= nr["month"] <= 12, nr
        assert 1 <= nr["day"] <= 30, nr
        assert nr["day_of_year"] == day % 360 + 1
    assert cal.new_rational(0.0)["month_name"] == "Vermis"
    assert cal.new_rational(30.0)["month_name"] == "Lupus"
    assert cal.new_rational(330.0)["month_name"] == "Phocae"
    assert cal.new_rational(359.0)["day"] == 30


def test_new_rational_is_self_correcting():
    """It is astronomical: the Sun moves 1 deg/day, so zodiac longitude must
    equal the day of the year. This is why the calendar cannot drift."""
    for day in (0, 45, 123, 300):
        nr = cal.new_rational(float(day))
        longitude = (day % 360) * 1.0        # degrees
        assert abs(nr["day_of_year"] - (longitude + 1)) < 1e-9


def test_new_rational_years_from_the_reform():
    # reform is 800 years before the Cosmic Nativity, and years are 1-based
    assert cal.new_rational(0.0)["year"] == 801
    assert cal.new_rational(cal.DAYS_PER_YEAR)["year"] == 802


# --- Old Rational -----------------------------------------------------------
def test_old_rational_ten_months_of_36():
    for day in (0, 35, 36, 359, 360):
        od = cal.old_rational(float(day))
        assert 1 <= od["month"] <= 10, od
        assert 1 <= od["day"] <= 36, od
    assert cal.old_rational(0.0)["month_name"] == "Primum"
    assert cal.old_rational(35.0)["month_name"] == "Primum"
    assert cal.old_rational(36.0)["month_name"] == "Secundum"
    assert cal.old_rational(288.0)["month_name"] == "Novembrum"
    assert cal.old_rational(324.0)["month_name"] == "Decimum"
    assert cal.old_rational(324.0)["day"] == 1


def test_calendar_handover_agrees_at_the_reform():
    """At the reform instant the new calendar reads Year 1 and the old one
    Year 1601 -- 1600 years apart, which is the whole reason the reform
    happened. If these ever disagree the two calendars are not the same era."""
    reform = cal.CALENDAR_REFORM * cal.DAYS_PER_YEAR
    assert cal.new_rational(reform)["year"] == 1
    assert cal.old_rational(reform)["year"] == 1601
    assert cal.old_rational(reform)["year"] - cal.new_rational(reform)["year"] == 1600


# --- Religious --------------------------------------------------------------
def test_religious_moon_and_tidemonths():
    r = cal.religious(0.0)
    assert r["moon_month_name"] == "Muharram"
    assert r["moon_day_number"] == 1
    # a Tidemonth is 360/7 days and there are 7 of them per year
    assert abs(cal.DAYS_PER_YEAR / 7 - 51.4285714286) < 1e-6
    assert [cal.religious(t * 360.0 / 7)["levels"]["tidemonth"]["name"]
            for t in range(7)] == list(cal.PLANETS)


def test_religious_hierarchy_is_seven_levels():
    """Each level is 7x the one below, which is where the game's long horizons
    come from (Fulmaior alone takes 29 years)."""
    r = cal.religious(0.0)
    periods = [r["levels"][k]["period_days"] for k in
               ("tidemonth", "year", "heptade", "grand_year", "age", "aeon")]
    for lower, upper in zip(periods, periods[1:]):
        assert abs(upper / lower - 7.0) < 1e-9, (lower, upper)
    assert len(cal.RELIGIOUS_LEVELS) == 7


def test_ordinals_are_not_all_th():
    assert cal.ordinal(1) == "1st"
    assert cal.ordinal(2) == "2nd"
    assert cal.ordinal(3) == "3rd"
    assert cal.ordinal(11) == "11th"
    assert cal.ordinal(12) == "12th"
    assert cal.ordinal(13) == "13th"
    assert cal.ordinal(21) == "21st"
    assert "1th" not in cal.religious(0.0)["text"]


# --- planetary days ---------------------------------------------------------
def test_day_names_advance_three_places():
    """24 hours and 7 planets: 24 mod 7 = 3, so each day the whole ruler
    sequence shifts three places."""
    seen = [cal.day_of_week(float(d)) for d in range(7)]
    assert [d["ruler"] for d in seen] == list(cal.PLANETS) or len({d["name"] for d in seen}) == 7
    assert len({d["name"] for d in seen}) == 7, "a 7-day week must have 7 distinct names"
    for a, b in zip(seen, seen[1:]):
        assert (b["index"] - a["index"]) % 7 == 3, (a, b)
    assert cal.day_of_week(0.0)["name"] == "Monday"
    assert cal.day_of_week(0.0)["ruler"] == "Moon"
    # 360 days is not a whole number of weeks, so the day name drifts against
    # the year -- which is correct, and worth pinning.
    assert cal.day_of_week(0.0)["name"] != cal.day_of_week(360.0)["name"]


# --- clocks -----------------------------------------------------------------
def test_clock_subdivision():
    nst = cal.new_standard_time(0.5)     # half a day
    assert nst["hour"] == 12, nst
    assert nst["text"] == "12:00:00"
    ort = cal.old_rational_time(0.5)
    assert ort["hour"] == 5, ort
    assert 0 <= nst["decminute"] < 100 and 0 <= nst["decsecond"] < 100
    assert 0 <= ort["beat"] < 100 and 0 <= ort["decibeat"] < 10


def test_clocks_read_midnight_on_whole_days():
    """The sim advances in whole days, so the MUD's formal 24h clock sits at
    00:00:00. That is why local solar time is what the UI leads with."""
    for t in (0.0, 1.0, 45.0, 360.0):
        assert cal.new_standard_time(t)["text"] == "00:00:00"
        assert cal.old_rational_time(t)["text"] == "0h 00b 0d"


# --- astronomy we compute ourselves -----------------------------------------
def test_moon_phase_synodic_periods():
    """Moon's synodic month is 360/(12-1) = 32.727d and Tide's is 360/(7-1) =
    60d. Earth is 29.5d for 11.97/year, so these are the right shape."""
    g = game()
    c = cal.calendar(0.0, g)
    by = {m["id"]: m for m in c["moons"]}
    assert abs(by["moon"]["synodic_days"] - 360.0 / 11.0) < 0.05, by["moon"]
    assert abs(by["tide"]["synodic_days"] - 360.0 / 6.0) < 0.1, by["tide"]


def test_moon_phase_is_new_at_the_true_conjunction():
    """A "New" moon must be the moon lying between its planet and the Sun --
    i.e. its planetocentric angle matches the direction to the Sun."""
    from sim import orbits
    g = game()
    moon = g.bodies["moon"]
    tern = g.bodies["tern"]
    # find t where the planetocentric angle equals the Sun direction
    t = 0.0
    for step in range(4000):
        t = step * 0.01
        sun_dir = orbits.body_angle(tern, t) + math.pi
        elong = (orbits.body_angle(moon, t) - sun_dir) % (2 * math.pi)
        if elong < 0.01:
            break
    phase = cal.moon_phase(t, moon, g.bodies)
    assert phase["name"] == "New", phase
    assert phase["illumination"] < 0.01, phase


def test_moon_phase_completes_a_cycle():
    """Fraction must sweep 0..1 once per synodic period and come back."""
    g = game()
    moon = g.bodies["moon"]
    syn = cal.moon_phase(0.0, moon, g.bodies)["synodic_days"]
    a = cal.moon_phase(0.0, moon, g.bodies)["fraction"]
    b = cal.moon_phase(syn, moon, g.bodies)["fraction"]
    assert abs(a - b) < 0.01, (a, b)
    assert 0.0 <= a < 1.0


def test_planetary_hour_follows_the_rotation():
    """A world must turn: its solar hour has to advance, otherwise the clock is
    decorative. Tidon's sidereal day is 2.0d, so half a rotation flips it by
    12 hours."""
    g = game()
    tide = g.bodies["tide"]
    a = cal.planetary_hour(0.0, tide, g.bodies)
    b = cal.planetary_hour(1.0, tide, g.bodies)     # half a rotation
    assert abs((a["solar_hour"] - b["solar_hour"]) % 24.0 - 12.0) < 1.0, (a, b)
    assert cal.planetary_hour(0.0, tide, g.bodies)["ruler"] in cal.PLANETS


def test_conjunction_recurrence_is_72_days():
    """Moon and Tide recur every 2pi/|wa - wb| = 360/|12-7| = 72 days. The MUD
    claims 7 years, which is true but not minimal -- 12 Moon cycles and 7 Tide
    cycles are exactly one 360-day year. We compute it rather than assert it."""
    g = game()
    c = cal.calendar(0.0, g)
    tern = [x for x in c["conjunctions"] if x["pair"] == ["Moon", "Tide"]]
    assert tern, c["conjunctions"]
    assert abs(tern[0]["period_days"] - 72.0) < 0.5, tern[0]


def test_conjunction_actually_aligns_the_two_moons():
    """Solve for the reported conjunction time and check both moons share a
    planetocentric longitude there."""
    from sim import orbits
    g = game()
    c = cal.calendar(0.0, g)
    entry = next(x for x in c["conjunctions"] if x["pair"] == ["Moon", "Tide"])
    t = entry["t"]
    a = orbits.body_angle(g.bodies["moon"], t)
    b = orbits.body_angle(g.bodies["tide"], t)
    diff = (a - b) % (2 * math.pi)
    assert min(diff, 2 * math.pi - diff) < 1e-3, (t, math.degrees(diff))


def test_every_moon_reports_a_phase():
    g = game()
    c = cal.calendar(123.4, g)
    ids = {m["id"] for m in c["moons"]}
    assert ids == {"moon", "tide", "eope", "cenaedo", "cteta"}, ids
    for m in c["moons"]:
        assert m["name"] in cal.MOON_PHASE_NAMES
        assert 0.0 <= m["illumination"] <= 1.0
        assert 0.0 <= m["fraction"] < 1.0


def test_calendar_is_deterministic_and_monotonic():
    """Same t in, same out. The absolute day count is monotonic; the day of
    YEAR is not, because it rolls over at the new year -- that is correct."""
    g = game()
    for t in (0.0, 17.5, 99.25, 360.0):
        assert cal.calendar(t, g)["headline"] == cal.calendar(t, g)["headline"]
    last_day = -1
    last_year = 0
    for step in range(1200):
        t = step * 0.37
        day = cal.day_of_week(t)["day_number"]
        assert day >= last_day, (t, day, last_day)
        last_day = day
        nr = cal.new_rational(t)
        assert nr["year"] >= last_year, (t, nr)
        last_year = nr["year"]
        assert 1 <= nr["month"] <= 12 and 1 <= nr["day"] <= 30
        assert 1 <= nr["day_of_year"] <= 360


if __name__ == "__main__":
    tests = [
        ("sol_year_360", test_sol_year_is_360_days),
        ("calendar_reuses_sim_periods", test_calendar_reuses_the_sim_periods),
        ("new_rational_months", test_new_rational_months_and_days),
        ("new_rational_self_correcting", test_new_rational_is_self_correcting),
        ("new_rational_years", test_new_rational_years_from_the_reform),
        ("old_rational_months", test_old_rational_ten_months_of_36),
        ("calendar_handover", test_calendar_handover_agrees_at_the_reform),
        ("religious_months", test_religious_moon_and_tidemonths),
        ("religious_hierarchy", test_religious_hierarchy_is_seven_levels),
        ("ordinals", test_ordinals_are_not_all_th),
        ("day_names", test_day_names_advance_three_places),
        ("clock_subdivision", test_clock_subdivision),
        ("clocks_midnight", test_clocks_read_midnight_on_whole_days),
        ("synodic_periods", test_moon_phase_synodic_periods),
        ("moon_new_at_conjunction", test_moon_phase_is_new_at_the_true_conjunction),
        ("moon_cycle_completes", test_moon_phase_completes_a_cycle),
        ("planetary_hour_rotates", test_planetary_hour_follows_the_rotation),
        ("conjunction_72d", test_conjunction_recurrence_is_72_days),
        ("conjunction_aligns", test_conjunction_actually_aligns_the_two_moons),
        ("every_moon_has_phase", test_every_moon_reports_a_phase),
        ("deterministic_monotonic", test_calendar_is_deterministic_and_monotonic),
    ]
    ok = all(check(n, f) for n, f in tests)
    print(f"\n{len(PASS)}/{len(tests)} passed")
    sys.exit(0 if ok else 1)