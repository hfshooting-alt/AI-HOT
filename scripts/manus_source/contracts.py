"""contracts.py — Manus 信源三份数据契约的本地严格校验（纯标准库，离线可测）。

契约对象（详见 docs/2026-08-17-manus-only-source-migration-plan.md §2）：
  1. 发现结果（schema v2）：source_audits 从结构上区分“来源成功但当天无文章”与“来源采集失败”
  2. 正文批次结果：本地门槛（最小长度/风控页特征/URL-标题-日期一致性），失败不进入模型加工
  3. 规范化 feed（data/manus/current.json）：必填字段、枚举、stats 自洽、classification 合法、无全文

校验失败一律抛 ContractError；调用方决定降级与告警，不得静默吞掉。
"""
import hashlib
import json
import re
from datetime import date, datetime
from .window import ten_am_window, contains, timestamp

DISCOVERY_SCHEMA_VERSION = 2
WINDOW_DISCOVERY_SCHEMA_VERSION = 3
FEED_SCHEMA_VERSION = 2
SUPPORTED_FEED_SCHEMA_VERSIONS = (1, 2)
MIN_CONTENT_CHARS = 100          # 正文最小长度门槛（可被上层配置覆盖）
CONTENT_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
# 风控/验证页特征：正文过短且命中特征词时判为风控页而非普通短文
RISK_PAGE_MARKERS = ("安全验证", "验证码", "访问人数过多", "环境异常", "请登录", "扫码登录")

FEED_ITEM_REQUIRED_FIELDS = (
    "id", "title", "summary", "url", "source", "sourceType", "collector",
    "mpName", "publishedAt", "publishedPrecision", "contentSha256",
    "enrichmentStatus", "classification",
)
FEED_ENRICHMENT_STATUSES = ("complete", "fallback")


class ContractError(ValueError):
    """数据契约校验失败。消息必须可用于 Action summary 与告警 Issue。"""


# ================= 稳定 ID 与标题归一化 =================

def norm_title(title: str) -> str:
    """标题归一化：压缩全部空白 + 小写。用于稳定 ID 与跨源标题去重。"""
    return " ".join((title or "").split()).lower()


def stable_article_id(account_name: str, published_date: str, title: str) -> str:
    """稳定文章 ID：账号规范名 + 发布日期 + 归一化标题的哈希。

    不依赖可能变化的镜像/签名 URL；同账号同日期同标题跨镜像必然同 ID。
    """
    raw = f"{(account_name or '').strip()}|{published_date}|{norm_title(title)}"
    return "manus:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ================= 契约 1：发现结果 =================

