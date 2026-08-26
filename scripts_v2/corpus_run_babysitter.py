"""run_id=4 长时盯守脚本。

职责（仅此而已）：
- 周期性查询 corpus_runs 状态与条目计数，追加写入日志文件；
- 当运行因“外部服务错误”熔断暂停时，调用 resume 接口尝试恢复。
  恢复路径内置最小生成探针：模型未恢复则继续保持暂停并等待下一轮，
  因此本脚本不会绕过任何熔断/质量约束；
- 不修改数据、不重置状态、不创建新运行。

用法：
    python scripts_v2/corpus_run_babysitter.py [--interval 300]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8876"
RUN_ID = 4
APP_ROOT = Path(__file__).resolve().parents[1]
LOG = APP_ROOT / "runtime" / "babysitter_run4.log"


def log(line: str) -> None:
    stamp = dt.datetime.now().isoformat(timespec="seconds")
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"[{stamp}] {line}\n")


def api(path: str, method: str = "GET", csrf: str | None = None) -> dict:
    req = urllib.request.Request(BASE + path, method=method)
    if csrf:
        req.add_header("X-CSRF-Token", csrf)
    opener: urllib.request.OpenerDirector
    if cookies:
        opener = urllib.request.build_opener()
        req.add_header("Cookie", cookies)
    else:
        opener = urllib.request.build_opener()
    try:
        with opener.open(req, timeout=60) as resp:
            set_cookie = resp.headers.get_all("Set-Cookie") or []
            global_cookie_store(set_cookie)
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # noqa: F821
        return {"error": f"HTTP {exc.code}", "body": exc.read().decode("utf-8", "replace")[:200]}


cookies = ""
csrf_token = ""


def global_cookie_store(set_cookie: list[str]) -> None:
    global cookies
    pairs = []
    for item in set_cookie:
        first = item.split(";", 1)[0]
        name = first.split("=", 1)[0].strip()
        if name in ("bid_writer_session", "bid_writer_csrf"):
            pairs.append((name, first))
    if pairs:
        # 用最新会话覆盖
        kept = [p for p in cookies.split("; ") if p and not any(p.startswith(n + "=") for n, _ in pairs)]
        kept.extend(v for _, v in pairs)
        cookies = "; ".join(kept)
    for item in set_cookie:
        first = item.split(";", 1)[0]
        if first.startswith("bid_writer_csrf="):
            globals()["csrf_token"] = first.split("=", 1)[1]


def login() -> bool:
    """从环境变量或 .env 读取管理员凭据登录。"""
    import os
    import re

    user = os.environ.get("BID_WRITER_BOOTSTRAP_ADMIN", "")
    pwd = os.environ.get("BID_WRITER_BOOTSTRAP_PASSWORD", "")
    if not user or not pwd:
        env_path = APP_ROOT / ".env"
        for line in env_path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^([A-Z_]+)=(.*)$", line)
            if not m:
                continue
            val = m.group(2).strip().strip('"')
            if m.group(1) == "BID_WRITER_BOOTSTRAP_ADMIN":
                user = val
            elif m.group(1) == "BID_WRITER_BOOTSTRAP_PASSWORD":
                pwd = val
    body = json.dumps({"username": user, "password": pwd}).encode()
    req = urllib.request.Request(
        BASE + "/api/auth/login", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            sc = resp.headers.get_all("Set-Cookie") or []
            resp.read()
            global_cookie_store(sc)
        return True
    except Exception as exc:  # noqa: BLE001
        log(f"登录失败: {type(exc).__name__}: {exc}")
        return False


def snapshot() -> dict:
    run = api(f"/api/knowledge/corpus-runs/{RUN_ID}")
    if "error" in run:
        return {"error": run["error"]}
    counters = run.get("counters") or {}
    return {
        "status": run.get("status"),
        "stage": run.get("stage"),
        "pause_reason": run.get("pause_reason") or "",
        "terminal": counters.get("terminal"),
        "remaining": counters.get("remaining"),
        "total": counters.get("total"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=300)
    args = parser.parse_args()

    LOG.parent.mkdir(parents=True, exist_ok=True)
    log(f"盯守启动 run_id={RUN_ID} interval={args.interval}s")
    if not login():
        return 1
    log("管理员登录成功")

    while True:
        snap = snapshot()
        if "error" in snap:
            log(f"查询失败: {snap['error']}")
            if "401" in str(snap["error"]):
                log("会话过期，重新登录…")
                if login():
                    log("重新登录成功")
                else:
                    log("重新登录失败，下轮重试")
        else:
            log(json.dumps(snap, ensure_ascii=False))
            if snap["status"] == "paused" and "外部服务错误" in snap["pause_reason"]:
                result = api(f"/api/knowledge/corpus-runs/{RUN_ID}/resume", method="POST", csrf=csrf_token)
                if "error" in result and "401" in str(result.get("error", "")):
                    login()
                    result = api(f"/api/knowledge/corpus-runs/{RUN_ID}/resume", method="POST", csrf=csrf_token)
                if "error" in result:
                    log(f"resume 尝试失败(将重试): {result}")
                else:
                    after = snapshot()
                    log(f"resume 已调用 -> {json.dumps(after, ensure_ascii=False)}")
            elif snap["status"] in {"completed", "cancelled"}:
                log(f"运行进入终态 {snap['status']}，盯守退出")
                return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
