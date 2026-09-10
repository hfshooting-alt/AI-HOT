#!/usr/bin/env python3
"""build_snapshot.py — 抓取 aihot 公开 API，生成 AI HOT 仪表盘静态快照（单文件 HTML）。

用法:
    python3 scripts/build_snapshot.py [--out web/public/index.html]
        [--template scripts/templates/index.template.html]
        [--history-template scripts/templates/history.template.html]
        [--history-dir web/public/history]
        [--archive-dir data/archive] [--archive-days 30]
        [--api-base https://aihot.virxact.com]
        [--manus-json data/manus/current.json]
        [--days 7]

流程:
    1. 分页抓取 /api/v1/items（扁平条目流，天然去重）
    2. 合并 Manus 公众号 feed（data/manus/current.json，只读消费；缺失/损坏/过期时降级）
    3. 历史归档（唯一数据源）：增量并集 upsert 进 data/archive/YYYY-MM-DD.json；
       定稿冻结前天及更早的归档（昨天保留开放，兜住迟到条目）；超 30 天滚动硬删
    4. AIHOT 成品日报按索引实际日期同步；本站周报继续从归档池推导
    5. 按六版块分组、全局连续编号、北京时间人话时间
    6. 用模板渲染主快照 + history/YYYY-MM-DD.html 只读归档页（近 N 天可回溯）

纯标准库实现，Windows / Linux / macOS 均可运行。
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

import tag_news  # 打标签 harness（同目录）
from manus_source import contracts  # Manus feed 契约校验（同目录包）
from manus_source.window import ten_am_window, timestamp, matching_item

MANUS_MAX_STALE_DAYS = 3  # feed targetDate 旧于该窗口视为过期，降级为仅 aihot 数据

# 六版块固定顺序（与前端 SECTION_COLORS 对应）
SECTIONS = ["模型发布/更新", "产品发布/更新", "AI泛娱乐新闻", "行业动态", "论文研究", "技巧与观点"]

# API category -> 六版块
CATEGORY_MAP = {
    "ai-models": "模型发布/更新",
    "ai-products": "产品发布/更新",
    "industry": "行业动态",
    "paper": "论文研究",
    "tip": "技巧与观点",
}

BJ = timezone(timedelta(hours=8), name="Asia/Shanghai")
WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

CN_DIGITS = "〇一二三四五六七八九"


def cn_num(n: int) -> str:
    """1-99 → 中文数字（用于 VOL 期刊号与中文日期）。"""
    if n < 10:
        return CN_DIGITS[n]
    tens, rem = divmod(n, 10)
    if tens == 1:
        return "十" + (CN_DIGITS[rem] if rem else "")
    return CN_DIGITS[tens] + "十" + (CN_DIGITS[rem] if rem else "")


def fmt_cn_date(d: date) -> str:
    """2026-08-14 → 二〇二六年八月十四日（VOL 期刊头用）。"""
    year = "".join(CN_DIGITS[int(c)] for c in str(d.year))
    return f"{year}年{cn_num(d.month)}月{cn_num(d.day)}日"


def week_start_of(d: date) -> date:
    """返回 d 所属自然周的周一（周一起算）。"""
    return d - timedelta(days=d.weekday())


def month_first_monday(d: date) -> date:
    """d 所在月份的第一个周一。"""
    first = d.replace(day=1)
    return first + timedelta(days=(7 - first.weekday()) % 7)


def week_index_of(ws: date) -> int:
    """以周一为起点在月内的序号（当月第一个周一 = 第 1 周）。"""
    return (ws - month_first_monday(ws)).days // 7 + 1


def week_vol_label(ws: date) -> str:
    """自然周期刊号，如「八月第2周」（归属起始周一所在月）。"""
    return f"{cn_num(ws.month)}月第{week_index_of(ws)}周"

MAX_PAGES = 50  # 分页上限（v1 每页 100 条），防止异常游标导致死循环

DEFAULT_ARCHIVE_DAYS = 30  # 历史归档保留天数（滚动硬删）

TAG_TAXONOMY: dict | None = None  # 打标签分类体系（main 中加载，供 build_item 映射 label）

# 公众号文章六版块分类规则（按顺序匹配，命中即归入；兜底「行业动态」）
WECHAT_CATEGORY_RULES = [
    ("模型发布/更新", ["模型", "开源", "权重", "参数", "benchmark", "评测", "GPT", "Qwen", "Kimi", "Claude", "Gemini", "DeepSeek", "GLM", "大模型", "多模态", "tokenizer"]),
    ("论文研究", ["论文", "paper", "arxiv", "SOTA", "研究", "基准测试"]),
    ("AI泛娱乐新闻", ["娱乐", "游戏", "影视", "视频生成", "音乐", "虚拟人", "数字人"]),
    ("产品发布/更新", ["功能", "App", "Agent", "agent", "工具", "平台", "上线", "API", "接入", "助手", "Copilot", "升级", "插件", "组件"]),
    ("行业动态", ["融资", "投资", "估值", "市场", "监管", "政策", "诉讼", "IPO", "营收", "财报", "合作", "战略"]),
]


def classify_wechat(item: dict) -> str:
    """公众号文章按关键词规则归入六版块。"""
    text = ((item.get("title") or "") + " " + (item.get("summary") or "")).lower()
    for label, kws in WECHAT_CATEGORY_RULES:
        if any(k.lower() in text for k in kws):
            return label
    return "技巧与观点"


def norm_url(url: str) -> str:
    """URL 归一化（去 query 参数），用于跨源去重。

    例外：mp.weixin.qq.com 链接不剥 query —— 微信文章的唯一标识在 query 里
    （__biz/mid/sn 或 signature），剥掉后所有文章都变成 "mp.weixin.qq.com/s"，
    任意一条微信链接存在就会误伤拦截全部公众号文章（实测 bug）。
    """
    url = (url or "").rstrip("/").lower()
    if "mp.weixin.qq.com" in url:
        return url
    return url.split("?")[0]


def load_manus_feed(path: str, taxonomy_path: str,
                    max_stale_days: int = MANUS_MAX_STALE_DAYS) -> tuple[list[dict], dict]:
    """只读消费 Manus 规范化 feed（data/manus/current.json）。

    返回 (公众号条目, mp_status)。缺失/损坏/过期/ok=false 时返回空条目与降级状态，
    坏数据绝不进入归档；展示版块仍由现有关键词规则生成，classification 作为语义标签透传。
    """
    def degraded(reason: str) -> tuple[list[dict], dict]:
        return [], {"connected": False, "collector": "manus",
                    "note": f"公众号源不可用（Manus feed {reason}），仅显示 aihot 数据"}

    try:
        with open(path, "r", encoding="utf-8") as f:
            feed = json.load(f)
    except (OSError, json.JSONDecodeError):
        return degraded("缺失或不可读")
    try:
        contracts.validate_feed(feed, taxonomy_path)
    except contracts.ContractError as exc:
        return degraded(f"契约校验失败：{exc}")
    if not feed.get("ok"):
        return degraded("ok=false")
    target = date.fromisoformat(feed["targetDate"])
    age_days = (datetime.now(BJ).date() - target).days
    if age_days > max_stale_days:
        return degraded(f"已过期 {age_days} 天（目标日期 {feed['targetDate']}）")

    out = []
    for it in feed.get("items") or []:
        it = dict(it)
        # 展示版块继续用现有规则（标题+新摘要），避免本次迁移重做信息架构
        it["category"] = classify_wechat(it)
        out.append(it)
    status = {"connected": True, "collector": "manus", "targetDate": feed["targetDate"],
              "degraded": bool(feed.get("degraded")),
              "note": (f"Manus 采集已接入（目标日期 {feed['targetDate']}"
                       + ("，本轮存在来源级失败" if feed.get("degraded") else "")
                       + f"，共 {len(out)} 篇公众号文章）")}
    return out, status


def load_wechat(path: str) -> list[dict]:
    """旧版公众号入口（已停用）：仅为历史兼容保留，生产链路不再调用。"""
    return []


# ================= 历史归档层（P1：可重建条目归档，唯一数据源） =================

def archive_key(item: dict) -> str:
    """归档去重键。

    - aihot 条目用稳定的 API id
    - Manus 公众号条目用其稳定 id（账号+日期+标题哈希，不随镜像/签名 URL 变化）
    - 旧 wechat 条目（早期采集路线，id 为 wechat:* 或无稳定 id）继续用
      （source+标题）做键，兼容已存在的历史归档，不重建不删除
    """
    if item.get("sourceType") == "wechat":
        iid = str(item.get("id") or "")
        if iid.startswith("manus:"):
            return "id:" + iid
        return "wx:" + (item.get("source") or "") + "|" + (item.get("title") or "").strip().lower()
    return "id:" + str(item.get("id") or item.get("permalink") or "")


def _day_file_path(archive_dir: str, date_str: str) -> str:
    return os.path.join(archive_dir, f"{date_str}.json")


def _load_day_file(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _save_day_file(path: str, day: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(day, f, ensure_ascii=False, indent=1)


def upsert_archive(archive_dir: str, items: list[dict], now_bj: datetime) -> None:
    """增量并集：本轮条目按 publishedAt（北京时间）归入对应日期归档文件。

    - 未定稿文件：同键条目整条覆盖（摘要/评分更新时最新赢），归档只增不减
    - 已定稿文件：跳过不写（历史冻结）
    - 同题跨源查重：aihot 自带公众号与外部采集到同一篇时按标题去重
      （跨源 URL 格式不兼容，URL 归一化在此场景无效，标题才可靠）
    """
    os.makedirs(archive_dir, exist_ok=True)
    day_files: dict[str, dict] = {}
    added = 0
    for it in items:
        dt = to_bj(it.get("publishedAt") or "")
        if dt.year < 2020:  # 时间缺失/不可解析的条目不入档
            continue
        date_str = dt.date().isoformat()
        if date_str not in day_files:
            day_files[date_str] = _load_day_file(_day_file_path(archive_dir, date_str)) or {
                "date": date_str, "finalized": False, "finalizedAt": None, "updatedAt": None, "items": [],
            }
        day = day_files[date_str]
        if day.get("finalized"):
            continue
        k = archive_key(it)
        index = {archive_key(x): i for i, x in enumerate(day["items"])}
        title = (it.get("title") or "").strip().lower()
        if k not in index and title and any(
            (x.get("title") or "").strip().lower() == title and archive_key(x) != k for x in day["items"]
        ):
            continue  # 跨源同题重复，跳过
        if k in index:
            day["items"][index[k]] = it  # 定稿前最新覆盖
        else:
            day["items"].append(it)
            added += 1
        day["updatedAt"] = now_bj.isoformat()
    for date_str, day in day_files.items():
        _save_day_file(_day_file_path(archive_dir, date_str), day)
    if added:
        print(f"历史归档：涉及 {len(day_files)} 个日期文件，新增 {added} 条")


def finalize_archive(archive_dir: str, now_bj: datetime) -> int:
    """定稿：冻结「前天」及更早的日期归档（次日定稿 + 一天宽限）。

    昨天保留开放：兜住索引滞后/晚间发布次日才入池的迟到条目，
    避免被定稿锁死而永久丢失。定稿后条目不再变化（为后续 AI 正文等生成物提供冻结基线）。
    """
    if not os.path.isdir(archive_dir):
        return 0
    close_before = (now_bj - timedelta(days=1)).date().isoformat()  # 严格早于昨天的日期才定稿
    n = 0
    for name in sorted(os.listdir(archive_dir)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(archive_dir, name)
        day = _load_day_file(path)
        if not day or day.get("finalized"):
            continue
        if (day.get("date") or name[:-5]) >= close_before:
            continue
        day["finalized"] = True
        day["finalizedAt"] = now_bj.isoformat()
        _save_day_file(path, day)
        n += 1
    if n:
        print(f"历史归档：定稿 {n} 个日期归档（冻结不再变化）")
    return n


def cleanup_archive(archive_dir: str, history_dir: str, now_bj: datetime, keep_days: int) -> list[str]:
    """滚动硬删：删除超期归档文件与对应历史页，返回保留的日期列表（升序）。"""
    cutoff = (now_bj - timedelta(days=keep_days)).date().isoformat()
    kept: list[str] = []
    if os.path.isdir(archive_dir):
        for name in os.listdir(archive_dir):
            if not name.endswith(".json"):
                continue
            date_str = name[:-5]
            if date_str < cutoff:
                try:
                    os.remove(os.path.join(archive_dir, name))
                except OSError:
                    pass
                continue
            kept.append(date_str)
    # 顺带清理无对应归档日的残留历史页
    if os.path.isdir(history_dir):
        for name in os.listdir(history_dir):
            if name.endswith(".html") and name[:-5] not in kept:
                try:
                    os.remove(os.path.join(history_dir, name))
                except OSError:
                    pass
    return sorted(kept)


def load_archive_pool(day_files: dict[str, dict]) -> list[dict]:
    """归档数据池 = 全部保留日期文件条目的并集（按归档键去重），按 publishedAt 降序。"""
    seen: set[str] = set()
    pool: list[dict] = []
    for day in day_files.values():
        for it in day.get("items") or []:
            k = archive_key(it)
            if k in seen:
                continue
            seen.add(k)
            pool.append(it)
    pool.sort(key=lambda i: to_bj(i.get("publishedAt") or ""), reverse=True)
    return pool


def day_nav_entry(day: dict) -> dict:
    """主页历史归档日期导航条目：日期 + 当日头条（评分最高，无评分取最新条目）。"""
    items = sorted(day.get("items") or [], key=lambda i: to_bj(i.get("publishedAt") or ""), reverse=True)
    scored = [i for i in items if isinstance(i.get("score"), (int, float))]
    title = max(scored, key=lambda i: i["score"]).get("title") if scored else (
        items[0].get("title") if items else "")
    d = date.fromisoformat(day["date"])
    return {
        "date": day["date"],
        "label": f"{d.month}月{d.day}日 {WEEKDAYS[d.weekday()]}",
        "title": title or "",
        "total": len(items),
        "finalized": bool(day.get("finalized")),
        "url": f"history/{day['date']}.html",
    }


def tag_archive_days(archive_dir: str, all_days: dict[str, dict], tx: dict, cache_path: str) -> bool:
    """对归档条目（含未定稿的当天条目）批量打标签并写回 classification 字段。

    含补写扫描：历史日期若因 key 缺失/故障未打标，后续轮次自动补齐。
    受控例外：仅追加分类字段，不改条目本体。返回是否有新写回。
    当天条目被下轮 upsert 整条覆盖后 classification 会丢失，但每轮构建都会
    重跑打标（缓存命中，零 LLM 成本），自愈。
    """
    pending: list[dict] = []
    for day in all_days.values():
        for it in day.get("items") or []:
            if not it.get("classification"):
                pending.append(it)
    if not pending:
        return False
    results = tag_news.tag_items(pending, tx, cache_path)
    changed = 0
    for date_str, day in all_days.items():
        dirty = False
        for it in day.get("items") or []:
            if it.get("classification"):
                continue
            r = results.get(tag_news.item_key(it))
            if r:
                it["classification"] = r
                dirty = True
                changed += 1
        if dirty:
            _save_day_file(_day_file_path(archive_dir, date_str), day)
    if changed:
        print(f"AI 打标签：{changed} 条分类结果写回归档")
    return changed > 0


def week_items(all_days: dict[str, dict], ws: date) -> list[dict]:
    """自然周 [ws, ws+7) 内的归档条目并集。"""
    items: list[dict] = []
    for i in range(7):
        day = all_days.get((ws + timedelta(days=i)).isoformat())
        if day:
            items.extend(day.get("items") or [])
    return items


def build_weekly_journals(all_days: dict[str, dict], weekly_dir: str, weekly_template: str,
                          now_bj: datetime, generated_at: datetime, keep: int = 5) -> list[dict]:
    """生成已完结自然周的周期刊（周一起算，归属起始周一所在月）。

    周在次日周一 00:00 后视为完结；保留最新 keep 份，超存的滚动清理。
    返回导航列表（新到旧）：供主页/历史页/周期刊页互链。
    """
    os.makedirs(weekly_dir, exist_ok=True)
    nav: list[dict] = []
    retained: set[str] = set()
    earliest = min(all_days) if all_days else None
    ws = week_start_of(now_bj.date()) - timedelta(days=7)  # 最近的已完结周
    while len(retained) < keep:
        if earliest and (ws + timedelta(days=6)).isoformat() < earliest:
            break  # 整周完全早于归档覆盖范围才停止（周与归档部分重叠时仍可能有数据）
        items = week_items(all_days, ws)
        if items:
            ws0 = datetime.combine(ws, datetime.min.time(), tzinfo=BJ)
            view = build_view("daily", items, datetime.combine(ws + timedelta(days=6), datetime.min.time(), tzinfo=BJ),
                              7, generated_at, {}, time_ref=ws0 + timedelta(days=8))
            vol_label = week_vol_label(ws)
            artifact = {
                "weekStart": ws.isoformat(), "weekEnd": (ws + timedelta(days=7)).isoformat(),
                "volLabel": vol_label, "finalized": True, "generatedAt": generated_at.isoformat(),
                "aiReport": None,  # P2+ 预留：AI 周报正文（冻结生成物）
                "items": items,
            }
            with open(os.path.join(weekly_dir, f"{ws.isoformat()}.json"), "w", encoding="utf-8") as f:
                json.dump(artifact, f, ensure_ascii=False, indent=1)
            wdata = dict(view,
                         vol=f"VOL.{ws.year} · {vol_label}",
                         dateLabel=f"{fmt_date(ws)} 至 {fmt_date(ws + timedelta(days=6))}",
                         cnLabel=f"{fmt_cn_date(ws)} 至 {fmt_cn_date(ws + timedelta(days=6))}",
                         nav=nav)
            render(weekly_template, os.path.join(weekly_dir, f"{ws.isoformat()}.html"), wdata)
            retained.add(ws.isoformat())
            nav.append({"url": f"weekly/{ws.isoformat()}.html",
                        "label": vol_label,
                        "range": f"{ws.month}月{ws.day}日 - {(ws + timedelta(days=6)).month}月{(ws + timedelta(days=6)).day}日",
                        "total": view["total"]})
        ws -= timedelta(days=7)
    # 滚动清理：超存的周期刊文件（json + html）
    for name in os.listdir(weekly_dir):
        stem = name.rsplit(".", 1)[0]
        if name.endswith((".json", ".html")) and stem not in retained:
            try:
                os.remove(os.path.join(weekly_dir, name))
            except OSError:
                pass
    if nav:
        print(f"周期刊：保留 {len(nav)} 份（最新 {nav[0]['label']}）")
    return nav


def week_data_for_date(d: date, all_days: dict[str, dict], now_bj: datetime,
                       generated_at: datetime) -> dict:
    """历史页「本周周报」 tab 的数据：该日所属自然周（已完结则嵌入完整视图）。"""
    ws = week_start_of(d)
    we = ws + timedelta(days=7)
    vol_label = week_vol_label(ws)
    if datetime.combine(we, datetime.min.time(), tzinfo=BJ) > now_bj:
        return {"available": False, "reason": "pending",
                "note": f"本周（{fmt_date(ws)} 起）尚未结束，周报将于 {fmt_date(we)} 周一定稿"}
    items = week_items(all_days, ws)
    if not items:
        return {"available": False, "reason": "missing", "note": "该周无归档数据"}
    ws0 = datetime.combine(ws, datetime.min.time(), tzinfo=BJ)
    view = build_view("daily", items, datetime.combine(ws + timedelta(days=6), datetime.min.time(), tzinfo=BJ),
                      7, generated_at, {}, time_ref=ws0 + timedelta(days=8))
    return {"available": True, "label": vol_label,
            "vol": f"VOL.{ws.year} · {vol_label}",
            "url": f"weekly/{ws.isoformat()}.html",
            "rangeLabel": f"{fmt_date(ws)} 至 {fmt_date(ws + timedelta(days=6))}",
            **view}


def normalize_v1_item(raw: dict) -> dict:
    """把稳定 v1 条目映射到既有归档/前端结构，并保留 canonical 与原文链接。"""
    source = raw.get("source") or {}
    links = raw.get("links") or {}
    published_at = raw.get("publishedAt") or raw.get("discoveredAt") or ""
    return {
        **raw,
        "source": source.get("name") if isinstance(source, dict) else str(source),
        "url": links.get("original") or links.get("aihot") or "",
        "permalink": links.get("aihot") or links.get("original") or "",
        "originalUrl": links.get("original") or "",
        "aihotUrl": links.get("aihot") or "",
        "publishedAt": published_at,
        "discoveredAt": raw.get("discoveredAt") or "",
        "timeBasis": "published" if raw.get("publishedAt") else "discovered",
    }


def is_wechat_item(item: dict) -> bool:
    """识别 AIHOT 或本地归档中的公众号条目。"""
    source = str(item.get("source") or "")
    source_type = str(item.get("sourceType") or "").lower()
    item_id = str(item.get("id") or "")
    urls = " ".join(str(item.get(key) or "") for key in
                    ("url", "permalink", "originalUrl", "aihotUrl"))
    return (source_type == "wechat"
            or source.startswith(("公众号：", "微信公众号"))
            or item_id.startswith(("wechat:", "manus:"))
            or "mp.weixin.qq.com" in urls.lower())


def without_wechat_topics(payload: dict) -> dict:
    """保留 AIHOT 排名，仅移除公众号主条目与信源名。"""
    result = dict(payload)
    topics = []
    for topic in payload.get("items") or []:
        primary = {
            "source": (topic.get("source") or {}).get("name") if isinstance(topic.get("source"), dict)
                      else topic.get("source"),
            "url": (topic.get("links") or {}).get("original"),
        }
        if is_wechat_item(primary):
            continue
        clean = dict(topic)
        clean_names = [name for name in topic.get("sourceNames") or []
                       if not str(name).startswith(("公众号：", "微信公众号"))]
        clean["sourceNames"] = clean_names
        clean["sourceCount"] = len(clean_names)
        topics.append(clean)
    result["items"] = topics
    result["count"] = len(topics)
    return result


def fetch_items(api_base: str, since_bj: datetime, window: str = "7d") -> list[dict]:
    """按 AIHOT 稳定 v1 契约分页抓取公开全量流。"""
    items: list[dict] = []
    cursor = None
    for _ in range(MAX_PAGES):
        params = {"mode": "all", "window": window, "by": "timeline", "limit": "100"}
        if cursor:
            params["cursor"] = cursor
        url = f"{api_base}/api/v1/items?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "User-Agent": "AI-HOT-dashboard/1.0 (+https://github.com/hfshooting-alt/AI-HOT)",
        })
        with urllib.request.urlopen(request, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        batch = data.get("items") or []
        items.extend(normalize_v1_item(item) for item in batch)
        page = data.get("page") or {}
        if not page.get("hasMore") or not page.get("nextCursor"):
            break
        cursor = page["nextCursor"]
    return items


def fetch_hot_topics(api_base: str) -> dict:
    """抓取 AI HOT 热点榜（/api/v1/hot-topics），失败返回空列表结构。"""
    url = f"{api_base}/api/v1/hot-topics"
    try:
        request = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "User-Agent": "AI-HOT-dashboard/1.0 (+https://github.com/hfshooting-alt/AI-HOT)",
        })
        with urllib.request.urlopen(request, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"热点榜抓取失败: {exc}", file=sys.stderr)
        return {"items": []}

    items = data.get("items", [])
    items.sort(key=lambda x: x.get("rank", 9999))
    return {"schemaVersion": data.get("schemaVersion", 1), "count": data.get("count", len(items)), "items": items}


def fetch_latest_daily(api_base: str) -> dict | None:
    """先读日报索引，再按实际日期抓取 AIHOT 成品日报；失败不阻断新闻快照。"""
    headers = {
        "Accept": "application/json",
        "User-Agent": "AI-HOT-dashboard/1.0 (+https://github.com/hfshooting-alt/AI-HOT)",
    }
    try:
        index_url = f"{api_base}/api/v1/dailies?limit=1"
        with urllib.request.urlopen(urllib.request.Request(index_url, headers=headers), timeout=30) as resp:
            index = json.loads(resp.read().decode("utf-8"))
        entries = index.get("items") or []
        daily_date = entries[0].get("date") if entries and isinstance(entries[0], dict) else None
        if not isinstance(daily_date, str):
            raise ValueError("日报索引为空")
        date.fromisoformat(daily_date)
        detail_url = f"{api_base}/api/v1/dailies/{urllib.parse.quote(daily_date)}"
        with urllib.request.urlopen(urllib.request.Request(detail_url, headers=headers), timeout=30) as resp:
            detail = json.loads(resp.read().decode("utf-8"))
        report = detail.get("report")
        if not isinstance(report, dict) or report.get("date") != daily_date \
                or not isinstance(report.get("sections"), list):
            raise ValueError("日报正文契约不合法")
        return report
    except Exception as exc:  # noqa: BLE001 - 日报短暂不可用时保留上次快照
        print(f"AIHOT 日报同步失败，保留已有日报: {exc}", file=sys.stderr)
        return None


def load_daily_reports(snapshot_json: str) -> dict[str, dict]:
    """读取上次快照中已同步的 AIHOT 日报，坏文件按空集合处理。"""
    try:
        with open(snapshot_json, "r", encoding="utf-8") as f:
            raw = json.load(f).get("dailyReports") or {}
        return {key: value for key, value in raw.items()
                if isinstance(key, str) and isinstance(value, dict)
                and value.get("date") == key and isinstance(value.get("sections"), list)}
    except (OSError, ValueError, AttributeError):
        return {}


def daily_report_entry(report: dict) -> dict:
    """将 AIHOT 日报正文转换为前端日期导航项。"""
    report_date = date.fromisoformat(report["date"])
    items = [item for section in report.get("sections") or []
             for item in section.get("items") or [] if isinstance(item, dict)]
    flashes = [item for item in report.get("flashes") or [] if isinstance(item, dict)]
    lead = report.get("lead") if isinstance(report.get("lead"), dict) else {}
    title = lead.get("title") or ((items + flashes)[0].get("title") if items or flashes else "AIHOT 日报")
    return {
        "date": report["date"],
        "label": f"{report_date.month}月{report_date.day}日 {WEEKDAYS[report_date.weekday()]}",
        "title": title,
        "total": len(items) + len(flashes),
        "finalized": True,
        "url": (report.get("links") or {}).get("aihot") or f"https://aihot.news/daily/{report['date']}",
    }


def to_bj(iso: str) -> datetime:
    """ISO8601 -> 北京时间 datetime（无法解析时返回遥远的过去）。"""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(BJ)
    except (ValueError, AttributeError):
        return datetime(2000, 1, 1, tzinfo=BJ)


def fmt_date(d: datetime) -> str:
    return f"{d.year}年{d.month}月{d.day}日 {WEEKDAYS[d.weekday()]}"


def fmt_time_text(dt: datetime, today: datetime) -> str:
    """北京时间人话：今天 HH:MM / 昨天 HH:MM / M/D HH:MM"""
    day_diff = (today.date() - dt.date()).days
    hm = dt.strftime("%H:%M")
    if day_diff == 0:
        return f"今天 {hm}"
    if day_diff == 1:
        return f"昨天 {hm}"
    return f"{dt.month}/{dt.day} {hm}"


def build_item(raw: dict, num: int, today: datetime) -> dict:
    """API item -> 模板 item 结构。category 已是中文六版块时直通。"""
    published = to_bj(raw.get("publishedAt") or "")
    cat = raw.get("category") or ""
    category = cat if cat in SECTIONS else CATEGORY_MAP.get(cat, "行业动态")
    url = raw.get("url") or raw.get("permalink") or ""
    source = raw.get("source") or raw.get("attribution", {}).get("source") or "AI HOT"
    # 修复历史 bug：aihot 数据里 source 以「公众号：」开头的条目应标记为 wechat，
    # 否则前端「仅看公众号」筛选（sourceType===wechat）永远为空
    source_type = raw.get("sourceType") or ("wechat" if str(source).startswith("公众号：") else "aihot")
    # 稳定 id 直通：旧 wechat:*（早期采集）与新 manus:*（Manus 信源）都不加 aihot: 前缀
    raw_id = str(raw.get("id") or "")
    item_id = raw.get("id") if raw_id.startswith(("wechat:", "manus:")) else f"aihot:{raw.get('id')}"
    return {
        "id": item_id,
        "title": raw.get("title") or "",
        "summary": raw.get("summary") or "",
        "url": url,
        "source": source,
        "sourceType": source_type,
        "category": category,
        "categoryUnclassified": not bool(raw.get("category")),
        "publishedAt": raw.get("publishedAt") or "",
        "discoveredAt": raw.get("discoveredAt") or "",
        "timeBasis": raw.get("timeBasis") or ("published" if raw.get("publishedAt") else "discovered"),
        "score": raw.get("score") if isinstance(raw.get("score"), (int, float)) else None,
        "selected": bool(raw.get("selected")) if "selected" in raw else None,
        "aihotUrl": raw.get("aihotUrl") or raw.get("permalink") or "",
        "originalUrl": raw.get("originalUrl") or raw.get("url") or "",
        "reason": raw.get("reason") if isinstance(raw.get("reason"), str) else None,
        "mpName": raw.get("mpName") if "mpName" in raw else None,
        # AI 两级分类结果（id → label 展示结构）；未打标条目为 None，前端自然隐藏徽章
        "classification": (tag_news.to_display(TAG_TAXONOMY, raw["classification"])
                           if TAG_TAXONOMY and raw.get("classification") else None),
        "num": num,
        "timeText": fmt_time_text(published, today),
    }


def group_sections(items: list[dict]) -> list[dict]:
    """按六版块固定顺序分组。"""
    grouped = {s: [] for s in SECTIONS}
    for it in items:
        grouped.setdefault(it["category"], []).append(it)
    return [
        {"label": s, "count": len(grouped[s]), "items": grouped[s]}
        for s in SECTIONS
    ]


def format_items(items: list[dict], today: datetime, time_ref: datetime | None = None) -> list[dict]:
    """将原始条目列表格式化为前端消费的结构（带 timeText / num）。"""
    ref = time_ref or today
    return [build_item(it, idx + 1, ref) for idx, it in enumerate(items)]


def build_daily_nav(all_days: dict[str, dict], weekly_nav: list[dict], time_ref: datetime) -> list[dict]:
    """按月份组织日报/周报导航，并附带格式化后的条目列表。

    返回 [{month, label, daily:[...], weekly:[...]}]，月份从新到旧。
    """
    months: dict[str, dict] = {}
    # 日报：按月份分组
    for date_str, day in sorted(all_days.items(), reverse=True):
        month_key = date_str[:7]
        if month_key not in months:
            months[month_key] = {
                "month": month_key,
                "label": f"{date_str[:4]} 年 {int(date_str[5:7])} 月",
                "daily": [],
                "weekly": [],
            }
        d = date.fromisoformat(date_str)
        raw_items = sorted(day.get("items") or [], key=lambda i: to_bj(i.get("publishedAt") or ""), reverse=True)
        items = format_items(raw_items, time_ref)
        months[month_key]["daily"].append({
            "date": date_str,
            "label": f"{d.month}月{d.day}日 {WEEKDAYS[d.weekday()]}",
            "title": raw_items[0].get("title") if raw_items else "",
            "total": len(raw_items),
            "finalized": bool(day.get("finalized")),
            "url": f"history/{date_str}.html",
            "items": items,
        })
    # 周报：按月份分组
    for w in weekly_nav:
        url = w.get("url") or ""
        week_start_str = url.split("/")[-1].split(".")[0]
        try:
            ws = date.fromisoformat(week_start_str)
        except ValueError:
            continue
        month_key = ws.isoformat()[:7]
        if month_key not in months:
            months[month_key] = {
                "month": month_key,
                "label": f"{ws.year} 年 {ws.month} 月",
                "daily": [],
                "weekly": [],
            }
        raw_items = sorted(week_items(all_days, ws), key=lambda i: to_bj(i.get("publishedAt") or ""), reverse=True)
        items = format_items(raw_items, time_ref)
        months[month_key]["weekly"].append({
            "url": url,
            "label": w.get("label") or "",
            "range": w.get("range") or "",
            "total": w.get("total") or 0,
            "items": items,
        })
    return sorted(months.values(), key=lambda m: m["month"], reverse=True)


def build_view(view: str, items: list[dict], day: datetime, days: int, generated_at: datetime, mp_status: dict,
               time_ref: datetime | None = None, end: datetime | None = None) -> dict:
    """组装 daily / weekly 视图。items 需已按 publishedAt 降序。

    day: 视图锚点日（当天 00:00 北京时间）；窗口起点 = day - (days-1) 天
    end: 窗口右边界，默认 day+1 天（完整自然日）；日报传生成时刻实现「昨天 00:00 至今」
    time_ref: 「今天/昨天」标签参照时刻，默认锚点日；传生成时刻让标签相对真实今天
    """
    start = day - timedelta(days=days - 1)
    end = end or (day + timedelta(days=1))
    ref = time_ref or day
    raw = [i for i in items if start <= to_bj(i.get("publishedAt") or "") < end]
    raw.sort(key=lambda i: to_bj(i.get("publishedAt") or ""), reverse=True)
    converted = [build_item(it, idx + 1, ref) for idx, it in enumerate(raw)]
    sections = group_sections(converted)
    # 今日头条：日报取评分最高的一条（公众号文章无评分，不参与竞争）
    scored = [it for it in converted if isinstance(it.get("score"), (int, float))]
    lead = max(scored, key=lambda it: it["score"])["title"] if view == "daily" and scored else None
    return {
        "view": view,
        "range": {
            "start": start.date().isoformat(),
            "end": day.date().isoformat(),
            "label": f"{fmt_date(start)} 至 {fmt_date(day)}" if start.date() != day.date() else fmt_date(day),
        },
        "total": len(converted),
        "lead": lead,
        "sections": sections,
        "stats": [{"label": s["label"], "count": s["count"]} for s in sections],
        "mpStatus": mp_status,
        "generatedAt": generated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def render(template_path: str, out_path: str, data: dict) -> None:
    """读模板，替换 DATA 占位符，输出快照 HTML。"""
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()
    json_str = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # 注意：不能用 re.sub 替换，替换串里的 \n 会被 re 解释成换行；用 str.replace 最安全
    placeholder = "const DATA = __DATA__;"
    if placeholder not in html:
        raise RuntimeError(f"模板中未找到 DATA 占位符（{template_path}）")
    new_html = html.replace(placeholder, f"const DATA = {json_str};", 1)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(new_html)
    print(f"已生成 {out_path}（{len(new_html)} 字节）")


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 AI HOT 仪表盘静态快照")
    parser.add_argument("--out", default="web/public/index.html")
    parser.add_argument("--snapshot-json", default="web/public/snapshot.json",
                        help="新版前端消费的 JSON 数据快照（与 HTML 快照同源同构）")
    parser.add_argument("--template", default="scripts/templates/index.template.html")
    parser.add_argument("--history-template", default="scripts/templates/history.template.html",
                        help="历史归档只读页模板")
    parser.add_argument("--history-dir", default="web/public/history",
                        help="历史归档页输出目录（按天一页）")
    parser.add_argument("--weekly-template", default="scripts/templates/weekly.template.html",
                        help="自然周期刊页模板")
    parser.add_argument("--weekly-dir", default="web/public/weekly",
                        help="周期刊输出目录（按周起始日一页）")
    parser.add_argument("--weekly-keep", type=int, default=5,
                        help="周期刊存量上限（默认 5 份，超存滚动清理）")
    parser.add_argument("--archive-dir", default="data/archive",
                        help="历史归档目录（按日 JSON，唯一数据源）")
    parser.add_argument("--archive-days", type=int, default=DEFAULT_ARCHIVE_DAYS,
                        help="历史归档保留天数（默认 30，滚动硬删）")
    parser.add_argument("--api-base", default="https://aihot.virxact.com")
    parser.add_argument("--api-window", choices=("24h", "7d"), default="7d",
                        help="AIHOT v1 滚动窗口；本地候选预览推荐 24h")
    parser.add_argument("--manus-json", default="data/manus/current.json",
                        help="Manus 规范化 feed（只读消费；缺失/损坏/过期时降级为仅 aihot 数据）")
    parser.add_argument("--manus-max-stale-days", type=int, default=MANUS_MAX_STALE_DAYS,
                        help=f"Manus feed 允许的最大滞后天数（默认 {MANUS_MAX_STALE_DAYS}）")
    parser.add_argument("--days", type=int, default=7, help="周报窗口天数（默认 7）")
    parser.add_argument("--taxonomy", default="config/taxonomy.json",
                        help="AI 打标签分类体系配置（缺失时跳过打标）")
    parser.add_argument("--tag-cache", default="data/cache/tag_cache.json",
                        help="打标签结果缓存（键含 taxonomy/prompt/模型版本）")
    parser.add_argument("--no-tags", action="store_true",
                        help="跳过 AI 打标签（本地调试无 key 时用）")
    parser.add_argument("--exclude-wechat", action="store_true",
                        help="排除 AIHOT 与本地归档中的公众号内容，并跳过 Manus feed")
    parser.add_argument("--window-date", help="只采集此前一日十点至此日十点的新增新闻；AIHOT 成品日报独立同步")
    args = parser.parse_args()

    now_bj = datetime.now(BJ)
    window = ten_am_window(args.window_date) if args.window_date else None
    window_start = timestamp(window["start"]) if window else None
    window_end = timestamp(window["end"]) if window else None
    try:
        items = fetch_items(args.api_base, window_start or now_bj - timedelta(days=args.days + 2), args.api_window)
    except Exception as exc:  # noqa: BLE001 - 抓取失败给出可读错误
        print(f"抓取失败: {exc}", file=sys.stderr)
        return 1
    if not items:
        print("抓取结果为空，放弃生成", file=sys.stderr)
        return 1
    if args.exclude_wechat:
        before = len(items)
        items = [item for item in items if not is_wechat_item(item)]
        print(f"公众号过滤：AIHOT 抓取结果移除 {before - len(items)} 条，保留 {len(items)} 条非公众号内容")
        if not items:
            print("排除公众号后抓取结果为空，放弃生成", file=sys.stderr)
            return 1

    # 按 publishedAt 降序，去重（同 id 保留最新）
    items.sort(key=lambda i: to_bj(i.get("publishedAt") or ""), reverse=True)
    seen: set[str] = set()
    deduped = []
    for i in items:
        key = i.get("id") or i.get("permalink") or ""
        if key in seen:
            continue
        seen.add(key)
        deduped.append(i)
    items = deduped

    # 合并 Manus 公众号 feed：只读最近一次成功文件，不调用不等待 Manus；
    # 保留标题与 URL 去重，feed 自带 summary/classification，本脚本不覆盖
    if args.exclude_wechat:
        wechat_items = []
        mp_status = {"connected": False, "collector": "excluded", "degraded": False,
                     "note": "本次仅使用 AIHOT 非公众号信源；公众号来源已按配置排除"}
    else:
        wechat_items, mp_status = load_manus_feed(args.manus_json, args.taxonomy,
                                                  args.manus_max_stale_days)
    if wechat_items:
        seen_urls = {norm_url(i.get("url") or i.get("permalink") or "") for i in items}
        seen_titles = {(i.get("title") or "").strip().lower() for i in items}
        merged = 0
        for w in wechat_items:
            if norm_url(w.get("url") or "") in seen_urls:
                continue
            if (w.get("title") or "").strip().lower() in seen_titles:
                continue
            items.append(w)
            merged += 1
        items.sort(key=lambda i: to_bj(i.get("publishedAt") or ""), reverse=True)
        print(f"Manus 公众号源：feed 共 {len(wechat_items)} 条，去重后合并 {merged} 条")
        mp_status["note"] = (mp_status["note"].rstrip("）")
                             + f"，去重后合并 {merged} 条新文章）")
    elif mp_status.get("connected"):
        # feed 有效但无条目可合并（当天无文章或全部重复）：仍属已接入
        print("Manus 公众号源：feed 有效，本次无新增条目")
    else:
        print(f"Manus 公众号源降级：{mp_status['note']}", file=sys.stderr)

    if window:
        # 分页响应可能越过边界；只入库明确处于固定窗口内的新文章。
        items = [i for i in items if matching_item(window, i)]

    # ---- 历史归档：增量并集 upsert → 定稿冻结 → 滚动硬删 ----
    upsert_archive(args.archive_dir, items, now_bj)
    finalized_n = finalize_archive(args.archive_dir, now_bj)
    kept_dates = cleanup_archive(args.archive_dir, args.history_dir, now_bj, args.archive_days)
    all_days: dict[str, dict] = {}
    for date_str in kept_dates:
        day = _load_day_file(_day_file_path(args.archive_dir, date_str))
        if day:
            if args.exclude_wechat:
                day = dict(day)
                day["items"] = [item for item in day.get("items") or [] if not is_wechat_item(item)]
            all_days[date_str] = day

    # 归档为唯一数据源：主页与历史页从同一池推导，天然一致
    items = load_archive_pool(all_days)
    if not items:
        print("归档数据池为空，放弃生成", file=sys.stderr)
        return 1

    # ---- AI 打标签：定稿日条目批量打标（缓存优先、失败降级、不阻断发布） ----
    # taxonomy 同时供 build_item 的 classification 展示映射：即使 --no-tags，
    # Manus feed 自带的分类标签也要能渲染成中文徽章
    global TAG_TAXONOMY
    tx = None
    try:
        tx = tag_news.load_taxonomy(args.taxonomy)
        TAG_TAXONOMY = tx
    except Exception as exc:  # noqa: BLE001 - taxonomy 缺失时静默降级
        print(f"taxonomy 加载失败（跳过分类展示与打标）: {exc}", file=sys.stderr)
    if tx and not args.no_tags:
        try:
            if os.environ.get(tx["model"]["api_key_env"]):
                if tag_archive_days(args.archive_dir, all_days, tx, args.tag_cache):
                    # 分类已写回归档文件，重载使后续视图/历史页/周期刊都带上标签
                    for date_str in list(all_days):
                        day = _load_day_file(_day_file_path(args.archive_dir, date_str))
                        if day:
                            all_days[date_str] = day
                    items = load_archive_pool(all_days)
            else:
                print(f"AI 打标签跳过：未配置 {tx['model']['api_key_env']}")
        except Exception as exc:  # noqa: BLE001 - 打标签失败静默降级
            print(f"AI 打标签失败（不阻断发布）: {exc}", file=sys.stderr)

    generated_at = datetime.now(timezone.utc)
    report_ref = window_end or now_bj
    if window:
        items = [i for i in items if to_bj(i.get("publishedAt") or "") < window_end]
    today_start = datetime.combine(now_bj.date(), datetime.min.time(), tzinfo=BJ)

    # 周期刊：已完结自然周生成/保留/清理（周一起算，归属起始周一所在月）
    weekly_nav = build_weekly_journals(all_days, args.weekly_dir, args.weekly_template,
                                       now_bj, generated_at, keep=args.weekly_keep)

    # 主页周报 = 当前进行中的自然周（周一起至今，实时更新；完结周转入周期刊）
    this_ws = week_start_of(report_ref.date())
    this_ws0 = datetime.combine(this_ws, datetime.min.time(), tzinfo=BJ)
    weekly_view = build_view("weekly", items, this_ws0, 1, generated_at, mp_status,
                             time_ref=now_bj, end=report_ref)
    weekly_view["range"]["label"] = f"{fmt_date(this_ws)} 至今"
    weekly_view["vol"] = f"VOL.{this_ws.year} · {week_vol_label(this_ws)}"
    weekly_view["range"]["cnLabel"] = f"{fmt_cn_date(this_ws)} {WEEKDAYS[this_ws.weekday()]} 至今 · 本周进行中"

    daily_view = build_view("daily", items, today_start, 2, generated_at, mp_status,
                            time_ref=now_bj, end=now_bj)
    daily_view["vol"] = f"VOL.{now_bj.year}-{now_bj.month:02d}-{now_bj.day:02d}"
    daily_view["range"]["cnLabel"] = fmt_cn_date(now_bj.date()) + " " + WEEKDAYS[now_bj.weekday()]
    if window:
        daily_view = build_view("daily", [i for i in items if matching_item(window, i)],
                                window_start, 1, generated_at, mp_status, time_ref=now_bj, end=window_end)
        label = f"{fmt_cn_date(window_start.date())} 十点 至 {fmt_cn_date(window_end.date())} 十点"
        daily_view["range"].update(start=window_start.date().isoformat(), end=window_end.date().isoformat(),
                                    label=label, cnLabel=label, startAt=window["start"], endAt=window["end"])
        daily_view["vol"] = f"VOL.{window_end.year}-{window_end.month:02d}-{window_end.day:02d}"

    # 新版前端字段：全部 AI 动态 / 热点榜 / 日报周报导航 / 分类标签
    # 定时十点快照应完整展示该 24 小时窗口；非窗口构建沿用旧版 200 条上限，
    # 避免把整个历史归档一次性塞进前端。
    current_items = [i for i in items if matching_item(window, i)] if window else items[:200]
    all_pool = format_items(current_items, now_bj)
    category_counts: dict[str, int] = {}
    for it in all_pool:
        category_counts[it["category"]] = category_counts.get(it["category"], 0) + 1
    all_tags = [{"tag": cat, "count": category_counts.get(cat, 0)} for cat in SECTIONS if category_counts.get(cat, 0) > 0]

    # AIHOT 每日约 08:00 产出成品日报；十点流水线只同步，不再把本站新闻窗口冒充日报。
    daily_reports = load_daily_reports(args.snapshot_json)
    latest_daily = fetch_latest_daily(args.api_base)
    if latest_daily:
        daily_reports[latest_daily["date"]] = latest_daily
    daily_reports = dict(sorted(daily_reports.items(), reverse=True)[:31])
    daily_history = [daily_report_entry(report) for report in daily_reports.values()]
    hot_topics = fetch_hot_topics(args.api_base)
    if args.exclude_wechat:
        hot_topics = without_wechat_topics(hot_topics)

    data = {
        **({"collectionWindow": window} if window else {}),
        # 兼容旧模板的数据视图；新版“AI 日报”页面使用 dailyReports/dailyHistory。
        "daily": daily_view,
        # 周报：当前进行中的自然周（口径与周期刊统一）
        "weekly": weekly_view,
        # 历史归档日期导航（新到旧）+ 周期刊导航
        "history": [day_nav_entry(all_days[d]) for d in sorted(all_days, reverse=True)],
        "dailyHistory": daily_history,
        "dailyReports": daily_reports,
        "weeklyNav": weekly_nav,
        # 新版单页前端字段
        "hot": hot_topics,
        "all": {"items": all_pool, "tags": all_tags, "live": True},
        "dailyNav": build_daily_nav(all_days, weekly_nav, now_bj),
        "categories": ["模型", "产品", "行业", "论文", "教程", "观点"],
    }
    render(args.template, args.out, data)

    # JSON 数据快照：新版前端（Next.js 页面）直接消费，结构与 HTML 内嵌 DATA 完全一致
    os.makedirs(os.path.dirname(args.snapshot_json) or ".", exist_ok=True)
    with open(args.snapshot_json, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"已生成 {args.snapshot_json}")

    # ---- 历史页：每个保留归档日渲染一页只读精简版（日报 + 本周周报双 tab） ----
    os.makedirs(args.history_dir, exist_ok=True)
    nav_list = data["history"]
    for date_str in sorted(all_days):
        day = all_days[date_str]
        day0 = datetime.combine(date.fromisoformat(date_str), datetime.min.time(), tzinfo=BJ)
        # time_ref=day+2：让全部时间显示为绝对「M/D HH:MM」，避免历史页出现误导的「今天/昨天」
        view = build_view("daily", day.get("items") or [], day0, 1, generated_at, {},
                          time_ref=day0 + timedelta(days=2))
        hdata = dict(view,
                     vol=f"VOL.{date_str.replace('-', '.')}",
                     dateLabel=fmt_date(day0),
                     cnLabel=fmt_cn_date(day0.date()) + " " + WEEKDAYS[day0.weekday()],
                     finalized=bool(day.get("finalized")), finalizedAt=day.get("finalizedAt"),
                     nav=nav_list,
                     weekData=week_data_for_date(day0.date(), all_days, now_bj, generated_at))
        render(args.history_template, os.path.join(args.history_dir, f"{date_str}.html"), hdata)
    print(f"历史归档：保留 {len(all_days)} 天（本次定稿 {finalized_n} 天），历史页已输出至 {args.history_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
