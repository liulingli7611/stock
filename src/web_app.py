"""Local web app: public screener + admin (login, refresh, catalog)."""

from __future__ import annotations

import hmac
import json
import os
import secrets
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.build_screener_app import build_screener_app_html
from src.catalog import (
    add_category,
    add_stock,
    clear_exclusion,
    delete_category,
    delete_stock,
    exclude_stock,
    load_catalog,
    normalize_ticker,
    update_category,
    update_stock,
)
from src.fetch_holdings import blank_membership
from src.run_screener import persist_outputs, upsert_analyzed_row
from src.screener import analyze_ticker
from src.screener_config import ScreenerConfig
from src.tech_filters import load_enabled, public_state, save_enabled

DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
ADMIN_PATH = DATA_DIR / "admin.json"

def _hash_password(password: str) -> str:
    # LibreSSL / older macOS Python builds may lack hashlib.scrypt (Werkzeug default).
    return generate_password_hash(password, method="pbkdf2:sha256")


def _password_issues(password: str, confirm: Optional[str] = None) -> Optional[str]:
    if len(password) < 8:
        return "密碼至少 8 個字元"
    if confirm is not None and password != confirm:
        return "兩次密碼不一致"
    return None


app = Flask(
    __name__,
    template_folder=str(Path(__file__).resolve().parent / "templates"),
)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
app.config["TEMPLATES_AUTO_RELOAD"] = True

_AUTH_LOCK = threading.Lock()
_JOB_LOCK = threading.Lock()
_LOGIN_HITS: dict[str, list[float]] = {}

_JOB: dict[str, Any] = {
    "status": "idle",
    "current": 0,
    "total": 0,
    "ticker": "",
    "name": "",
    "message": "",
    "started_at": None,
    "finished_at": None,
    "error": None,
    "counts": None,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_admin() -> Optional[dict[str, Any]]:
    if not ADMIN_PATH.exists():
        return None
    try:
        data = json.loads(ADMIN_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("username") or not data.get("password_hash"):
        return None
    return data


def _save_admin(data: dict[str, Any]) -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ADMIN_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def _ensure_secret() -> str:
    env = os.environ.get("SCREENER_SECRET_KEY", "").strip()
    if env:
        return env
    data = _load_admin()
    if data and data.get("secret_key"):
        return str(data["secret_key"])
    # Ephemeral until first setup; rotated when admin.json is created.
    return "dev-" + secrets.token_hex(16)


app.secret_key = _ensure_secret()


def _bootstrap_from_env() -> None:
    user = os.environ.get("SCREENER_ADMIN_USER", "").strip()
    password = os.environ.get("SCREENER_ADMIN_PASSWORD", "")
    if not user or not password or _load_admin():
        return
    data = {
        "username": user,
        "password_hash": _hash_password(password),
        "secret_key": secrets.token_hex(32),
        "created_at": _now_iso(),
    }
    _save_admin(data)
    app.secret_key = data["secret_key"]


_bootstrap_from_env()


def _client_ip() -> str:
    return request.headers.get("X-Forwarded-For", request.remote_addr or "local").split(",")[0].strip()


def _rate_limited() -> bool:
    ip = _client_ip()
    now = time.time()
    with _AUTH_LOCK:
        hits = [t for t in _LOGIN_HITS.get(ip, []) if now - t < 60]
        _LOGIN_HITS[ip] = hits
        if len(hits) >= 8:
            return True
        hits.append(now)
        _LOGIN_HITS[ip] = hits
    return False


def _csrf_token() -> str:
    token = session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf"] = token
    return token


def _check_csrf() -> bool:
    sent = (
        request.headers.get("X-CSRF-Token")
        or (request.form.get("csrf") if request.form else None)
        or ((request.get_json(silent=True) or {}).get("csrf") if request.is_json else None)
    )
    expected = session.get("csrf") or ""
    if not sent or not expected:
        return False
    return hmac.compare_digest(str(sent), str(expected))


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "未登入"}), 401
            return redirect(url_for("login_page", next=request.path))
        return fn(*args, **kwargs)

    return wrapped


