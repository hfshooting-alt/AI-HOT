#!/usr/bin/env python3
"""eval_tagging.py — 打标签准确性评测与回归门禁。

对 tests/evaluation/golden.json（人工标注）逐条走 tag_news 全链路（真实调用模型，不走缓存），
产出指标报告；taxonomy.json 配置了 thresholds 时执行门禁（不达标退出码非零）。

指标：
    - 类别准确率（主指标）
    - 每维度取值准确率（仅在 golden 与预测类别一致的样本上计算）
    - 「其他」类取值使用率（清单覆盖缺口信号）
    - 类别混淆对 top 列表

用法:
    python3 scripts/eval_tagging.py [--golden tests/evaluation/golden.json] [--taxonomy taxonomy.json]

纯标准库实现。
"""
import argparse
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tag_news  # noqa: E402

OTHER_VALUE_IDS = {"other", "ai_other"}  # 「其他」类兜底取值


def load_golden(path: str, tx: dict) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        sheet = json.load(f)
    cat_ids = {c["id"] for c in tx["categories"]}
    samples = []
    for it in sheet.get("items") or []:
        ans = it.get("answer") or {}
        if not ans.get("category"):
            continue  # 未标注的跳过
        if ans["category"] not in cat_ids:
            print(f"  [跳过] #{it.get('no')} 标注类别非法: {ans['category']}", file=sys.stderr)
            continue
        samples.append(it)
    return samples


def evaluate(tx: dict, samples: list[dict]) -> dict:
    m = tx["model"]
    preds: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=m.get("concurrency", 8)) as ex:
        futs = {ex.submit(tag_news.tag_one, tx, it): it["no"] for it in samples}
        for fut in as_completed(futs):
            preds[futs[fut]] = fut.result()

    cat_ok = 0
    confusion: Counter = Counter()
    dim_total: Counter = Counter()
    dim_ok: Counter = Counter()
    other_used = 0
    other_total = 0
    per_item = []
    for it in samples:
        g = it["answer"]
        p = preds[it["no"]]
        hit = g["category"] == p["category"]
        cat_ok += hit
        if not hit:
            confusion[(g["category"], p["category"])] += 1
        if hit:  # 维度准确率仅在类别一致的样本上计算
            cat = next(c for c in tx["categories"] if c["id"] == g["category"])
            for dim_id in cat.get("dims", []):
                dim_total[dim_id] += 1
                gv, pv = (g.get("tags") or {}).get(dim_id), p["tags"].get(dim_id)
                if gv and gv == pv:
                    dim_ok[dim_id] += 1
                if pv in OTHER_VALUE_IDS:
                    other_used += 1
                if pv:
                    other_total += 1
        per_item.append({"no": it["no"], "title": it["title"][:40],
                         "golden": g["category"], "pred": p["category"], "hit": hit,
                         "autoFallback": p.get("autoFallback", False)})

    n = len(samples)
    report = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "model": m["model"],
        "taxonomyVersion": tx["version"],
        "promptVersion": tx["promptVersion"],
        "samples": n,
        "categoryAccuracy": round(cat_ok / n, 4) if n else 0,
        "dimAccuracy": {d: round(dim_ok[d] / dim_total[d], 4) if dim_total[d] else None
                        for d in dim_total},
        "otherUsageRate": round(other_used / other_total, 4) if other_total else 0,
        "autoFallbackCount": sum(1 for x in per_item if x["autoFallback"]),
        "topConfusion": [{"golden": a, "pred": b, "count": c}
                         for (a, b), c in confusion.most_common(10)],
        "items": per_item,
    }
    return report


def gate(tx: dict, report: dict) -> bool:
    """对照 thresholds 门禁。未配置阈值时仅提示（返回 True）。"""
    th = tx.get("thresholds")
    if not th:
        print("taxonomy.json 未配置 thresholds：本轮仅产出基线，不执行门禁")
        return True
    ok = True
    if report["categoryAccuracy"] < th.get("categoryAccuracy", 0):
        ok = False
    for dim_id, acc in report["dimAccuracy"].items():
        if acc is not None and acc < th.get("dimAccuracy", 0):
            ok = False
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="打标签准确性评测与回归门禁")
    parser.add_argument("--golden", default="tests/evaluation/golden.json")
    parser.add_argument("--taxonomy", default="config/taxonomy.json")
    parser.add_argument("--report-dir", default="eval")
    args = parser.parse_args()

    tx = tag_news.load_taxonomy(args.taxonomy)
    if not os.path.exists(args.golden):
        print(f"缺少 golden set：{args.golden}（先运行 make_annotation_sheet.py 并完成标注）",
              file=sys.stderr)
        return 2
    samples = load_golden(args.golden, tx)
    if not samples:
        print("golden set 中没有已完成标注的样本", file=sys.stderr)
        return 2

    print(f"评测开始：{len(samples)} 条样本 · 模型 {tx['model']['model']}（真实调用，不走缓存）")
    report = evaluate(tx, samples)

    os.makedirs(args.report_dir, exist_ok=True)
    out_path = os.path.join(args.report_dir, f"report-{time.strftime('%Y%m%d-%H%M%S')}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    print(f"\n== 评测结果 ==")
    print(f"  类别准确率: {report['categoryAccuracy']:.1%}（{report['samples']} 条）")
    for d, acc in report["dimAccuracy"].items():
        if acc is not None:
            print(f"  维度 {d} 准确率: {acc:.1%}")
    print(f"  「其他」类取值使用率: {report['otherUsageRate']:.1%}（偏高=清单覆盖有缺口）")
    print(f"  兜底(general)次数: {report['autoFallbackCount']}")
    if report["topConfusion"]:
        print("  主要混淆对: " + "; ".join(
            f"{c['golden']}→{c['pred']}×{c['count']}" for c in report["topConfusion"][:5]))
    print(f"  报告: {out_path}")

    if not gate(tx, report):
        print("\n[门禁] 未达标：请调整 prompt/taxonomy 后重跑", file=sys.stderr)
        return 1
    print("\n[门禁] 通过（或未配置阈值）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
