#!/usr/bin/env python3
from __future__ import annotations
import json
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "market-cloud.json"
REMOTE_FETCH_HOST = "hermes-ops@172.245.219.24"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/center/boardlist.html",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

INDEX_SECIDS = [
    "1.000001",  # 上证指数
    "0.399001",  # 深证成指
    "0.399006",  # 创业板指
    "1.000688",  # 科创50
    "1.000300",  # 沪深300
    "1.000016",  # 上证50
    "0.399905",  # 中证500
    "0.399852",  # 中证1000
]


def direction(pct: float) -> str:
    if pct > 0.2:
        return "up"
    if pct < -0.2:
        return "down"
    return "flat"


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "-"):
            return default
        return float(value)
    except Exception:
        return default


def fetch_json_local(session: requests.Session, url: str, params: dict[str, str]) -> dict[str, Any]:
    resp = session.get(url, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_json_remote(url: str, params: dict[str, str]) -> dict[str, Any]:
    full_url = f"{url}?{urlencode(params)}"
    code = r'''
import json, sys, time, requests
url = sys.argv[1]
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/center/boardlist.html",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
last = None
for attempt in range(4):
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        sys.stdout.write(resp.text)
        raise SystemExit(0)
    except Exception as exc:
        last = exc
        time.sleep(2 * (attempt + 1))
raise RuntimeError(last)
'''
    remote_cmd = f"python3 -c {shlex.quote(code)} {shlex.quote(full_url)}"
    proc = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", REMOTE_FETCH_HOST, remote_cmd],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=45,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"remote fetch failed: {proc.stderr.strip() or proc.stdout[:200]}")
    return json.loads(proc.stdout)


def fetch_json(session: requests.Session, url: str, params: dict[str, str], retries: int = 3) -> dict[str, Any]:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            return fetch_json_local(session, url, params)
        except Exception as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
            try:
                session.get("https://quote.eastmoney.com/center/boardlist.html", headers=HEADERS, timeout=10)
            except Exception:
                pass
    try:
        return fetch_json_remote(url, params)
    except Exception as exc:
        raise RuntimeError(f"EastMoney request failed locally ({last}) and remotely ({exc})") from exc


def fetch_indices(session: requests.Session) -> list[dict[str, Any]]:
    payload = fetch_json(
        session,
        "https://push2.eastmoney.com/api/qt/ulist.np/get",
        {
            "fltt": "2",
            "invt": "2",
            "fields": "f12,f14,f2,f3,f5,f6,f20",
            "secids": ",".join(INDEX_SECIDS),
        },
    )
    rows = ((payload.get("data") or {}).get("diff") or [])
    nodes: list[dict[str, Any]] = []
    for raw in rows:
        pct = as_float(raw.get("f3"))
        amount = as_float(raw.get("f6"))
        nodes.append(
            {
                "code": raw.get("f12") or "",
                "name": raw.get("f14") or "--",
                "type": "index",
                "pct_chg": pct,
                "latest": as_float(raw.get("f2")),
                "amount": amount,
                "direction": direction(pct),
                "visual_size": max(1.0, amount / 100_000_000_000),
            }
        )
    wanted = {sec.split(".", 1)[1]: i for i, sec in enumerate(INDEX_SECIDS)}
    nodes.sort(key=lambda x: wanted.get(x["code"], 999))
    return nodes


def fetch_boards(session: requests.Session, board_type: str, fs: str, limit: int = 36) -> list[dict[str, Any]]:
    payload = fetch_json(
        session,
        "https://push2.eastmoney.com/api/qt/clist/get",
        {
            "pn": "1",
            "pz": str(limit),
            "po": "1",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fid": "f6",
            "fs": fs,
            "fields": "f12,f14,f2,f3,f5,f6,f20",
        },
    )
    rows = ((payload.get("data") or {}).get("diff") or [])
    nodes: list[dict[str, Any]] = []
    for raw in rows:
        pct = as_float(raw.get("f3"))
        amount = as_float(raw.get("f6"))
        nodes.append(
            {
                "code": raw.get("f12") or "",
                "name": raw.get("f14") or "--",
                "type": board_type,
                "pct_chg": pct,
                "latest": as_float(raw.get("f2")),
                "amount": amount,
                "direction": direction(pct),
                "visual_size": max(1.0, amount / 1_000_000_000),
            }
        )
    return nodes


def main() -> None:
    session = requests.Session()
    # Warm up cookies/anti-hotlink state; EastMoney sometimes closes cold clist requests.
    try:
        session.get("https://quote.eastmoney.com/center/boardlist.html", headers=HEADERS, timeout=10)
    except Exception:
        pass
    indices = fetch_indices(session)
    industry = fetch_boards(session, "industry", "m:90+t:2", 36)
    concept = fetch_boards(session, "concept", "m:90+t:3", 36)
    today = datetime.now().strftime("%Y-%m-%d")
    data = {
        "trade_date": today,
        "source": "eastmoney.realtime",
        "indices": indices,
        "industry": industry,
        "concept": concept,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "trade_date": today,
        "indices": len(indices),
        "industry": len(industry),
        "concept": len(concept),
        "source": data["source"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