def validate_discovery(payload: dict, expected_group: str, target_date: str,
                       expected_accounts: list[str]) -> list[dict]:
    """校验一组 Manus 发现结果；通过时返回其中的 complete 文章列表。"""
    if not isinstance(payload, dict):
        raise ContractError("发现结果不是 JSON 对象")
    for field in ("schema_version", "source_group", "target_date", "source_audits", "articles"):
        if field not in payload:
            raise ContractError(f"发现结果缺少必填字段：{field}")
    window = payload.get("collectionWindow")
    version = WINDOW_DISCOVERY_SCHEMA_VERSION if window else DISCOVERY_SCHEMA_VERSION
    if window is not None and window != ten_am_window(target_date):
        raise ContractError("发现结果 collectionWindow 与目标日十点窗口不一致")
    if payload["schema_version"] != version:
        raise ContractError(f"发现结果 schema_version 应为 {version}，"
                            f"实际 {payload['schema_version']!r}")
    if payload["source_group"] != expected_group:
        raise ContractError(f"发现结果 source_group 不匹配：期望 {expected_group}，"
                            f"实际 {payload['source_group']!r}")
    if payload["target_date"] != target_date:
        raise ContractError(f"发现结果 target_date 不匹配：期望 {target_date}，"
                            f"实际 {payload['target_date']!r}")
    if not isinstance(payload["articles"], list):
        raise ContractError("发现结果 articles 不是数组")

    audits = payload["source_audits"]
    if not isinstance(audits, list):
        raise ContractError("source_audits 不是数组")
    seen = set()
    for audit in audits:
        name = audit.get("account_name")
        if not name:
            raise ContractError("source_audits 存在无账号名的记录")
        if name in seen:
            raise ContractError(f"source_audits 中账号 {name} 重复出现")
        seen.add(name)
        if name not in expected_accounts:
            raise ContractError(f"source_audits 出现未配置账号：{name}")
        status = audit.get("source_status")
        if status not in ("complete", "failed"):
            raise ContractError(f"账号 {name} 的 source_status 非法：{status!r}")
        if status == "failed" and not audit.get("note"):
            raise ContractError(f"账号 {name} 来源失败但缺少失败原因 note")
    missing = set(expected_accounts) - seen
    if missing:
        raise ContractError(f"source_audits 缺少账号审计结果：{sorted(missing)}")

    complete: list[dict] = []
    per_account_complete = {name: 0 for name in expected_accounts}
    for art in payload["articles"]:
        status = art.get("extraction_status")
        if status not in ("complete", "failed"):
            raise ContractError(f"文章 extraction_status 非法：{status!r}")
        account = art.get("account_name") or ""
        if status == "complete":
            if account not in expected_accounts:
                raise ContractError(f"complete 文章来自未配置账号：{account!r}")
            if not (art.get("article_url") or "").strip():
                raise ContractError(f"账号 {account} 的 complete 文章缺少 article_url")
            if not (art.get("title") or "").strip():
                raise ContractError(f"账号 {account} 的 complete 文章缺少 title")
            if window:
                try:
                    if not contains(window, art.get("published_at")):
                        raise ValueError("不在窗口内")
                    if timestamp(art["published_at"]).date().isoformat() != art.get("published_date"):
                        raise ValueError("日期与时间不一致")
                except (ValueError, TypeError) as exc:
                    raise ContractError(f"账号 {account} 发布时间不合法或不在十点窗口内") from exc
            elif art.get("published_date") != target_date:
                raise ContractError(f"账号 {account} 的 complete 文章日期 {art.get('published_date')!r} "
                                    f"与请求日期 {target_date} 不匹配")
            per_account_complete[account] += 1
            complete.append(art)
        else:
            for field in ("article_url", "title", "published_date", "author", *(["published_at"] if window else [])):
                if art.get(field) is not None:
                    raise ContractError(f"账号 {account} 的 failed 记录字段 {field} 必须为 null")
            if not art.get("note"):
                raise ContractError(f"账号 {account} 的 failed 记录缺少失败原因 note")

    for audit in audits:
        name = audit["account_name"]
        want = audit.get("article_count")
        got = per_account_complete.get(name, 0)
        if audit.get("source_status") == "failed":
            if want != 0 or got != 0:
                raise ContractError(f"失败账号 {name} 不应有 complete 文章或 article_count")
        elif want != got:
            raise ContractError(f"账号 {name} 审计 article_count={want} 与实际 complete 文章数 {got} 不一致")
    return complete


def find_duplicate_urls(articles: list[dict]) -> dict[str, list[str]]:
    """检测跨镜像重复 URL：返回 {url: [账号名...]}，仅含被 2+ 账号共享的 URL。"""
    holders: dict[str, list[str]] = {}
    for art in articles:
        url = (art.get("article_url") or "").strip()
        if not url:
            continue
        holders.setdefault(url, [])
        name = art.get("account_name") or ""
        if name not in holders[url]:
            holders[url].append(name)
    return {url: sorted(names) for url, names in holders.items() if len(names) > 1}


# ================= 契约 2：正文批次结果 =================

def _is_risk_page(text: str) -> bool:
    return len(text) < 200 and any(m in text for m in RISK_PAGE_MARKERS)