def _web_config(**overrides: Any) -> ScreenerConfig:
    cfg = ScreenerConfig(universe="all", tech_filters=tuple(load_enabled()))
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def _attach_tech(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("all") if isinstance(payload.get("all"), list) else []
    state = public_state(rows)
    payload["tech_filters"] = state
    cfg = payload.get("config")
    if isinstance(cfg, dict):
        cfg["tech_filters"] = list(state["enabled"])
    return payload


def empty_payload() -> dict[str, Any]:
    return _attach_tech(
        {
            "generated_at": None,
            "disclaimer": "研究參考用途，不構成投資建議。作空僅提供價格區間參考。",
            "config": _web_config().to_dict(),
            "catalog": load_catalog(),
            "counts": {"universe": 0, "long_candidate": 0, "short_candidate": 0, "watch": 0, "skip": 0},
            "long_candidates": [],
            "short_candidates": [],
            "watch": [],
            "all": [],
        }
    )


def load_screener_payload() -> dict[str, Any]:
    from src.run_screener import _json_safe

    path = OUTPUT_DIR / "screener_latest.json"
    if not path.exists():
        return empty_payload()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_payload()
    payload = _json_safe(payload)
    if not isinstance(payload, dict):
        return empty_payload()
    payload["catalog"] = load_catalog()
    payload.setdefault("disclaimer", "研究參考用途，不構成投資建議。作空僅提供價格區間參考。")
    payload.setdefault("all", [])
    return _attach_tech(payload)


def _json_error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


def _drop_ticker_from_outputs(ticker: str) -> None:
    from src.run_screener import load_latest_frame
    from src.screener import apply_scores

    frame = load_latest_frame()
    if frame is None or frame.empty or "ticker" not in frame.columns:
        return
    frame = frame.copy()
    frame["ticker"] = frame["ticker"].astype(str).str.zfill(4)
    t = normalize_ticker(ticker)
    kept = frame.loc[~frame["ticker"].eq(t)]
    if len(kept) == len(frame) or kept.empty:
        return
    persist_outputs(apply_scores(kept, _web_config()), _web_config())


def _add_stock_and_fetch(body: dict[str, Any]) -> tuple[dict[str, Any], int]:
    ticker = normalize_ticker(body.get("ticker"))
    name = str(body.get("name") or "").strip()
    category_ids = body.get("category_ids") or []
    if not isinstance(category_ids, list):
        return {"ok": False, "error": "category_ids 需為陣列"}, 400
    if not ticker:
        return {"ok": False, "error": "股票代碼需為 4～6 位數字"}, 400

    payload = load_screener_payload()
    present = {
        normalize_ticker(r.get("ticker"))
        for r in (payload.get("all") or [])
        if isinstance(r, dict)
    }
    catalog = load_catalog()
    excluded = set(catalog.get("excluded") or [])
    if ticker in present and ticker not in excluded:
        return {"ok": False, "error": f"{ticker} 已在名單中"}, 400

    clear_exclusion(ticker)
    fetch = bool(body.get("fetch", True))
    try:
        if not name:
            name = _lookup_name(ticker)
        if any(s["ticker"] == ticker for s in load_catalog()["stocks"]):
            item = next(s for s in load_catalog()["stocks"] if s["ticker"] == ticker)
            if name and not item.get("name"):
                item = update_stock(ticker, name=name)
        else:
            item = add_stock(ticker, name=name, category_ids=[str(x) for x in category_ids])
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}, 400

    fetched = False
    fetch_error = None
    if fetch:
        cfg = _web_config(use_cache_prices=False)
        catalog = load_catalog()
        cat_by_id = {c["id"]: c["name"] for c in catalog["categories"]}
        meta = {
            "name": item["name"] or item["ticker"],
            **blank_membership(),
            "custom": True,
            "category_ids": item["category_ids"],
            "category_names": [cat_by_id[i] for i in item["category_ids"] if i in cat_by_id],
        }
        from src.run_screener import load_latest_frame

        existing = load_latest_frame()
        if existing is not None and not existing.empty and "ticker" in existing.columns:
            existing = existing.copy()
            existing["ticker"] = existing["ticker"].astype(str).str.zfill(4)
            hit = existing[existing["ticker"] == item["ticker"]]
            if not hit.empty:
                prev = hit.iloc[0].to_dict()
                meta["in_0050"] = bool(prev.get("in_0050"))
                meta["in_00919"] = bool(prev.get("in_00919"))
                meta["weight_0050"] = prev.get("weight_0050")
                meta["weight_00919"] = prev.get("weight_00919")
                weights = prev.get("weights") if isinstance(prev.get("weights"), dict) else {}
                meta["weights"] = weights
                members = prev.get("member_etfs") if isinstance(prev.get("member_etfs"), list) else []
                meta["member_etfs"] = members
                meta["weight_max"] = prev.get("weight_max") or 0.0
                meta["etf_membership"] = prev.get("etf_membership") or "custom"
                meta["custom"] = meta["etf_membership"] == "custom"
                if not item["name"] and prev.get("name"):
                    meta["name"] = prev["name"]
        analyzed = analyze_ticker(item["ticker"], meta, cfg, DATA_DIR)
        if analyzed:
            if item["name"]:
                analyzed["name"] = item["name"]
            analyzed["custom"] = meta["custom"]
            analyzed["category_ids"] = item["category_ids"]
            analyzed["category_names"] = meta["category_names"]
            upsert_analyzed_row(analyzed, cfg)
            fetched = True
        else:
            fetch_error = "已加入名單，但行情抓取失敗"
    return {
        "ok": True,
        "stock": item,
        "fetched": fetched,
        "fetch_error": fetch_error,
        "catalog": load_catalog(),
    }, 200


