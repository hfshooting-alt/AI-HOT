"""crawler.py — 阶段 B 本地脚本爬虫：按 URL 抓取文章页并用 trafilatura 提取正文。

背景与定位（详见 docs/2026-08-20-manus-pipeline-smoke-issues.md）：
  Manus GUI 浏览器正文任务存在字段错位/占位文本/标题漂移等不稳定问题，且按 agent
  耗时计费。本模块把"给定固定 URL 抓取 SSR 文章页"这一环节换成确定性脚本：

  - fetch：urllib + 浏览器 UA，跟随跳转并返回 final URL（供跳转漂移检查），
    瞬时 5xx/连接中断指数退避重试，请求间隔限速（礼貌爬取）。
  - extract：trafilatura.extract() 输出纯文本 + extract_metadata() 取标题；
    提取失败返回 None。
  - 风控：HTML 层特征词 + 提取文本层复用 contracts.RISK_PAGE_MARKERS（由上层门槛判定）。
  - 回退：CRAWL_FALLBACK=jina 时，trafilatura 提取失败的 URL 走
    https://r.jina.ai/<url>（免费 reader 服务，正文经第三方，默认关闭）。
  - 输出：与 Manus 正文任务相同 schema 的文章记录，由 contracts.validate_content_batch 统一校验。

依赖：trafilatura（唯一第三方依赖，惰性导入；未安装时仅在真正爬取时抛明确错误）。
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from . import contracts

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
# HTML 层风控/验证页特征词（文本层特征复用 contracts.RISK_PAGE_MARKERS）
HTML_RISK_MARKERS = ("安全验证", "验证码", "访问人数过多", "环境异常", "请登录",
                     "扫码登录", "滑动验证", "人机验证", "captcha")
JINA_READER_URL = "https://r.jina.ai/"


class CrawlError(RuntimeError):
    """抓取/提取失败。消息须可进入 failed 记录的 note。"""


def _trafilatura():
    """惰性导入 trafilatura；未安装时给出明确安装指引。"""
    try:
        import trafilatura  # noqa: PLC0415
        return trafilatura
    except ImportError as exc:
        raise RuntimeError("缺少正文提取依赖 trafilatura：请先 `pip install trafilatura`") from exc


# ================= 抓取 =================

def fetch_html(url: str, timeout_seconds: float = 20, retries: int = 2,
               retry_base_seconds: float = 2.0, user_agent: str = DEFAULT_USER_AGENT,
               request_delay_seconds: float = 0.0,
               transport: Callable[[str, dict], tuple[str, bytes]] | None = None,
               ) -> tuple[str, bytes]:
    """抓取 URL，返回 (final_url, html_bytes)；跟随跳转。失败抛 CrawlError。

    transport 可注入（离线单测）：签名 (url, headers) -> (final_url, bytes)。
    """
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "close",
    }
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            if transport is not None:
                final_url, data = transport(url, headers)
            else:
                request = Request(url, headers=headers, method="GET")
                with urlopen(request, timeout=timeout_seconds) as response:
                    final_url = response.geturl()
                    data = response.read()
            if request_delay_seconds > 0:
                time.sleep(request_delay_seconds)  # 礼貌限速，降低风控概率
            return final_url, data
        except (HTTPError, URLError, OSError) as error:
            last_error = error
            if attempt >= retries:
                break
            time.sleep(retry_base_seconds * (2 ** attempt))
    raise CrawlError(f"抓取失败：{url}（{last_error}）")


def fetch_jina_text(url: str, timeout_seconds: float = 30,
                    user_agent: str = DEFAULT_USER_AGENT) -> str:
    """Jina Reader 回退：https://r.jina.ai/<url> 直接返回纯文本；失败返回空串。"""
    try:
        request = Request(
            JINA_READER_URL + url,
            headers={"User-Agent": user_agent, "X-Return-Format": "text"},
        )
        with urlopen(request, timeout=timeout_seconds) as response:
            return response.read().decode("utf-8", errors="replace").strip()
    except (HTTPError, URLError, OSError):
        return ""


# ================= 提取与清洗 =================


