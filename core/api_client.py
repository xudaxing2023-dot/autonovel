"""
core/api_client.py — 通用 OpenAI Chat Completions 兼容 API 客户端

支持所有遵循 OpenAI Chat Completions 格式的 API 提供商：
- NVIDIA NIM: https://integrate.api.nvidia.com/v1
- 硅基流动 SiliconFlow: https://api.siliconflow.cn/v1
- DeepSeek 官方: https://api.deepseek.com/v1
- 以及其他任何兼容端点

特性：
- 全局 4 秒速率限制 (RateLimiter 单例)
- 自动 system role 兼容 (不支持则合并到 user message)
- 统一超时、重试、错误处理
- 所有生成脚本通过此模块调用 LLM，消除重复代码
"""

import json
import time
import threading
import sys
from typing import Optional

import httpx

from core.config import config


# ============================================================================
# Rate Limiter — 全局单例，确保任意两次 API 调用间隔 >= 4 秒
# ============================================================================

class RateLimiter:
    """线程安全的全局速率限制器。"""

    def __init__(self, min_interval: float = 4.0):
        self._min_interval = min_interval
        self._last_call_time: float = 0.0
        self._lock = threading.Lock()

    def wait(self) -> float:
        """阻塞直到距上次调用 >= min_interval 秒。返回实际等待时间。"""
        with self._lock:
            now = time.time()
            elapsed = now - self._last_call_time
            wait_time = max(0.0, self._min_interval - elapsed)
            if wait_time > 0:
                time.sleep(wait_time)
            self._last_call_time = time.time()
            return wait_time

    @property
    def min_interval(self) -> float:
        return self._min_interval


# 全局速率限制器（间隔可从 config 覆盖）
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        cfg = config
        cfg.load()
        interval = cfg.api_interval_seconds if cfg.loaded else 4.0
        _rate_limiter = RateLimiter(min_interval=interval)
    return _rate_limiter


# ============================================================================
# API 客户端核心
# ============================================================================

# 已知不支持 system role 的模型 / 提供商特征
# 此列表用于自动降级：把 system prompt 合并到 user message 前缀
_SYSTEM_ROLE_BLACKLIST = [
    # 已知部分 llama.cpp / Ollama 端点不支持 system
    # 绝大多数主流 API 提供商都支持，这里仅做防御性保留
]
_SYSTEM_ROLE_FAILED_FOR_ENDPOINT: set = set()  # 运行时检测到不支持则缓存


