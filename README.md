# Sol Merchant

A slow interstellar trading game: place capital, wait weeks, and find out what happened.

The simulation is written in Python with no third-party runtime dependencies. It models circular, coplanar Keplerian orbits, phase-gated Hohmann transfers, local ports with actual counterparties, slow capital allocation, and event-driven markets.

## Run the web interface

From this directory:

```sh
python3 web/server.py 8765
```

Then open <http://192.168.1.38:8765/> from another device on the LAN, or <http://127.0.0.1:8765/> locally.

The server exposes a JSON API under `/api/` and saves the campaign to `~/ai/tmp/spacegame/live.json` by default. Set `SPACEGAME_SAVE` to change the save path, `SPACEGAME_HOST` to change the bind address, or `SPACEGAME_AUTO=1` to advance one game day per real minute.

The game opens on a title screen with `Continue`, `New Game`, `Load Game`, `Save Game`, and `Settings`. New campaigns collect a captain name, company, first-ship name, campaign name, and difficulty — you start with one hull free, and it is the anchor for the whole arc. Blank company/ship fields fall back to `"<Captain>'s Company"` and `"Wayfarer"`. Saves are real named slots with metadata and offline-safe campaign state. Once in a campaign, market, ship, log, contacts, contracts, and settings open as centered modal dialogs rather than permanent dashboard panels.

## Interface controls

Once a campaign is opened, the game view is a camera-based canvas:

- drag to pan;
- use the wheel or a pinch gesture to zoom around the pointer;
- click a world or ship to select it;
- double-click a world to enter its full local system view (`100×–160×` depending on the world);
- use **System view** or `F` to focus the selected world in its co-moving local frame;
- use the **go to** selector to jump directly to any world, then **System view** to fit its moons and orbital sites automatically;
- read the **What have I selected** card at the top of the right rail — it follows whatever you last clicked (world, ship, or orbital site);
- use the frame selector to switch between heliocentric inertial coordinates and following the selected world;
- press `0` to reset the view and `+`/`-` to zoom; `F` enters the selected world's local system frame;
- when the selected ship is parked, select another world and use **Plan selected orbit** or the destination selector to plot and commit a transfer;
- use `+30d` or `+90d` for larger time jumps, or **Auto 1d/min** to let the live server advance one day per real minute; the same button pauses it.

At higher zoom, elevator terminals and stations appear as distinct markers orbiting their world. Surface locations remain valid destinations in the ship planner, but are intentionally not rendered as orbital objects. Selecting a station or terminal focuses the camera and preselects the matching local-transfer location in the ship panel. The local marker radii are renderer geometry for inspection; they do not change the Hohmann or delta-v simulation.

### System scale

Planetocentric radii are sized for the renderer, not for realism at a glance: the
innermost moon rides ~12–18 planet display radii out (`PLANET_DISC_DIV = 18` sets
the outermost ring), and station/terminal rings sit far inside the first moon
(Tern's terminal is 6% of Moon's orbit, its station 10%). Getting that ordering
wrong is what makes a system read inside-out — orbital infrastructure beyond the
moons, moons skimming the planet like low orbit.

The radii are therefore free to look right, because **periods are fixed by the
parent's `mu`, not by the radius**: `n = sqrt(mu/a^3)`, so scaling a moon's `a`
by `k` only needs its parent's `mu` scaled by `k^3` to hold the clock. Tern's
moons moved out 8× and Fulmaior's 6× with no change to the MUD-literal periods
(Moon 30d, Tide 360/7d, Eope 6d, Cenaedo 16d, Cteta 38d) — guarded by
`tests/test_infra.py::periods_after_rescale`. The heliocentric overview fits
itself to the outermost charted body, so the gate stays on screen.

### The Fulmaior Gate

The first inter-system anchor. It is a real body on the real map at a=15.0,
beyond Fulmaior's 9.43, with a time-driven lifecycle: `sealed` → `stabilising`
(within 120d of opening) → `open` at t=400d, ~1.1 Tern years. The overview
draws it as two counter-rotating rings rather than a disc.

**Transit is deliberately not wired up.** `orbits` refuses the gate in both
`next_window` and `fast_option`, and the selection card says so, because there
is no delta-v budget or wait time that would buy a crossing. The far side is
fixture data only — `state.build_alpha_phocae()` (hot inner world, temperate
middle, cold outer, one moon) so the shape of a second system is already
decided. Wiring the crossing is the next step, not this one.

### Selection

**What have I selected** is the top card in the right rail and the primary
readout: click a world, a ship, or an orbital location and it reports that
thing. `sel.focus` records *what was pointed at* — separate from
`sel.body`/`sel.ship`/`sel.location`, which are the derived camera and panel
context. Without it, clicking a ship parked at Tern is indistinguishable from
clicking Tern itself.

The right-hand panels follow the current selection. The interface defaults to a Classic Elite vector-HUD theme (cyan/amber, scanlines, starfield, squared telemetry panels); use **Theme: Greenhouse** to switch back to the original Nilotic Greenhouse styling. The **Body / Frame** panel shows the selected body's orbital period, parent, moons, orbital sites, and active reference frame. The operator console also includes a command palette (`Ctrl/Cmd+K`), arrival/deadline timeline, port watchlist, world bookmarks, ledger/contract/contact filters, snapshot export, and a diagnostics overlay. A body selection can be used as the transfer destination without leaving the system view.

Time jumps sweep the orbits rather than cutting to them: bodies interpolate on
their native angular period, and a stale poll can no longer truncate a sweep
in flight. A poll with unchanged game time leaves a running transition alone —
that bug snapped every world straight to its final position part-way through,
which read as a broken orbit. Sweep duration scales with the size of the jump
(1.2–3.2s).

## Tests

The test suite uses only the Python standard library:

```sh
python3 tests/test_movement.py
python3 tests/test_infra.py
python3 tests/test_markets.py
python3 tests/test_contacts.py
python3 tests/test_server.py
```

## Design

`gdd/gdd.md` is the design reference. The core principle is that movement, market information, and time are the scarce resources: every trade is a decision about `mass × delta-v × time × risk` against delivered value, scarcity, and urgency.
