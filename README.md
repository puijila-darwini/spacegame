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

Planetocentric radii are **real fractions of the heliocentric chart**, not
stylised: Moon 0.26% of Tern's orbit (Earth/Moon is 0.257%), Cteta 0.22% of
Fulmaior's (Jupiter's Callisto is 0.24%). They were briefly 20–29%, which put
a visible ring around every world in the heliocentric view and made the
planetary orbits look wrong by comparison.

The renderer handles the 400:1 span between a planetary orbit and a moon orbit
in two ways:

- **System views fit the outermost ring**, so absolute scale is invisible
  there — only ratios among moons and rings matter. `PLANET_DISC_DIV = 60` is
  the real Earth/Moon figure (60 Earth radii), which is also what leaves room
  for a synchronous shell at 5.6 disc-radii so an elevator ring does not sit
  inside its own planet. `MAX_ZOOM` is 6000 to reach a real moon system.
- **The heliocentric view suppresses anything under `MIN_RING_PX` (5px).** A
  moon system is genuinely sub-pixel from across a system, so it collapses to a
  speck instead of stacking a bright ring on the planet.

Ordering, and it is an ordering, not a vibe: innermost moon at ~42–60 disc
radii; synchronous shell at ~9% of the inner moon (Earth: 9.3%); station inside
that and faster than the ground. Getting it wrong makes a system read
inside-out — infrastructure beyond the moons, moons skimming the planet.

Periods are unaffected by any of this, because they are fixed by the parent's
`mu` and not by the radius: `n = sqrt(mu/a^3)`, so scaling a moon's `a` by `k`
needs its parent's `mu` scaled by `k^3` to hold the clock. MUD-literal periods
(Moon 30d, Tide 360/7d, Eope 6d, Cenaedo 16d, Cteta 38d) are guarded by
`tests/test_infra.py::periods_after_rescale`.

The planetary orbits themselves are Kepler-consistent with their MUD-literal
periods, so the radial gaps (Veluvy→Nellus 1.31×, →Tern 2.23×, →Arax 5.24×,
→Fulmaior 1.80×) are forced by `T ∝ a^1.5`, not chosen. The star's drawn size
scales with the innermost planetary orbit so its glow can never eclipse the
inner system — it used to be a fixed 26px glow over a 22px inner system.

### Space elevators are synchronous

A tether's counterweight must co-rotate with the ground, so **an elevator
terminal's orbital period IS its host's sidereal rotation** —
`state.ROTATION` (0.9–1.8d) with the terminal period taken directly from it
(`state.orbit_geometry`). This is why the tether is stable and why the 0.006dv
elevator ride undercuts a rocket climb. Stations are ordinary low orbit: inside
the synchronous shell at 0.55 of its radius and correspondingly faster
(0.16× the rotation period).

Guarded by `test_terminals_are_in_synchronous_orbit`,
`test_terminal_synchronous_radius_matches_the_planet`, and
`test_stations_orbit_inside_and_faster_than_the_ground`. The selection card
shows the terminal's period and the host's sidereal day side by side.

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

### Reading the canvas

**What have I selected** is the top card in the right rail and the primary
readout: click a world, a ship, or an orbital location and it reports that
thing. `sel.focus` records *what was pointed at* — separate from
`sel.body`/`sel.ship`/`sel.location`, which are the derived camera and panel
context. Without it, clicking a ship parked at Tern is indistinguishable from
clicking Tern itself.

**Labels** all go through one placement pass (`placeLabels`/`drawLabels`) and
therefore share a single collision space. Candidates are sorted by priority
(selection > ship > planet > moon > gate > location); each takes the first slot
that clears every already-placed box *and* every marker anchor on the map, and is
dropped entirely when nothing fits. Before this each subsystem drew its own text
at a fixed 10–11px, which put an 11px label on a 4px planet and stacked four
labels on the same point in Tern's system.

Three rules keep type in scale:

- **Font scales with its subject** — `labelFontPx` is `disc × 1.9` clamped to
  8–12px. A 3213× system view puts a planet 4px across; a fixed 11px label was
  nearly three times the size of the thing it named.
- **Halo is dark and proportional** (`lineWidth = font × 0.16`, theme `bg`).
  Its job is separating text from orbit rings. Stroking it in the *ink* colour
  bloomed the glyph counters and made labels unreadable.
- **Short names** — "Tern Elevator Crown" (114px) is drawn as `CROWN`;
  `shortLocName` takes the tail word. Surfaces get no label at all: they are
  body-anchored, so their label always landed underneath their planet's own.

Markers scale logarithmically and stay smaller than the world they mark: station
3.3px, terminal 2.8px, against a 4.3px planet disc at Tern's fitted zoom. They
used to be `3.5·√zoom` clamped at 10px — a 10px square on a 9px orbit.

### Zooming

The heliocentric view and a moon system are ~3200× apart. Three things make that
span usable:

- **The wheel rate eases with depth** — ~1.7× per notch at the overview settling
  to ~1.3× inside a system. A fixed 0.001 coefficient needed ~81 notches to
  cross the gulf; an earlier level-snapping rate was worse in a different way
  (2.3× jumps then a 0.7% dead notch), so the rate is a smooth monotonic
  function of zoom with no snapping.
- **Fitting a system eases** over ~520ms, interpolating zoom in log space.
  Fitting Tern is a 3000× move; done instantly it read as a cut. Any direct
  gesture (wheel, pan, pinch) cancels an in-flight move.
- **`MAX_ZOOM` is 4200**, chosen so the *deepest* mooned system still fits the
  canvas at full zoom (Tern's outer ring is 338px against a 340px half-canvas).
  Shallower systems can be zoomed past, which is ordinary map behaviour.

**The canvas backing store matches the element** at `devicePixelRatio` and draws
through a `PX` transform, with a `ResizeObserver` catching size changes the window
`resize` event misses. It was previously a fixed 860×680 stretched to ~1401px on
this display — every frame upscaled ~1.6×, which is why zooming looked soft.

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
python3 tests/test_page.py      # static gates for web/index.html
```

`test_page.py` exists because the canvas renderer now carries more logic than the
sim does (label placement, occlusion, zoom, marker scaling) and none of it is
reachable from Python. A 200 from the server proves nothing about the page, so it
checks the two things that actually break it: `node --check` on the extracted
script, and a `getElementById` cross-check against the markup. It also pins the
renderer invariants as static assertions — labels go through the single placement
pass, the halo uses the theme background rather than ink, the zoom rate carries no
level-snapping, markers are not `√zoom`-sized, and `MAX_ZOOM` still frames the
deepest moon system.

## Design

`gdd/gdd.md` is the design reference. The core principle is that movement, market information, and time are the scarce resources: every trade is a decision about `mass × delta-v × time × risk` against delivered value, scarcity, and urgency.
