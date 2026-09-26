"""M7 live-server tests: real HTTP over localhost. Run: python3 tests/test_server.py"""
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "web"))

import server as live

PASS = []
BASE = ""


def check(name, fn):
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        print(f"FAIL {name}: {type(e).__name__}: {e}")
        return False
    print(f"ok   {name}")
    PASS.append(name)
    return True


def call(method, path, payload=None):
    data = json.dumps(payload or {}).encode() if method == "POST" else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_snapshot_shape():
    code, body = call("GET", "/api/snapshot")
    assert code == 200
    assert body["v"] == 3 and len(body["bodies"]) == 12 and len(body["locations"]) == 18
    assert body["campaign"]["captain"] == "Commander"
    assert len(body["contacts"]) == 14


def test_advance():
    _, before = call("GET", "/api/snapshot")
    code, body = call("POST", "/api/advance", {"days": 7})
    assert code == 200 and body["ok"]
    assert abs(body["snapshot"]["t"] - (before["t"] + 7)) < 1e-9


def test_buy_and_hold():
    code, body = call("POST", "/api/buy", {"ship": "pc1", "comm": "water", "qty": 5})
    assert code == 200 and body["ok"]
    assert body["snapshot"]["ships"][0]["cargo"] == {"water": 5}


def test_plot_then_commit_then_arrive():
    code, body = call("POST", "/api/plot", {"ship": "pc1", "dest": "arax"})
    assert code == 200 and "wait" in body["result"]["summary"]
    code, body = call("POST", "/api/commit", {"ship": "pc1", "dest": "arax"})
    assert code == 200 and body["result"]["leg"]["kind"] == "hohmann"
    arrive = body["result"]["leg"]["arrive"]
    t = body["snapshot"]["t"]
    code, body = call("POST", "/api/advance", {"days": arrive - t})
    assert code == 200
    ship = body["snapshot"]["ships"][0]
    assert ship["at"] == "arax" and ship["loc"] == "arax-station"


def test_bad_action():
    code, body = call("POST", "/api/buy", {"ship": "pc1", "comm": "moon-rock", "qty": 1})
    assert code == 400 and not body["ok"]
    code, body = call("POST", "/api/nope", {})
    assert code == 400 and not body["ok"]


def test_contract_lapse_over_wire():
    code, body = call("POST", "/api/board", {"port": "arax"})
    assert code == 200 and len(body["result"]) == 3
    cid = body["result"][0]["id"]
    deadline = body["result"][0]["deadline"]
    code, body = call("POST", "/api/accept", {"cid": cid})
    assert code == 200
    t = body["snapshot"]["t"]
    code, body = call("POST", "/api/advance", {"days": deadline - t + 1})
    assert code == 200
    assert body["snapshot"]["contracts"] and \
        [c for c in body["snapshot"]["contracts"] if c["id"] == cid][0]["status"] == "lapsed"


def test_reset():
    code, body = call("POST", "/api/reset", {})
    assert code == 200
    assert body["snapshot"]["t"] == 0 and body["snapshot"]["credits"] == 10000


def test_auto_toggle():
    code, body = call("POST", "/api/auto", {"enabled": True})
    assert code == 200 and body["result"]["enabled"] is True
    code, body = call("GET", "/api/auto")
    assert code == 200 and body["enabled"] is True
    code, body = call("POST", "/api/auto", {"enabled": False})
    assert code == 200 and body["result"]["enabled"] is False


def test_save_slots_and_new_game():
    code, body = call("GET", "/api/saves")
    assert code == 200 and any(s["slot"] == "autosave" for s in body["saves"])
    code, body = call("POST", "/api/save", {"slot": "test_slot", "label": "Test Slot"})
    assert code == 200 and body["result"]["slot"] == "test_slot"
    code, body = call("GET", "/api/saves")
    assert any(s["slot"] == "test_slot" and s["label"] == "Test Slot" for s in body["saves"])
    code, body = call("POST", "/api/new", {"captain": "Test Captain", "difficulty": "hard"})
    assert code == 200 and body["result"]["captain"] == "Test Captain"
    assert body["snapshot"]["credits"] == 8000 and body["snapshot"]["ships"][0]["dv"] == 0.22
    code, body = call("POST", "/api/save", {"slot": "captain_slot"})
    assert code == 200
    code, body = call("GET", "/api/saves")
    assert any(s["slot"] == "captain_slot" and s["captain"] == "Test Captain" for s in body["saves"])
    code, body = call("POST", "/api/load", {"slot": "test_slot"})
    assert code == 200 and body["ok"]
    code, body = call("POST", "/api/delete-save", {"slot": "captain_slot"})
    assert code == 200 and body["result"]["deleted"] == "captain_slot"
    code, body = call("POST", "/api/delete-save", {"slot": "autosave"})
    assert code == 400


