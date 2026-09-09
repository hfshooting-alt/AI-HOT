"""候选目录替换；异常回滚，进程中断后可由下一次 resume 恢复。

多目录文件系统替换不是面向并发读者的全局原子事务。GitHub 发布在提交后读取整套结果。
"""
import json
import os
from pathlib import Path


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def recover(root: Path, run_dir: Path) -> None:
    journal = run_dir / "publication.json"
    if not journal.exists():
        return
    data = json.loads(journal.read_text(encoding="utf-8"))
    if data["status"] != "pending":
        return
    for entry in reversed(data["entries"]):
        rel = entry["path"]
        if rel not in ALLOWED:
            raise ValueError("发布记录包含不允许的路径")
        target, staged, backup = root / rel, run_dir / "workspace" / rel, run_dir / "backup" / rel
        for base in (root, run_dir / "workspace", run_dir / "backup"):
            if not (base / rel).resolve().is_relative_to(base.resolve()):
                raise ValueError("恢复路径越出工作目录")
        if backup.exists():
            if target.exists():
                staged.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, staged)
            os.replace(backup, target)
        elif not entry["existed"] and not staged.exists() and target.exists():
            os.replace(target, staged)
    data["status"] = "rolled_back"
    save(journal, data)


ALLOWED = ("data/manus", "data/archive", "data/cache", "data/funding",
           "data/company-overview", "web/public")


def publish(root: Path, run_dir: Path, paths: list[str]) -> None:
    entries = []
    for rel in paths:
        if rel not in ALLOWED or not (run_dir / "workspace" / rel).is_dir():
            raise ValueError("候选输出缺失或发布路径不合法")
        for base in (root, run_dir / "workspace", run_dir / "backup"):
            if not (base / rel).resolve().is_relative_to(base.resolve()):
                raise ValueError("发布路径越出工作目录")
        entries.append({"path": rel, "existed": (root / rel).exists()})
    journal = run_dir / "publication.json"
    save(journal, {"status": "pending", "entries": entries})
    try:
        for entry in entries:
            rel = entry["path"]
            target, staged, backup = root / rel, run_dir / "workspace" / rel, run_dir / "backup" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            backup.parent.mkdir(parents=True, exist_ok=True)
            if backup.exists():
                raise ValueError("备份目录已存在，请新建运行")
            if target.exists():
                os.replace(target, backup)
            os.replace(staged, target)
        save(journal, {"status": "committed", "entries": entries})
    except BaseException:
        recover(root, run_dir)
        raise