def call_llm(
    prompt: str,
    system: Optional[str] = None,
    max_tokens: int = 16000,
    temperature: float = 0.8,
    timeout: int = 600,
    retries: int = 3,
    max_total_time: int = None,
) -> str:
    """
    调用 OpenAI Chat Completions 兼容 API。

    Args:
        prompt: 用户消息内容。
        system: 系统提示（可选）。如果 API 不支持 system role 则自动合并到 prompt 前。
        max_tokens: 最大生成 token 数。
        temperature: 采样温度。
        timeout: 请求超时（秒）。
        retries: 失败重试次数。
        max_total_time: 整个调用（含重试）的最长总耗时（秒）。None = 不限制。

    Returns:
        LLM 生成的文本内容。

    Raises:
        RuntimeError: 所有重试均失败，或超过 max_total_time 限制。
    """
    cfg = config
    cfg.load()

    api_base = cfg.api_base_url.rstrip("/")
    api_key = cfg.api_key
    model = cfg.model_name

    if not api_key:
        raise RuntimeError(
            "API Key 未配置。请运行 novel_app.bat 进行配置，"
            "或确保 .env 文件中有有效的 AUTONOVEL_API_KEY。"
        )

    # 构建 messages
    messages = []
    endpoint_key = f"{api_base}|{model}"

    if system and endpoint_key not in _SYSTEM_ROLE_FAILED_FOR_ENDPOINT:
        messages.append({"role": "system", "content": system})
    elif system:
        # 该端点已知不支持 system role，合并到 user message
        prompt = f"[系统指令]\n{system}\n\n---\n\n{prompt}"

    messages.append({"role": "user", "content": prompt})

    url = f"{api_base}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    limiter = get_rate_limiter()

    last_error = None
    t_start = time.time()

    for attempt in range(1, retries + 1):
        # 总超时检查（在速率限制等待之前，避免等待后才发现超时）
        if max_total_time is not None:
            elapsed_total = time.time() - t_start
            if elapsed_total > max_total_time:
                raise RuntimeError(
                    f"API 调用总超时: 累计 {elapsed_total:.0f}s 超过 "
                    f"{max_total_time}s 限制（共 {retries} 次重试机会）"
                )

        # 速率限制等待
        waited = limiter.wait()

        elapsed_total = time.time() - t_start if max_total_time is not None else 0
        total_info = f"（累计 {elapsed_total:.0f}s / 限制 {max_total_time}s）" if max_total_time is not None else ""

        if waited > 0.5:
            print(f"  [API] 速率限制等待 {waited:.1f}s ...", file=sys.stderr)

        print(f"  [API] 调用 {model} (max_tokens={max_tokens}, t={temperature}) ...",
              file=sys.stderr)

        try:
            resp = httpx.post(
                url,
                headers=headers,
                json=payload,
                timeout=timeout,
            )

            if resp.status_code == 200:
                data = resp.json()
                # 标准 OpenAI 响应路径
                try:
                    content = data["choices"][0]["message"]["content"]
                    token_count = data.get("usage", {}).get("total_tokens", "?")
                    print(f"  [API] 成功 — {token_count} tokens, "
                          f"{len(content)} chars", file=sys.stderr)
                    return content
                except (KeyError, IndexError, TypeError) as e:
                    print(f"  [API] 响应格式异常: {e}", file=sys.stderr)
                    print(f"  [API] 原始响应: {json.dumps(data, ensure_ascii=False)[:500]}",
                          file=sys.stderr)
                    last_error = RuntimeError(f"响应格式异常: {e}")
                    continue

            elif resp.status_code == 429:
                # 速率限制 — 等待更长时间后重试
                wait_extra = 10 * attempt
                print(f"  [API] 429 速率限制，额外等待 {wait_extra}s ...", file=sys.stderr)
                time.sleep(wait_extra)
                last_error = RuntimeError(f"HTTP 429: {resp.text[:300]}")
                continue

            elif resp.status_code in (400, 422):
                # 检查是否因为 system role 不支持
                error_text = resp.text.lower()
                if "system" in error_text and (
                    "not supported" in error_text
                    or "role" in error_text
                    or "invalid" in error_text
                ):
                    print(f"  [API] 检测到 system role 不支持，将自动降级合并到 user message",
                          file=sys.stderr)
                    _SYSTEM_ROLE_FAILED_FOR_ENDPOINT.add(endpoint_key)

                    # 重新构建 messages（无 system role）
                    messages = [{"role": "user", "content": f"[系统指令]\n{system}\n\n---\n\n{prompt}"}]
                    payload["messages"] = messages
                    continue

                print(f"  [API] 调用失败，重试 {attempt}/{retries}{total_info} — HTTP {resp.status_code}: {resp.text[:300]}",
                      file=sys.stderr)
                last_error = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                if attempt < retries:
                    time.sleep(5 * attempt)
                continue

            else:
                print(f"  [API] 调用失败，重试 {attempt}/{retries}{total_info} — HTTP {resp.status_code}: {resp.text[:300]}",
                      file=sys.stderr)
                last_error = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                if attempt < retries:
                    time.sleep(5 * attempt)
                continue

        except httpx.TimeoutException:
            print(f"  [API] 调用失败，重试 {attempt}/{retries}{total_info} — 超时 ({timeout}s)",
                  file=sys.stderr)
            last_error = RuntimeError(f"请求超时 ({timeout}s)")
            continue

        except httpx.RequestError as e:
            print(f"  [API] 调用失败，重试 {attempt}/{retries}{total_info} — 网络错误: {e}",
                  file=sys.stderr)
            last_error = e
            time.sleep(5 * attempt)
            continue

        except Exception as e:
            print(f"  [API] 异常: {e}", file=sys.stderr)
            last_error = e
            if attempt < retries:
                time.sleep(5 * attempt)
            continue

    raise RuntimeError(f"API 调用失败（{retries} 次重试后）: {last_error}")


