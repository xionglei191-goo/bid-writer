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
        for attempt in range(1, 4):
            try:
                response = self._request(settings, headers, instructions, prompt, max_output_tokens)
                response.raise_for_status()
                data = response.json()
                content = self._text(data, settings["wire_api"])
                usage = self._usage(data)
                return {
                    **settings,
                    "content": content,
                    "error": "" if content else "模型未返回文本",
                    "latency_ms": round((time.time() - started) * 1000),
                    "attempts": attempt,
                    **usage,
                }
            except requests.HTTPError as exc:
                last_error = f"HTTPError: {exc}"
                status = exc.response.status_code if exc.response is not None else 0
                if status not in {429, 500, 502, 503, 504}:
                    break
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
                break
            time.sleep(attempt * 2)
        return {
            **settings,
            "content": "",
            "error": last_error or "模型调用失败",
            "latency_ms": round((time.time() - started) * 1000),
            "attempts": 3,
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
                timeout=180,
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
            timeout=180,
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
