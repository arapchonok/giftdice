import os, json, time, hashlib, urllib.request, urllib.parse, sys, random, argparse, unittest
from typing import Dict, Any, List, Optional

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
POLL_TIMEOUT = int(os.getenv("POLL_TIMEOUT", "25"))
DICE_TIERS = [(1,10,'D6'),(10,50,'D8'),(50,200,'D12'),(200,None,'D20')]

def pick_dice(stake: float) -> str:
    for mi, ma, dice in DICE_TIERS:
        if stake >= mi and (ma is None or stake < ma):
            return dice
    return 'D6'

def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()

def commit_reveal_roll(seed: str, round_id: int, user_id: int, dice_type: str, phase: int = 1) -> int:
    sides = int(dice_type[1:])
    d = hashlib.sha256(f"{seed}|{round_id}|{user_id}|{phase}".encode()).digest()
    return 1 + (int.from_bytes(d, 'big') % sides)

class TelegramAPI:
    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}"
        self.offset = None
    def _req(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        data = urllib.parse.urlencode(params).encode()
        with urllib.request.urlopen(self.base + '/' + method, data=data, timeout=POLL_TIMEOUT+10) as r:
            return json.loads(r.read().decode())
    def get_updates(self, timeout: int) -> List[Dict[str, Any]]:
        params = {"timeout": timeout}
        if self.offset is not None:
            params["offset"] = self.offset
        try:
            with urllib.request.urlopen(self.base + '/getUpdates?' + urllib.parse.urlencode(params), timeout=timeout+10) as r:
                data = json.loads(r.read().decode())
        except Exception:
            return []
        if not data.get('ok'):
            return []
        result = data.get('result', [])
        if result:
            self.offset = result[-1]['update_id'] + 1
        return result
    def send_message(self, chat_id: int, text: str, reply_markup: Optional[Dict[str, Any]] = None) -> None:
        params = {"chat_id": chat_id, "text": text}
        if reply_markup:
            params["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
        try:
            self._req('sendMessage', params)
        except Exception:
            pass

class Bot:
    def __init__(self, token: str, webapp_url: str, api: Optional[TelegramAPI] = None):
        self.api = api if api is not None else TelegramAPI(token)
        self.webapp_url = webapp_url
        self.round_id = 1
        self.seed = sha256(str(random.randint(1, 10**12)))
        self.commit_hash = sha256(self.seed)
        self.players: Dict[int, Dict[str, Any]] = {}
        self.state = 'collecting'

    def inline_markup(self) -> Dict[str, Any]:
        rows: List[List[Dict[str, Any]]] = [[]]
        if self.webapp_url:
            rows[0].append({"text": "Open Gift Dice", "web_app": {"url": self.webapp_url}})
        rows[0].append({"text": "Join Round", "callback_data": "join"})
        return {"inline_keyboard": rows}

    def reply_keyboard(self) -> Optional[Dict[str, Any]]:
        if not self.webapp_url:
            return None
        # Persistent reply keyboard with WebApp button
        kb = [[{"text": "Open Gift Dice", "web_app": {"url": self.webapp_url}},
               {"text": "Join /join"}]]
        return {"keyboard": kb, "resize_keyboard": True, "is_persistent": True}

    def send_menu(self, chat_id: int):
        # Send reply keyboard (persistent) + a message with inline keyboard as fallback
        rk = self.reply_keyboard()
        if rk:
            self.api.send_message(chat_id, "Menu:", rk)
        self.api.send_message(
            chat_id,
            f"Gift Dice\nRound: {self.round_id}\nStatus: {self.state}\nCommit: {self.commit_hash[:12]}…",
            self.inline_markup()
        )

    def handle_update(self, upd: Dict[str, Any]):
        msg = upd.get('message') or upd.get('edited_message')
        cbq = upd.get('callback_query')
        if msg:
            chat_id = msg['chat']['id']
            text = (msg.get('text') or '').strip()
            if text.startswith('/start') or text.startswith('/menu'):
                self.send_menu(chat_id)
            elif text.startswith('/status'):
                self.api.send_message(chat_id, f"Status: {self.state}\nPlayers: {len(self.players)}")
            elif text.startswith('/join') or text == 'Join /join':
                uid = msg['from']['id']
                self.players.setdefault(uid, {"user_id": uid, "stake": 1.0, "dice": pick_dice(1.0)})
                self.api.send_message(chat_id, f"Joined. Dice {self.players[uid]['dice']}. Players: {len(self.players)}")
            elif text.startswith('/lock'):
                if self.state != 'collecting':
                    self.api.send_message(chat_id, 'Already locked')
                elif len(self.players) < 2:
                    self.api.send_message(chat_id, 'Need at least 2 players')
                else:
                    self.state = 'locking'
                    self.api.send_message(chat_id, f"Locked. Commit {self.commit_hash[:12]}…")
            elif text.startswith('/roll'):
                if self.state not in ('locking','rolling'):
                    self.api.send_message(chat_id, 'Not ready for rolling')
                else:
                    self.state = 'rolling'
                    rolls = []
                    for uid, p in self.players.items():
                        val = commit_reveal_roll(self.seed, self.round_id, uid, p['dice'], phase=1)
                        rolls.append((uid, val))
                    maxv = max(v for _, v in rolls)
                    winners = [u for (u, v) in rolls if v == maxv]
                    if len(winners) == 1:
                        self.state = 'finished'
                        self.api.send_message(chat_id, f"Reveal: {self.seed}\nWinner: {winners[0]} with {maxv}")
                    else:
                        self.api.send_message(chat_id, f"Tie on {maxv}. Winners: {', '.join(map(str, winners))}")
            else:
                self.api.send_message(chat_id, "Commands: /menu, /start, /join, /status, /lock, /roll")
        elif cbq:
            data = cbq.get('data')
            chat_id = cbq['message']['chat']['id']
            if data == 'join':
                uid = cbq['from']['id']
                self.players.setdefault(uid, {"user_id": uid, "stake": 1.0, "dice": pick_dice(1.0)})
                self.api.send_message(chat_id, f"Joined. Dice {self.players[uid]['dice']}. Players: {len(self.players)}")

    def run_polling(self):
        while True:
            updates = self.api.get_updates(POLL_TIMEOUT)
            for upd in updates:
                self.handle_update(upd)

# ---------- Tests ----------
class BotTests(unittest.TestCase):
    def test_pick_dice_tiers(self):
        self.assertEqual(pick_dice(1), 'D6')
        self.assertEqual(pick_dice(9.99), 'D6')
        self.assertEqual(pick_dice(10), 'D8')
        self.assertEqual(pick_dice(49.99), 'D8')
        self.assertEqual(pick_dice(50), 'D12')
        self.assertEqual(pick_dice(199.99), 'D12')
        self.assertEqual(pick_dice(200), 'D20')
    def test_commit_reveal_deterministic(self):
        seed = 'abcd'
        r, u = 10, 20
        for dice in ('D6','D8','D12','D20'):
            v1 = commit_reveal_roll(seed, r, u, dice, 1)
            v2 = commit_reveal_roll(seed, r, u, dice, 1)
            self.assertEqual(v1, v2)
            self.assertTrue(1 <= v1 <= int(dice[1:]))

class MockTelegramAPI:
    def __init__(self):
        self.messages: List[Dict[str, Any]] = []
        self.offset = None
    def get_updates(self, timeout: int) -> List[Dict[str, Any]]:
        return []
    def send_message(self, chat_id: int, text: str, reply_markup: Optional[Dict[str, Any]] = None) -> None:
        self.messages.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})