def _hide_stock(ticker: str) -> tuple[dict[str, Any], int]:
    try:
        exclude_stock(ticker)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}, 400
    _drop_ticker_from_outputs(ticker)
    return {"ok": True, "catalog": load_catalog()}, 200


def _lookup_name(ticker: str) -> str:
    try:
        import yfinance as yf

        info = yf.Ticker(f"{ticker}.TW").info or {}
        return str(info.get("shortName") or info.get("longName") or "").strip()
    except Exception:
        return ""


def _job_snapshot() -> dict[str, Any]:
    with _JOB_LOCK:
        return dict(_JOB)


def _run_refresh() -> None:
    from src.run_screener import main as run_main

    cfg = _web_config(use_cache_holdings=False, use_cache_prices=False)

    def progress_cb(info: dict[str, Any]) -> None:
        with _JOB_LOCK:
            _JOB.update(info)
            _JOB["status"] = "running"

    try:
        run_main(cfg, progress_cb=progress_cb)
        payload = load_screener_payload()
        with _JOB_LOCK:
            _JOB["status"] = "done"
            _JOB["finished_at"] = _now_iso()
            _JOB["message"] = "更新完成"
            _JOB["counts"] = payload.get("counts")
            _JOB["error"] = None
    except Exception as exc:
        with _JOB_LOCK:
            _JOB["status"] = "error"
            _JOB["finished_at"] = _now_iso()
            _JOB["error"] = str(exc)
            _JOB["message"] = "更新失敗"


@app.after_request
def _security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/")
def index():
    payload = load_screener_payload()
    html = build_screener_app_html(payload)
    authed = "true" if session.get("user") else "false"
    inject = (
        "window.__LIVE__ = true;\n"
        f"window.__ADMIN__ = {authed};\n"
        "window.__SCREENER__ = "
    )
    html = html.replace("window.__SCREENER__ = ", inject, 1)
    return html


@app.get("/admin/login")
def login_page():
    if session.get("user") and _load_admin():
        return redirect(url_for("admin_page"))
    return render_template("login.html")


@app.get("/admin")
@login_required
def admin_page():
    return render_template("admin.html")


@app.post("/admin/logout")
@login_required
def logout():
    session.clear()
    if request.is_json or request.headers.get("X-Requested-With") == "fetch":
        return jsonify({"ok": True})
    return redirect(url_for("login_page"))


@app.get("/api/session")
def api_session():
    admin = _load_admin()
    return jsonify(
        {
            "ok": True,
            "setup_required": admin is None,
            "authenticated": bool(session.get("user")),
            "username": session.get("user"),
            "csrf": _csrf_token(),
        }
    )


