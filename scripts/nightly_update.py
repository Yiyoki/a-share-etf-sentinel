#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

BACKEND = Path("/home/admin/.hermes/artifacts/a-share-etf-sentinel")
PAGES = Path("/home/admin/.hermes/artifacts/a-share-etf-sentinel-pages-repo")
PYTHON = BACKEND / ".venv" / "bin" / "python"
LOG_DIR = PAGES / "logs"
DATA_DIR = PAGES / "data"
PROJECT = "a-share-etf-sentinel"


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S %Z")


def log(message: str) -> None:
    print(f"[{now()}] {message}", flush=True)


def run(cmd: list[str], cwd: Path, retries: int = 1, delay: int = 8, check: bool = True) -> subprocess.CompletedProcess[str]:
    last: subprocess.CompletedProcess[str] | None = None
    for attempt in range(1, retries + 1):
        log(f"run attempt {attempt}/{retries}: {' '.join(cmd)}")
        last = subprocess.run(cmd, cwd=str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=420)
        if last.stdout:
            print(last.stdout, end="" if last.stdout.endswith("\n") else "\n", flush=True)
        if last.returncode == 0:
            return last
        if attempt < retries:
            time.sleep(delay * attempt)
    if check and last and last.returncode != 0:
        raise RuntimeError(f"command failed ({last.returncode}): {' '.join(cmd)}")
    assert last is not None
    return last


def read_keys() -> dict[str, str]:
    keys: dict[str, str] = {}
    key_file = Path("/opt/key.txt")
    if key_file.exists():
        for line in key_file.read_text(errors="ignore").splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                keys[k.strip()] = v.strip()
    return keys


def export_backend_json() -> None:
    sys.path.insert(0, str(BACKEND))
    from app.main import latest_signal, market_map  # type: ignore

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "latest-signal.json").write_text(
        json.dumps(latest_signal(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (DATA_DIR / "market-map.json").write_text(
        json.dumps(market_map(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    log("exported latest-signal.json and market-map.json")


def trigger_pages_deploy() -> None:
    keys = read_keys()
    token = keys.get("cloudflare")
    account_id = keys.get("cloudflare_account_id")
    if not token or not account_id:
        log("Cloudflare credentials not found; skip explicit deployment trigger")
        return
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/pages/projects/{PROJECT}/deployments"
    req = urllib.request.Request(url, method="POST", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    log(f"Cloudflare deployment trigger success={payload.get('success')}")


def github_request(method: str, path: str, token: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"https://api.github.com/repos/Yiyoki/a-share-etf-sentinel{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "a-share-etf-sentinel-nightly",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def push_files_via_github_api(files: list[str], message: str) -> None:
    keys = read_keys()
    token = keys.get("github")
    if not token:
        raise RuntimeError("GitHub token not found")
    for rel in files:
        content = (PAGES / rel).read_bytes()
        current = github_request("GET", f"/contents/{rel}?ref=main", token)
        remote_sha = current.get("sha")
        local_sha = run(["git", "hash-object", rel], PAGES).stdout.strip()
        if current.get("sha") and current.get("sha") == local_sha:
            log(f"skip unchanged remote file {rel}")
            continue
        payload = {
            "message": f"{message}: {rel}",
            "content": base64.b64encode(content).decode("ascii"),
            "sha": remote_sha,
            "branch": "main",
        }
        github_request("PUT", f"/contents/{rel}", token, payload)
        log(f"updated {rel} through GitHub Contents API")


def git_commit_push() -> None:
    files = ["data/latest-signal.json", "data/market-map.json", "data/market-cloud.json"]
    run(["git", "add", *files], PAGES)
    status = run(["git", "status", "--short", *files], PAGES, check=False)
    if not status.stdout.strip():
        log("no data changes to commit")
        return
    msg = f"Nightly data refresh {datetime.now().strftime('%Y-%m-%d')}"
    run(["git", "commit", "-m", msg], PAGES)
    pushed = run(["git", "push", "origin", "main"], PAGES, retries=3, delay=12, check=False)
    if pushed.returncode != 0:
        log("git push failed; fallback to GitHub Contents API")
        push_files_via_github_api(files, msg)
    trigger_pages_deploy()


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if not PYTHON.exists():
        raise RuntimeError(f"backend venv python not found: {PYTHON}")

    # 1) 国家队三因子：整轮更新重试，内部数据源也有单请求重试/降级日志。
    run([str(PYTHON), "scripts/update_data.py"], BACKEND, retries=3, delay=15)

    # 2) 导出国家队 JSON。
    export_backend_json()

    # 3) 大盘云图：东方财富实时行情，脚本内部有单接口重试。
    run([sys.executable, "scripts/update_market_cloud.py"], PAGES, retries=3, delay=15)

    # 4) 发布静态 JSON 到 GitHub/Cloudflare Pages。
    git_commit_push()
    log("nightly refresh completed")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"ERROR: {exc}")
        raise
