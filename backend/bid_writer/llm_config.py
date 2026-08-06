from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any


SYSTEM_PROMPT = "你是资深建筑工程技术标编制专家，输出严谨、可落地、可审查的技术标章节。"


def environment_value(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value not in (None, ""):
        return str(value)
    if os.name == "nt" and os.environ.get("BID_WRITER_DISABLE_USER_ENV") != "1":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                registry_value, _ = winreg.QueryValueEx(key, name)
            if registry_value not in (None, ""):
                return str(registry_value)
        except (FileNotFoundError, OSError):
            pass
    return default


def llm_settings() -> dict[str, Any]:
    api_key = environment_value("OPENAI_API_KEY")
    base_url = environment_value("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = environment_value("OPENAI_MODEL", "gpt-4.1-mini")
    wire_api = environment_value("OPENAI_WIRE_API", "chat_completions").strip().lower()
    if wire_api not in {"chat_completions", "responses"}:
        wire_api = "chat_completions"
    return {
        "provider": "openai-compatible",
        "configured": bool(api_key),
        "api_key_env": "OPENAI_API_KEY" if api_key else "",
        "base_url": base_url,
        "model": model,
        "wire_api": wire_api,
        "generation_mode": "llm" if api_key else "local_fallback",
        "note": "LLM configured via environment variables." if api_key else "OPENAI_API_KEY is not configured; section generation uses local fallback drafts.",
    }


def _response_text(data: dict[str, Any], wire_api: str) -> str:
    if wire_api == "chat_completions":
        return str(data["choices"][0]["message"]["content"] or "")

    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct

    parts: list[str] = []
    for output in data.get("output") or []:
        if not isinstance(output, dict):
            continue
        for content in output.get("content") or []:
            if not isinstance(content, dict):
                continue
            text = content.get("text") or content.get("output_text")
            if isinstance(text, str) and text:
                parts.append(text)
    if parts:
        return "\n".join(parts)

    # Some compatible gateways expose a Responses endpoint but return a
    # Chat Completions-shaped body.
    choices = data.get("choices") or []
    if choices and isinstance(choices[0], dict):
        message = choices[0].get("message") or {}
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return str(message["content"])
    return ""


def call_chat_completion(
    prompt: str,
    *,
    timeout: int = 120,
    instructions: str = SYSTEM_PROMPT,
    max_output_tokens: int | None = None,
) -> dict[str, Any]:
    settings = llm_settings()
    api_key = environment_value("OPENAI_API_KEY")
    if not api_key:
        return {**settings, "content": None, "error": "OPENAI_API_KEY is not configured."}
    configured_limit = int(environment_value("OPENAI_MAX_OUTPUT_TOKENS", "8000") or 8000)
    output_limit = max(32, min(max_output_tokens or configured_limit, 32000))
    if settings["wire_api"] == "responses":
        endpoint = f"{settings['base_url']}/responses"
        payload = {
            "model": settings["model"],
            "instructions": instructions,
            "input": prompt,
            "max_output_tokens": output_limit,
        }
    else:
        endpoint = f"{settings['base_url']}/chat/completions"
        payload = {
            "model": settings["model"],
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": output_limit,
        }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - user-configured endpoint.
            data = json.loads(response.read().decode("utf-8"))
        content = _response_text(data, str(settings["wire_api"]))
        if not content:
            return {
                **settings,
                "content": None,
                "latency_ms": round((time.time() - started) * 1000),
                "error": "Model response did not contain output text.",
            }
        return {
            **settings,
            "content": content,
            "latency_ms": round((time.time() - started) * 1000),
            "error": "",
        }
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        return {**settings, "content": None, "latency_ms": round((time.time() - started) * 1000), "error": f"HTTP {exc.code}: {detail[:500]}"}
    except Exception as exc:  # noqa: BLE001
        return {**settings, "content": None, "latency_ms": round((time.time() - started) * 1000), "error": f"{type(exc).__name__}: {exc}"}


def probe_llm() -> dict[str, Any]:
    settings = llm_settings()
    if not settings["configured"]:
        return {**settings, "ok": False, "latency_ms": 0, "error": "OPENAI_API_KEY is not configured."}
    result = call_chat_completion("请只回复 OK，用于检测模型连通性。", timeout=30, max_output_tokens=32)
    return {
        **settings,
        "ok": bool(result.get("content")) and not result.get("error"),
        "latency_ms": result.get("latency_ms", 0),
        "error": result.get("error", ""),
        "sample": str(result.get("content") or "")[:80],
    }
