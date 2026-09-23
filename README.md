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
