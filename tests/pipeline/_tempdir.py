"""tests/_tempdir.py — 沙箱兼容的临时目录创建。

Windows 沙箱下 tempfile.mkdtemp（内部以 mode=0o700 创建）生成的目录无法再
创建子目录（WinError 5 权限拒绝）；改用默认权限（0o777 & umask）的 makedirs，
语义不变、跨平台可移植。
"""
import os
import tempfile
import uuid


def make_temp_dir(prefix: str = "test-") -> str:
    path = os.path.join(tempfile.gettempdir(), f"{prefix}{uuid.uuid4().hex}")
    os.makedirs(path, exist_ok=True)
    return path
