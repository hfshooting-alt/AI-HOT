"""公司 Overview 产物组装、校验与原子晋升。"""
import json
import os
from pathlib import Path

from .config import ALL_EVIDENCE_FIELDS, SCALAR_FIELDS, SCHEMA_VERSION


def assemble(companies: list[dict], stats: dict, generated_at: str) -> dict:
    return {"schemaVersion": SCHEMA_VERSION, "generatedAt": generated_at,
            "coverageNote": "覆盖快照日报、周报与最新 Manus feed 的全部新闻类别；历史公司持续保留",
            "stats": stats, "companies": companies}


def validate(data: dict, tx: dict) -> None:
    if data.get("schemaVersion") != SCHEMA_VERSION or not data.get("generatedAt"):
        raise ValueError("公司库版本或生成时间不合法")
    stats = data.get("stats") or {}
    processed = stats.get("articlesProcessed", 0)
    if processed and stats.get("articlesComplete", 0) == 0:
        raise ValueError("全部文章均未成功抽取，禁止覆盖上次公司库")
    companies = data.get("companies")
    if not isinstance(companies, list):
        raise ValueError("companies 必须为数组")
    industry_values = {v["label"] for v in tx["dimensions"]["industry"]["values"]}
    region_values = {v["label"] for v in tx["dimensions"]["region"]["values"]}
    ids = set()
    for rec in companies:
        rid = rec.get("id")
        if not isinstance(rid, str) or not rid.startswith("company:") or rid in ids:
            raise ValueError("公司 id 缺失或重复")
        ids.add(rid)
        if not isinstance(rec.get("company_name"), str) or not rec["company_name"].strip():
            raise ValueError(f"{rid} 公司名称缺失")
        if not isinstance(rec.get("product_names"), list) or not isinstance(rec.get("aliases"), list):
            raise ValueError(f"{rid} aliases/product_names 类型不合法")
        for field in SCALAR_FIELDS:
            if rec.get(field) is not None and not isinstance(rec[field], str):
                raise ValueError(f"{rid} 字段 {field} 类型不合法")
        dims = rec.get("dims") or {}
        if dims.get("行业") not in industry_values or dims.get("国家/地区") not in region_values:
            raise ValueError(f"{rid} 分类维度不合法")
        if not rec.get("sourceArticles"):
            raise ValueError(f"{rid} 缺少来源文章")
        sources = rec.get("fieldSources")
        if not isinstance(sources, dict) or not sources.get("company_name"):
            raise ValueError(f"{rid} 缺少公司名称来源")
        for field, evidence in sources.items():
            if field not in ALL_EVIDENCE_FIELDS or not isinstance(evidence, list):
                raise ValueError(f"{rid} 字段来源结构不合法")
            for item in evidence:
                if not item.get("value") or not item.get("articleId") or item.get("origin") != "article":
                    raise ValueError(f"{rid} 字段来源内容不合法")


def atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def promote(data: dict, data_dir: Path | str, public_dir: Path | str):
    data_dir, public_dir = Path(data_dir), Path(public_dir)
    current = data_dir / "current.json"
    web = public_dir / "company-overview.json"
    archive = data_dir / "archive" / f"{data['generatedAt'][:10]}.json"
    for path in (current, web, archive):
        atomic_write(path, data)
    return current, web