@app.post("/api/setup")
def api_setup():
    if _load_admin():
        return _json_error("管理員已建立，請直接登入", 409)
    if _rate_limited():
        return _json_error("嘗試過於頻繁，請稍後再試", 429)
    body = request.get_json(silent=True) or {}
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    confirm = str(body.get("confirm") or "")
    if len(username) < 3:
        return _json_error("帳號至少 3 個字元")
    issue = _password_issues(password, confirm)
    if issue:
        return _json_error(issue)
    data = {
        "username": username,
        "password_hash": _hash_password(password),
        "secret_key": secrets.token_hex(32),
        "created_at": _now_iso(),
    }
    _save_admin(data)
    app.secret_key = data["secret_key"]
    session.clear()
    session.permanent = True
    session["user"] = username
    session["csrf"] = secrets.token_urlsafe(32)
    return jsonify({"ok": True, "username": username, "csrf": session["csrf"]})


@app.post("/api/login")
def api_login():
    admin = _load_admin()
    if admin is None:
        return _json_error("尚未建立管理員，請先完成初始設定", 409)
    if _rate_limited():
        return _json_error("嘗試過於頻繁，請稍後再試", 429)
    body = request.get_json(silent=True) or {}
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    user_ok = hmac.compare_digest(username, str(admin.get("username") or ""))
    pass_ok = check_password_hash(str(admin.get("password_hash") or ""), password)
    if not (user_ok and pass_ok):
        return _json_error("帳號或密碼不正確", 401)
    session.clear()
    session.permanent = True
    session["user"] = admin["username"]
    session["csrf"] = secrets.token_urlsafe(32)
    if admin.get("secret_key"):
        app.secret_key = str(admin["secret_key"])
    return jsonify({"ok": True, "username": admin["username"], "csrf": session["csrf"]})


@app.post("/api/admin/account")
@login_required
def api_update_account():
    if not _check_csrf():
        return _json_error("CSRF 驗證失敗", 403)
    if _rate_limited():
        return _json_error("嘗試過於頻繁，請稍後再試", 429)
    admin = _load_admin()
    if admin is None:
        return _json_error("找不到管理員資料", 404)
    body = request.get_json(silent=True) or {}
    current = str(body.get("current_password") or "")
    new_username = str(body.get("username") or "").strip()
    new_password = str(body.get("new_password") or "")
    confirm = str(body.get("confirm") or "")

    if not check_password_hash(str(admin.get("password_hash") or ""), current):
        return _json_error("目前密碼不正確", 401)

    changed = []
    if new_username and new_username != str(admin.get("username") or ""):
        if len(new_username) < 3:
            return _json_error("帳號至少 3 個字元")
        admin["username"] = new_username
        changed.append("帳號")
    if new_password:
        issue = _password_issues(new_password, confirm)
        if issue:
            return _json_error(issue)
        if check_password_hash(str(admin.get("password_hash") or ""), new_password):
            return _json_error("新密碼不可與目前密碼相同")
        admin["password_hash"] = _hash_password(new_password)
        changed.append("密碼")
    if not changed:
        return _json_error("沒有要更新的項目")

    admin["updated_at"] = _now_iso()
    _save_admin(admin)
    session["user"] = admin["username"]
    return jsonify(
        {
            "ok": True,
            "username": admin["username"],
            "changed": changed,
            "message": "已更新" + "與".join(changed),
        }
    )


@app.get("/api/screener")
def api_screener():
    return jsonify({"ok": True, "payload": load_screener_payload()})


@app.post("/api/stocks")
def api_public_add_stock():
    body = request.get_json(silent=True) or {}
    payload, status = _add_stock_and_fetch(body)
    return jsonify(payload), status


@app.delete("/api/stocks/<ticker>")
def api_public_delete_stock(ticker: str):
    payload, status = _hide_stock(ticker)
    return jsonify(payload), status


@app.get("/api/catalog")
def api_catalog_public():
    return jsonify({"ok": True, "catalog": load_catalog()})


@app.get("/api/admin/status")
@login_required
def api_admin_status():
    payload = load_screener_payload()
    return jsonify(
        {
            "ok": True,
            "username": session.get("user"),
            "csrf": _csrf_token(),
            "job": _job_snapshot(),
            "generated_at": payload.get("generated_at"),
            "counts": payload.get("counts"),
            "catalog": payload.get("catalog") or load_catalog(),
            "tech_filters": payload.get("tech_filters"),
        }
    )


