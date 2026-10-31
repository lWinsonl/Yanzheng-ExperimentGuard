"""LLM 客户端(OpenAI 兼容接口)。

支持任何 OpenAI 兼容服务(OpenAI / DeepSeek / 通义千问 / 本地 vLLM 等)。
API 密钥仅存在于服务端环境变量,绝不下发前端。

无密钥时 is_available() 返回 False,智能体降级到启发式规则,
不报错、不阻断,但明确告知用户"接入模型可获得更深入分析"。
"""

from __future__ import annotations

import json
import logging
import re

from app.config import settings

logger = logging.getLogger("llm_client")


class LlmClient:
    """OpenAI 兼容 LLM 客户端。"""

    def __init__(self) -> None:
        self._cached_available: bool | None = None

    def is_available(self) -> bool:
        """是否配置了可用的模型密钥。"""
        if self._cached_available is not None:
            return self._cached_available
        available = bool(settings.llm_api_key and settings.llm_base_url and settings.llm_model)
        self._cached_available = available
        if not available:
            logger.info("LLM 未配置(缺 api_key/base_url/model),智能体将使用启发式降级模式")
        return available

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 2000,
        timeout: int = 20,
    ) -> str | None:
        """调用模型,返回原始文本。失败返回 None(调用方自行降级)。"""
        if not self.is_available():
            return None
        try:
            import urllib.request

            url = settings.llm_base_url.rstrip("/") + "/chat/completions"
            payload = json.dumps(
                {
                    "model": settings.llm_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
                ensure_ascii=False,
            ).encode("utf-8")

            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {settings.llm_api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM 调用失败,降级到启发式:%s", exc)
            return None

    @staticmethod
    def parse_json_response(raw: str) -> dict | list | None:
        """解析模型 JSON 输出,容错处理 markdown 代码块包裹。"""
        if not raw:
            return None
        text = raw.strip()
        m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if m:
            text = m.group(1).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None


# 全局单例
llm_client = LlmClient()