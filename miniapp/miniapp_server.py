import json, hashlib, random, sys
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
    "log": []
}

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

class Handler(SimpleHTTPRequestHandler):
    def do_OPTIONS(self):
        self._cors(); self.send_response(204); self.end_headers()

    def do_GET(self):
        if self.path.startswith("/api/state"):
            return self._json(200, self._public_state())
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
    dev = bool(data.get("dev", False))

    if uid <= 0:
        return self._json(400, {"error": "user_id required"})

    # Разрешаем только Telegram-пользователей, кроме явного dev-режима
    # (В реальном Telegram user_id может быть любым положительным int; тут просто отсечём "мусор".
    #  Гостям позволим заходить только если dev=True.)
    if not dev and uname.startswith("guest_"):
        return self._json(400, {"error": "Open via Telegram bot button"})

    if STATE["status"] != "collecting":
        return self._json(400, {"error": "round is not collecting"})

    if uid not in STATE["players"]:
        STATE["players"][uid] = {"id": uid, "username": uname, "stake": 1.0, "dice": pick_dice(1.0)}
        STATE["log"].append(f"{ts()} JOIN {uname} ({uid}) dice={STATE['players'][uid]['dice']}")
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
                STATE["log"].append(f"{ts()} REVEAL seed={STATE['seed']} winner={STATE['winner']} val={maxv}")
            else:
                STATE["log"].append(f"{ts()} TIE on {maxv} among {winners}")
            return self._json(200, self._public_state())

        if p == "/api/reset":
            self._reset_state()
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
    port = 8081
    if len(sys.argv) >= 2:
        try: port = int(sys.argv[1])
        except: pass
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Serving miniapp + API on http://127.0.0.1:{port}")
    httpd.serve_forever()

if __name__ == "__main__":
    main()

    httpd.serve_forever()

if __name__ == "__main__":
    main()
