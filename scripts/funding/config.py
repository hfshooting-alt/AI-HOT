"""融资流水线：config。"""
from datetime import datetime
from zoneinfo import ZoneInfo


FUNDING_DEFAULTS = {
    "content_input_chars": 16000,
    "timeout_seconds": 90,
    "concurrency": 3,
    "budget_seconds": 600,
}
SEARCH_DEFAULTS = {
    "provider": "tavily",
    "api_key_env": "TAVILY_API_KEY",
    "max_results": 5,
    "cache_ttl_days": 7,
}
TABLE_SCHEMA_VERSION = 1
# 抽取 prompt 版本：字段清单/约束变更时 +1，自动作废抽取缓存
FUNDING_PROMPT_VERSION = 4

# 表格字段（company_name 为去重键，不计入）
COMPANY_FIELDS = ("product_name", "founded", "country", "industry", "team",
                  "business", "investors", "total_funding", "valuation")
# 融资专属枚举字段（仅用于构建行 dims，不进入展示列）
ENUM_FIELDS = ("industry_id", "company_type_id")
FIELD_LABELS = {
    "product_name": "产品名称",
    "founded": "公司成立时间",
    "country": "国家",
    "industry": "所属行业",
    "team": "团队情况",
    "business": "主营业务",
    "investors": "历史投资人",
    "total_funding": "累计融资金额",
    "valuation": "最新估值",
}
# 公司名归一化时剥离的常见后缀（小写匹配）
COMPANY_SUFFIXES = (
    "inc.", "inc", "ltd.", "ltd", "llc", "corp.", "corp", "corporation", "company",
    "co., ltd", "co. ltd",
    "股份有限公司", "有限责任公司", "有限公司", "集团公司", "集团", "科技公司",
    "技术有限公司", "信息技术有限公司",
)


def now_bj_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def funding_cfg(tx: dict) -> dict:
    cfg = dict(FUNDING_DEFAULTS)
    cfg.update({k: v for k, v in (tx.get("funding") or {}).items() if not k.startswith("_")})
    return cfg


def search_cfg(tx: dict) -> dict:
    cfg = dict(SEARCH_DEFAULTS)
    cfg.update({k: v for k, v in ((tx.get("funding") or {}).get("search") or {}).items()
                if not k.startswith("_")})
    return cfg
