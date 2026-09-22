"""融资流水线：inputs。"""
import json
from pathlib import Path
from company_index.inputs import selected_snapshot_items


# ================= 输入装配 =================

def _read_snapshot(snapshot_path: Path | str) -> dict:
    snapshot_path = Path(snapshot_path)
    if not snapshot_path.exists():
        return {}
    try:
        with open(snapshot_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _snapshot_pool(snap: dict) -> list[dict]:
    selected = selected_snapshot_items(snap)
    if selected is not None:
        return [it for it in selected
                if (it.get('classification') or {}).get('cat') == 'financing']
    seen: dict[str, dict] = {}
    for view in (snap.get("daily"), snap.get("weekly")):
        for sec in (view or {}).get("sections") or []:
            for it in sec.get("items") or []:
                iid = it.get("id")
                if iid and iid not in seen:
                    seen[iid] = it
    return [it for it in seen.values()
            if (it.get("classification") or {}).get("cat") == "financing"]


def load_snapshot_pool(snapshot_path: Path | str) -> list[dict]:
    """新版仅精选融资；旧快照保留 daily+weekly 的兼容读取。"""
    return _snapshot_pool(_read_snapshot(snapshot_path))


def load_feed_pool(feed_path: Path | str) -> list[dict]:
    """data/manus/current.json → 筛 financing 条目（feed 无效时返回空）。"""
    feed_path = Path(feed_path)
    if not feed_path.exists():
        return []
    try:
        with open(feed_path, "r", encoding="utf-8") as f:
            feed = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if not feed.get("ok"):
        return []
    return [it for it in feed.get("items") or []
            if (it.get("classification") or {}).get("category") == "financing"]


def dims_from_snapshot_item(item: dict) -> dict[str, str]:
    """snapshot 条目 classification.dims [{label,value}] → {label: value}。"""
    out: dict[str, str] = {}
    for d in (item.get("classification") or {}).get("dims") or []:
        if d.get("label") and d.get("value"):
            out[d["label"]] = d["value"]
    return out


def dims_from_feed_item(item: dict, tx: dict) -> dict[str, str]:
    """feed 条目 classification.tags {dimId: valueId} → {维度label: 取值label}。"""
    out: dict[str, str] = {}
    for dim_id, val_id in ((item.get("classification") or {}).get("tags") or {}).items():
        dim = tx.get("dimensions", {}).get(dim_id)
        if not dim:
            continue
        label = next((v["label"] for v in dim["values"] if v["id"] == val_id), None)
        if label:
            out[dim["label"]] = label
    return out


def build_content_index(work_dir: Path | str) -> dict[str, dict]:
    """work/manus/*/raw/content-batch-*.json 全量索引：{article_url: {title, content_text}}。"""
    work_dir = Path(work_dir)
    index: dict[str, dict] = {}
    if not work_dir.exists():
        return index
    for path in sorted(work_dir.glob("*/raw/content-batch-*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                batch = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        for art in batch.get("articles") or []:
            url = art.get("article_url")
            text = (art.get("content_text") or "").strip()
            if url and text and url not in index:
                index[url] = {"title": art.get("title") or "", "content_text": text}
    return index


def to_article_record(item: dict, tx: dict, content_index: dict[str, dict],
                      is_feed: bool) -> dict:
    """统一文章记录：正文优先（work 索引命中 url 或 title），否则退回 title+summary。"""
    url = item.get("url") or ""
    entry = content_index.get(url)
    if not entry:
        title = (item.get("title") or "").strip()
        for v in content_index.values():
            if v["title"] and v["title"] == title:
                entry = v
                break
    content = (entry or {}).get("content_text") or ""
    if not content:
        parts = [item.get("title") or ""]
        if item.get("summary"):
            parts.append(item["summary"])
        content = "\n\n".join(p for p in parts if p)
    return {
        "id": item.get("id") or "",
        "title": item.get("title") or "",
        "url": url,
        "mpName": item.get("mpName") or item.get("source") or "",
        "publishedAt": item.get("publishedAt") or "",
        "dims": dims_from_feed_item(item, tx) if is_feed else dims_from_snapshot_item(item),
        "content_text": content,
        "evidenceKind": item.get("evidenceKind"),
    }


def load_articles(snapshot_path: Path, feed_path: Path, work_dir: Path, tx: dict) -> list[dict]:
    """快照池 + feed 池（按 id 去重，快照优先）→ 统一文章记录列表。"""
    content_index = build_content_index(work_dir)
    merged: dict[str, dict] = {}
    snapshot = _read_snapshot(snapshot_path)
    for it in _snapshot_pool(snapshot):
        if it.get("id") and it["id"] not in merged:
            merged[it["id"]] = to_article_record(it, tx, content_index, is_feed=False)
    feed_items = [] if 'newsSelectionVersion' in snapshot else load_feed_pool(feed_path)
    for it in feed_items:
        if it.get("id") and it["id"] not in merged:
            merged[it["id"]] = to_article_record(it, tx, content_index, is_feed=True)
    return list(merged.values())
