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
from typing import Literal

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
        timeout: float | None = None,
        retries: int = 0,
        thinking: Literal["enabled", "disabled"] | None = None,
    ) -> str | None:
        """调用模型,返回原始文本。失败返回 None(调用方自行降级)。

        retries: 失败后重试次数(0=不重试)。重试间隔 1 秒,
        用于应对偶发超时/网络抖动——竞赛演示场景建议 deep_review 等长任务设 1-2。
        """
        if not self.is_available():
            return None
        import time
        import urllib.error
        import urllib.parse
        import urllib.request

        url = settings.llm_base_url.rstrip("/") + "/chat/completions"
        timeout = settings.llm_timeout_seconds if timeout is None else timeout
        body = {
            "model": settings.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        # Only send provider-specific parameters to the model we adapted.
        # Other compatible services keep their existing request format.
        if (urllib.parse.urlparse(url).hostname == "open.bigmodel.cn"
                and settings.llm_model.lower() == "glm-4.7-flash"):
            body["thinking"] = {"type": thinking or settings.llm_thinking}
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")

        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            from app.access import current_owner, demo_access
            if not demo_access.allow_model(current_owner.get()):
                logger.warning("演示服务本小时模型调用额度已用尽，返回未完成状态或练习反馈")
                return None
            try:
                req = urllib.request.Request(
                    url,
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {settings.llm_api_key}",
                    },
                    method="POST",
                )
                logger.info("LLM request model=%s timeout=%s max_tokens=%d thinking=%s",
                            settings.llm_model, timeout, max_tokens,
                            body.get("thinking", {}).get("type", "provider_default"))
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    choice = data["choices"][0]
                    logger.info("LLM response model=%s finish_reason=%s",
                                data.get("model", settings.llm_model), choice.get("finish_reason"))
                    if choice.get("finish_reason") == "length":
                        logger.warning("LLM output truncated model=%s max_tokens=%d; result not adopted",
                                       settings.llm_model, max_tokens)
                        return None
                    return choice["message"]["content"]
            except urllib.error.HTTPError as exc:
                # Keep credentials, submitted text and provider response bodies
                # out of logs. A numeric business code is enough to triage 429.
                code = "unknown"
                try:
                    error = json.loads(exc.read(8192).decode("utf-8"))
                    candidate = error.get("error", {}).get("code")
                    if str(candidate).isascii() and str(candidate).isdigit():
                        code = str(candidate)[:10]
                except (ValueError, UnicodeError, AttributeError, OSError):
                    pass
                logger.warning("LLM HTTP failure model=%s status=%s provider_code=%s",
                               settings.llm_model, exc.code, code)
                last_exc = exc
                if attempt < retries:
                    time.sleep(1.0)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < retries:
                    logger.warning(
                        "LLM 调用失败(第 %d 次),%.0f 秒后重试:%s",
                        attempt + 1, 1.0, exc,
                    )
                    time.sleep(1.0)
        logger.warning("LLM 调用失败(已重试 %d 次),降级到启发式:%s", retries, last_exc)
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
