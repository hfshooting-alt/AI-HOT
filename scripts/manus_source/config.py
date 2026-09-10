"""config.py — Manus 信源运行配置（环境变量 + 本地 .env，纯标准库）。"""
import os
from dataclasses import dataclass
from pathlib import Path

ALLOWED_PROFILES = {"manus-1.6-lite", "manus-1.6", "manus-1.6-max"}
ALLOWED_CONTENT_MODES = {"script", "manus"}


def load_dotenv(path: Path) -> None:
    """无第三方依赖的最小 .env 加载；已存在的环境变量优先。

    utf-8-sig 读取：兼容 Windows 编辑器写出的带 BOM 文件，避免首行 key 静默丢失
    （与 llm_common.load_dotenv 语义保持一致）。
    """
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class Settings:
    manus_api_key: str
    manus_agent_profile: str
    poll_seconds: int
    timeout_seconds: int
    register_grace_seconds: int
    content_batch_size: int
    content_concurrency: int
    content_mode: str
    crawl_timeout_seconds: int
    crawl_retries: int
    crawl_concurrency: int
    crawl_request_delay_seconds: float
    crawl_user_agent: str | None
    crawl_jina_fallback: bool
    max_content_chars: int
    min_content_chars: int
    sources_path: Path
    discovery_prompt_path: Path
    content_prompt_path: Path
    work_dir: Path

    @classmethod
    def from_environment(cls, project_root: Path) -> "Settings":
        load_dotenv(project_root / ".env")
        if not os.getenv("MANUS_API_KEY"):
            raise RuntimeError("Missing required environment variable: MANUS_API_KEY")
        agent_profile = os.getenv("MANUS_AGENT_PROFILE", "manus-1.6")
        if agent_profile not in ALLOWED_PROFILES:
            raise RuntimeError("MANUS_AGENT_PROFILE must be one of: " + ", ".join(sorted(ALLOWED_PROFILES)))
        content_mode = os.getenv("MANUS_CONTENT_MODE", "script")
        if content_mode not in ALLOWED_CONTENT_MODES:
            raise RuntimeError("MANUS_CONTENT_MODE must be one of: " + ", ".join(sorted(ALLOWED_CONTENT_MODES)))

        def rel(env_value: str, default: str) -> Path:
            p = Path(os.getenv(env_value, default))
            return p if p.is_absolute() else project_root / p

        sources_path = rel("MANUS_SOURCES_PATH", "config/manus_sources.json")
        if not sources_path.exists():
            raise RuntimeError(f"Manus sources config does not exist: {sources_path}")
        discovery_prompt_path = rel("MANUS_DISCOVERY_PROMPT_PATH", "scripts/prompts/manus_discovery.md")
        if not discovery_prompt_path.exists():
            raise RuntimeError(f"Manus discovery prompt does not exist: {discovery_prompt_path}")
        return cls(
            manus_api_key=os.environ["MANUS_API_KEY"],
            manus_agent_profile=agent_profile,
            poll_seconds=int(os.getenv("MANUS_POLL_SECONDS", "10")),
            timeout_seconds=int(os.getenv("MANUS_TIMEOUT_SECONDS", "3600")),
            register_grace_seconds=int(os.getenv("MANUS_REGISTER_GRACE_SECONDS", "90")),
            content_batch_size=int(os.getenv("MANUS_CONTENT_BATCH_SIZE", "4")),
            content_concurrency=int(os.getenv("MANUS_CONTENT_CONCURRENCY", "2")),
            content_mode=content_mode,
            crawl_timeout_seconds=int(os.getenv("MANUS_CRAWL_TIMEOUT_SECONDS", "20")),
            crawl_retries=int(os.getenv("MANUS_CRAWL_RETRIES", "2")),
            crawl_concurrency=int(os.getenv("MANUS_CRAWL_CONCURRENCY", "4")),
            crawl_request_delay_seconds=float(os.getenv("MANUS_CRAWL_REQUEST_DELAY_SECONDS", "1.0")),
            crawl_user_agent=os.getenv("MANUS_CRAWL_UA") or None,
            crawl_jina_fallback=os.getenv("MANUS_CRAWL_JINA_FALLBACK", "").lower() in ("1", "true", "yes"),
            max_content_chars=int(os.getenv("MANUS_MAX_CONTENT_CHARS", "20000")),
            min_content_chars=int(os.getenv("MANUS_MIN_CONTENT_CHARS", "100")),
            sources_path=sources_path,
            discovery_prompt_path=discovery_prompt_path,
            content_prompt_path=rel("MANUS_CONTENT_PROMPT_PATH", "scripts/prompts/manus_content.md"),
            work_dir=rel("MANUS_WORK_DIR", "work/manus"),
        )


def load_sources(path: Path) -> dict:
    """读取 manus_sources.json（唯一账号配置源），返回 {group: [来源...]}。"""
    import json
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    groups = data.get("groups")
    if not isinstance(groups, dict) or not groups:
        raise RuntimeError(f"manus_sources.json 缺少非空 groups：{path}")
    for group, sources in groups.items():
        if not isinstance(sources, list) or not sources:
            raise RuntimeError(f"manus_sources.json 分组 {group} 为空或非法")
        for s in sources:
            for field in ("account_name", "platform", "home_url"):
                if not s.get(field):
                    raise RuntimeError(f"manus_sources.json 分组 {group} 来源缺少字段 {field}")
    return groups


def render_sources_block(sources: list[dict]) -> str:
    """把一组来源渲染成 prompt 中的编号清单（与原 prompt 版式一致）。"""
    lines = []
    for i, s in enumerate(sources, 1):
        lines.append(f"{i}. 媒体名称：{s['account_name']}")
        lines.append(f"   - url：{s['home_url']}")
        lines.append(f"   - 平台：{s['platform']}")
    return "\n".join(lines)
