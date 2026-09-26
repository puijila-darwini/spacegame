"""Live backend: stdlib HTTP serving web/ + a JSON API over the sim.

Run:  python3 web/server.py [port]      (default 8765, from the spacegame dir)
Play: open http://localhost:8765 — ships move, markets tick, every action
      saves to ~/ai/tmp/spacegame/live.json (override with SPACEGAME_SAVE).
      Set SPACEGAME_AUTO=1 to also advance 1 day per real minute (the daemon).

No third-party anything; the whole dynamic game is stdlib + sim/.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
WEB = os.path.join(ROOT, "web")
HOST = os.environ.get("SPACEGAME_HOST", "0.0.0.0")

from sim import api, contacts, contracts, infra, markets, persist, ships  # noqa: E402
from sim import time as simtime  # noqa: E402
from sim.state import build_sol  # noqa: E402

SAVE = os.environ.get("SPACEGAME_SAVE", "/home/pthag/ai/tmp/spacegame/live.json")
DIFFICULTY = {
    "story": {"credits": 12000.0, "dv": 0.30, "label": "Story"},
    "balanced": {"credits": 10000.0, "dv": 0.25, "label": "Balanced"},
    "hard": {"credits": 8000.0, "dv": 0.22, "label": "Hard"},
}


def fresh_game(captain: str = "Commander", difficulty: str = "balanced",
               campaign: str = "Sol Merchant"):
    g = build_sol()
    markets.seed(g)
    contacts.seed(g)
    infra.seed(g)
    settings = DIFFICULTY.get(difficulty, DIFFICULTY["balanced"])
    g.credits = settings["credits"]
    g.difficulty = difficulty if difficulty in DIFFICULTY else "balanced"
    for ship in g.ships.values():
        ship.dv_cap = settings["dv"]
        ship.dv = settings["dv"]
    g.captain = captain or "Commander"
    g.campaign = campaign or "Sol Merchant"
    return g


class Store:
    """The one live game. All mutations hold the lock and then save."""

    def __init__(self, path: str = SAVE, slots: str | None = None):
        self.path = path
        self.slot_dir = slots or os.path.join(os.path.dirname(path) or ".", "slots")
        self.lock = threading.Lock()
        self.auto_enabled = os.environ.get("SPACEGAME_AUTO") == "1"
        try:
            self.game = persist.load(path)
        except (FileNotFoundError, ValueError, KeyError):
            self.game = fresh_game()
            self._save()

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        persist.save(self.game, self.path)

    @staticmethod
    def _valid_slot(slot: str) -> str:
        slot = str(slot or "quicksave").strip().lower()
        if not re.fullmatch(r"[a-z0-9_-]{1,32}", slot):
            raise ValueError("slot must be 1-32 letters, numbers, _ or -")
        return slot

    def _slot_path(self, slot: str) -> str:
        return os.path.join(self.slot_dir, f"slot-{self._valid_slot(slot)}.json")

    @staticmethod
    def _save_meta(data: dict, slot: str, label: str) -> dict:
        meta = data.get("meta", {})
        ship = (data.get("ships") or [{}])[0]
        return {"slot": slot, "label": label, "t": data.get("t", 0),
                "credits": data.get("credits", 0), "captain": meta.get("captain", "Commander"),
                "difficulty": meta.get("difficulty", "balanced"),
                "campaign": meta.get("campaign", "Sol Merchant"),
                "ship": ship.get("name", "PC-1")}

    def list_saves(self) -> list:
        saves = [self._save_meta(persist.to_dict(self.game), "autosave", "Current campaign")]
        try:
            names = sorted(os.listdir(self.slot_dir))
        except FileNotFoundError:
            names = []
        for name in names:
            if not (name.startswith("slot-") and name.endswith(".json")):
                continue
            try:
                with open(os.path.join(self.slot_dir, name)) as f:
                    data = json.load(f)
                slot = name[5:-5]
                saves.append(self._save_meta(data, slot, slot.replace("_", " ").title()))
            except (OSError, ValueError, KeyError):
                continue
        return saves

    def save_slot(self, slot: str, label: str = "") -> dict:
        path = self._slot_path(slot)
        os.makedirs(self.slot_dir, exist_ok=True)
        persist.save(self.game, path)
        return self._save_meta(persist.to_dict(self.game), self._valid_slot(slot),
                               label or self._valid_slot(slot).replace("_", " ").title())

    def delete_slot(self, slot: str) -> dict:
        if self._valid_slot(slot) == "autosave":
            raise ValueError("cannot delete autosave")
        path = self._slot_path(slot)
        if not os.path.exists(path):
            raise ValueError("save slot not found")
        os.remove(path)
        return {"deleted": self._valid_slot(slot)}

    def load_slot(self, slot: str) -> dict:
        path = self._slot_path(slot)
        self.game = persist.load(path)
        self._save()
        return {"slot": self._valid_slot(slot), "snapshot_t": self.game.t}

    def snapshot(self) -> dict:
        with self.lock:
            return api.snapshot(self.game)

    def act(self, name: str, p: dict):
        with self.lock:
            g = self.game
            if name == "saves":
                return {"saves": self.list_saves()}
            if name == "save":
                return self.save_slot(p.get("slot", "quicksave"), p.get("label", ""))
            if name == "load":
                return self.load_slot(p.get("slot", ""))
            if name == "delete-save":
                return self.delete_slot(p.get("slot", ""))
            if name == "new":
                self.game = fresh_game(p.get("captain", "Commander"),
                                       p.get("difficulty", "balanced"),
                                       p.get("campaign", "Sol Merchant"))
                self._save()
                return {"new": True, "captain": self.game.captain,
                        "difficulty": self.game.difficulty, "campaign": self.game.campaign}
            if name == "advance":
                days = float(p.get("days", 1))
                if days <= 0 or days > 3650:
                    raise ValueError("days must be 1..3650")
                reports = simtime.advance(g, days)
                self._save()
                return {"reports": reports}
            if name == "plot":
                return ships.plot(g, p["ship"], p["dest"], p.get("dest_loc"),
                                  None, p.get("arrive_by"))
            if name == "commit":
                leg = ships.commit(g, p["ship"], p["dest"], p.get("dest_loc"),
                                   None, p.get("arrive_by"))
                self._save()
                return {"leg": {"from": leg.origin, "to": leg.dest,
                                "depart": leg.t_depart, "arrive": leg.t_arrive,
                                "kind": leg.kind}}
            if name == "buy":
                res = markets.buy(g, p["ship"], p["comm"], float(p.get("qty", 1)))
                self._save()
                return res
            if name == "sell":
                res = markets.sell(g, p["ship"], p["comm"], float(p.get("qty", 1)))
                self._save()
                return res
            if name == "transfer":
                res = infra.transfer_local(g, p["ship"], p["loc"])
                self._save()
                return res
            if name == "refuel":
                res = infra.refuel(g, p["ship"])
                self._save()
                return res
            if name == "board":
                return contracts.board(g, p["port"])
            if name == "accept":
                contracts.accept(g, p["cid"])
                self._save()
                return {"accepted": p["cid"]}
            if name == "fulfill":
                res = contracts.fulfill(g, p["ship"], p["cid"], p.get("qty"))
                self._save()
                return res
            if name == "refer":
                party = contacts.refer(g, p["npc"])
                self._save()
                return {"introduced": party}
            if name == "quote":
                return contacts.quote(g, p["npc"], p.get("comm"))
            if name == "auto":
                self.auto_enabled = bool(p.get("enabled", True))
                return {"enabled": self.auto_enabled, "interval_s": 60, "days": 1}
            if name == "reset":
                self.game = fresh_game()
                self._save()
                return {"reset": True}
            raise ValueError(f"unknown action {name!r}")


class Handler(BaseHTTPRequestHandler):
    store: Store | None = None

    def log_message(self, *args):  # quiet unless asked
        if os.environ.get("SPACEGAME_DEBUG"):
            super().log_message(*args)

    def _send(self, code: int, obj, ctype: str = "application/json") -> None:
        body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/api/snapshot", "/snapshot.json"):
            assert self.store is not None
            self._send(200, self.store.snapshot())
            return
        if path == "/api/auto":
            assert self.store is not None
            self._send(200, {"enabled": self.store.auto_enabled,
                             "interval_s": 60, "days": 1})
            return
        if path == "/api/saves":
            assert self.store is not None
            with self.store.lock:
                saves = self.store.list_saves()
            self._send(200, {"saves": saves})
            return
        if path == "/":
            path = "/index.html"
        target = os.path.normpath(os.path.join(WEB, path.lstrip("/")))
        if not target.startswith(WEB) or not os.path.isfile(target):
            self._send(404, {"ok": False, "error": "not found"})
            return
        ctype = "text/html" if target.endswith(".html") else "application/json"
        with open(target, "rb") as f:
            self._send(200, f.read(), ctype)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if not path.startswith("/api/"):
            self._send(404, {"ok": False, "error": "not found"})
            return
        assert self.store is not None
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, OSError) as e:
            self._send(400, {"ok": False, "error": f"bad request: {e}"})
            return
        try:
            result = self.store.act(path[len("/api/"):], payload)
        except (ValueError, KeyError) as e:
            self._send(400, {"ok": False, "error": f"{type(e).__name__}: {e}"})
            return
        self._send(200, {"ok": True, "result": result, "snapshot": self.store.snapshot()})


def make_server(port: int = 8765, save: str = SAVE,
                host: str | None = None) -> ThreadingHTTPServer:
    Handler.store = Store(save)
    return ThreadingHTTPServer((host or HOST, port), Handler)


def auto_loop(store: Store, interval: float = 60.0, days: float = 1.0) -> None:
    import time as wall

    while True:
        wall.sleep(interval)
        if not store.auto_enabled:
            continue
        try:
            store.act("advance", {"days": days})
        except Exception:  # never kill the daemon on a bad tick
            pass


def main(argv: list) -> None:
    port = int(argv[1]) if len(argv) > 1 else 8765
    server = make_server(port)
    threading.Thread(target=auto_loop, args=(server.RequestHandlerClass.store,),
                     daemon=True).start()
    if server.RequestHandlerClass.store.auto_enabled:
        print("daemon auto-advance on: 1 day / minute")
    print(f"Sol Merchant live on http://{HOST}:{port}  (save: {SAVE})")
    server.serve_forever()


if __name__ == "__main__":
    main(sys.argv)
