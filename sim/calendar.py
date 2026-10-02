"""Calendar and clock: the pthmud Situation timekeeping, ported to game-days.

Source of truth is `pthmud/world/timekeeping.py` + `world/names.py` +
`zodiac.csv`. The MUD measures `t` in game-*seconds* with
GAME_YEAR = 31_104_000; spacegame already counts `t` in game-DAYS, and the two
agree exactly because a Sol year is 360 days (`MU_SUN` gives Tern a 360d period,
which is also the MUD's arithmetic). So `DAY_LENGTH` here is exactly 1.0 and no
unit conversion is needed -- this is the MUD's calendar with the seconds divided
out. That is why the periods in `sim/orbits.py` are "MUD-literal" and why Moon is
30d (360/12) and Tide 360/7d.

Four calendars, two clocks, and the Chaldean planetary day, all computed from `t`:

- **New Rational** -- the official one. Astronomical, 12 zodiac months of exactly
  30 days, year beginning at 0 deg Aries (the equinox). Because the Sun moves
  1 deg/day in a 360-day year, ecliptic longitude IS the day of the year, so it
  cannot drift. Years run from the calendar reform at t = -800 years.
- **Old Rational** -- the Meritocracy's arithmetic calendar: 10 months of 36 days
  (360/year, no intercalation), years from the founding at t = -2400 years. It
  drifted against the seasons over 1600 years, which is what motivated the
  reform. At the reform instant it reads Year 1601 while the new one reads
  Year 1 -- `test_calendar.py` pins that handover.
- **Religious (bilunar)** -- observational, tracking both moons: 12 Moon months
  of 30d and 7 Tidemonths of 360/7d, nested in a 7-level hierarchy of sevens
  (Month, Tidemonth, Year, Heptade, Grand Year, Age, Aeon) each named for a
  planet. This is where the long horizons come from, and it matters for a game
  whose outer planet takes 29 years to go around.
- **Planetary days** -- 7-day week in Chaldean order, each day's ruler 3 places
  further on than the last (24 mod 7 = 3). So every day shifts the whole sequence.

Clocks: New Standard is 24h x 100 decminutes x 100 decseconds. Old Rational is
10h x 100 beats x 10 decibeats, the smaller unit (~8.6 real seconds) that older
institutions schedule against.

Two things are computed here that the MUD delegates to its astrology handler,
because spacegame has the orbital elements to do it properly:

- `planetary_hour` uses each body's `state.ROTATION` to find its subsolar
  longitude. The MUD's version has 12 variable-length daytime hours and 12
  variable-length night hours sized by a real sunrise/sunset at an observer's
  latitude; without a latitude for our locations we use 12 equal two-hour blocks
  and say so. The Chaldean ruler sequence and the 3-per-day drift are identical.
- `moon_phase` is real, not decorative: it is the true planetocentric angle
  between a moon and the Sun as seen from its primary, so a "new Moon" here is
  the same event the MUD calls one.
"""
from __future__ import annotations

import math

from .state import ROTATION, rotation_period

# --- Constants ---------------------------------------------------------------
DAYS_PER_YEAR = 360.0          # MUD GAME_YEAR, in spacegame's game-days
DAY_LENGTH = 1.0               # one game-day; the MUD divides GAME_YEAR by this
ZODIAC_DEGREES = 30.0          # the Sun moves 1 deg/day, so longitude = day of year

# Era epochs, in game-years relative to the Cosmic Nativity (t = 0).
MERITOCRATIC_FOUNDING = -2400.0
CALENDAR_REFORM = -800.0

# Planet sequence, Chaldean order. Same tuple as world.names.PLANETS.
PLANETS = ("Moon", "Tide", "Veluvy", "Nellus", "Sun", "Arax", "Fulmaior")

# Day names in DAYS order (world.names.DAYS).
DAY_NAMES = ("Monday", "Wracksday", "Gleamsday", "Tidanday",
             "Welanday", "Snelsday", "Sunday")

# Old Rational months: bureaucratic Latin, unique to the timekeeping module.
OLD_RATIONAL_MONTHS = ("Primum", "Secundum", "Tertium", "Quartum", "Quintum",
                       "Sextum", "Septimum", "Octavum", "Novembrum", "Decimum")

# Religious calendar: Moon months are the Islamic-style placeholder names from
# the MUD; the Tidemonth is named for its planet instead.
MOON_MONTHS = ("Muharram", "Safar", "Rabi al-Awwal", "Rabi al-Thani",
               "Jumada al-Awwal", "Jumada al-Thani", "Rajab", "Shaban",
               "Ramzan", "Shawwal", "Dhu al-Qadah", "Dhu al-Hijjah")

