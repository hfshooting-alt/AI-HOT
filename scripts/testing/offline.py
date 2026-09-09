"""默认测试禁止网络和子进程；模拟 transport 不受影响。"""
from contextlib import ExitStack, contextmanager
import os
import socket
import subprocess
from unittest.mock import patch


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
