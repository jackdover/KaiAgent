"""沙箱环境 — 为 L2 (SANDBOX) 权限级别提供隔离执行环境。"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from types import TracebackType
from typing import Any


class Sandbox:
    """沙箱环境 — 在临时目录中隔离执行。

    提供:
    - 临时工作目录 (自动清理)
    - 受限的文件系统访问
    - 环境变量的隔离

    使用方式:
        async with Sandbox() as sandbox:
            work_dir = sandbox.work_dir
            # 在 work_dir 中执行操作
    """

    def __init__(
        self,
        prefix: str = "harness_sandbox_",
        copy_from: str | None = None,
        env_whitelist: list[str] | None = None,
    ):
        self._prefix = prefix
        self._copy_from = Path(copy_from) if copy_from else None
        self._env_whitelist = env_whitelist or ["PATH", "HOME", "USER"]
        self._work_dir: Path | None = None
        self._original_env: dict[str, str] = {}

    async def __aenter__(self) -> Sandbox:
        self.create()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_val: BaseException | None = None,
        exc_tb: TracebackType | None = None,
    ) -> None:
        self.cleanup()

    def create(self) -> Path:
        """创建沙箱工作目录。"""
        self._work_dir = Path(tempfile.mkdtemp(prefix=self._prefix))

        # 复制初始内容
        if self._copy_from and self._copy_from.exists():
            for item in self._copy_from.iterdir():
                dst = self._work_dir / item.name
                if item.is_dir():
                    shutil.copytree(item, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dst)

        # 隔离环境变量
        self._original_env = dict(os.environ)
        os.environ.clear()
        for key in self._env_whitelist:
            if key in self._original_env:
                os.environ[key] = self._original_env[key]

        return self._work_dir

    @property
    def work_dir(self) -> Path:
        """获取沙箱工作目录。"""
        assert self._work_dir is not None, "Sandbox not created"
        return self._work_dir

    def cleanup(self) -> None:
        """清理沙箱环境。"""
        if self._work_dir and self._work_dir.exists():
            shutil.rmtree(self._work_dir, ignore_errors=True)
            self._work_dir = None

        # 恢复环境变量
        os.environ.clear()
        os.environ.update(self._original_env)

    def resolve_path(self, path: str) -> Path:
        """在沙箱内解析路径，防止路径逃逸。

        Args:
            path: 用户提供的路径 (相对或绝对)

        Returns:
            Path: 沙箱内的绝对路径

        Raises:
            PermissionError: 如果路径试图逃逸沙箱
        """
        assert self._work_dir is not None, "Sandbox not created"

        # 解析为沙箱内的路径
        joined = self._work_dir / path
        resolved = joined.resolve()

        # 检查是否在沙箱目录内
        try:
            resolved.relative_to(self._work_dir.resolve())
        except ValueError:
            raise PermissionError(
                f"Path '{path}' escapes sandbox directory "
                f"(resolved to '{resolved}')"
            )

        return resolved

    def copy_out(self, src_path: str, dst_path: str) -> None:
        """从沙箱复制文件到外部。"""
        src = self.resolve_path(src_path)
        dst = Path(dst_path)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    def copy_in(self, src_path: str, dst_path: str) -> None:
        """从外部复制文件到沙箱。"""
        src = Path(src_path)
        dst = self.resolve_path(dst_path)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