# Zodiac: (name, element, mode, ruler, sect, time_of_day) from world/zodiac.csv.
ZODIAC = (
    ("Vermis", "fire", "cardinal", "Arax", "diurnal", "afternoon"),
    ("Lupus", "earth", "fixed", "Nellus", "nocturnal", "dawn/dusk"),
    ("Iudices", "air", "mutable", "Veluvy", "diurnal", "deep night"),
    ("Castor", "water", "cardinal", "Moon", "nocturnal", "midnight"),
    ("Pavo", "fire", "fixed", "Sun", "diurnal", "noon"),
    ("Verna", "earth", "mutable", "Veluvy", "nocturnal", "deep night"),
    ("Hasta", "air", "cardinal", "Nellus", "diurnal", "dawn/dusk"),
    ("Torpedo", "water", "fixed", "Arax", "nocturnal", "afternoon"),
    ("Lustrarius", "fire", "mutable", "Fulmaior", "diurnal", "morning"),
    ("Aprolutra", "earth", "cardinal", "Tide", "nocturnal", "evening"),
    ("Veterarius", "air", "fixed", "Tide", "diurnal", "evening"),
    ("Phocae", "water", "mutable", "Fulmaior", "nocturnal", "morning"),
)

# Clock subdivision.
NEW_HOURS_PER_DAY = 24
NEW_DECMINUTES_PER_HOUR = 100
NEW_DECSECONDS_PER_MINUTE = 100
OLD_HOURS_PER_DAY = 10
OLD_BEATS_PER_HOUR = 100
OLD_DECIBEATS_PER_BEAT = 10

RELIGIOUS_LEVELS = ("Month", "Tidemonth", "Year", "Heptade",
                    "Grand Year", "Age", "Aeon")

_SUFFIX = {1: "st", 2: "nd", 3: "rd"}


def ordinal(n: int) -> str:
    """1 -> 1st, 2 -> 2nd, 13 -> 13th. The MUD f-string wrote '1th'."""
    if 11 <= (n % 100) <= 13:
        return str(n) + "th"
    return str(n) + _SUFFIX.get(n % 10, "th")

MOON_PHASE_NAMES = ("New", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
                    "Full", "Waning Gibbous", "Last Quarter", "Waning Crescent")

TAU = math.tau
_wrap = lambda x: (x + math.pi) % TAU - math.pi


def _whole(t: float, period: float) -> int:
    """floor(t / period) for t >= 0, nudged off exact-integer boundaries.

    360/7 is not representable in binary, so t = 3*(360/7) divides back to
    2.9999999999999996 and a plain floor() silently drops a whole Tidemonth --
    which came out as Moon, Tide, Veluvy, Veluvy, Sun, Arax, Arax. The MUD dodges
    this by working in integer game-seconds; we work in days, so we absorb the
    ULP with an epsilon orders of magnitude below anything the player could
    advance (1e-9 days is about 0.1ms).
    """
    q = t / period
    return int(math.floor(q + (1e-9 if q >= 0 else -1e-9)))


# --- New Rational: the official calendar ------------------------------------
def new_rational(t: float, reform: float = CALENDAR_REFORM * DAYS_PER_YEAR) -> dict:
    """12 zodiac months of exactly 30 days. Month 1 begins at 0 deg Aries.

    Self-correcting by construction: the Sun moves 1 deg/day, so ecliptic
    longitude equals the day of the year directly and no drift is possible.
    """
    elapsed = t - reform
    year = _whole(elapsed, DAYS_PER_YEAR) + 1
    total_days = _whole(t, DAY_LENGTH)
    doy = total_days % 360
    month = doy // 30 + 1
    day = doy % 30 + 1
    sign = ZODIAC[month - 1]
    return {
        "year": year, "month": month, "day": day,
        "month_name": sign[0],
        "sign": {"name": sign[0], "element": sign[1], "mode": sign[2],
                 "ruler": sign[3], "sect": sign[4], "time_of_day": sign[5],
                 "degree": round((doy % 30) * ZODIAC_DEGREES / 30.0, 2)},
        "day_of_year": doy + 1,
        "text": f"{day} {sign[0]}, Year {year}",
    }