@app.post("/api/admin/tech-filters")
@login_required
def api_save_tech_filters():
    if not _check_csrf():
        return _json_error("CSRF 驗證失敗", 403)
    body = request.get_json(silent=True) or {}
    enabled = body.get("enabled")
    if not isinstance(enabled, list):
        return _json_error("enabled 需為陣列")
    saved = save_enabled(enabled)
    payload = load_screener_payload()
    return jsonify({"ok": True, "tech_filters": payload.get("tech_filters"), "enabled": saved})


@app.post("/api/admin/refresh")
@login_required
def api_refresh():
    if not _check_csrf():
        return _json_error("CSRF 驗證失敗", 403)
    with _JOB_LOCK:
        if _JOB.get("status") == "running":
            return _json_error("更新進行中，請稍候", 409)
        _JOB.update(
            {
                "status": "running",
                "current": 0,
                "total": 0,
                "ticker": "",
                "name": "",
                "message": "準備抓取成份與行情…",
                "started_at": _now_iso(),
                "finished_at": None,
                "error": None,
                "counts": None,
            }
        )
    threading.Thread(target=_run_refresh, name="screener-refresh", daemon=True).start()
    return jsonify({"ok": True, "job": _job_snapshot()})


@app.get("/api/admin/refresh")
@login_required
def api_refresh_status():
    return jsonify({"ok": True, "job": _job_snapshot()})


@app.get("/api/admin/catalog")
@login_required
def api_catalog():
    return jsonify({"ok": True, "catalog": load_catalog()})


@app.post("/api/admin/categories")
@login_required
def api_add_category():
    if not _check_csrf():
        return _json_error("CSRF 驗證失敗", 403)
    body = request.get_json(silent=True) or {}
    try:
        item = add_category(str(body.get("name") or ""), str(body.get("note") or ""))
    except ValueError as exc:
        return _json_error(str(exc))
    return jsonify({"ok": True, "category": item, "catalog": load_catalog()})


@app.patch("/api/admin/categories/<cat_id>")
@login_required
def api_update_category(cat_id: str):
    if not _check_csrf():
        return _json_error("CSRF 驗證失敗", 403)
    body = request.get_json(silent=True) or {}
    try:
        item = update_category(cat_id, name=body.get("name"), note=body.get("note"))
    except KeyError:
        return _json_error("找不到分類", 404)
    except ValueError as exc:
        return _json_error(str(exc))
    return jsonify({"ok": True, "category": item, "catalog": load_catalog()})


@app.delete("/api/admin/categories/<cat_id>")
@login_required
def api_delete_category(cat_id: str):
    if not _check_csrf():
        return _json_error("CSRF 驗證失敗", 403)
    try:
        delete_category(cat_id)
    except KeyError:
        return _json_error("找不到分類", 404)
    except ValueError as exc:
        return _json_error(str(exc))
    return jsonify({"ok": True, "catalog": load_catalog()})


