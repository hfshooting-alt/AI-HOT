"""融资流水线：companies。"""
import hashlib
import re
import unicodedata
from .config import COMPANY_FIELDS, COMPANY_SUFFIXES


# ================= 去重合并 =================

def normalize_company_key(name: str) -> str:
    """公司名归一化：NFKC → 去空白/括号内容 → 小写 → 循环剥离常见后缀。"""
    s = unicodedata.normalize("NFKC", name or "").strip().lower()
    s = re.sub(r"[（(【\[].*?[)）】\]]", "", s)
    s = re.sub(r"\s+", "", s).strip("·.-_ ")
    changed = True
    while changed and s:
        changed = False
        for suf in COMPANY_SUFFIXES:
            if s.endswith(suf) and len(s) > len(suf):
                s = s[: -len(suf)].strip("·.-_ ")
                changed = True
    return s


def company_row_id(key: str) -> str:
    return "fund:" + hashlib.md5(key.encode("utf-8")).hexdigest()[:16]


# 国家/地区文本 → 全局 region 枚举 label 的确定性映射
_COUNTRY_REGION_KEYWORDS = {
    "中国": ["中国", "中", "中国大陆", "内地", "香港", "台湾", "澳门"],
    "美国": ["美国", "us", "usa", "美利坚合众国"],
    "欧洲": ["欧洲", "英国", "法国", "德国", "意大利", "瑞士", "瑞典", "荷兰", "西班牙", "eu"],
    "东南亚": ["东南亚", "新加坡", "泰国", "越南", "印尼", "印度尼西亚", "马来西亚", "菲律宾"],
    "日韩": ["日本", "韩国", "日韩"],
}


def _country_to_region_label(country: str | None) -> str:
    """将 LLM 抽取的国家文本映射到全局 region 枚举 label；无命中回退「其他」。"""
    if not country:
        return "其他"
    c = country.strip().lower()
    for region, keywords in _COUNTRY_REGION_KEYWORDS.items():
        if any(kw in c for kw in keywords):
            return region
    return "其他"


def _article_region_label(art: dict, country: str | None) -> str:
    """优先取源文章 dims 的 region label，缺失时用 country 文本映射。"""
    region = (art.get("dims") or {}).get("国家/地区")
    if region:
        return region
    return _country_to_region_label(country)


def merge_companies(articles: list[dict], extracts: dict[str, dict]) -> list[dict]:
    """按归一化公司名去重合并：publishedAt 降序处理，新文章字段优先、旧文章补空。"""
    companies: dict[str, dict] = {}
    for art in sorted(articles, key=lambda a: a.get("publishedAt") or "", reverse=True):
        ext = extracts.get(art["id"]) or {}
        for c in ext.get("companies") or []:
            key = normalize_company_key(c.get("company_name") or "")
            if not key:
                continue
            rid = company_row_id(key)
            rec = companies.get(rid)
            if rec is None:
                rec = {"id": rid, "company_name": c["company_name"],
                       **{f: None for f in COMPANY_FIELDS},
                       "dims": {}, "filledBySearch": [],
                       "searchSources": [], "sourceArticles": []}
                for f in COMPANY_FIELDS:
                    rec[f] = c.get(f)
                # dims 取最新文章的非空枚举值
                rec["dims"]["所属行业"] = c.get("industry_id") or "其他"
                rec["dims"]["公司类型"] = c.get("company_type_id") or "其他"
                rec["dims"]["国家/地区"] = _article_region_label(art, c.get("country"))
                companies[rid] = rec
            else:
                for f in COMPANY_FIELDS:  # 旧文章只补空
                    if rec[f] is None and c.get(f):
                        rec[f] = c[f]
                # dims 取最新非空
                if rec["dims"].get("所属行业") == "其他" and c.get("industry_id") and c["industry_id"] != "其他":
                    rec["dims"]["所属行业"] = c["industry_id"]
                if rec["dims"].get("公司类型") == "其他" and c.get("company_type_id") and c["company_type_id"] != "其他":
                    rec["dims"]["公司类型"] = c["company_type_id"]
                if rec["dims"].get("国家/地区") == "其他":
                    region = (art.get("dims") or {}).get("国家/地区")
                    if region:
                        rec["dims"]["国家/地区"] = region
                    elif c.get("country"):
                        rec["dims"]["国家/地区"] = _country_to_region_label(c["country"])
            if not any(sa.get("id") == art["id"] for sa in rec["sourceArticles"]):
                rec["sourceArticles"].append({
                    "id": art["id"], "title": art.get("title") or "",
                    "url": art.get("url") or "", "publishedAt": art.get("publishedAt") or "",
                    "mpName": art.get("mpName") or "",
                })
    rows = sorted(companies.values(),
                  key=lambda r: (r["sourceArticles"] or [{}])[0].get("publishedAt") or "",
                  reverse=True)
    for r in rows:
        r["sourceArticles"].sort(key=lambda sa: sa.get("publishedAt") or "", reverse=True)
    return rows
