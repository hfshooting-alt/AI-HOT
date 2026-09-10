"""llm_common.py — OpenAI-compatible /chat/completions 调用与 JSON 输出解析（稳定函数）。

从 tag_news.py 抽取的公共能力，供打标签（tag_news）与正文加工（enrich_news）复用。
纯标准库实现。

.env 加载：设置页（scripts/settings-server.mjs）把密钥写入项目根 .env，
本模块在首次调用时自动加载（幂等），本地流水线因此免手动 export；
语义与 scripts/manus_source/config.py 的 load_dotenv 一致：已存在的环境变量优先。
"""
import json
import os
import re
import urllib.request
from pathlib import Path

# 项目根 = 本文件（scripts/）的上级目录；.env 真实文件已被 .gitignore 忽略。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DOTENV_LOADED = False


def load_dotenv(path: str | Path) -> None:
    """最小 .env 解析；已存在的环境变量优先（不覆盖）。供测试直接调用。

    utf-8-sig 读取：兼容 Windows 编辑器写出的带 BOM 文件，避免首行 key 静默丢失。
    """
    p = Path(path)
    if not p.exists():
        return
    for raw_line in p.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def ensure_env_loaded() -> None:
    """幂等加载项目根 .env（进程内只执行一次）。"""
    global _DOTENV_LOADED
    if not _DOTENV_LOADED:
        load_dotenv(_PROJECT_ROOT / ".env")
        _DOTENV_LOADED = True


def resolve_model(tx: dict) -> str:
    """模型解析：LLM_MODEL 环境变量可覆盖 taxonomy.json 的 model（DeepSeek 之外的其他模型）。"""
    ensure_env_loaded()
    return os.environ.get("LLM_MODEL", "").strip() or tx["model"]["model"]


def model_request_options(model: str) -> dict:
    """返回模型专用的低成本请求参数。

    DeepSeek V4 默认启用思考模式；新闻分类和结构化抽取不需要思考过程，
    显式关闭可避免 reasoning tokens 占用输出预算。其他 OpenAI-compatible
    模型不接收 DeepSeek 私有字段，因此保持空对象。
    """
    if model.startswith("deepseek-v4-"):
        return {"thinking": {"type": "disabled"}}
    return {}


def call_llm(tx: dict, system: str, user: str, timeout_seconds: int | None = None) -> str:
    """OpenAI 兼容 /chat/completions，返回原始文本。缺 key/网络错误抛异常由上层处理。

    timeout_seconds 缺省沿用 taxonomy model 配置；长正文加工可传入更大值。
    """
    ensure_env_loaded()
    m = tx["model"]
    api_key = os.environ.get(m["api_key_env"], "")
    if not api_key:
        raise RuntimeError(f"环境变量 {m['api_key_env']} 未配置")
    base = os.environ.get(m["api_base_env"], "") or m["default_base"]
    model = resolve_model(tx)
    body = {
        "model": model,
        "temperature": m.get("temperature", 0),
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    body.update(model_request_options(model))
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=timeout_seconds or m.get("timeout_seconds", 20)) as resp:
        d = json.loads(resp.read().decode("utf-8"))
    return d["choices"][0]["message"]["content"] or ""


def parse_output(text: str) -> dict | None:
    """json_object 模式输出 → 裸 JSON → markdown 围栏剥离；失败返回 None。"""
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return d if isinstance(d, dict) else None
