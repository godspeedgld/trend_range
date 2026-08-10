#!/usr/bin/env python
"""BigQuant SDK 运行时引导。

供自定义脚本复用：初始化 bigquant SDK、检查登录状态、返回 DataSource 引用。

用法：
  from pathlib import Path; import sys
  sys.path.append(str(Path("scripts").resolve()))
  from bigquant_runtime import init_bigquant

  DataSource = init_bigquant()
  df = DataSource('bar1d_CN_FUTURE').read(start_date='2024-01-01', end_date='2025-06-30')
"""

from __future__ import annotations

import sys


def check_installed() -> bool:
    """检查 bigquant 包是否安装。"""
    try:
        import bigquant  # noqa: F401
        return True
    except ImportError:
        return False


def init_bigquant():
    """初始化 BigQuant SDK，返回 DataSource 类。

    认证：SDK 自动读取 ~/.bigquant/config.json 中的 AK/SK 密钥对。
    获取密钥：https://bigquant.com/account/settings → API 密钥
    """
    if not check_installed():
        print("错误: bigquant SDK 未安装。请执行: pip install bigquant -U", file=sys.stderr)
        print("", file=sys.stderr)
        print("安装后需配置 AK/SK 到 ~/.bigquant/config.json", file=sys.stderr)
        print("获取密钥: https://bigquant.com/account/settings", file=sys.stderr)
        raise ImportError("bigquant not installed")

    from bigquant import dai
    print("[bigquant] SDK 已就绪", file=sys.stderr)
    return dai
