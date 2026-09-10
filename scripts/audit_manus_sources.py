#!/usr/bin/env python3
"""离线审计 Manus 公众号配置；不访问网页、不调用 API。"""
import argparse
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from manus_source.config import load_sources  # noqa: E402


def audit(groups: dict) -> dict:
    errors = []
    names, urls, platforms, hosts = [], [], Counter(), Counter()
    for group, sources in groups.items():
        for index, source in enumerate(sources, 1):
            context = f"{group}[{index}]"
            name = source.get("account_name", "").strip()
            url = source.get("home_url", "").strip()
            platform = source.get("platform", "").strip()
            parsed = urlparse(url)
            names.append(name)
            urls.append(url.rstrip("/"))
            platforms[platform] += 1
            if parsed.hostname:
                hosts[parsed.hostname.lower()] += 1
            if parsed.scheme != "https" or not parsed.hostname:
                errors.append(f"{context} home_url 必须是完整 HTTPS URL")
            if parsed.username or parsed.password:
                errors.append(f"{context} home_url 不得包含认证信息")
    duplicate_names = sorted(name for name, count in Counter(names).items() if count > 1)
    duplicate_urls = sorted(url for url, count in Counter(urls).items() if count > 1)
    errors.extend(f"账号名称重复：{name}" for name in duplicate_names)
    errors.extend(f"主页 URL 重复：{url}" for url in duplicate_urls)
    return {
        "ok": not errors,
        "configuredAccounts": len(names),
        "groups": {group: len(sources) for group, sources in groups.items()},
        "platforms": dict(sorted(platforms.items())),
        "hosts": dict(sorted(hosts.items())),
        "duplicateNames": duplicate_names,
        "duplicateUrls": duplicate_urls,
        "errors": errors,
    }


def check_url(url: str, timeout_seconds: int = 8) -> dict:
    """单次小体积 GET，不重试；403/429 记为站点可达但受限。"""
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; AI-HOT source audit/1.0)",
        "Range": "bytes=0-4095",
    })
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            response.read(1)
            return {"reachable": True, "restricted": False,
                    "status": response.status, "finalUrl": response.geturl()}
    except HTTPError as exc:
        restricted = exc.code in (401, 403, 429)
        return {"reachable": restricted, "restricted": restricted,
                "status": exc.code, "error": f"HTTP_{exc.code}"}
    except (URLError, TimeoutError, OSError):
        return {"reachable": False, "restricted": False, "error": "connection_failed"}


def audit_links(groups: dict, *, checker=check_url, concurrency: int = 4) -> dict:
    """每个配置账号只请求一次；返回账号级可达性，不读取或保存正文。"""
    sources = [(group, source) for group, values in groups.items() for source in values]
    results = []
    with ThreadPoolExecutor(max_workers=max(1, min(concurrency, len(sources)))) as pool:
        futures = {pool.submit(checker, source["home_url"]): (group, source)
                   for group, source in sources}
        for future in as_completed(futures):
            group, source = futures[future]
            try:
                result = future.result()
            except Exception:  # noqa: BLE001 - 单个来源失败不阻断完整审计
                result = {"reachable": False, "restricted": False, "error": "check_failed"}
            results.append({"group": group, "accountName": source["account_name"],
                            "homeUrl": source["home_url"], **result})
    results.sort(key=lambda item: (item["group"], item["accountName"]))
    return {
        "requests": len(results),
        "reachableAccounts": sum(bool(item["reachable"]) for item in results),
        "restrictedAccounts": sum(bool(item["restricted"]) for item in results),
        "unreachableAccounts": sum(not item["reachable"] for item in results),
        "items": results,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", default="config/manus_sources.json")
    parser.add_argument("--check-links", action="store_true",
                        help="对每个主页发一个小体积 GET；不调用 Manus 或模型")
    parser.add_argument("--timeout-seconds", type=int, default=8)
    parser.add_argument("--report-dir", default="work/source-audit",
                        help="链接审计报告目录（默认已被 Git 忽略）")
    args = parser.parse_args(argv)
    if not 2 <= args.timeout_seconds <= 20:
        parser.error("--timeout-seconds 必须在 2-20 之间")
    groups = load_sources(Path(args.sources))
    report = audit(groups)
    if args.check_links and report["ok"]:
        report["checkedAt"] = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
        report["linkAudit"] = audit_links(
            groups, checker=lambda url: check_url(url, args.timeout_seconds))
        report_dir = Path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"source-health-{datetime.now(ZoneInfo('Asia/Shanghai')).date()}.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["reportPath"] = str(report_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    links_ok = not args.check_links or report.get("linkAudit", {}).get("unreachableAccounts") == 0
    return 0 if report["ok"] and links_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
