# -*- coding: utf-8 -*-
"""
MASTER OFFICIAL - Dashboard Server (IND Region)
Full version with pause, bulk add, mode switch, match counters
"""

import asyncio
import json
import os
import time
from typing import Dict, List, Any, Optional
from aiohttp import web


# ==================== BOT STATE ====================
class BotState:
    def __init__(self):
        self.accounts: Dict[str, Dict[str, Any]] = {}
        self.logs: List[Dict[str, Any]] = []
        self.max_logs = 200
        self.total_matches = 0
        self.total_gained_exp = 0
        self.start_time = time.time()
        self.account_workers: Dict[str, asyncio.Task] = {}
        self.refresh_callbacks: Dict[str, Any] = {}
        self.account_credentials: Dict[str, Dict[str, Any]] = {}

    def log(self, message: str, level: str = "info", uid: Optional[str] = None):
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "level": level,
            "message": message,
            "uid": uid
        }
        self.logs.append(entry)
        if len(self.logs) > self.max_logs:
            self.logs.pop(0)

    def register_account(self, uid: str, nickname: str, region: str, level: int, exp: int, likes: int = 0):
        uid_str = str(uid)
        lvl_val = max(1, int(level or 1))
        if uid_str not in self.accounts:
            self.accounts[uid_str] = {
                "uid": uid_str,
                "nickname": nickname or f"Player_{uid_str[:6]}",
                "region": region or "IND",
                "level": lvl_val,
                "initial_exp": exp,
                "current_exp": exp,
                "gained_exp": 0,
                "likes": likes or 0,
                "mode": "BR",
                "mode_manual": False,
                "status": "ONLINE",
                "is_paused": False,
                "matches_played": 0,
                "matches_completed": 0,
                "active_matches": 0,
                "uptime_seconds": 0,
                "last_match_time": None,
                "last_match_failed": None,
                "last_updated": time.strftime("%H:%M:%S")
            }
        else:
            acc = self.accounts[uid_str]
            if nickname:
                acc["nickname"] = nickname
            if region:
                acc["region"] = "IND"
            if level:
                acc["level"] = lvl_val
            acc["current_exp"] = exp
            acc["gained_exp"] = max(0, exp - acc["initial_exp"])
            acc["likes"] = likes
            if not acc.get("mode_manual", False):
                acc["mode"] = "BR"
            acc["status"] = "ONLINE"
            acc["last_updated"] = time.strftime("%H:%M:%S")
        self.recalc_totals()

    def update_exp(self, uid: str, current_exp: int, level: Optional[int] = None):
        uid_str = str(uid)
        if uid_str in self.accounts:
            acc = self.accounts[uid_str]
            old_exp = acc["current_exp"]
            acc["current_exp"] = current_exp
            if level is not None and level > 0:
                acc["level"] = int(level)
            if not acc.get("mode_manual", False):
                acc["mode"] = "BR"
            acc["gained_exp"] = max(0, current_exp - acc["initial_exp"])
            acc["last_updated"] = time.strftime("%H:%M:%S")
            diff = current_exp - old_exp
            if diff > 0:
                self.log(
                    f"{acc['nickname']} ({uid_str}) +{diff} EXP! Total: +{acc['gained_exp']}",
                    "success", uid_str
                )
            self.recalc_totals()

    def get_account_level(self, uid: str) -> int:
        acc = self.accounts.get(str(uid))
        return int(acc.get("level", 1) or 1) if acc else 1

    def get_account_mode(self, uid: str) -> str:
        acc = self.accounts.get(str(uid))
        if not acc:
            return "BR"
        mode = str(acc.get("mode", "BR") or "BR").upper()
        return "LONE_WOLF" if mode == "LONE_WOLF" and acc.get("mode_manual", False) else "BR"

    def set_account_mode(self, uid: str, mode: str):
        uid_str = str(uid)
        mode = str(mode or "").upper().replace("-", "_").replace(" ", "_")
        if mode in ("LW", "LONEWOLF", "LONE_WOLF"):
            mode = "LONE_WOLF"
        elif mode == "BR":
            mode = "BR"
        else:
            return False, "Invalid mode"

        acc = self.accounts.get(uid_str)
        if not acc:
            return False, "Account not found"

        level = int(acc.get("level", 1) or 1)
        if level < 5 and mode != "BR":
            return False, "Lone Wolf is locked until Level 5"

        acc["mode"] = mode
        acc["mode_manual"] = True
        acc["last_updated"] = time.strftime("%H:%M:%S")
        self.log(f"{acc.get('nickname','Unknown')} ({uid_str}) switched to {mode}", "success", uid_str)
        return True, mode

    def update_status(self, uid: str, status: str, active_matches: Optional[int] = None):
        uid_str = str(uid)
        if uid_str in self.accounts:
            self.accounts[uid_str]["status"] = status
            if active_matches is not None:
                self.accounts[uid_str]["active_matches"] = active_matches
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")

    # ==================== PAUSE METHODS ====================
    def is_paused(self, uid: str) -> bool:
        uid_str = str(uid)
        acc = self.accounts.get(uid_str)
        if not acc:
            return False
        return bool(acc.get("is_paused", False) or acc.get("status") == "PAUSED")

    def set_paused(self, uid: str, paused: bool):
        uid_str = str(uid)
        if uid_str in self.accounts:
            self.accounts[uid_str]["is_paused"] = bool(paused)
            if paused:
                self.accounts[uid_str]["status"] = "PAUSED"
            else:
                self.accounts[uid_str]["status"] = "ONLINE"
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")
            return True
        return False

    # ==================== MATCH COUNTERS ====================
    def increment_match_started(self, uid: str):
        uid_str = str(uid)
        if uid_str in self.accounts:
            self.accounts[uid_str]["matches_played"] = self.accounts[uid_str].get("matches_played", 0) + 1
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")

    def increment_match(self, uid: str):
        uid_str = str(uid)
        self.total_matches += 1
        if uid_str in self.accounts:
            self.accounts[uid_str]["matches_completed"] = self.accounts[uid_str].get("matches_completed", 0) + 1
            self.accounts[uid_str]["last_match_time"] = time.strftime("%H:%M:%S")
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")

    def match_failed(self, uid: str):
        uid_str = str(uid)
        if uid_str in self.accounts:
            self.accounts[uid_str]["last_match_failed"] = time.strftime("%H:%M:%S")
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")

    def recalc_totals(self):
        self.total_gained_exp = sum(acc.get("gained_exp", 0) for acc in self.accounts.values())