@app.post("/api/admin/stocks")
@login_required
def api_add_stock():
    if not _check_csrf():
        return _json_error("CSRF 驗證失敗", 403)
    body = request.get_json(silent=True) or {}
    ticker = normalize_ticker(body.get("ticker"))
    name = str(body.get("name") or "").strip()
    category_ids = body.get("category_ids") or []
    if not isinstance(category_ids, list):
        return _json_error("category_ids 需為陣列")
    fetch = bool(body.get("fetch", True))
    try:
        if not name:
            name = _lookup_name(ticker)
        item = add_stock(ticker, name=name, category_ids=[str(x) for x in category_ids])
    except ValueError as exc:
        return _json_error(str(exc))

    fetched = False
    fetch_error = None
    if fetch:
        from src.run_screener import load_latest_frame

        cfg = _web_config(use_cache_prices=False)
        catalog = load_catalog()
        cat_by_id = {c["id"]: c["name"] for c in catalog["categories"]}
        meta = {
            "name": item["name"] or item["ticker"],
            **blank_membership(),
            "custom": True,
            "category_ids": item["category_ids"],
            "category_names": [cat_by_id[i] for i in item["category_ids"] if i in cat_by_id],
        }
        existing = load_latest_frame()
        if existing is not None and not existing.empty and "ticker" in existing.columns:
            existing = existing.copy()
            existing["ticker"] = existing["ticker"].astype(str).str.zfill(4)
            hit = existing[existing["ticker"] == item["ticker"]]
            if not hit.empty:
                prev = hit.iloc[0].to_dict()
                meta["in_0050"] = bool(prev.get("in_0050"))
                meta["in_00919"] = bool(prev.get("in_00919"))
                meta["weight_0050"] = prev.get("weight_0050")
                meta["weight_00919"] = prev.get("weight_00919")
                weights = prev.get("weights") if isinstance(prev.get("weights"), dict) else {}
                meta["weights"] = weights
                members = prev.get("member_etfs") if isinstance(prev.get("member_etfs"), list) else []
                meta["member_etfs"] = members
                meta["weight_max"] = prev.get("weight_max") or 0.0
                meta["etf_membership"] = prev.get("etf_membership") or "custom"
                meta["custom"] = meta["etf_membership"] == "custom"
                if not item["name"] and prev.get("name"):
                    meta["name"] = prev["name"]
        analyzed = analyze_ticker(item["ticker"], meta, cfg, DATA_DIR)
        if analyzed:
            if item["name"]:
                analyzed["name"] = item["name"]
            upsert_analyzed_row(analyzed, cfg)
            fetched = True
        else:
            fetch_error = "已加入名單，但行情抓取失敗（可稍後點「更新全部成份股」）"
    return jsonify(
        {
            "ok": True,
            "stock": item,
            "fetched": fetched,
            "fetch_error": fetch_error,
            "catalog": load_catalog(),
        }
    )


@app.patch("/api/admin/stocks/<ticker>")
@login_required
def api_update_stock(ticker: str):
    if not _check_csrf():
        return _json_error("CSRF 驗證失敗", 403)
    body = request.get_json(silent=True) or {}
    try:
        item = update_stock(ticker, name=body.get("name"), category_ids=body.get("category_ids"))
    except KeyError:
        return _json_error("找不到股票", 404)
    except ValueError as exc:
        return _json_error(str(exc))
    return jsonify({"ok": True, "stock": item, "catalog": load_catalog()})


@app.delete("/api/admin/stocks/<ticker>")
@login_required
def api_delete_stock(ticker: str):
    if not _check_csrf():
        return _json_error("CSRF 驗證失敗", 403)
    try:
        delete_stock(ticker)
    except KeyError:
        return _json_error("找不到股票", 404)
    except ValueError as exc:
        return _json_error(str(exc))

    from src.run_screener import load_latest_frame
    from src.screener import apply_scores

    frame = load_latest_frame()
    if frame is not None and not frame.empty and "ticker" in frame.columns:
        t = normalize_ticker(ticker)
        frame["ticker"] = frame["ticker"].astype(str).str.zfill(4)
        is_custom = pd.Series(False, index=frame.index)
        if "custom" in frame.columns:
            is_custom = frame["custom"].fillna(False).astype(bool)
        if "etf_membership" in frame.columns:
            is_custom = is_custom | frame["etf_membership"].astype(str).eq("custom")
        drop = frame["ticker"].eq(t) & is_custom
        kept = frame.loc[~drop]
        if len(kept) != len(frame) and not kept.empty:
            cfg = _web_config()
            persist_outputs(apply_scores(kept, cfg), cfg)
    return jsonify({"ok": True, "catalog": load_catalog()})


@app.errorhandler(404)
def _not_found(err):
    path = request.path or ""
    wants_html = "text/html" in (request.headers.get("Accept") or "")
    if wants_html and not path.startswith("/api"):
        return redirect(url_for("index"))
    return _json_error("找不到頁面", 404)


def main() -> int:
    host = os.environ.get("SCREENER_HOST", "127.0.0.1")
    port = int(os.environ.get("SCREENER_PORT", "5050"))
    print(f"Screener app  http://{host}:{port}")
    print(f"Admin login   http://{host}:{port}/admin/login")
    app.run(host=host, port=port, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
