#!/usr/bin/env python3
"""make_annotation_sheet.py — 从历史归档抽样生成打标签 golden set 待标注表。

抽样策略：随机 60 条打底 + 关键词启发式富集（各类别候选约 20 条），
保证六类别候选覆盖。输出 tests/evaluation/annotation_sheet.json，由人工回填 answer
字段（category + 各绑定维度取值）后另存为 tests/evaluation/golden.json 入库。

标注规则（写入 instructions）：多事件新闻按固定优先级链裁决归属。

用法:
    python3 scripts/make_annotation_sheet.py [--archive-dir data/archive] [--out tests/evaluation/annotation_sheet.json]

纯标准库实现。
"""
import argparse
import json
import os
import random
import sys

SEED = 42
BASE_N = 60          # 随机打底条数
ENRICH_PER_CAT = 5   # 每类别关键词富集上限

# 类别候选富集关键词（启发式，只影响抽样分布，不影响标注口径）
ENRICH_KEYWORDS = {
    "financing": ["融资", "投资", "估值", "领投", "种子轮", "IPO"],
    "interview": ["专访", "访谈", "对话", "采访", "对谈"],
    "release": ["发布", "推出", "开源", "上线", "开放", "更新"],
    "bigtech": ["离职", "加入", "任命", "人事", "组织架构", "业务线", "裁员", "重组"],
    "paper": ["论文", "paper", "arXiv", "SOTA", "研究", "技术报告"],
}


def load_pool(archive_dir: str) -> list[dict]:
    """归档池全部条目（按 id 去重），只保留有标题的。"""
    pool: dict[str, dict] = {}
    if not os.path.isdir(archive_dir):
        return []
    for name in sorted(os.listdir(archive_dir)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(archive_dir, name), "r", encoding="utf-8") as f:
                day = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        for it in day.get("items") or []:
            if not (it.get("title") or "").strip():
                continue
            key = str(it.get("id") or it.get("title"))
            pool.setdefault(key, it)
    return list(pool.values())


def build_sheet(pool: list[dict], tx: dict) -> dict:
    random.Random(SEED).shuffle(pool)
    picked: list[dict] = []
    seen_titles: set[str] = set()

    def take(it: dict):
        t = (it.get("title") or "").strip().lower()
        if t in seen_titles:
            return False
        seen_titles.add(t)
        picked.append(it)
        return True

    for it in pool[:BASE_N]:
        take(it)
    # 关键词富集：在剩余条目里为每类别找候选
    rest = pool[BASE_N:]
    for cat_id, kws in ENRICH_KEYWORDS.items():
        n = 0
        for it in rest:
            if n >= ENRICH_PER_CAT:
                break
            text = ((it.get("title") or "") + " " + (it.get("summary") or "")).lower()
            if any(k.lower() in text for k in kws) and take(it):
                n += 1

    items = []
    for i, it in enumerate(picked, 1):
        items.append({
            "no": i,
            "id": str(it.get("id") or ""),
            "title": (it.get("title") or "").strip(),
            "summary": (it.get("summary") or "").strip(),
            "source": it.get("source") or "",
            "answer": {"category": "", "tags": {}},  # 人工回填
        })

    # 标注说明：类别标准 + 优先级链 + 维度取值表
    taxonomy_ref = {
        "priority": tx["priority"],
        "categories": [
            {"id": c["id"], "label": c["label"], "criteria": c["criteria"],
             "dims": {d: [v["id"] + "（" + v["label"] + "）" for v in tx["dimensions"][d]["values"]]
                      for d in c.get("dims", [])}}
            for c in tx["categories"]
        ],
    }
    instructions = (
        "1. 每条先判定 category（6 选 1，互斥）；同时命中多个判定标准时，按 priority 优先级链归入最高者。"
        "2. 再在该类别绑定的维度内各选 1 个取值（单选，只能从枚举选）。"
        "3. paper 与 general 无维度，tags 留空对象 {}。"
        "4. 完成后将本文件另存为 eval/golden.json。"
    )
    return {"instructions": instructions, "taxonomy": taxonomy_ref, "items": items}


def main() -> int:
    parser = argparse.ArgumentParser(description="生成打标签 golden set 待标注表")
    parser.add_argument("--archive-dir", default="data/archive")
    parser.add_argument("--taxonomy", default="config/taxonomy.json")
    parser.add_argument("--out", default="tests/evaluation/annotation_sheet.json")
    args = parser.parse_args()

    with open(args.taxonomy, "r", encoding="utf-8") as f:
        tx = json.load(f)
    pool = load_pool(args.archive_dir)
    if not pool:
        print(f"归档池为空（{args.archive_dir}），无法抽样", file=sys.stderr)
        return 1
    sheet = build_sheet(pool, tx)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(sheet, f, ensure_ascii=False, indent=1)
    print(f"已生成 {args.out}：共 {len(sheet['items'])} 条待标注（归档池 {len(pool)} 条）")
    print("请回填每条的 answer.category 与 answer.tags 后另存为 eval/golden.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
