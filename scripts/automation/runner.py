"""统一阶段编排；外部调用仅通过原有 CLI 执行。"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .publish import ALLOWED, publish, recover, save

STAGES = ("discovery", "content", "feed", "snapshot", "funding")


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    if root.exists():
        for path in sorted(root.rglob("*")):
            if path.is_file():
                digest.update(str(path.relative_to(root)).encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()


def validate_candidates(workspace: Path, root: Path, stages: list[str]) -> None:
    import tag_news
    from build_manus_feed import validate_publishable
    from manus_source.contracts import validate_feed
    from funding.output import validate_table
    tx_path = root / "config/taxonomy.json"
    if "feed" in stages:
        feed = json.loads((workspace / "data/manus/current.json").read_text(encoding="utf-8"))
        validate_feed(feed, str(tx_path))
        validate_publishable(feed)
    if "snapshot" in stages:
        snapshot = json.loads((workspace / "web/public/snapshot.json").read_text(encoding="utf-8"))
        for key in ("daily", "weekly"):
            if not isinstance(snapshot[key]["sections"], list):
                raise ValueError("候选快照不合法")
        for key in ("history", "weeklyNav"):
            if not isinstance(snapshot[key], list):
                raise ValueError("候选快照导航不合法")
    if "funding" in stages:
        table = json.loads((workspace / "data/funding/current.json").read_text(encoding="utf-8"))
        validate_table(table, tag_news.load_taxonomy(str(tx_path)))
        web_table = json.loads((workspace / "web/public/funding-table.json").read_text(encoding="utf-8"))
        if table != web_table:
            raise ValueError("候选融资产物不一致")


def plan(root: Path, workspace: Path, date: str, resume=False, skip_search=False):
    def script(name, *args):
        return [sys.executable, str(root / "scripts" / name), *map(str, args)]
    def out(rel):
        return workspace / rel
    commands = {
        "discovery": script("manus_source/runner.py", "--date", date, *(["--resume"] if resume else [])),
        "content": script("manus_source/content_phase.py", "--date", date),
        "feed": script("build_manus_feed.py", "--date", date, "--data-dir", out("data/manus")),
        "snapshot": script("build_snapshot.py", "--out", out("web/public/index.html"),
                           "--snapshot-json", out("web/public/snapshot.json"),
                           "--history-dir", out("web/public/history"), "--weekly-dir", out("web/public/weekly"),
                           "--archive-dir", out("data/archive"), "--tag-cache", out("data/cache/tag_cache.json"),
                           "--manus-json", out("data/manus/current.json")),
        "funding": script("funding_table.py", "--snapshot", out("web/public/snapshot.json"),
                          "--feed", out("data/manus/current.json"), "--data-dir", out("data/funding"),
                          "--cache-dir", out("data/funding"), "--public-dir", out("web/public"),
                          *(["--skip-search"] if skip_search else [])),
    }
    return commands


def fingerprint(root: Path, stages, skip_search):
    digest = hashlib.sha256()
    for folder in ("config", "scripts"):
        for path in sorted((root / folder).rglob("*")):
            if path.is_file() and path.suffix in (".py", ".json", ".md", ".html"):
                digest.update(str(path.relative_to(root)).encode())
                digest.update(path.read_bytes())
    digest.update(json.dumps([stages, skip_search, os.getenv("LLM_MODEL", ""),
                              os.getenv("LLM_API_BASE", ""), os.getenv("MANUS_CONTENT_MODE", "script")]).encode())
    return digest.hexdigest()


def run(root: Path, date: str, stages: list[str], *, resume=False, no_promote=False,
        skip_search=False, execute=None):
    execute = execute or (lambda cmd: subprocess.run(cmd, cwd=root).returncode)
    runs = root / "work" / "runs" / date
    runs.mkdir(parents=True, exist_ok=True)
    lock = root / "work" / "pipeline.lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    try:
        latest = runs / "latest.json"
        sig = fingerprint(root, stages, skip_search)
        if resume:
            run_id = json.loads(latest.read_text(encoding="utf-8"))["runId"]
            if not isinstance(run_id, str) or len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
                raise ValueError("运行标识不合法")
            run_dir = runs / run_id
            recover(root, run_dir)
            state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            journal = run_dir / "publication.json"
            if journal.exists() and json.loads(journal.read_text(encoding="utf-8"))["status"] == "committed":
                print("本次运行已经发布，无需重复执行")
                return 0
            if state["fingerprint"] != sig:
                raise ValueError("代码、配置或所选阶段已变化，请去掉 --resume 开始新运行")
        else:
            run_id = uuid.uuid4().hex
            run_dir = runs / run_id
            workspace = run_dir / "workspace"
            for rel in ALLOWED:
                source, dest = root / rel, workspace / rel
                if source.exists():
                    shutil.copytree(source, dest)
                else:
                    dest.mkdir(parents=True, exist_ok=True)
            state = {"date": date, "fingerprint": sig, "stages": {}, "published": False,
                     "baseline": {rel: tree_digest(root / rel) for rel in ALLOWED}}
            save(run_dir / "state.json", state)
            save(latest, {"runId": run_id})
        commands = plan(root, run_dir / "workspace", date, resume, skip_search)
        for stage in stages:
            if state["stages"].get(stage, {}).get("status") == "success":
                print(f"[{stage}] 复用已成功阶段", flush=True)
                continue
            state["stages"][stage] = {"status": "running"}
            save(run_dir / "state.json", state)
            started = time.monotonic()
            print(f"[{stage}] 开始", flush=True)
            code = execute(commands[stage])
            state["stages"][stage] = {"status": "success" if code == 0 else "failed", "exitCode": code,
                                       "seconds": round(time.monotonic() - started, 2)}
            save(run_dir / "state.json", state)
            if code:
                print(f"[{stage}] 失败；正式数据未更新。补齐配置后用 --resume 继续。", flush=True)
                return code
        outputs = set()
        if "feed" in stages:
            outputs.add("data/manus")
        if "snapshot" in stages:
            outputs.update(("data/archive", "data/cache", "web/public"))
        if "funding" in stages:
            outputs.update(("data/funding", "web/public"))
        if not no_promote and outputs:
            validate_candidates(run_dir / "workspace", root, stages)
            if any(tree_digest(root / rel) != state["baseline"][rel] for rel in outputs):
                raise ValueError("正式数据已由其他运行更新，禁止旧候选覆盖；请开始新运行")
            publish(root, run_dir, [p for p in ALLOWED if p in outputs])
            state["published"] = True
        save(run_dir / "state.json", state)
        print("候选产物已保留，未发布" if no_promote else "所选阶段完成，产物已更新", flush=True)
        return 0
    finally:
        lock.unlink()
