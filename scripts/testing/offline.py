"""默认测试禁止网络和子进程；模拟 transport 不受影响。"""
from contextlib import ExitStack, contextmanager
import os
import socket
import subprocess
from pathlib import Path
from unittest.mock import patch

import llm_common
from manus_source import config as manus_config

PROJECT_ENV = Path(__file__).resolve().parents[2] / '.env'


def without_project_env(loader):
    """保留临时文件的 dotenv 单测，禁止加载开发者的真实配置。"""
    def load(path):
        if Path(path).resolve() != PROJECT_ENV.resolve():
            return loader(path)
    return load


class OfflineViolation(RuntimeError):
    pass


@contextmanager
def isolated():
    violations = []

    def denied(*args, **kwargs):
        # 不记录参数，避免请求头/命令中的密钥进入日志。
        violations.append("network_or_subprocess")
        raise OfflineViolation("离线测试禁止真实网络和子进程；请注入模拟响应")

    with ExitStack() as stack:
        for module in (llm_common, manus_config):
            stack.enter_context(patch.object(module, 'load_dotenv', without_project_env(module.load_dotenv)))
        stack.enter_context(patch.object(llm_common, '_DOTENV_LOADED', False))
        # 不提供默认测试模型，以免再次掩盖测试夹具缺少模型配置的问题。
        stack.enter_context(patch.dict(os.environ, {'LLM_MODEL': '', 'LLM_API_BASE': ''}))
        stack.enter_context(patch.dict(os.environ, {'PARATERA_API_KEY': ''}))
        for target, names in (
            (socket, ("create_connection", "getaddrinfo")),
            (socket.socket, ("connect", "connect_ex", "sendto")),
            (subprocess, ("Popen",)),
            (os, ("system",)),
        ):
            for name in names:
                stack.enter_context(patch.object(target, name, denied))
        stack.enter_context(patch.dict(os.environ, {
            name: "offline-test-disabled" for name in (
                "MANUS_API_KEY", "DEEPSEEK_API_KEY", "TAVILY_API_KEY")
        }))
        yield violations
