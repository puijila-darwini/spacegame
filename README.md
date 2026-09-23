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

## Interface controls

The system view is a camera-based canvas:

- drag to pan;
- use the wheel or a pinch gesture to zoom around the pointer;
- click a world or ship to select it;
- double-click a world to enter its full local system view (`100×–160×` depending on the world);
- use **System view** or `F` to focus the selected world in its co-moving local frame;
- use the frame selector to switch between heliocentric inertial coordinates and following the selected world;
- press `0` to reset the view and `+`/`-` to zoom; `F` enters the selected world's local system frame;
- when the selected ship is parked, select another world and use **Plan selected orbit** or the destination selector to plot and commit a transfer;
- use `+30d` for a month jump, or **Auto 1d/min** to let the live server advance one day per real minute; the same button pauses it.

At higher zoom, elevator terminals and stations appear as distinct markers orbiting their world. Surface locations remain valid destinations in the ship planner, but are intentionally not rendered as orbital objects. Selecting a station or terminal focuses the camera and preselects the matching local-transfer location in the ship panel. The local marker radii are renderer geometry for inspection; they do not change the Hohmann or delta-v simulation.

The right-hand panels follow the current selection. The **Body / Frame** panel shows the selected body's orbital period, parent, moons, orbital sites, and active reference frame. A body selection can be used as the transfer destination without leaving the system view.

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