class _HeadTitleParser(HTMLParser):
    """只读取 head 中的标准标题，避免正文提取器把导航标题当文章标题。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_title = False
        self.title_parts: list[str] = []
        self.meta_titles: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value for key, value in attrs if value is not None}
        if tag.lower() == "title":
            self.in_title = True
        elif tag.lower() == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            if key in ("og:title", "twitter:title") and values.get("content"):
                self.meta_titles[key] = values["content"].strip()

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)


def extract_head_title(html_bytes: bytes) -> str | None:
    parser = _HeadTitleParser()
    try:
        parser.feed(_html_text(html_bytes))
    except Exception:  # noqa: BLE001 - 破损 HTML 回退给 trafilatura
        return None
    title = (parser.meta_titles.get("og:title") or
             parser.meta_titles.get("twitter:title") or
             "".join(parser.title_parts).strip())
    return title or None

def extract_text(html_bytes: bytes) -> tuple[str | None, str | None]:
    """提取正文；标题优先取 head 标准字段，再回退 trafilatura 元数据。"""
    tr = _trafilatura()
    text = None
    meta_title = extract_head_title(html_bytes)
    try:
        text = tr.extract(html_bytes, output_format="txt")
    except Exception:  # noqa: BLE001 - 提取器内部异常按"无法提取"处理
        text = None
    if not meta_title:
        try:
            meta = tr.extract_metadata(html_bytes)
            meta_title = meta.title if meta else None
        except Exception:  # noqa: BLE001
            meta_title = None
    return text, meta_title


def _html_text(html_bytes: bytes) -> str:
    return html_bytes.decode("utf-8", errors="replace")


def _looks_like_risk_page(html_bytes: bytes, text: str | None = None) -> bool:
    """风控页判定：HTML 头部（title/meta）命中特征词，或提取文本短且命中特征词。

    只扫 head 区域与短文本，避免正文中偶然出现的"验证码/扫码登录"等词误杀。
    """
    html_text = _html_text(html_bytes)
    head = html_text.split("</head>")[0] if "</head>" in html_text else html_text[:4000]
    if any(marker in head for marker in HTML_RISK_MARKERS):
        return True
    if text is not None and len(text) < 200 and any(m in text for m in contracts.RISK_PAGE_MARKERS):
        return True
    return False


def _url_drifted(requested: str, final: str) -> bool:
    """跳转漂移：仅当 host 或 path 变化才算漂移；查询参数/片段变化忽略。

    mp.weixin.qq.com 的 /s?__biz=... 同 path 不同文章由标题一致性门槛兜底。
    """
    try:
        a, b = urlparse(requested), urlparse(final)
        host_a = (a.netloc or "").lower().split(":")[0]
        host_b = (b.netloc or "").lower().split(":")[0]
        if host_a != host_b:
            return True
        return a.path.rstrip("/") != b.path.rstrip("/")
    except ValueError:
        return True


def _title_mismatch(expected: str, actual: str) -> bool:
    """标题一致性（宽松版）：剥离全部空白后双向子串包含即视为一致。

    容忍站点后缀（"_腾讯新闻"）与空格漂移（冒烟报告问题 3 的 Manus 场景）；
    发现阶段记录与页面实际标题完全无关时判为跳转漂移。
    """
    if not expected or not actual:
        return False
    e = "".join(expected.split()).lower()
    a = "".join(actual.split()).lower()
    return e not in a and a not in e


def truncate_head_tail(text: str, limit: int) -> str:
    """超长正文头尾保留（与 Manus prompt 规则一致），中段以一行说明占位。

    返回长度不超过 limit（占位行计入预算）。
    """
    if len(text) <= limit:
        return text
    marker = "\n……（正文过长已截断）……\n"
    budget = limit - len(marker)
    head_len = budget * 3 // 4
    tail_len = budget - head_len
    return text[:head_len] + marker + text[-tail_len:]


# ================= 单篇爬取 =================

def crawl_one(article: dict, target_date: str, *, max_content_chars: int = 20000,
              min_content_chars: int = 100, timeout_seconds: float = 20, retries: int = 2,
              user_agent: str = DEFAULT_USER_AGENT, request_delay_seconds: float = 0.0,
              jina_fallback: bool = False,
              transport: Callable[[str, dict], tuple[str, bytes]] | None = None,
              ) -> dict:
    """单篇完整流程：抓取 → 跳转检查 → 提取 → 风控/漂移/过短判定 → 截断。

    恒返回与 Manus 正文任务同 schema 的记录（content_status=complete|failed）。
    """
    url = article["article_url"]
    record = {
        "account_name": article["account_name"],
        "article_url": url,
        "title": article["title"],
        "published_date": article["published_date"],
        "content_text": "",
        "content_status": "failed",
        "content_truncated": False,
        "note": None,
    }
    try:
        final_url, html = fetch_html(url, timeout_seconds=timeout_seconds, retries=retries,
                                     user_agent=user_agent,
                                     request_delay_seconds=request_delay_seconds,
                                     transport=transport)
    except CrawlError as error:
        record["note"] = str(error)
        return record
    if _url_drifted(url, final_url):
        record["note"] = f"页面跳转漂移：请求 {url} → 落地 {final_url}"
        return record

    text, meta_title = extract_text(html)
    if not text and jina_fallback:
        text = fetch_jina_text(url, timeout_seconds=timeout_seconds, user_agent=user_agent)
    # 判定顺序：风控页 → 无正文 → 正文过短 → 标题漂移（避免 404/风控页被误报为漂移）
    if _looks_like_risk_page(html, text):
        record["note"] = "页面返回验证码/风控页，未获得正文"
        return record
    if not text:
        record["note"] = "无法从页面提取正文"
        return record
    text = text.strip()
    if len(text) < min_content_chars:
        record["note"] = f"正文过短（{len(text)} < {min_content_chars} 字符）"
        return record
    if _title_mismatch(article.get("title") or "", meta_title or ""):
        record["note"] = "正文标题与发现阶段记录不一致（跳转漂移）"
        return record
    truncated = False
    if max_content_chars and len(text) > max_content_chars:
        text = truncate_head_tail(text, max_content_chars)
        truncated = True
    record.update(content_text=text, content_status="complete", content_truncated=truncated)
    if truncated:
        record["note"] = "正文超过上限已截断"
    return record


# ================= 批量爬取 =================

def crawl_batch(batch: list[dict], target_date: str, *, concurrency: int = 4,
                **kwargs) -> dict:
    """并发爬取一批文章，产出与 Manus 正文任务相同 schema 的 payload。

    输出顺序与请求清单一致（由 article_url 映射回填），供上层
    "URL 集合一一对应"门槛直接通过。
    """
    records: list[dict] = []
    if concurrency > 1 and len(batch) > 1:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(crawl_one, a, target_date, **kwargs) for a in batch]
            for future in as_completed(futures):
                records.append(future.result())
    else:
        records = [crawl_one(a, target_date, **kwargs) for a in batch]
    by_url = {r["article_url"]: r for r in records}
    return {"target_date": target_date,
            "articles": [by_url[a["article_url"]] for a in batch]}
