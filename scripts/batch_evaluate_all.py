"""奖学金全量批量评估驱动：并发调用单评 SSE 端点，逐人等完成。

用法（服务器上）：
    set -a; source /etc/zhipu-talent.env; set +a
    nohup /opt/zhipu-talent/venv/bin/python scripts/batch_evaluate_all.py \
        --workers 6 --username pengguanqiao --password "$APP_AUTH_PASSWORD" \
        > /opt/zhipu-talent/backups/batch_eval_20260930.log 2>&1 &

只评 eligible/scored/finalized（可评估状态）；409=已有评估在跑则跳过。
进度实时写 stdout；结束打印汇总。--include-done 默认重评已完成者。
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

BASE = "http://127.0.0.1:8503"
EVALUABLE = {"eligible", "scored", "finalized"}
_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def make_session(username: str, password: str) -> requests.Session:
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"username": username, "password": password}, timeout=15)
    r.raise_for_status()
    return s


def evaluate_one(session: requests.Session, app_id: str, name: str) -> str:
    """跑一个人的评估，返回结果描述。SSE 逐行读到 done/error。"""
    started = time.time()
    try:
        with session.post(
            f"{BASE}/api/scholarship/applications/{app_id}/evaluate",
            stream=True, timeout=(10, 180),
        ) as r:
            if r.status_code == 409:
                return "SKIP:已有评估在跑"
            if r.status_code != 200:
                return f"FAIL:HTTP {r.status_code}"
            for line in r.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                try:
                    ev = json.loads(line[6:])
                except ValueError:
                    continue
                etype = ev.get("type")
                if etype == "done":
                    score = (ev.get("payload") or {}).get("blind_score")
                    return f"OK:{score}分({time.time() - started:.0f}s)"
                if etype == "error":
                    return f"FAIL:{str((ev.get('payload') or {}).get('message'))[:120]}"
            return "FAIL:流意外结束"
    except requests.RequestException as exc:
        return f"FAIL:{str(exc)[:120]}({time.time() - started:.0f}s)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--username", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--limit", type=int, default=0, help="最多评估 N 人（0=全部），调试用")
    args = ap.parse_args()

    session = make_session(args.username, args.password)
    apps = session.get(f"{BASE}/api/scholarship/applications", timeout=30).json()
    targets = [a for a in apps if a.get("status") in EVALUABLE]
    if args.limit:
        targets = targets[: args.limit]
    log(f"待评估 {len(targets)} 人（{args.workers} 路并发）")

    local = threading.local()
    done = ok = fail = skip = 0
    started = time.time()

    def worker(app):
        if not getattr(local, "session", None):
            local.session = make_session(args.username, args.password)
        return app, evaluate_one(local.session, app["id"], app.get("name") or "")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(worker, a) for a in targets]
        for fut in as_completed(futures):
            app, result = fut.result()
            done += 1
            if result.startswith("OK:"):
                ok += 1
            elif result.startswith("SKIP"):
                skip += 1
            else:
                fail += 1
            log(f"[{done}/{len(targets)}] {app.get('name')}({app['id'][:8]}) {result}"
                f" | 累计 成功{ok} 失败{fail} 跳过{skip} 用时{time.time() - started:.0f}s")

    log(f"全部完成：成功 {ok} | 失败 {fail} | 跳过 {skip} | 总用时 {(time.time() - started) / 60:.0f} 分钟")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