bot_state = BotState()


# ==================== PATHS ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(BASE_DIR, "templates", "index.html")
ACCOUNTS_FILE = os.path.join(BASE_DIR, "accounts.json")


# ==================== HANDLERS ====================
async def handle_index(request: web.Request) -> web.Response:
    if os.path.exists(TEMPLATE_PATH):
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = "<h1>templates/index.html not found!</h1>"
    return web.Response(text=content, content_type="text/html", charset="utf-8")


async def handle_get_stats(request: web.Request) -> web.Response:
    accounts_data = list(bot_state.accounts.values())
    accounts_data.sort(key=lambda x: x.get("gained_exp", 0), reverse=True)
    return web.json_response({
        "total_accounts": len(bot_state.accounts),
        "total_matches": bot_state.total_matches,
        "total_gained_exp": bot_state.total_gained_exp,
        "accounts": accounts_data,
        "logs": bot_state.logs[-60:],
        "uptime": int(time.time() - bot_state.start_time)
    })


async def handle_add_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        existing = _load_accounts_file()

        if "uid" in data and "password" in data:
            uid = str(data["uid"]).strip()
            pwd = str(data["password"]).strip()
            if not uid or not pwd:
                return web.json_response({"status": "error", "error": "UID and Password required"})
            existing = [acc for acc in existing if str(acc.get("uid")) != uid]
            existing.append({"uid": uid, "password": pwd})
        elif "token" in data:
            token = str(data["token"]).strip()
            if not token:
                return web.json_response({"status": "error", "error": "Token required"})
            existing = [acc for acc in existing if acc.get("token") != token]
            existing.append({"token": token})
        else:
            return web.json_response({"status": "error", "error": "Invalid payload"})

        _save_accounts_file(existing)
        bot_state.log(f"New account added: {data.get('uid') or 'Token'}", "success")

        if "on_account_added" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_account_added"](data))

        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_bulk_add(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        new_accounts = data.get("accounts", [])

        if not isinstance(new_accounts, list):
            return web.json_response({"status": "error", "error": "Invalid accounts list"})

        existing = _load_accounts_file()

        existing_keys = set()
        for acc in existing:
            if "uid" in acc and acc.get("uid"):
                existing_keys.add(f"uid:{acc['uid']}")
            elif "token" in acc and acc.get("token"):
                existing_keys.add(f"tok:{str(acc['token'])[:20]}")

        added = 0
        skipped = 0
        invalid = 0
        added_entries = []

        for acc in new_accounts:
            if not isinstance(acc, dict):
                invalid += 1
                continue

            if "uid" in acc and "password" in acc:
                uid = str(acc["uid"]).strip()
                pwd = str(acc["password"]).strip()
                if not uid or not pwd:
                    invalid += 1
                    continue
                key = f"uid:{uid}"
                if key in existing_keys:
                    skipped += 1
                    continue
                existing_keys.add(key)
                entry = {"uid": uid, "password": pwd}
                existing.append(entry)
                added_entries.append(entry)
                added += 1

            elif "token" in acc:
                token = str(acc["token"]).strip()
                if not token:
                    invalid += 1
                    continue
                key = f"tok:{token[:20]}"
                if key in existing_keys:
                    skipped += 1
                    continue
                existing_keys.add(key)
                entry = {"token": token}
                existing.append(entry)
                added_entries.append(entry)
                added += 1

            else:
                invalid += 1

        _save_accounts_file(existing)

        if added > 0:
            bot_state.log(f"Bulk add: +{added} accounts, {skipped} skipped, {invalid} invalid", "success")
            if "on_account_added" in bot_state.refresh_callbacks:
                for entry in added_entries:
                    try:
                        asyncio.create_task(bot_state.refresh_callbacks["on_account_added"](entry))
                    except Exception:
                        pass

        return web.json_response({
            "status": "ok",
            "added": added,
            "skipped": skipped,
            "invalid": invalid
        })
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_delete_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid", "")).strip()
        token = str(data.get("token", "")).strip()
        existing = _load_accounts_file()

        if token:
            existing = [acc for acc in existing if str(acc.get("token", "")).strip() != token]
        elif uid:
            existing = [acc for acc in existing if str(acc.get("uid", "")).strip() != uid]

        _save_accounts_file(existing)

        worker_keys = []
        if uid:
            worker_keys.append(uid)
        if token:
            worker_keys.append(token[:10])
        for key in worker_keys:
            worker = bot_state.account_workers.get(key)
            if worker:
                if not worker.done():
                    worker.cancel()
                bot_state.account_workers.pop(key, None)

        if uid and uid in bot_state.accounts:
            del bot_state.accounts[uid]
        bot_state.log(f"Account {uid or token[:10] or 'unknown'} removed", "warning", uid or None)
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_refresh_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid", "")).strip()
        if "on_refresh_account" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_refresh_account"](uid))
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_mode_switch(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid", "")).strip()
        mode = str(data.get("mode", "")).strip()
        ok, result = bot_state.set_account_mode(uid, mode)
        if not ok:
            return web.json_response({"status": "error", "error": result}, status=400)
        return web.json_response({
            "status": "ok",
            "uid": uid,
            "mode": result,
            "level": bot_state.get_account_level(uid)
        })
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)}, status=400)


