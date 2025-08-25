import json, hashlib, random, sys, os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from datetime import datetime

STATE = {
    "round_id": 1,
    "status": "collecting",
    "seed": None,
    "commit": None,
    "players": {},
    "rolls": {},
    "winner": None,
    "pot": 0.0,
    "log": []
}

STATE_FILE = os.path.join(os.path.dirname(__file__), "game_state.json")

def sha256(s: str) -> str:
    import hashlib as _h
    return _h.sha256(s.encode()).hexdigest()

def pick_dice(stake: float) -> str:
    if stake >= 200: return "D20"
    if stake >= 50:  return "D12"
    if stake >= 10:  return "D8"
    if stake >= 1:   return "D6"
    return "D6"

def roll_value(seed: str, round_id: int, user_id: int, dice: str, phase: int = 1) -> int:
    sides = int(dice[1:])
    d = hashlib.sha256(f"{seed}|{round_id}|{user_id}|{phase}".encode()).digest()
    return 1 + (int.from_bytes(d, "big") % sides)

def ts():
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"

def save_state():
    data = {
        "players": STATE["players"],
        "rolls": STATE["rolls"],
        "winner": STATE["winner"],
        "log": STATE["log"],
    }
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

class Handler(SimpleHTTPRequestHandler):
    def do_OPTIONS(self):
        self._cors(); self.send_response(204); self.end_headers()

    def do_GET(self):
        if self.path.startswith("/api/state"):
            return self._json(200, self._public_state())
        if self.path in ("/", "/index.html"):
            ua = self.headers.get("User-Agent", "")
            if "Mobi" in ua:
                self.path = "/mini_app.html"
            else:
                self.path = "/desktop_app.html"
        return super().do_GET()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            data = {}
        p = urlparse(self.path).path

        if p == "/api/join":
            uid = int(data.get("user_id", 0))
            uname = str(data.get("username") or f"user_{uid}")
            stake = float(data.get("stake", 1.0))

            if uid <= 0:
                return self._json(400, {"error": "user_id required"})
            if stake <= 0:
                return self._json(400, {"error": "stake must be positive"})

            if STATE["status"] != "collecting":
                return self._json(400, {"error": "round is not collecting"})

            if uid not in STATE["players"]:
                dice = pick_dice(stake)
                STATE["players"][uid] = {"id": uid, "username": uname, "stake": stake, "dice": dice}
                STATE["pot"] += stake
                STATE["log"].append(f"{ts()} JOIN {uname} ({uid}) stake={stake} dice={dice}")
            save_state()
            return self._json(200, self._public_state())

        if p == "/api/lock":
            if STATE["status"] != "collecting":
                return self._json(400, {"error": "already locked"})
            if len(STATE["players"]) < 2:
                return self._json(400, {"error": "need at least 2 players"})
            STATE["status"] = "locking"
            STATE["seed"] = str(random.randint(1, 10**12))
            STATE["commit"] = sha256(STATE["seed"])
            STATE["log"].append(f"{ts()} LOCK commit={STATE['commit'][:12]}…")
            save_state()
            return self._json(200, self._public_state())

        if p == "/api/roll":
            if STATE["status"] not in ("locking", "rolling"):
                return self._json(400, {"error": "not ready"})
            STATE["status"] = "rolling"
            STATE["rolls"].clear()
            maxv = -1
            winners = []
            for uid, pinfo in STATE["players"].items():
                v = roll_value(STATE["seed"], STATE["round_id"], int(uid), pinfo["dice"], 1)
                STATE["rolls"][str(uid)] = v
                if v > maxv:
                    maxv = v; winners = [uid]
                elif v == maxv:
                    winners.append(uid)
            if len(winners) == 1:
                STATE["status"] = "finished"
                STATE["winner"] = int(winners[0])
                STATE["log"].append(f"{ts()} REVEAL seed={STATE['seed']} winner={STATE['winner']} val={maxv} pot={STATE['pot']}")
                STATE["pot"] = 0.0
            else:
                STATE["log"].append(f"{ts()} TIE on {maxv} among {winners}")
            save_state()
            return self._json(200, self._public_state())

        if p == "/api/reset":
            self._reset_state()
            save_state()
            return self._json(200, self._public_state())

        return self._json(404, {"error": "not found"})

    def _public_state(self):
        return {
            "round_id": STATE["round_id"],
            "status": STATE["status"],
            "commit": STATE["commit"],
            "reveal": STATE["seed"] if STATE["status"] in ("rolling", "finished") else None,
            "players": list(STATE["players"].values()),
            "rolls": STATE["rolls"],
            "winner": STATE["winner"],
            "pot": STATE["pot"],
            "log": STATE["log"][-20:]
        }

    def _reset_state(self):
        STATE["round_id"] += 1
        STATE["status"] = "collecting"
        STATE["seed"] = None
        STATE["commit"] = None
        STATE["players"].clear()
        STATE["rolls"].clear()
        STATE["winner"] = None
        STATE["pot"] = 0.0
        STATE["log"].append(f"{ts()} RESET to round {STATE['round_id']}")

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code); self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")

def main():
    save_state()
    port = 8081
    if len(sys.argv) >= 2:
        try: port = int(sys.argv[1])
        except: pass
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Serving miniapp + API on http://127.0.0.1:{port}")
    httpd.serve_forever()

if __name__ == "__main__":
    main()