def validate_content_batch(batch: dict, target_date: str,
                           expected_titles: dict[str, str] | None = None,
                           min_content_chars: int = MIN_CONTENT_CHARS,
                           expected_dates: dict[str, str] | None = None) -> tuple[list[dict], list[dict]]:
    """校验正文批次；返回 (可加工文章, 失败记录[{article_url, account_name, reason}])。

    expected_titles：发现阶段记录的 {article_url: title}，用于拦截跳转漂移。
    批次级结构错误（缺字段/日期不匹配）抛 ContractError；单篇正文问题进失败记录。
    """
    if not isinstance(batch, dict) or not isinstance(batch.get("articles"), list):
        raise ContractError("正文批次缺少 articles 数组")
    if batch.get("target_date") != target_date:
        raise ContractError(f"正文批次 target_date 不匹配：期望 {target_date}，实际 {batch.get('target_date')!r}")
    expected_titles = expected_titles or {}

    ok: list[dict] = []
    failed: list[dict] = []
    for art in batch["articles"]:
        url = art.get("article_url") or ""
        account = art.get("account_name") or ""

        def fail(reason: str):
            failed.append({"article_url": url, "account_name": account, "reason": reason})

        if art.get("content_status") == "failed":
            fail(art.get("note") or "正文提取失败")
            continue
        if art.get("content_status") != "complete":
            fail(f"content_status 非法：{art.get('content_status')!r}")
            continue
        expected_date = expected_dates.get(url) if expected_dates is not None else target_date
        if expected_date is None or art.get("published_date") != expected_date:
            raise ContractError(f"正文批次中 {account} 的日期 {art.get('published_date')!r} "
                                f"与目标日期 {target_date} 不匹配")
        text = (art.get("content_text") or "").strip()
        if _is_risk_page(text):
            fail("页面返回验证码/风控页，未获得正文")
            continue
        want_title = expected_titles.get(url)
        if want_title is not None and norm_title(want_title) != norm_title(art.get("title") or ""):
            fail("正文标题与发现阶段记录不一致（跳转漂移）")
            continue
        if len(text) < min_content_chars:
            fail(f"正文过短（{len(text)} < {min_content_chars} 字符）")
            continue
        ok.append(art)
    return ok, failed


def content_sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


# ================= 契约 3：规范化 feed =================