def test_new_game_company_and_ship_name():
    code, body = call("POST", "/api/new", {"captain": "Ilsa Marr",
                                           "company": "Marr & Vance",
                                           "ship_name": "Kestrel",
                                           "difficulty": "balanced"})
    assert code == 200 and body["ok"]
    result = body["result"]
    assert result["company"] == "Marr & Vance", result
    assert result["ship"] == "Kestrel", result
    campaign = body["snapshot"]["campaign"]
    assert campaign["company"] == "Marr & Vance" and campaign["captain"] == "Ilsa Marr"
    assert body["snapshot"]["ships"][0]["name"] == "Kestrel"


def test_new_game_defaults_company_and_ship():
    code, body = call("POST", "/api/new", {"captain": "Rell"})
    assert code == 200
    # Blank fields must still produce a usable identity, not empty strings.
    assert body["result"]["company"] == "Rell's Company"
    assert body["result"]["ship"], "starting ship needs a default name"


def test_company_and_ship_survive_save_load():
    call("POST", "/api/new", {"captain": "Ossian", "company": "Ossian Freight",
                              "ship_name": "Marginalia"})
    call("POST", "/api/save", {"slot": "identity_slot"})
    code, body = call("GET", "/api/saves")
    slot = next(s for s in body["saves"] if s["slot"] == "identity_slot")
    assert slot["company"] == "Ossian Freight" and slot["ship"] == "Marginalia"
    call("POST", "/api/reset", {})
    code, body = call("POST", "/api/load", {"slot": "identity_slot"})
    assert code == 200 and body["ok"]
    assert body["snapshot"]["campaign"]["company"] == "Ossian Freight"
    assert body["snapshot"]["ships"][0]["name"] == "Marginalia"
    call("POST", "/api/delete-save", {"slot": "identity_slot"})


def test_gate_is_charted_beyond_fulmaior():
    code, body = call("GET", "/api/snapshot")
    assert code == 200
    bodies = {b["id"]: b for b in body["bodies"]}
    assert "gate" in bodies, "the gate must exist on the chart"
    assert bodies["gate"]["a"] > bodies["fulmaior"]["a"], "gate must lie beyond Fulmaior"
    assert bodies["gate"]["kind"] == "wormhole"
    gates = body["gates"]
    assert len(gates) == 1 and gates[0]["dest_system"]
    assert gates[0]["transit"] is False, "inter-system transit is not wired up yet"


def test_gate_refuses_flight_planning():
    code, body = call("POST", "/api/plot", {"ship": "pc1", "dest": "gate"})
    assert code == 400, "planning to the gate must be refused cleanly"
    assert "gate" in body["error"].lower()
    code, body = call("POST", "/api/commit", {"ship": "pc1", "dest": "gate"})
    assert code == 400


def test_gate_opens_over_time():
    call("POST", "/api/reset", {})
    code, body = call("GET", "/api/snapshot")
    assert body["gates"][0]["status"] == "sealed"
    call("POST", "/api/advance", {"days": 300})
    code, body = call("GET", "/api/snapshot")
    gate = body["gates"][0]
    assert gate["status"] == "stabilising" and gate["eta_d"] < 120
    call("POST", "/api/advance", {"days": 150})
    code, body = call("GET", "/api/snapshot")
    gate = body["gates"][0]
    assert gate["status"] == "open" and gate["eta_d"] == 0
    assert gate["transit"] is False, "an open gate still has no commissioned transit"


if __name__ == "__main__":
    tmp = tempfile.mkdtemp(prefix="spacegame-live-")
    srv = live.make_server(0, os.path.join(tmp, "live.json"))
    BASE = f"http://127.0.0.1:{srv.server_address[1]}"
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    tests = [
        ("snapshot_shape", test_snapshot_shape),
        ("advance", test_advance),
        ("buy_and_hold", test_buy_and_hold),
        ("plot_commit_arrive", test_plot_then_commit_then_arrive),
        ("bad_action", test_bad_action),
        ("contract_lapse", test_contract_lapse_over_wire),
        ("reset", test_reset),
        ("auto_toggle", test_auto_toggle),
        ("save_slots_new_game", test_save_slots_and_new_game),
        ("new_game_company_ship", test_new_game_company_and_ship_name),
        ("new_game_identity_defaults", test_new_game_defaults_company_and_ship),
        ("identity_save_roundtrip", test_company_and_ship_survive_save_load),
        ("gate_charted", test_gate_is_charted_beyond_fulmaior),
        ("gate_refuses_flight", test_gate_refuses_flight_planning),
        ("gate_opens_over_time", test_gate_opens_over_time),
    ]
    ok = all(check(n, f) for n, f in tests)
    print(f"\n{len(PASS)}/{len(tests)} passed")
    srv.shutdown()
    sys.exit(0 if ok else 1)
