"""pytest 全局配置。

所有后端单元测试强制关闭 LLM(不受 .env 真实密钥影响):
- 测试不依赖外网,断网也能跑;
- 测试结果确定,不受模型输出波动影响;
- 测试快速完成,不为每次提取真实调用 API。

如需测试 LLM 真实链路,请单独编写集成测试并在其中显式开启。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.agent.llm_client import llm_client


@pytest.fixture(autouse=True)
def _no_llm():
    """全局强制关闭 LLM,所有测试走规则/启发式路径。"""
    with patch.object(llm_client, "is_available", return_value=False):
        yield