# --- Old Rational: the arithmetic calendar -----------------------------------
def old_rational(t: float, founding: float = MERITOCRATIC_FOUNDING * DAYS_PER_YEAR) -> dict:
    """10 months of 36 days, 360/year, no intercalation. Drift is the point."""
    total_days = _whole(t - founding, DAY_LENGTH)
    year = total_days // 360 + 1
    doy = total_days % 360
    month = doy // 36 + 1
    day = doy % 36 + 1
    return {"year": year, "month": month, "day": day,
            "month_name": OLD_RATIONAL_MONTHS[month - 1],
            "text": f"{day} {OLD_RATIONAL_MONTHS[month - 1]}, Year {year} (Old Reckoning)"}


# --- Religious: bilunar, seven levels of sevens ------------------------------
def religious(t: float) -> dict:
    """Moon months 30d, Tidemonths 360/7d, nested in a 7-level hierarchy.

    The hierarchy is: Month (30d, counted mod 12, named after the Islamic-style
    months), then six further levels each 7x the last and counted mod 7 --
    Tidemonth, Year, Heptade, Grand Year, Age, Aeon -- each named for a planet.
    Those six are what a date can be expanded into.
    """
    moon_period = DAYS_PER_YEAR / 12.0
    tidemonth_period = DAYS_PER_YEAR / 7.0
    # The six 7-fold levels, innermost first.
    level_periods = [tidemonth_period]
    for _ in range(5):
        level_periods.append(level_periods[-1] * 7.0)
    level_keys = ("tidemonth", "year", "heptade", "grand_year", "age", "aeon")

    moon_day = _whole(t % moon_period, DAY_LENGTH)
    tidemonth_day = _whole(t % tidemonth_period, DAY_LENGTH)
    moon_month = _whole(t, moon_period) % 12

    levels = {}
    for key, period in zip(level_keys, level_periods):
        index = _whole(t, period) % 7
        levels[key] = {"index": index, "name": PLANETS[index],
                       "period_days": period,
                       "progress": (t % period) / period if period else 0.0}
    return {
        "moon_day": moon_day, "moon_day_number": moon_day + 1,
        "moon_month": moon_month, "moon_month_name": MOON_MONTHS[moon_month],
        "moon_period_days": moon_period,
        "tidemonth_day": tidemonth_day,
        "levels": levels,
        "text": (f"the {ordinal(moon_day + 1)} day of the Month of {MOON_MONTHS[moon_month]}, "
                 f"in the Tidemonth of {levels['tidemonth']['name']}, "
                 f"in the Year of {levels['year']['name']}, "
                 f"in the Heptade of {levels['heptade']['name']}, "
                 f"in the Grand Year of {levels['grand_year']['name']}, "
                 f"in the Age of {levels['age']['name']}, "
                 f"in the Aeon of {levels['aeon']['name']}"),
        "secular": "  ".join(f"{n}: {levels[k]['name']}" for n, k in
                             (("Month", "tidemonth"), ("Year", "year"),
                              ("Heptade", "heptade"), ("GrandYear", "grand_year"),
                              ("Age", "age"), ("Aeon", "aeon"))),
        "mystical": (f"the {ordinal(moon_day + 1)} of {MOON_MONTHS[moon_month]}, "
                     f"in the {PLANETS[1]} of {levels['tidemonth']['name']}, "
                     f"in the {PLANETS[2]} of {levels['year']['name']}, "
                     f"in the {PLANETS[3]} of {levels['heptade']['name']}, "
                     f"in the {PLANETS[4]} of {levels['grand_year']['name']}, "
                     f"in the {PLANETS[5]} of {levels['age']['name']}, "
                     f"in the {PLANETS[6]} of {levels['aeon']['name']}"),
    }


# --- Planetary days ----------------------------------------------------------
def day_of_week(t: float) -> dict:
    """7-day week, Chaldean order. 24 hours and 7 planets give 24 mod 7 = 3, so
    the whole ruler sequence shifts 3 places each day."""
    total_days = _whole(t, DAY_LENGTH)
    idx = (total_days * 3) % 7
    return {"index": idx, "name": DAY_NAMES[idx], "ruler": PLANETS[idx],
            "day_number": total_days, "text": f"{DAY_NAMES[idx]} — {PLANETS[idx]}"}


