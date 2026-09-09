"""content_phase.py — 阶段 B 独立 CLI：从已保存的发现结果出发，按批提取正文。

用法:
    python scripts/manus_source/content_phase.py --date 2026-08-16

前置：runner.py 已把三组发现结果写入 work/manus/<date>/raw/。
正文提供方：默认本地脚本爬虫（MANUS_CONTENT_MODE=script，crawler.py，需 trafilatura）；
            可选 Manus 正文任务（MANUS_CONTENT_MODE=manus）。
产出：work/manus/<date>/raw/content-batch-*.json（含正文，运行时目录，不入库）
      work/manus/diagnostics/<date>/（去正文诊断，可上传 Artifact）
"""
import argparse
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from manus_source.config import Settings, load_sources  # noqa: E402
from manus_source.window import ten_am_window  # noqa: E402
from manus_source.pipeline import (  # noqa: E402
    ContentPipeline, ManusContentProvider, ScriptContentProvider,
)
from manus_source.crawler import DEFAULT_USER_AGENT  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
import build_manus_feed  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manus 正文提取阶段")
    parser.add_argument("--date", required=True, help="目标日期 YYYY-MM-DD")
    parser.add_argument("--ten-am", action="store_true", help="读取 date 结束的十点窗口")
    args = parser.parse_args(argv)

    settings = Settings.from_environment(PROJECT_ROOT)
    if args.ten_am:
        settings = replace(settings, work_dir=settings.work_dir / "ten-am")
    groups_cfg = load_sources(settings.sources_path)
    discoveries = build_manus_feed.load_discoveries(
        settings.work_dir / args.date / "raw", args.date, groups_cfg)
    if args.ten_am and any(d.get("collectionWindow") != ten_am_window(args.date) for d in discoveries.values()):
        raise ValueError("发现结果不是请求的十点窗口")
    prompt_text = settings.content_prompt_path.read_text(encoding="utf-8")

    if settings.content_mode == "manus":
        from manus_source.client import ManusClient  # noqa: E402
        client = ManusClient(
            api_key=settings.manus_api_key,
            agent_profile=settings.manus_agent_profile,
            poll_seconds=settings.poll_seconds,
            timeout_seconds=settings.timeout_seconds,
            register_grace_seconds=settings.register_grace_seconds,
        )
        provider = ManusContentProvider(client, prompt_text, args.date)
    else:
        provider = ScriptContentProvider(
            args.date,
            concurrency=settings.crawl_concurrency,
            max_content_chars=settings.max_content_chars,
            min_content_chars=settings.min_content_chars,
            timeout_seconds=settings.crawl_timeout_seconds,
            retries=settings.crawl_retries,
            request_delay_seconds=settings.crawl_request_delay_seconds,
            user_agent=settings.crawl_user_agent or DEFAULT_USER_AGENT,
            jina_fallback=settings.crawl_jina_fallback,
        )
    pipeline = ContentPipeline(
        provider,
        prompt_text,
        args.date,
        settings.work_dir,
        batch_size=settings.content_batch_size,
        max_content_chars=settings.max_content_chars,
        min_content_chars=settings.min_content_chars,
    )
    result = pipeline.run(discoveries)
    print(f"正文阶段完成：可加工 {len(result.ok_articles)} 篇，失败 {len(result.failed)} 篇，"
          f"新跑 {result.batches_run} 批，续跑复用 {result.batches_resumed} 批，"
          f"去重丢弃 {result.duplicates_dropped} 篇")
    for f in result.failed:
        print(f"  [failed] {f['account_name']} {f['article_url']}：{f['reason']}", file=sys.stderr)
    if not result.ok_articles:
        print("警告：没有任何可加工正文（来源全失败或全被风控拦截）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
