"""融资流水线：output。"""
import json
import os
from pathlib import Path
from .config import COMPANY_FIELDS, TABLE_SCHEMA_VERSION


# ================= 组装与校验 =================

def assemble_table(companies: list[dict], stats: dict, generated_at: str,
                   search_note: str) -> dict:
    return {
        "schemaVersion": TABLE_SCHEMA_VERSION,
        "generatedAt": generated_at,
        "coverageNote": "覆盖快照日报+周报池与最新 Manus feed 中的融资类新闻（约最近一周）",
        "searchNote": search_note,
        "stats": stats,
        "companies": companies,
    }


def validate_table(table: dict, tx: dict) -> None:
    """输出 schema 校验：违规抛 ValueError（调用方不晋升产物）。"""
    stats = table.get("stats") or {}
    processed = stats.get("articlesProcessed", 0)
    if processed > 0 and stats.get("extractionFailed", 0) >= processed:
        raise ValueError("融资文章全部抽取失败或未完成，禁止覆盖上次成功表格")
    if table.get("schemaVersion") != TABLE_SCHEMA_VERSION:
        raise ValueError("schemaVersion 不合法")
    if not isinstance(table.get("generatedAt"), str) or not table["generatedAt"]:
        raise ValueError("generatedAt 缺失")
    dim_labels = {d["label"]: {v["label"] for v in d["values"]}
                  for d in tx.get("dimensions", {}).values()}
    # 融资专属维度并入合法集
    if tx.get("funding"):
        for dim_key in ("industry_dim", "company_type_dim"):
            dim = tx["funding"].get(dim_key)
            if dim and "label" in dim and "values" in dim:
                dim_labels[dim["label"]] = {v["label"] for v in dim["values"]}
    companies = table.get("companies")
    if not isinstance(companies, list):
        raise ValueError("companies 必须为数组")
    for rec in companies:
        if not isinstance(rec.get("id"), str) or not rec["id"].startswith("fund:"):
            raise ValueError(f"公司行 id 不合法：{rec.get('id')}")
        if not isinstance(rec.get("company_name"), str) or not rec["company_name"].strip():
            raise ValueError(f"公司行 {rec['id']} company_name 缺失")
        for f in COMPANY_FIELDS:
            v = rec.get(f)
            if v is not None and not isinstance(v, str):
                raise ValueError(f"公司行 {rec['id']} 字段 {f} 类型不合法")
        for label, value in (rec.get("dims") or {}).items():
            if label not in dim_labels or value not in dim_labels[label]:
                raise ValueError(f"公司行 {rec['id']} dims 取值不合法：{label}={value}")
        if not rec.get("sourceArticles"):
            raise ValueError(f"公司行 {rec['id']} sourceArticles 为空")
        for sa in rec["sourceArticles"]:
            if not sa.get("url"):
                raise ValueError(f"公司行 {rec['id']} 来源条目缺 url")
        for f in rec.get("filledBySearch") or []:
            if f not in COMPANY_FIELDS:
                raise ValueError(f"公司行 {rec['id']} filledBySearch 字段名不合法：{f}")


def atomic_write_json(path: Path, data: dict) -> None:
    """同目录临时文件 + os.replace 原子替换（同 build_manus_feed）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def promote_table(table: dict, data_dir: Path | str, public_dir: Path | str) -> tuple[Path, Path]:
    data_dir = Path(data_dir)
    public_dir = Path(public_dir)
    current = data_dir / "current.json"
    atomic_write_json(current, table)
    atomic_write_json(data_dir / "archive" / f"{table['generatedAt'][:10]}.json", table)
    web = public_dir / "funding-table.json"
    atomic_write_json(web, table)
    return current, web