def _load_taxonomy(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _validate_classification(tx: dict, cls: dict, ctx: str) -> None:
    cats = {c["id"]: c for c in tx["categories"]}
    cat = cls.get("category")
    if cat not in cats:
        raise ContractError(f"{ctx} classification.category 非法：{cat!r}")
    tags = cls.get("tags")
    if not isinstance(tags, dict):
        raise ContractError(f"{ctx} classification.tags 不是对象")
    dims = cats[cat].get("dims", [])
    if set(tags.keys()) != set(dims):
        raise ContractError(f"{ctx} tags 维度与类别 {cat} 绑定不一致：{sorted(tags.keys())}")
    for dim_id in dims:
        valid = {v["id"] for v in tx["dimensions"][dim_id]["values"]}
        if tags[dim_id] not in valid:
            raise ContractError(f"{ctx} tags[{dim_id}] 取值非法：{tags[dim_id]!r}")
    if not isinstance(cls.get("autoFallback"), bool):
        raise ContractError(f"{ctx} classification.autoFallback 必须为布尔值")


def validate_feed(feed: dict, taxonomy_path: str) -> None:
    """校验 data/manus/current.json；任何违规抛 ContractError。通过即代表可安全消费。"""
    if not isinstance(feed, dict):
        raise ContractError("feed 不是 JSON 对象")
    for field in ("schemaVersion", "targetDate", "generatedAt", "collector",
                  "ok", "degraded", "stats", "items"):
        if field not in feed:
            raise ContractError(f"feed 缺少必填字段：{field}")
    if feed["schemaVersion"] not in SUPPORTED_FEED_SCHEMA_VERSIONS:
        raise ContractError(f"feed schemaVersion 不受支持：{feed['schemaVersion']!r}")
    if feed["collector"] != "manus":
        raise ContractError(f"feed collector 应为 manus，实际 {feed['collector']!r}")
    if not isinstance(feed["ok"], bool) or not isinstance(feed["degraded"], bool):
        raise ContractError("feed ok/degraded 必须为布尔值")
    try:
        date.fromisoformat(feed["targetDate"])
    except (TypeError, ValueError) as exc:
        raise ContractError(f"feed targetDate 非法：{feed['targetDate']!r}") from exc
    try:
        datetime.fromisoformat(feed["generatedAt"])
    except (TypeError, ValueError) as exc:
        raise ContractError(f"feed generatedAt 非法：{feed['generatedAt']!r}") from exc

    items = feed["items"]
    if not isinstance(items, list):
        raise ContractError("feed items 不是数组")
    stats = feed["stats"]
    if not isinstance(stats, dict):
        raise ContractError("feed stats 不是对象")

    if not feed["ok"] and items:
        raise ContractError("ok=false 的 feed 不允许携带 items（坏数据不得进入消费链路）")

    tx = _load_taxonomy(taxonomy_path)
    seen_ids = set()
    fallback_count = 0
    for i, it in enumerate(items):
        ctx = f"items[{i}]"
        for field in FEED_ITEM_REQUIRED_FIELDS:
            if field not in it:
                raise ContractError(f"{ctx} 缺少必填字段：{field}")
        if "content_text" in it:
            raise ContractError(f"{ctx} 携带全文 content_text：全文不得进入 feed")
        iid = it["id"]
        if not isinstance(iid, str) or not iid.startswith("manus:"):
            raise ContractError(f"{ctx} id 必须以 manus: 开头：{iid!r}")
        if iid in seen_ids:
            raise ContractError(f"{ctx} id 重复：{iid}")
        seen_ids.add(iid)
        for field in ("title", "summary", "url", "source", "mpName"):
            if not isinstance(it[field], str) or not it[field].strip():
                raise ContractError(f"{ctx} 字段 {field} 不能为空")
        allowed_source_types = ("wechat",) if feed["schemaVersion"] == 1 else ("wechat", "media", "direct")
        if it["sourceType"] not in allowed_source_types:
            raise ContractError(f"{ctx} sourceType 非法：{it['sourceType']!r}")
        if feed["schemaVersion"] >= 2 and it.get("sourceChannel") not in (
                "wechat_original", "tencent_syndication", "netease_syndication",
                "publisher_site", "media_page"):
            raise ContractError(f"{ctx} sourceChannel 非法：{it.get('sourceChannel')!r}")
        if it["collector"] != "manus":
            raise ContractError(f"{ctx} collector 应为 manus，实际 {it['collector']!r}")
        if it["publishedPrecision"] not in ("date", "datetime"):
            raise ContractError(f"{ctx} publishedPrecision 非法")
        try:
            datetime.fromisoformat(it["publishedAt"])
        except (TypeError, ValueError) as exc:
            raise ContractError(f"{ctx} publishedAt 非法：{it['publishedAt']!r}") from exc
        if not isinstance(it["contentSha256"], str) or not CONTENT_SHA256_RE.match(it["contentSha256"]):
            raise ContractError(f"{ctx} contentSha256 非法")
        if it["enrichmentStatus"] not in FEED_ENRICHMENT_STATUSES:
            raise ContractError(f"{ctx} enrichmentStatus 非法：{it['enrichmentStatus']!r}")
        if it["enrichmentStatus"] == "fallback":
            fallback_count += 1
        _validate_classification(tx, it["classification"], ctx)

    want_fields = ("configuredAccounts", "completeAccounts", "failedAccounts",
                   "discoveredArticles", "publishedArticles", "fallbackArticles")
    for field in want_fields:
        if not isinstance(stats.get(field), int):
            raise ContractError(f"stats.{field} 必须为整数")
    if stats["configuredAccounts"] != stats["completeAccounts"] + stats["failedAccounts"]:
        raise ContractError("stats 不自洽：configuredAccounts != completeAccounts + failedAccounts")
    if stats["publishedArticles"] != len(items):
        raise ContractError(f"stats.publishedArticles={stats['publishedArticles']} 与 items 数 {len(items)} 不一致")
    if stats["fallbackArticles"] != fallback_count:
        raise ContractError(f"stats.fallbackArticles={stats['fallbackArticles']} 与实际 fallback 条数 {fallback_count} 不一致")
    if stats["discoveredArticles"] < stats["publishedArticles"]:
        raise ContractError("stats 不自洽：discoveredArticles < publishedArticles")
    relevance_fields = ("screenedArticles", "relevanceIncludedArticles",
                        "relevanceExcludedArticles", "relevanceFailedArticles",
                        "relevancePendingArticles")
    present = [field in stats for field in relevance_fields]
    if any(present):
        if not all(present) or any(not isinstance(stats[field], int) or stats[field] < 0
                                   for field in relevance_fields):
            raise ContractError("相关性筛选 stats 字段必须完整且为非负整数")
        if stats["screenedArticles"] != sum(stats[field] for field in relevance_fields[1:]):
            raise ContractError("相关性筛选 stats 不自洽")
        if stats["relevanceIncludedArticles"] < stats["publishedArticles"]:
            raise ContractError("相关性保留文章数不能小于发布文章数")
    if feed.get("collectionWindow") is not None:
        window = feed["collectionWindow"]
        if window != ten_am_window(feed["targetDate"]):
            raise ContractError("feed 时间窗口与目标日期不一致")
        for it in items:
            try:
                if it["publishedPrecision"] != "datetime" or not contains(window, it["publishedAt"]):
                    raise ValueError("窗口外或时间未知")
            except (ValueError, TypeError) as exc:
                raise ContractError("feed 包含无法确认在十点窗口内的文章") from exc