# ============================================================================
# 便捷函数
# ============================================================================

def call_writer(
    prompt: str,
    system: Optional[str] = None,
    max_tokens: int = 16000,
    temperature: float = 0.8,
    retries: int = 3,
    max_total_time: int = None,
) -> str:
    """写作模型调用（默认高温度，偏创造力）。"""
    return call_llm(
        prompt, system=system, max_tokens=max_tokens, temperature=temperature,
        retries=retries, max_total_time=max_total_time,
    )


def call_judge(
    prompt: str,
    system: Optional[str] = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    retries: int = 3,
    max_total_time: int = None,
) -> str:
    """裁判模型调用（默认低温度，偏判断力）。

    如果配置了独立的 judge_model_name / judge_api_base_url，
    则使用独立模型进行判断，避免 Writer/Judge 同一模型的自评偏差。
    """
    cfg = config
    cfg.load()
    judge_model = cfg.judge_model_name
    judge_base = cfg.judge_api_base_url
    judge_key = cfg.judge_api_key

    # 如果配置了独立判断模型，使用独立调用
    if judge_model or judge_base or judge_key:
        return _call_with_judge_config(
            prompt, system=system, max_tokens=max_tokens, temperature=temperature,
            retries=retries, max_total_time=max_total_time,
            judge_model=judge_model or cfg.model_name,
            judge_base=judge_base or cfg.api_base_url,
            judge_key=judge_key or cfg.api_key,
        )

    # 否则退回共用模式（保持向后兼容）
    return call_llm(
        prompt, system=system, max_tokens=max_tokens, temperature=temperature,
        retries=retries, max_total_time=max_total_time,
    )


def _call_with_judge_config(
    prompt: str,
    system: Optional[str] = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    retries: int = 3,
    max_total_time: int = None,
    judge_model: str = "",
    judge_base: str = "",
    judge_key: str = "",
) -> str:
    """使用独立的 Judge 配置调用 API（内部函数，不对外暴露）。"""
    import time as _time
    url = judge_base.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {judge_key}",
        "Content-Type": "application/json",
    }
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": judge_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    limiter = get_rate_limiter()
    last_error = None
    t_start = _time.time()

    for attempt in range(1, retries + 1):
        if max_total_time is not None:
            elapsed_total = _time.time() - t_start
            if elapsed_total > max_total_time:
                raise RuntimeError(
                    f"Judge API 调用总超时: 累计 {elapsed_total:.0f}s 超过 "
                    f"{max_total_time}s 限制"
                )
        limiter.wait()
        try:
            resp = httpx.post(url, headers=headers, json=payload, timeout=600)
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            elif resp.status_code == 429:
                _time.sleep(10 * attempt)
                last_error = RuntimeError(f"HTTP 429: {resp.text[:300]}")
                continue
            else:
                print(f"  [Judge API] 调用失败 — HTTP {resp.status_code}: {resp.text[:200]}", file=sys.stderr)
                last_error = RuntimeError(f"HTTP {resp.status_code}")
                if attempt < retries:
                    _time.sleep(5 * attempt)
                continue
        except httpx.TimeoutException:
            last_error = RuntimeError("请求超时")
            continue
        except Exception as e:
            last_error = e
            if attempt < retries:
                _time.sleep(5 * attempt)
            continue

    raise RuntimeError(f"Judge API 调用失败（{retries} 次重试后）: {last_error}")