class BotFlowTests(unittest.TestCase):
    def setUp(self):
        self.api = MockTelegramAPI()
        self.bot = Bot("dummy", webapp_url="https://example.com/app", api=self.api)
        self.chat = 1
        self.u1 = 101
        self.u2 = 202
    def _msg(self, uid: int, text: str) -> Dict[str, Any]:
        return {"update_id": 1, "message": {"message_id": 1, "chat": {"id": self.chat}, "from": {"id": uid}, "text": text}}
    def test_menu_shows_reply_keyboard(self):
        self.bot.handle_update(self._msg(self.u1, "/start"))
        has_reply_kb = any(m["reply_markup"] and m["reply_markup"].get("keyboard") for m in self.api.messages)
        self.assertTrue(has_reply_kb)
    def test_join_lock_roll_flow(self):
        self.bot.handle_update(self._msg(self.u1, "/join"))
        self.assertEqual(len(self.bot.players), 1)
        self.bot.handle_update(self._msg(self.u2, "/join"))
        self.assertEqual(len(self.bot.players), 2)
        self.bot.handle_update(self._msg(self.u1, "/lock"))
        self.bot.handle_update(self._msg(self.u1, "/roll"))
        self.assertIn(self.bot.state, ("rolling","finished"))

# ---------- Entrypoint ----------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-tests', action='store_true')
    args = parser.parse_args()

    if args.run_tests:
        unittest.main(argv=['ignored'], exit=False)
        return

    if not BOT_TOKEN:
        print('BOT_TOKEN is not set. Running offline self-tests instead of exiting.')
        unittest.main(argv=['ignored'], exit=False)
        return

    print('Bot starting…')
    print('WEBAPP_URL =', WEBAPP_URL or '(not set)')
    Bot(BOT_TOKEN, WEBAPP_URL).run_polling()

if __name__ == '__main__':
    main()