# --- Clocks ------------------------------------------------------------------
def new_standard_time(t: float) -> dict:
    """24h x 100 decminutes x 100 decseconds."""
    total = int((t % DAY_LENGTH) * (NEW_HOURS_PER_DAY * NEW_DECMINUTES_PER_HOUR
                                    * NEW_DECSECONDS_PER_MINUTE))
    hour = (total // (NEW_DECMINUTES_PER_HOUR * NEW_DECSECONDS_PER_MINUTE)) % NEW_HOURS_PER_DAY
    decmin = (total // NEW_DECSECONDS_PER_MINUTE) % NEW_DECMINUTES_PER_HOUR
    decsec = total % NEW_DECSECONDS_PER_MINUTE
    return {"hour": hour, "decminute": decmin, "decsecond": decsec,
            "text": f"{hour:02d}:{decmin:02d}:{decsec:02d}"}


def old_rational_time(t: float) -> dict:
    """10h x 100 beats x 10 decibeats -- the ~8.6-real-second scheduling unit."""
    total = int((t % DAY_LENGTH) * (OLD_HOURS_PER_DAY * OLD_BEATS_PER_HOUR
                                    * OLD_DECIBEATS_PER_BEAT))
    hour = (total // (OLD_BEATS_PER_HOUR * OLD_DECIBEATS_PER_BEAT)) % OLD_HOURS_PER_DAY
    beat = (total // OLD_DECIBEATS_PER_BEAT) % OLD_BEATS_PER_HOUR
    decibeat = total % OLD_DECIBEATS_PER_BEAT
    return {"hour": hour, "beat": beat, "decibeat": decibeat,
            "text": f"{hour}h {beat:02d}b {decibeat}d"}


# --- Astronomy the MUD delegates to its handler ------------------------------
def subsolar_longitude(t: float, body, bodies: dict) -> float:
    """Ground-frame longitude (radians) of the point under the Sun.

    A surface point's inertial longitude is its fixed longitude plus the body's
    rotation, so the subsolar point drifts westward once per sidereal day.
    """
    from . import orbits
    parent = bodies[body.parent] if body.parent else body
    # Direction from the body to the Sun is its heliocentric longitude + pi.
    sun_dir = orbits.body_angle(parent, t) + math.pi
    rot = rotation_period(body.id)
    return (sun_dir - TAU * t / rot) % TAU


def planetary_hour(t: float, body, bodies: dict) -> dict:
    """Chaldean hour at a body's prime meridian.

    The MUD splits the day into 12 variable daytime and 12 variable night hours
    sized by real sunrise/sunset at an observer's latitude. Our locations have
    no latitude, so this uses 12 equal two-hour blocks instead -- documented as
    a simplification. The ruler sequence and the 3-per-day drift are identical.
    """
    sub = subsolar_longitude(t, body, bodies)
    solar_hour = (12.0 - math.degrees(sub) / 15.0) % 24.0
    is_day = 6.0 <= solar_hour < 18.0
    block = int(solar_hour // 2.0)
    dow = day_of_week(t)["index"]
    ruler = PLANETS[(dow + block) % 7]
    return {"number": block + 1, "ruler": ruler, "is_day": is_day,
            "solar_hour": round(solar_hour, 3),
            "text": f"hour {block + 1} {'day' if is_day else 'night'} — {ruler}"}


def moon_phase(t: float, moon, bodies: dict) -> dict:
    """True phase of a moon as seen from its primary.

    This is the real planetocentric angle between the moon and the Sun, so "new
    Moon" means the same thing here as it does in the MUD's religious calendar:
    the moon lies between its planet and the Sun.
    """
    from . import orbits
    primary = bodies[moon.parent]
    sun_dir = orbits.body_angle(primary, t) + math.pi
    elong = _wrap(orbits.body_angle(moon, t) - sun_dir)
    frac = (elong % TAU) / TAU
    index = int(round(frac * 8.0)) % 8
    waxing = math.sin(elong) > 0
    rate = _synodic_rate(moon, primary)          # cycles per day
    return {"fraction": round(frac, 4), "elongation_deg": round(math.degrees(elong), 2),
            "index": index, "name": MOON_PHASE_NAMES[index],
            "waxing": waxing,
            "illumination": round((1.0 - math.cos(elong)) / 2.0, 4),
            "synodic_days": round(1.0 / abs(rate), 3) if rate else None}


def _synodic_rate(moon, primary) -> float:
    """Cycles/year difference between the moon and the Sun as seen from the
    primary: n_moon - n_sun. For Moon of Tern that is 12 - 1 = 11/year, giving
    a synodic month of 360/11 = 32.73d (Earth's is 29.5d for 11.97 synodic)."""
    from . import orbits
    n_moon = TAU / orbits.period(moon.a, orbits.MU_BY_PARENT[moon.parent])
    n_primary = TAU / orbits.period(primary.a, orbits.MU_SUN)
    return (n_moon - n_primary) / TAU


def conjunction_next(t: float, moons, bodies: dict) -> dict:
    """Next date on which two moons share a planetocentric longitude.

    Solve (a0 - b0) + (wa - wb)*t = 2*pi*k for the smallest t > now. Two moons
    recur every 2*pi/|wa - wb|; for Moon and Tide that is 360/|12-7| = 72 days.

    The MUD calls its epoch a "great conjunction" and says it recurs every 7
    years, because in 7 years Moon completes 84 cycles and Tide 49. True, but not
    minimal: 12 Moon cycles and 7 Tide cycles are exactly one 360-day year, so
    the same configuration returns every year. We compute the real recurrence
    from the fixture's own phases rather than assert a number.
    """
    best = None
    for i in range(len(moons)):
        for j in range(i + 1, len(moons)):
            a, b = moons[i], moons[j]
            wa = TAU / _period_of(a, bodies)
            wb = TAU / _period_of(b, bodies)
            omega = wa - wb
            if abs(omega) < 1e-12:
                continue
            phi = (a.angle0 - b.angle0) % TAU          # in [0, 2pi)
            if omega > 0:
                first = ((TAU - phi) % TAU) / omega    # phi == 0 -> one period
            else:
                first = phi / (-omega)                # phi == 0 -> 0, fixed below
                if first <= 1e-9:
                    first = TAU / (-omega)
            period = TAU / abs(omega)
            if first <= t + 1e-9:                     # already passed: next cycle
                k = math.floor((t - first) / period) + 1
                nxt = first + k * period
            else:
                nxt = first
            if best is None or nxt < best["t"]:
                best = {"t": nxt, "pair": [a.name, b.name],
                        "period_days": period}
    if best is None:
        return {}
    best["t"] = round(best["t"], 3)
    best["period_days"] = round(best["period_days"], 3)
    best["day"] = round(best["t"] - t, 2)
    best["date"] = new_rational(best["t"])["text"]
    return best


def _period_of(moon, bodies: dict) -> float:
    from . import orbits
    return orbits.period(moon.a, orbits.MU_BY_PARENT[moon.parent])


# --- The composite -----------------------------------------------------------
def calendar(t: float, game) -> dict:
    """Everything the renderer needs for one instant, in one dict."""
    nr = new_rational(t)
    dow = day_of_week(t)
    moons = []
    by_primary = {}
    for body in game.bodies.values():
        if not body.parent:
            continue
        phase = moon_phase(t, body, game.bodies)
        phase["id"] = body.id
        phase["name_full"] = body.name
        phase["primary"] = body.parent
        phase["period_days"] = round(_period_of(body, game.bodies), 2)
        moons.append(phase)
        by_primary.setdefault(body.parent, []).append(body)
    moons.sort(key=lambda m: (m["primary"], m["fraction"]))

    conjunctions = [conjunction_next(t, group, game.bodies)
                    for group in by_primary.values() if len(group) >= 2]

    ship = next(iter(game.ships.values()), None)
    body_clock = None
    solar = None
    if ship is not None:
        host = ship.at or (ship.leg.dest if ship.leg else None)
        if host and host in game.bodies:
            body_clock = planetary_hour(t, game.bodies[host], game.bodies)
            body_clock["body"] = host
            body_clock["body_name"] = game.bodies[host].name
            body_clock["rotation_days"] = round(rotation_period(host), 3)
            # Local solar time is the clock that actually moves here. The sim
            # advances in whole game-days, so the MUD's standard 24h clock reads
            # 00:00:00 forever; the world's own rotation does not.
            h = body_clock["solar_hour"]
            solar = {"hour": int(h), "minute": int(round((h % 1) * 60)),
                     "text": f"{int(h):02d}:{int(round((h % 1) * 60)):02d}",
                     "at": game.bodies[host].name}

    return {
        "t": round(t, 3),
        "day_of_year": nr["day_of_year"],
        "year_fraction": round((t % DAYS_PER_YEAR) / DAYS_PER_YEAR, 5),
        "new_rational": nr,
        "old_rational": old_rational(t),
        "religious": religious(t),
        "day": dow,
        "new_time": new_standard_time(t),
        "old_time": old_rational_time(t),
        "solar_time": solar,
        "sign": nr["sign"],
        "moons": moons,
        "conjunctions": [c for c in conjunctions if c],
        "body_clock": body_clock,
        "era": {"founding": MERITOCRATIC_FOUNDING * DAYS_PER_YEAR,
                "reform": CALENDAR_REFORM * DAYS_PER_YEAR},
        "headline": f"{nr['text']} · {dow['text']}",
    }