"""只做本地检查，不调用付费接口、不输出密钥。"""
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

from llm_common import load_dotenv


def inspect(root: Path, stages: list[str], target_date: str | None = None, *, ten_am=False,
            require_llm=True) -> list[dict]:
    load_dotenv(root / ".env")
    checks = []

    def check(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    check("Python", sys.version_info >= (3, 10), "需要 Python >= 3.10")
    tx = {}
    for rel in ("config/taxonomy.json", "config/manus_sources.json"):
        try:
            data = json.loads((root / rel).read_text(encoding="utf-8"))
            if "taxonomy" in rel:
                tx = data
                from tag_news import load_taxonomy
                load_taxonomy(str(root / rel))
            else:
                from manus_source.config import load_sources
                groups = load_sources(root / rel)
                if set(groups) != {"group_a", "group_b", "group_c"}:
                    raise ValueError("需要三组配置")
            check(rel, True, "JSON 与业务结构检查通过")
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            check(rel, False, "文件缺失、不可读或结构不合法")
    files = []
    if "discovery" in stages:
        files.append("scripts/prompts/manus_discovery_window.md" if ten_am else "scripts/prompts/manus_discovery.md")
    if "content" in stages:
        files.append("scripts/prompts/manus_content.md")
        mode = os.getenv("MANUS_CONTENT_MODE", "script")
        check("正文模式", mode in ("script", "manus"), "script 或 manus")
        if mode == "script":
            check("trafilatura", importlib.util.find_spec("trafilatura") is not None,
                  "缺少时执行 python -m pip install -r scripts/requirements.txt")
    if "snapshot" in stages:
        files.extend(f"scripts/templates/{name}.template.html" for name in ("index", "history", "weekly"))
    for rel in files:
        check(rel, (root / rel).is_file(), "必要模板/提示词")
    keys = []
    if any(s in stages for s in ("discovery", "content")):
        keys.append("MANUS_API_KEY")  # 现有正文 CLI 的 Settings 也要求 Manus key。
    if require_llm and any(s in stages for s in ("feed", "snapshot", "overview", "funding")):
        keys.append((tx.get("model") or {}).get("api_key_env", "DEEPSEEK_API_KEY"))
    for key in keys:
        value = os.getenv(key, "").strip()
        check(key, value and not value.lower().startswith("your-"), "仅检查配置存在，尚未验证额度或接口可用性")
    if target_date and "discovery" not in stages and any(s in stages for s in ("content", "feed")):
        from build_manus_feed import load_discoveries
        from manus_source.config import load_sources
        try:
            raw = root / "work/manus"
            if ten_am:
                raw = raw / "ten-am"
            discoveries = load_discoveries(raw / target_date / "raw", target_date,
                                          load_sources(root / "config/manus_sources.json"))
            if ten_am:
                from manus_source.window import ten_am_window
                if any(d.get("collectionWindow") != ten_am_window(target_date) for d in discoveries.values()):
                    raise ValueError("窗口不匹配")
            check("前序发现结果", True, "三组结果契约通过")
        except (OSError, ValueError, KeyError, RuntimeError):
            check("前序发现结果", False, "请先运行同日期 discovery 阶段")
    if stages in (["funding"], ["overview"]):
        readable = False
        for rel in ("web/public/snapshot.json", "data/manus/current.json"):
            try:
                data = json.loads((root / rel).read_text(encoding="utf-8"))
                readable |= isinstance(data, dict) and (bool(data.get("ok")) if "manus" in rel else
                            isinstance(data.get("daily"), dict) and isinstance(data.get("weekly"), dict))
            except (OSError, ValueError):
                pass
        check("数据输入池", readable, "至少一份有效快照或 Manus feed")
    for rel in ("work", "data", "web/public"):
        parent = root / rel
        while not parent.exists():
            parent = parent.parent
        try:
            with tempfile.TemporaryFile(dir=parent):
                pass
            check(rel + " 可写", True, "临时文件写入检查通过")
        except OSError:
            check(rel + " 可写", False, "输出目录不可写")
    return checks
