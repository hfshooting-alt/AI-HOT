#!/usr/bin/env python3
"""默认离线回归；Manus/LLM 真实探针均需使用显式的受限模式。"""
import argparse
import json
import os
from pathlib import Path
import sys
import unittest

from manus_source.config import load_dotenv
from testing.offline import isolated
from testing.manus_probe import ProbeError, auth, smoke
from testing.llm_probe import LLMProbeError, smoke as llm_smoke
from testing.llm_business_probe import smoke as llm_business_smoke

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", default="offline",
                        choices=("offline", "manus-auth", "manus-smoke", "llm-smoke",
                                 "llm-business-smoke"))
    parser.add_argument("--refresh", action="store_true", help="重新进行一次只读认证检查")
    parser.add_argument("--allow-paid", action="store_true",
                        help="允许单个受限付费探针，仍受各服务每日一次限制")
    parser.add_argument("--allow-retry-after-fix", action="store_true",
                        help="仅允许 LLM 首次结构化失败后补一次修复验证")
    args = parser.parse_args(argv)
    if args.mode == "offline":
        with isolated() as violations:
            suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
            result = unittest.TextTestRunner(verbosity=1).run(suite)
        # 即使业务代码捕获了网络异常，违规也会令这次测试失败。
        if violations:
            print(f"离线保护拦截 {len(violations)} 次网络/子进程调用", file=sys.stderr)
        return 0 if result.wasSuccessful() and not violations else 1
    if args.mode in ("manus-smoke", "llm-smoke", "llm-business-smoke") and not args.allow_paid:
        parser.error(f"{args.mode} 可能产生费用，需要 --allow-paid")
    load_dotenv(ROOT / ".env")
    if args.mode == "llm-smoke":
        try:
            tx = json.loads((ROOT / "config/taxonomy.json").read_text(encoding="utf-8"))
            report = llm_smoke(ROOT, tx, allow_paid=True,
                               allow_retry_after_fix=args.allow_retry_after_fix)
        except (LLMProbeError, OSError, ValueError, KeyError) as exc:
            print(exc.code if isinstance(exc, LLMProbeError) else "模型测试配置不可读")
            return 1
        print(json.dumps({k: v for k, v in report.items() if k != "keyFingerprint"},
                         ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1
    if args.mode == "llm-business-smoke":
        try:
            tx = json.loads((ROOT / "config/taxonomy.json").read_text(encoding="utf-8"))
            report = llm_business_smoke(
                ROOT, tx, ROOT / "tests/fixtures/llm_business_smoke.json", allow_paid=True)
        except (LLMProbeError, OSError, ValueError, KeyError) as exc:
            print(exc.code if isinstance(exc, LLMProbeError) else "业务测试配置不可读")
            return 1
        print(json.dumps({k: v for k, v in report.items() if k != "keyFingerprint"},
                         ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1
    key = os.getenv("MANUS_API_KEY", "").strip()
    if not key or key.startswith("your-"):
        print("缺少 MANUS_API_KEY")
        return 1
    try:
        report = auth(ROOT, key, refresh=args.refresh) if args.mode == "manus-auth" else smoke(ROOT, key, allow_paid=True)
    except (ProbeError, OSError, ValueError) as exc:
        print(exc.code if isinstance(exc, ProbeError) else "测试状态文件异常，请检查 work/test-cost")
        return 1
    print(json.dumps({k: v for k, v in report.items() if k != "keyFingerprint"}, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