async def handle_pause_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid", "")).strip()
        if not uid:
            return web.json_response({"status": "error", "error": "UID required"}, status=400)

        acc = bot_state.accounts.get(uid)
        if not acc:
            return web.json_response({"status": "error", "error": "Account not found"}, status=404)

        currently_paused = bot_state.is_paused(uid)
        new_state = not currently_paused
        bot_state.set_paused(uid, new_state)

        bot_state.log(
            f"{acc.get('nickname','Unknown')} ({uid}) {'paused' if new_state else 'resumed'}",
            "warning" if new_state else "success",
            uid
        )

        return web.json_response({
            "status": "ok",
            "uid": uid,
            "is_paused": new_state
        })
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)}, status=400)


async def handle_pause_all(request: web.Request) -> web.Response:
    try:
        if not bot_state.accounts:
            return web.json_response({"status": "error", "error": "No accounts"}, status=400)

        all_paused = all(bot_state.is_paused(uid) for uid in bot_state.accounts.keys())
        new_state = not all_paused

        for uid in bot_state.accounts.keys():
            bot_state.set_paused(uid, new_state)

        bot_state.log(
            f"All accounts {'paused' if new_state else 'resumed'}",
            "warning" if new_state else "success"
        )

        return web.json_response({
            "status": "ok",
            "all_paused": new_state
        })
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)}, status=400)


async def handle_clear_logs(request: web.Request) -> web.Response:
    bot_state.logs.clear()
    return web.json_response({"status": "ok"})


# ==================== HELPERS ====================
def _load_accounts_file() -> list:
    if not os.path.exists(ACCOUNTS_FILE):
        return []
    try:
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_accounts_file(accounts: list):
    try:
        tmp = ACCOUNTS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(accounts, f, indent=2)
        os.replace(tmp, ACCOUNTS_FILE)
    except Exception as e:
        print(f"Save accounts failed: {e}")


# ==================== START SERVER ====================
async def start_web_dashboard(host: str = "0.0.0.0", port: int = 5000):
    app = web.Application()

    # Routes
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/stats", handle_get_stats)
    app.router.add_post("/api/account/add", handle_add_account)
    app.router.add_post("/api/account/bulk_add", handle_bulk_add)
    app.router.add_post("/api/account/delete", handle_delete_account)
    app.router.add_post("/api/account/refresh", handle_refresh_account)
    app.router.add_post("/api/account/mode", handle_mode_switch)
    app.router.add_post("/api/account/pause", handle_pause_account)
    app.router.add_post("/api/account/pause_all", handle_pause_all)
    app.router.add_post("/api/logs/clear", handle_clear_logs)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"\033[92m[+] Web Dashboard running on http://localhost:{port}\033[0m")