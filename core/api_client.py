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
- Phase 分离模型配置（方案 D）：各 Phase 可使用独立 API Key/Base URL/Model
"""

import json
import time
import threading
import sys
from typing import Optional

import httpx

from core.config import config

# 可选导入 debug_log（避免循环导入）
try:
    from core.diagnostic import debug_log as _debug_log
except ImportError:
    def _debug_log(*args, **kwargs):
        pass


from core import _stderr_print


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


def _build_messages(
    prompt: str,
    system: Optional[str],
    api_base: str,
    model: str) -> list:
    """构建 messages 列表，处理 system role 兼容性。

    如果端点已知不支持 system role，则将 system prompt 合并到 user message 前缀。
    运行时新检测到的不支持端点由 _call_llm_internal 的 400/422 处理逻辑覆盖。
    """
    messages: list = []
    endpoint_key = f"{api_base}|{model}"

    if system and endpoint_key not in _SYSTEM_ROLE_FAILED_FOR_ENDPOINT:
        messages.append({"role": "system", "content": system})
    elif system:
        prompt = f"[系统指令]\n{system}\n\n---\n\n{prompt}"

    messages.append({"role": "user", "content": prompt})
    return messages


def _call_llm_internal(
    api_key: str,
    api_base: str,
    model: str,
    prompt: str,
    system: Optional[str],
    messages: list,
    temperature: float = 0.8,
    timeout: int = 600,
    retries: int = 5,
    max_total_time: int = None) -> str:
    """HTTP 引擎——封装 HTTP 调用、速率限制、重试、错误处理。

    从原 call_llm 提取的核心逻辑，参数化 api_key/api_base/model，
    使得 Phase 路由成为可能。

    超时策略（梯级递增，适用于所有模型）:
    - 第1次尝试: timeout=600s,  第2次: timeout=1200s,  第3次: timeout=1800s, ...
    - 重试间隔: 15s × attempt (指数退避)
    - max_total_time 未指定时: 自动按 Σ(timeout × attempt) 计算
    """
    if not api_key:
        raise RuntimeError(
            "API Key 未配置。请运行 novel_app.bat 进行配置，"
            "或确保 .env 文件中有有效的 AUTONOVEL_API_KEY。"
        )

    # ★ 自动计算总超时：Σ(timeout × attempt) for attempt in 1..retries
    if max_total_time is None:
        max_total_time = sum(timeout * a for a in range(1, retries + 1))

    endpoint_key = f"{api_base}|{model}"
    url = f"{api_base}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }

    limiter = get_rate_limiter()

    last_error = None
    t_start = time.time()

    for attempt in range(1, retries + 1):
        # 总超时检查（在速率限制等待之前，避免等待后才发现超时）
        elapsed_total = time.time() - t_start
        if elapsed_total > max_total_time:
            raise RuntimeError(
                f"API 调用总超时: 累计 {elapsed_total:.0f}s 超过 "
                f"{max_total_time}s 限制（共 {retries} 次重试机会）"
            )

        # 速率限制等待
        waited = limiter.wait()

        total_info = f"（累计 {elapsed_total:.0f}s / 限制 {max_total_time}s）"

        if waited > 0.5:
            _stderr_print(f"  [API] 速率限制等待 {waited:.1f}s ...")

        # ★ 梯级递增超时: 第N次尝试使用 timeout × N
        attempt_timeout = timeout * attempt
        prompt_len = len(prompt) if prompt else (len(str(messages)) if messages else 0)
        _debug_log("API_CALL", data={
            "model": model, "temperature": temperature,
            "attempt": attempt, "retries": retries,
            "timeout": attempt_timeout, "prompt_len": prompt_len,
        })
        _stderr_print(f"  [API] 调用 {model} (t={temperature}, timeout={attempt_timeout}s) ...")

        t_call_start = time.time()
        try:
            resp = httpx.post(
                url,
                headers=headers,
                json=payload,
                timeout=attempt_timeout)

            latency_s = round(time.time() - t_call_start, 1)

            if resp.status_code == 200:
                data = resp.json()
                # 标准 OpenAI 响应路径
                try:
                    content = data["choices"][0]["message"]["content"]
                    token_count = data.get("usage", {}).get("total_tokens", "?")
                    _debug_log("API_SUCCESS", data={
                        "model": model, "latency_s": latency_s,
                        "result_len": len(content), "tokens": token_count,
                    })
                    _stderr_print(f"  [API] 成功 — {token_count} tokens, "
                          f"{len(content)} chars")
                    return content
                except (KeyError, IndexError, TypeError) as e:
                    _debug_log("API_RETRY", f"响应格式异常: {e}",
                               data={"attempt": attempt, "model": model})
                    _stderr_print(f"  [API] 响应格式异常: {e}")
                    _stderr_print(f"  [API] 原始响应: {json.dumps(data, ensure_ascii=False)[:500]}")
                    last_error = RuntimeError(f"响应格式异常: {e}")
                    continue

            elif resp.status_code == 429:
                # 速率限制 — 等待更长时间后重试
                wait_extra = 10 * attempt
                _debug_log("API_RETRY", f"HTTP 429 速率限制",
                           data={"attempt": attempt, "model": model, "wait_s": wait_extra})
                _stderr_print(f"  [API] 429 速率限制，额外等待 {wait_extra}s ...")
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
                    _stderr_print(f"  [API] 检测到 system role 不支持，将自动降级合并到 user message")
                    _SYSTEM_ROLE_FAILED_FOR_ENDPOINT.add(endpoint_key)

                    # 重新构建 messages（无 system role）
                    messages = [{"role": "user", "content": f"[系统指令]\n{system}\n\n---\n\n{prompt}"}]
                    payload["messages"] = messages
                    continue

                _stderr_print(f"  [API] 调用失败，重试 {attempt}/{retries}{total_info} — HTTP {resp.status_code}: {resp.text[:300]}")
                last_error = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                if attempt < retries:
                    time.sleep(15 * attempt)
                continue

            else:
                _stderr_print(f"  [API] 调用失败，重试 {attempt}/{retries}{total_info} — HTTP {resp.status_code}: {resp.text[:300]}")
                last_error = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                if attempt < retries:
                    time.sleep(15 * attempt)
                continue

        except httpx.TimeoutException:
            latency_s = round(time.time() - t_call_start, 1)
            _debug_log("API_RETRY", f"超时 ({attempt_timeout}s)",
                       data={"attempt": attempt, "model": model,
                             "latency_s": latency_s, "max_retries": retries,
                             "error": f"Timeout ({attempt_timeout}s)"})
            _stderr_print(f"  [API] 调用失败，重试 {attempt}/{retries}{total_info} — 超时 ({attempt_timeout}s)")
            last_error = RuntimeError(f"请求超时 ({attempt_timeout}s)")
            continue

        except httpx.RequestError as e:
            latency_s = round(time.time() - t_call_start, 1)
            _debug_log("API_RETRY", f"网络错误: {e}",
                       data={"attempt": attempt, "model": model,
                             "latency_s": latency_s, "max_retries": retries,
                             "error": str(e)[:200]})
            _stderr_print(f"  [API] 调用失败，重试 {attempt}/{retries}{total_info} — 网络错误: {e}")
            last_error = e
            time.sleep(15 * attempt)
            continue

        except Exception as e:
            latency_s = round(time.time() - t_call_start, 1)
            _debug_log("API_RETRY", f"异常: {e}",
                       data={"attempt": attempt, "model": model,
                             "latency_s": latency_s, "max_retries": retries,
                             "error": str(e)[:200]})
            _stderr_print(f"  [API] 异常: {e}")
            last_error = e
            if attempt < retries:
                time.sleep(15 * attempt)
            continue

    _debug_log("API_FAIL", f"全部 {retries} 次重试耗尽",
               data={"model": model, "retries": retries,
                     "last_error": str(last_error)[:200]})
    raise RuntimeError(f"API 调用失败（{retries} 次重试后）: {last_error}")


def call_llm(
    prompt: str,
    system: Optional[str] = None,
    temperature: float = 0.8,
    timeout: int = 600,
    retries: int = 5,
    max_total_time: int = None) -> str:
    """调用 OpenAI Chat Completions 兼容 API。（行为不变）"""
    cfg = config
    cfg.load()

    api_base = cfg.api_base_url.rstrip("/")
    api_key = cfg.api_key
    model = cfg.model_name

    messages = _build_messages(prompt, system, api_base, model)

    return _call_llm_internal(
        api_key=api_key,
        api_base=api_base,
        model=model,
        prompt=prompt,
        system=system,
        messages=messages,
        temperature=temperature,
        timeout=timeout,
        retries=retries,
        max_total_time=max_total_time)


# ============================================================================
# 便捷函数
# ============================================================================

def call_writer(
    prompt: str,
    system: Optional[str] = None,
    temperature: float = 0.8,
    retries: int = 5,
    max_total_time: int = None) -> str:
    """写作模型调用（默认高温度，偏创造力）。"""
    return call_llm(
        prompt, system=system, temperature=temperature,
        retries=retries, max_total_time=max_total_time)


def call_judge(
    prompt: str,
    system: Optional[str] = None,
    temperature: float = 0.3,
    retries: int = 5,
    max_total_time: int = None) -> str:
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
            prompt, system=system, temperature=temperature,
            retries=retries, max_total_time=max_total_time,
            judge_model=judge_model or cfg.model_name,
            judge_base=judge_base or cfg.api_base_url,
            judge_key=judge_key or cfg.api_key)

    # 否则退回共用模式（保持向后兼容）
    return call_llm(
        prompt, system=system, temperature=temperature,
        retries=retries, max_total_time=max_total_time)


def _call_with_judge_config(
    prompt: str,
    system: Optional[str] = None,
    temperature: float = 0.3,
    retries: int = 5,
    max_total_time: int = None,
    judge_model: str = "",
    judge_base: str = "",
    judge_key: str = "") -> str:
    """使用独立的 Judge 配置调用 API（内部函数）。"""
    api_base = judge_base.rstrip("/")
    model = judge_model

    messages = _build_messages(prompt, system, api_base, model)

    return _call_llm_internal(
        api_key=judge_key,
        api_base=api_base,
        model=model,
        prompt=prompt,
        system=system,
        messages=messages,
        temperature=temperature,
        timeout=600,
        retries=retries,
        max_total_time=max_total_time)


# ============================================================================
# Phase 路由层（方案 D）
# ============================================================================

def _call_with_phase_config(
    phase: str,
    prompt: str,
    system: Optional[str] = None,
    temperature: float = 0.8,
    retries: int = 5,
    max_total_time: int = None) -> str:
    """按 Phase 选择 API 配置并调用 LLM。

    Args:
        phase: "p1" | "p2" | "p2_ctx" | "p3"
        其他参数同 call_llm。

    回退链由 config 的 Phase 属性自动处理 — 本函数直接 getattr 即可：
        p1:     p1_*     → 共用_*
        p2:     p2_*     → p1_*      → 共用_*
        p2_ctx: p2_ctx_* → p2_*      → p1_*      → 共用_*
        p3:     p3_*     → p1_*      → 共用_*
    """
    cfg = config
    cfg.load()

    api_key = getattr(cfg, f"{phase}_api_key")
    api_base = getattr(cfg, f"{phase}_api_base_url").rstrip("/")
    model = getattr(cfg, f"{phase}_model_name")

    messages = _build_messages(prompt, system, api_base, model)

    return _call_llm_internal(
        api_key=api_key,
        api_base=api_base,
        model=model,
        prompt=prompt,
        system=system,
        messages=messages,
        temperature=temperature,
        timeout=600,
        retries=retries,
        max_total_time=max_total_time)


# ============================================================================
# Phase 特定调用函数（方案 D）
# — 回退链由 config 的 Phase 属性自动处理
# — P2/P3 未配置时自动 → P1 → 共用
# ============================================================================

def call_p1_writer(
    prompt: str,
    system: Optional[str] = None,
    temperature: float = 0.8,
    retries: int = 3,
    max_total_time: int = None) -> str:
    """Phase 1 写作调用 — 使用 AUTONOVEL_P1_* 配置。

    用于: world / characters / outline / canon / voice 生成。
    回退链: p1_* → 共用_*
    """
    return _call_with_phase_config(
        "p1", prompt, system=system,
        temperature=temperature, retries=retries, max_total_time=max_total_time)


def call_p2_writer(
    prompt: str,
    system: Optional[str] = None,
    temperature: float = 0.8,
    retries: int = 3,
    max_total_time: int = None) -> str:
    """Phase 2 写作调用 — 使用 AUTONOVEL_P2_* 配置。

    用于: 章节起草（需要大上下文窗口）。
    回退链: p2_* → p1_* → 共用_*
    """
    return _call_with_phase_config(
        "p2", prompt, system=system,
        temperature=temperature, retries=retries, max_total_time=max_total_time)


def call_p2_ctx_writer(
    prompt: str,
    system: Optional[str] = None,
    temperature: float = 0.8,
    retries: int = 3,
    max_total_time: int = None) -> str:
    """Phase 2 大上下文写作调用 — 使用 AUTONOVEL_P2_CTX_* 配置。

    用于: canon 增量追加等大上下文任务。
    回退链: p2_ctx_* → p2_* → p1_* → 共用_*
    """
    return _call_with_phase_config(
        "p2_ctx", prompt, system=system,
        temperature=temperature, retries=retries, max_total_time=max_total_time)


def call_p3_judge(
    prompt: str,
    system: Optional[str] = None,
    temperature: float = 0.3,
    retries: int = 3,
    max_total_time: int = None) -> str:
    """Phase 3 裁判调用 — 使用 AUTONOVEL_P3_* 配置。

    用于: 对抗编辑、读者评审、全文评估等修订阶段裁判任务。
    回退链: p3_* → p1_* → 共用_*
    """
    return _call_with_phase_config(
        "p3", prompt, system=system,
        temperature=temperature, retries=retries, max_total_time=max_total_time)