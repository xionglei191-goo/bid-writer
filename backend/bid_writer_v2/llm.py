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
        wire_api = environment_value("OPENAI_WIRE_API", "responses").lower()
        if wire_api == "codex":
            token, _, source = self._codex_auth()
            configured = bool(token) and not disabled
        else:
            source = "env:OPENAI_API_KEY" if environment_value("OPENAI_API_KEY") else ""
            configured = bool(environment_value("OPENAI_API_KEY")) and not disabled
        settings = {
            "configured": configured,
            "base_url": environment_value("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            "model": environment_value("OPENAI_MODEL", "gpt-5.6-luna"),
            "wire_api": wire_api,
            "timeout_seconds": max(60, int(environment_value("OPENAI_TIMEOUT_SECONDS", "600"))),
            "reasoning_effort": environment_value("OPENAI_REASONING_EFFORT", "").strip().lower(),
            "auth_source": source,
        }
        fallback = self._fallback_settings(settings)
        settings["fallback_route"] = (
            {key: fallback[0][key] for key in ("model", "base_url", "wire_api", "reasoning_effort")}
            if fallback else None
        )
        return settings

    @staticmethod
    def _fallback_settings(primary: dict[str, Any]) -> tuple[dict[str, Any], str] | None:
        """Return the independently configured OpenAI-compatible backup route."""
        api_key = environment_value("OPENAI_FALLBACK_API_KEY")
        model = environment_value("OPENAI_FALLBACK_MODEL")
        if not api_key or not model:
            return None
        return ({
            "configured": True,
            "base_url": environment_value("OPENAI_FALLBACK_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/"),
            "model": model,
            "wire_api": environment_value("OPENAI_FALLBACK_WIRE_API", "chat_completions").lower(),
            "timeout_seconds": max(60, int(environment_value(
                "OPENAI_FALLBACK_TIMEOUT_SECONDS", str(primary["timeout_seconds"])
            ))),
            "reasoning_effort": environment_value("OPENAI_FALLBACK_REASONING_EFFORT", "").strip().lower(),
            "auth_source": "env:OPENAI_FALLBACK_API_KEY",
        }, api_key)

    def generate(self, instructions: str, prompt: str, max_output_tokens: int = 8000) -> dict[str, Any]:
        settings = self.settings()
        if not settings["configured"]:
            return {**settings, "content": "", "error": "大模型未配置或已禁用", "latency_ms": 0}
        fallback = self._fallback_settings(settings)
        if settings["wire_api"] == "codex":
            primary = self._generate_codex(settings, instructions, prompt)
        else:
            primary = self._generate_openai(
                settings,
                environment_value("OPENAI_API_KEY"),
                instructions,
                prompt,
                max_output_tokens,
                failover_on_rate_limit=bool(fallback),
            )
        primary["fallback_used"] = False
        primary["primary_error"] = ""
        if primary["content"] or not fallback or not primary.get("retryable"):
            return primary
        fallback_settings, fallback_key = fallback
        result = self._generate_openai(
            fallback_settings, fallback_key, instructions, prompt, max_output_tokens
        )
        result["fallback_used"] = True
        result["primary_error"] = primary["error"]
        for metric in ("latency_ms", "attempts", "input_tokens", "output_tokens"):
            result[metric] = int(primary.get(metric) or 0) + int(result.get(metric) or 0)
        return result

    def _generate_openai(
        self,
        settings: dict[str, Any],
        api_key: str,
        instructions: str,
        prompt: str,
        max_output_tokens: int,
        failover_on_rate_limit: bool = False,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        started = time.time()
        last_error = ""
        attempts_made = 0
        retryable = False
        # 外部模型服务（如 opencode 网关）存在阵发性瞬时错误：连接被远端关闭、
        # 502/503、限流等。短退避重试无法跨过数十秒的服务抖动窗口，会整批失败
        # 并触发阶段熔断；因此使用拉长的退避序列，重试耗尽后才进入熔断统计。
        retry_backoff_seconds = (5, 20, 45)
        for attempt in range(1, len(retry_backoff_seconds) + 2):
            attempts_made = attempt
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
                    retryable = True
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
                retryable = status in {429, 500, 502, 503, 504}
                # 429 表示主路当前限流；立即切备用路，避免无意义地等待退避窗口。
                if (failover_on_rate_limit and status == 429) or status not in {429, 500, 502, 503, 504}:
                    break
            except (
                requests.Timeout,
                requests.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
            ) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                retryable = True
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
                retryable = False
                break
            if attempt <= len(retry_backoff_seconds):
                time.sleep(retry_backoff_seconds[attempt - 1])
        return {
            **settings,
            "content": "",
            "error": last_error or "模型调用失败",
            "latency_ms": round((time.time() - started) * 1000),
            "attempts": attempts_made,
            "retryable": retryable,
            "input_tokens": 0,
            "output_tokens": 0,
        }

    @staticmethod
    def _codex_auth() -> tuple[str, str, str]:
        """解析 Codex 订阅认证：返回 (token, account_id, 来源描述)。

        优先级：显式环境变量 CODEX_API_KEY / CODEX_ACCOUNT_ID，
        否则从 pi 的 auth.json（openai-codex OAuth，会由 pi 自动刷新）实时读取，
        容器内通过 BID_WRITER_CODEX_AUTH_FILE 指向挂载进来的文件。
        """
        token = environment_value("CODEX_API_KEY")
        account_id = environment_value("CODEX_ACCOUNT_ID")
        if token:
            return token, account_id, "env:CODEX_API_KEY"
        candidates = [
            environment_value("BID_WRITER_CODEX_AUTH_FILE"),
            r"C:\Users\Administrator\.pi\agent\auth.json",
            os.path.join(os.path.expanduser("~"), ".pi", "agent", "auth.json"),
            "/run/secrets/codex-auth.json",
        ]
        for path in candidates:
            if not path:
                continue
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                entry = (data or {}).get("openai-codex") or {}
                file_token = str(entry.get("access") or "")
                file_account = str(entry.get("accountId") or "")
                if file_token:
                    return file_token, file_account, f"file:{path}"
            except (OSError, ValueError):
                continue
        return "", "", ""

    def _generate_codex(
        self, settings: dict[str, Any], instructions: str, prompt: str
    ) -> dict[str, Any]:
        """经 Codex 订阅接口（chatgpt.com/backend-api/codex/responses）调用。

        该接口只接受 SSE 流式 responses 请求：input 必须为消息列表，
        不支持 max_output_tokens / max_tokens 参数。
        """
        started = time.time()
        token, account_id, source = self._codex_auth()
        if not token:
            return {
                **settings,
                "content": "",
                "error": "Codex 认证缺失：未找到 CODEX_API_KEY，也读不到 pi auth.json 的 openai-codex 访问令牌",
                "latency_ms": round((time.time() - started) * 1000),
                "attempts": 0,
                "input_tokens": 0,
                "output_tokens": 0,
            }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": "codex-cli",
        }
        if account_id:
            headers["chatgpt-account-id"] = account_id
        payload = {
            "model": settings["model"],
            "store": False,
            "stream": True,
            "instructions": instructions,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        }
        url = f"{settings['base_url']}/codex/responses"
        timeout = int(settings.get("timeout_seconds") or 600)
        retry_backoff_seconds = (5, 20, 45)
        last_error = ""
        retryable = False
        attempts_made = 0
        for attempt in range(1, len(retry_backoff_seconds) + 2):
            attempts_made = attempt
            try:
                with requests.post(url, headers=headers, json=payload, timeout=timeout, stream=True) as response:
                    if response.status_code == 401:
                        last_error = "Codex 访问令牌过期（401）：请先在本机用 pi 跑一次 codex 模型刷新 auth.json 后重试"
                        retryable = False
                        break
                    response.raise_for_status()
                    content, usage = self._read_codex_stream(response)
                if not content:
                    last_error = "模型未返回文本"
                    retryable = True
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
                retryable = status in {429, 500, 502, 503, 504}
                if status not in {429, 500, 502, 503, 504}:
                    break
            except (
                requests.Timeout,
                requests.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
            ) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                retryable = True
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
                retryable = False
                break
            if attempt <= len(retry_backoff_seconds):
                time.sleep(retry_backoff_seconds[attempt - 1])
        return {
            **settings,
            "content": "",
            "error": last_error or "模型调用失败",
            "latency_ms": round((time.time() - started) * 1000),
            "attempts": attempts_made,
            "retryable": retryable,
            "input_tokens": 0,
            "output_tokens": 0,
        }

    @staticmethod
    def _read_codex_stream(response: requests.Response) -> tuple[str, dict[str, Any]]:
        parts: list[str] = []
        usage: dict[str, Any] = {"input_tokens": 0, "output_tokens": 0}
        for line in response.iter_lines():
            if not line or not line.startswith(b"data: "):
                continue
            payload_text = line[len(b"data: "):].decode("utf-8", errors="replace")
            if payload_text.strip() == "[DONE]":
                break
            try:
                event = json.loads(payload_text)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            event_type = str(event.get("type") or "")
            if event_type == "response.output_text.delta":
                delta = event.get("delta")
                if isinstance(delta, str):
                    parts.append(delta)
            elif event_type == "response.completed":
                completed = event.get("response") or {}
                event_usage = completed.get("usage") or {}
                usage = {
                    "input_tokens": int(event_usage.get("input_tokens") or 0),
                    "output_tokens": int(event_usage.get("output_tokens") or 0),
                    **({"model": completed["model"]} if isinstance(completed.get("model"), str) and completed["model"] else {}),
                }
        return "".join(parts), usage

    @staticmethod
    def _usage(data: dict[str, Any]) -> dict[str, Any]:
        usage = data.get("usage") or {}
        return {
            "input_tokens": int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or usage.get("completion_tokens") or 0),
            **({"model": data["model"]} if isinstance(data.get("model"), str) and data["model"] else {}),
        }

    @staticmethod
    def _stream_chat_completions(
        settings: dict[str, Any],
        headers: dict[str, str],
        instructions: str,
        prompt: str,
        max_output_tokens: int,
    ) -> tuple[str, dict[str, Any]]:
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
            response_model = ""
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
                if isinstance(chunk.get("model"), str) and chunk["model"]:
                    response_model = chunk["model"]
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
            **({"model": response_model} if response_model else {}),
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
