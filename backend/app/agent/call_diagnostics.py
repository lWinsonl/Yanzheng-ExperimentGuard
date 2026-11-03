"""Request-scoped, public-safe model diagnostics; never store prompts or keys."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import urllib.error


@dataclass
class ModelCallError:
    kind: str
    message: str
    retryable: bool = False
    http_status: int | None = None
    provider_code: str = ""


@dataclass
class CallDiagnostics:
    requested_model: str = ""
    response_model: str = ""
    error: ModelCallError | None = None


_active: ContextVar[CallDiagnostics | None] = ContextVar("llm_call_diagnostics", default=None)


@contextmanager
def capture_call_diagnostics():
    diagnostics = CallDiagnostics()
    token = _active.set(diagnostics)
    try:
        yield diagnostics
    finally:
        _active.reset(token)


def record_request(model: str):
    if (diagnostics := _active.get()) is not None:
        diagnostics.requested_model = model
        diagnostics.response_model = ""
        diagnostics.error = None


def record_success(model: str):
    if (diagnostics := _active.get()) is not None:
        diagnostics.response_model = model
        diagnostics.error = None


def record_failure(error: ModelCallError):
    if (diagnostics := _active.get()) is not None:
        diagnostics.error = error


def http_failure(status: int, code: str) -> ModelCallError:
    if code == "1305":
        kind, message, retryable = "provider_busy", "模型服务当前繁忙，本次复核未完成。请稍后再试，或手动尝试备用模型。", True
    elif code == "1302":
        kind, message, retryable = "rate_limited", "已达到该模型的调用速率限制。请等待其他请求结束后再试。", True
    elif code in {"1113", "1308", "1309", "1310", "1316", "1317", "1318", "1319", "1320", "1321"}:
        kind, message, retryable = "account_limit", "模型账户额度或套餐受限，请在智谱后台核对具体限制；重复提交不会解除限制。", False
    elif status == 401:
        kind, message, retryable = "authentication", "模型密钥验证失败，请管理员核对服务端 API Key。", False
    elif status == 403 or code in {"1311", "1314", "1315"}:
        kind, message, retryable = "permission", "当前密钥或账号无权使用该模型，请核对模型权限和密钥类型。", False
    elif status == 429:
        kind, message, retryable = "request_limited", "模型服务拒绝了本次请求，请按错误码核对调用限制。", True
    elif status >= 500:
        kind, message, retryable = "provider_unavailable", "模型服务暂时不可用，本次复核未完成。请稍后再试。", True
    else:
        kind, message, retryable = "invalid_request", "模型服务未接受请求，请管理员核对型号及调用参数。", False
    return ModelCallError(kind, message, retryable, status, code if code != "unknown" else "")


def exception_failure(error: Exception) -> ModelCallError:
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(reason, TimeoutError):
        return ModelCallError("timeout", "等待模型回复超时，本次复核未完成。请稍后再试，或手动尝试备用模型。", True)
    if isinstance(error, (urllib.error.URLError, OSError)):
        return ModelCallError("network", "与模型服务的连接中断或建立失败，本次复核未完成。请稍后再试。", True)
    return ModelCallError("invalid_response", "模型接口返回了无法处理的响应，本次复核未完成。")
