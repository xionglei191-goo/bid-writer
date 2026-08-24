from __future__ import annotations

import json
import os
import time
from typing import Any

import requests


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


class LlmClient:
    def settings(self) -> dict[str, Any]:
        disabled = environment_value("BID_WRITER_DISABLE_LLM", "0") == "1"
        return {
            "configured": bool(environment_value("OPENAI_API_KEY")) and not disabled,
            "base_url": environment_value("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            "model": environment_value("OPENAI_MODEL", "gpt-5.6-luna"),
            "wire_api": environment_value("OPENAI_WIRE_API", "responses").lower(),
            "timeout_seconds": max(60, int(environment_value("OPENAI_TIMEOUT_SECONDS", "600"))),
            "reasoning_effort": environment_value("OPENAI_REASONING_EFFORT", "").strip().lower(),
        }

    def generate(self, instructions: str, prompt: str, max_output_tokens: int = 8000) -> dict[str, Any]:
        settings = self.settings()
        if not settings["configured"]:
            return {**settings, "content": "", "error": "大模型未配置或已禁用", "latency_ms": 0}
        headers = {
            "Authorization": f"Bearer {environment_value('OPENAI_API_KEY')}",
            "Content-Type": "application/json",
        }
        started = time.time()
        last_error = ""
        # 外部模型服务（如 opencode 网关）存在阵发性瞬时错误：连接被远端关闭、
        # 502/503、限流等。短退避重试无法跨过数十秒的服务抖动窗口，会整批失败
        # 并触发阶段熔断；因此使用拉长的退避序列，重试耗尽后才进入熔断统计。
        retry_backoff_seconds = (5, 20, 45)
        for attempt in range(1, len(retry_backoff_seconds) + 2):
            try:
                if settings["wire_api"] == "responses":
                    response = self._request(settings, headers, instructions, prompt, max_output_tokens)
                    response.raise_for_status()
                    data = response.json()
                    content = self._text(data, settings["wire_api"])
                    usage = self._usage(data)
                else:
                    content, usage = self._stream_chat_completions(
                        settings, headers, instructions, prompt, max_output_tokens
                    )
                if not content:
                    last_error = "模型未返回文本"
                else:
                    return {
                        **settings,
                        "content": content,
                        "error": "",
                        "latency_ms": round((time.time() - started) * 1000),
                        "attempts": attempt,
                        **usage,
                    }
            except requests.HTTPError as exc:
                last_error = f"HTTPError: {exc}"
                status = exc.response.status_code if exc.response is not None else 0
                if status not in {429, 500, 502, 503, 504}:
                    break
            except (
                requests.Timeout,
                requests.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
            ) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
                break
            if attempt <= len(retry_backoff_seconds):
                time.sleep(retry_backoff_seconds[attempt - 1])
        return {
            **settings,
            "content": "",
            "error": last_error or "模型调用失败",
            "latency_ms": round((time.time() - started) * 1000),
            "attempts": len(retry_backoff_seconds) + 1,
            "input_tokens": 0,
            "output_tokens": 0,
        }

    @staticmethod
    def _usage(data: dict[str, Any]) -> dict[str, int]:
        usage = data.get("usage") or {}
        return {
            "input_tokens": int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or usage.get("completion_tokens") or 0),
        }

    @staticmethod
    def _stream_chat_completions(
        settings: dict[str, Any],
        headers: dict[str, str],
        instructions: str,
        prompt: str,
        max_output_tokens: int,
    ) -> tuple[str, dict[str, int]]:
        """以 SSE 流式调用 chat/completions。

        推理型模型在输出首字节前有较长的思考时间；非流式请求在部分网关链路上
        会因空闲超时被中途断开（RemoteDisconnected），且表现为确定性失败。
        流式传输让字节持续流动，可跨过这类空闲超时。
        """
        with requests.post(
            f"{settings['base_url']}/chat/completions",
            headers=headers,
            json={
                "model": settings["model"],
                "messages": [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
                "max_tokens": max_output_tokens,
                # 可选推理强度控制：推理型模型默认思考会拖慢速度并挤占输出预算，
                # 通过 OPENAI_REASONING_EFFORT 配置（如 low）可关闭/降低。
                **(
                    {"reasoning_effort": settings["reasoning_effort"]}
                    if settings.get("reasoning_effort")
                    else {}
                ),
                # 注意：不要传 stream_options/include_usage，opencode 网关上游会
                # 对该参数直接返回 503。usage 从流中自带 usage 的块尽力捕获。
                "stream": True,
            },
            timeout=int(settings.get("timeout_seconds") or 600),
            stream=True,
        ) as response:
            response.raise_for_status()
            parts: list[str] = []
            usage_data: dict[str, Any] = {}
            for line in response.iter_lines():
                if not line or not line.startswith(b"data: "):
                    continue
                payload_text = line[len(b"data: ") :].decode("utf-8", errors="replace")
                if payload_text.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload_text)
                except json.JSONDecodeError:
                    continue
                if isinstance(chunk.get("usage"), dict) and chunk["usage"]:
                    usage_data = chunk["usage"]
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                piece = delta.get("content")
                if isinstance(piece, str):
                    parts.append(piece)
        usage = {
            "input_tokens": int(usage_data.get("prompt_tokens") or 0),
            "output_tokens": int(usage_data.get("completion_tokens") or 0),
        }
        return "".join(parts), usage

    @staticmethod
    def _request(
        settings: dict[str, Any],
        headers: dict[str, str],
        instructions: str,
        prompt: str,
        max_output_tokens: int,
    ) -> requests.Response:
        if settings["wire_api"] == "responses":
            return requests.post(
                f"{settings['base_url']}/responses",
                headers=headers,
                json={
                    "model": settings["model"],
                    "instructions": instructions,
                    "input": prompt,
                    "max_output_tokens": max_output_tokens,
                },
                timeout=int(settings.get("timeout_seconds") or 600),
            )
        return requests.post(
            f"{settings['base_url']}/chat/completions",
            headers=headers,
            json={
                "model": settings["model"],
                "messages": [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
                "max_tokens": max_output_tokens,
            },
            timeout=int(settings.get("timeout_seconds") or 600),
        )

    @staticmethod
    def _text(data: dict[str, Any], wire_api: str) -> str:
        if wire_api == "chat_completions":
            return str(data.get("choices", [{}])[0].get("message", {}).get("content", ""))
        if isinstance(data.get("output_text"), str):
            return data["output_text"]
        parts: list[str] = []
        for output in data.get("output") or []:
            for item in output.get("content") or []:
                value = item.get("text") or item.get("output_text")
                if isinstance(value, str):
                    parts.append(value)
        if parts:
            return "\n".join(parts)
        choices = data.get("choices") or []
        if choices:
            return str(choices[0].get("message", {}).get("content", ""))
        return ""

    @staticmethod
    def json_payload(content: str) -> dict[str, Any] | None:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]
        candidates = [cleaned]
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start and (start > 0 or end < len(cleaned) - 1):
            candidates.append(cleaned[start : end + 1])
        for candidate in candidates:
            for attempt in (candidate, LlmClient._remove_trailing_json_commas(candidate)):
                try:
                    value = json.loads(attempt)
                    return value if isinstance(value, dict) else None
                except json.JSONDecodeError:
                    continue
        return None

    @staticmethod
    def _remove_trailing_json_commas(value: str) -> str:
        result: list[str] = []
        in_string = False
        escaped = False
        index = 0
        while index < len(value):
            char = value[index]
            if in_string:
                result.append(char)
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                index += 1
                continue
            if char == '"':
                in_string = True
                result.append(char)
                index += 1
                continue
            if char == ",":
                lookahead = index + 1
                while lookahead < len(value) and value[lookahead].isspace():
                    lookahead += 1
                if lookahead < len(value) and value[lookahead] in "}]":
                    index += 1
                    continue
            result.append(char)
            index += 1
        return "".join(result)
