"""从快照和 Manus feed 装配全类别文章输入。"""
import json
from datetime import datetime, timezone
from pathlib import Path


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def build_content_index(work_dir: Path | str) -> dict[str, str]:
    index: dict[str, str] = {}
    root = Path(work_dir)
    if not root.exists():
        return index
    for path in sorted(root.glob("**/raw/content-batch-*.json")):
        for item in (_read(path).get("articles") or []):
            url = item.get("article_url")
            text = (item.get("content_text") or "").strip()
            if url and text:
                index[url] = text
    return index


def _display_dims(item: dict, tx: dict, *, feed: bool) -> dict[str, str]:
    if not feed:
        return {d["label"]: d["value"] for d in
                ((item.get("classification") or {}).get("dims") or [])
                if d.get("label") and d.get("value")}
    out = {}
    for dim_id, value_id in ((item.get("classification") or {}).get("tags") or {}).items():
        dim = (tx.get("dimensions") or {}).get(dim_id) or {}
        value = next((v.get("label") for v in dim.get("values", [])
                      if v.get("id") == value_id), None)
        if dim.get("label") and value:
            out[dim["label"]] = value
    return out


def load_articles(snapshot_path: Path | str, feed_path: Path | str,
                  work_dir: Path | str, tx: dict) -> list[dict]:
    """读取所有类别，按 URL（无 URL 时按 id）去重，保留正文或标题摘要。"""
    content_index = build_content_index(work_dir)
    merged: dict[str, dict] = {}

    def add(item: dict, *, feed=False):
        article_id = str(item.get("id") or "").strip()
        url = str(item.get("url") or "").strip()
        if not article_id:
            return
        key = url or article_id
        if key in merged:
            return
        content = content_index.get(url) or "\n\n".join(
            p for p in (item.get("title"), item.get("summary")) if p)
        classification = item.get("classification") or {}
        merged[key] = {
            "id": article_id,
            "title": item.get("title") or "",
            "url": url,
            "sourceName": item.get("mpName") or item.get("source") or "",
            "publishedAt": item.get("publishedAt") or "",
            "category": classification.get("category" if feed else "cat") or item.get("category") or "",
            "dims": _display_dims(item, tx, feed=feed),
            "content_text": content,
        }

    snapshot = _read(Path(snapshot_path))
    for view in (snapshot.get("daily") or {}, snapshot.get("weekly") or {}):
        for section in view.get("sections") or []:
            for item in section.get("items") or []:
                add(item)
    feed = _read(Path(feed_path))
    if feed.get("ok"):
        for item in feed.get("items") or []:
            add(item, feed=True)
    # 模型额度有限时必须优先处理最新文章，否则 weekly 历史会挤占当天情报。
    def published_time(article):
        try:
            dt = datetime.fromisoformat(article["publishedAt"].replace("Z", "+00:00"))
            return dt.timestamp() if dt.tzinfo else dt.replace(tzinfo=timezone.utc).timestamp()
        except (ValueError, TypeError):
            return float("-inf")
    return sorted(merged.values(), key=published_time, reverse=True)


def load_previous(path: Path | str) -> dict:
    data = _read(Path(path))
    return data if data.get("schemaVersion") == 1 else {}
