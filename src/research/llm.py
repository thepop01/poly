"""Provider boundary for the AI Research Hub orchestration loop.

The orchestrator talks only to :class:`LLMProvider`. Production uses
:class:`OpenAIResponsesProvider`; tests use :class:`FakeLLMProvider`. API keys
stay server-side and no test may contact the network.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

SYSTEM_INSTRUCTIONS = """\
You are the Polymarket AI Research Hub analyst. Rules you must follow:

- Use a registered analytical tool for every quantitative claim (win rates,
  PnL, volumes, wallet counts, coverage, consensus). Never invent, rescale,
  or repair values; explain only values returned by tools.
- Preserve strict comparison words: "more than 70%" means win_rate > 70,
  never >= 70.
- Category scope is category -> subcategory -> league (e.g. Sports ->
  Cricket -> T20). Never swap subcategory and league.
- If a tool returns 0 rows, report that fact and answer the user. Do not
  retry the same tool with reshuffled arguments; the empty result is the
  finding.
- When a wallet search returns 0 rows, its summary carries
  `available_scopes`: real stored subcategory/league values with wallet
  counts. Never claim a scope is small or empty from speculation; check the
  hint and offer the closest real scope (e.g. Cricket exists under a blank
  league and IPL, never under T20).
- Cite the result label and snapshot time for every panel-backed claim, and
  always state the evidence floor (default: minimum 20 resolved positions)
  plus each wallet's resolved_count.
- Follow-up phrases such as "those wallets" or "them" refer to the most
  recent compatible result set in this chat; pass its opaque ID through.
- "All of them" requires coverage equal to the full input result-set size.
  Never silently substitute "most" for "all".
- Group consensus by the market's stored outcome label. Binary markets may be
  summarized as YES/NO; multi-outcome markets must retain actual labels.
- Historical same-market/same-outcome overlap is descriptive. Never label
  wallets as coordinated, copied, or collusive without separate temporal
  evidence.
"""


@dataclass(frozen=True)
class ModelAction:
    kind: Literal["tool_call", "answer"]
    text: str = ""
    tool_name: str | None = None
    arguments: dict[str, Any] | None = None


class ProviderError(Exception):
    code = "PROVIDER_ERROR"


class ProviderTimeoutError(ProviderError):
    code = "PROVIDER_TIMEOUT"


class ProviderResponseError(ProviderError):
    code = "PROVIDER_BAD_RESPONSE"


class ProviderConfigError(ProviderError):
    """Missing key/endpoint configuration. Message is safe to show to users."""

    code = "PROVIDER_NOT_CONFIGURED"


class LLMProvider(Protocol):
    async def next_action(
        self, context: Any, tools: list[dict[str, Any]]
    ) -> ModelAction:
        ...


class FakeLLMProvider:
    """Deterministic scripted provider used by tests."""

    def __init__(self, actions: list[ModelAction]):
        self.actions = deque(actions)

    async def next_action(
        self, context: Any, tools: list[dict[str, Any]]
    ) -> ModelAction:
        try:
            return self.actions.popleft()
        except IndexError:
            raise ProviderResponseError("fake provider ran out of actions") from None


def _client_error_message(exc: Exception) -> ProviderError:
    name = exc.__class__.__name__
    if name in ("APITimeoutError", "Timeout", "TimeoutException") or isinstance(exc, TimeoutError):
        return ProviderTimeoutError(f"provider timed out: {exc}")
    # httpx timeouts raised by the SDK surface under httpx names.
    if "Timeout" in name:
        return ProviderTimeoutError(f"provider timed out: {exc}")
    return ProviderError(f"provider request failed: {exc}")


@dataclass
class _OpenAIClientMixin:
    model: str = "gpt-5-mini"
    api_key: str | None = None
    base_url: str | None = None
    timeout_seconds: float = 60.0
    client: Any = None
    system_instructions: str = field(default=SYSTEM_INSTRUCTIONS)

    def _client(self) -> Any:
        if self.client is not None:
            return self.client
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise ProviderError(
                "openai package is required for OpenAIResponsesProvider"
            ) from exc
        api_key = self.api_key
        base_url = self.base_url
        if api_key is None or base_url is None:
            import os

            api_key = api_key or os.getenv("OPENAI_API_KEY")
            base_url = base_url or os.getenv("OPENAI_BASE_URL")
        if not api_key:
            raise ProviderConfigError(
                "no LLM API key configured: set OPENAI_API_KEY in .env "
                "(any OpenAI-compatible key works with OPENAI_BASE_URL), "
                "then restart the API"
            )
        kwargs: dict[str, Any] = {"api_key": api_key, "timeout": self.timeout_seconds}
        if base_url:
            kwargs["base_url"] = base_url
        return AsyncOpenAI(**kwargs)

    @staticmethod
    def _context_messages(context: Any) -> list[dict[str, Any]]:
        messages = [
            {"role": m["role"], "content": m["content"]}
            for m in getattr(context, "messages", [])
        ]
        refs = getattr(context, "result_refs", [])
        if refs:
            lines = [
                f"- {r.get('result_set_id')} [{r.get('kind')}] {r.get('label')} "
                f"({r.get('row_count')} rows)"
                for r in refs
            ]
            messages.append({
                "role": "system",
                "content": "Saved result sets in this chat (newest last):\n" + "\n".join(lines),
            })
        return messages


@dataclass
class OpenAIResponsesProvider(_OpenAIClientMixin):
    """OpenAI Responses API adapter behind the :class:`LLMProvider` interface.

    Accepts any OpenAI-compatible endpoint: set ``base_url`` (or the
    ``OPENAI_BASE_URL`` env var) to point at a compatible gateway and use its
    API key. A missing key raises :class:`ProviderError` with a message that
    tells the operator exactly what to configure.

    Note: some third-party gateways translate ``/v1/responses`` lossily (e.g.
    dropping function-call names). For those, use
    :class:`OpenAIChatCompletionsProvider` instead.
    """

    async def next_action(
        self, context: Any, tools: list[dict[str, Any]]
    ) -> ModelAction:
        function_tools = [
            {
                "type": "function",
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {"type": "object"}),
            }
            for t in tools
        ]
        try:
            response = await self._client().responses.create(
                model=self.model,
                instructions=self.system_instructions,
                input=self._context_messages(context),
                tools=function_tools,
            )
        except Exception as exc:
            raise _client_error_message(exc) from exc

        return self.parse_response(response)

    @staticmethod
    def parse_response(response: Any) -> ModelAction:
        """Map a Responses API payload to a ModelAction.

        Accepts SDK objects or plain dicts (the latter are handy in tests).
        """
        if isinstance(response, dict):
            output = response.get("output", [])
        else:
            output = getattr(response, "output", []) or []
        for item in output:
            kind = item.get("type") if isinstance(item, dict) else getattr(item, "type", None)
            if kind == "function_call":
                name = item.get("name") if isinstance(item, dict) else getattr(item, "name", None)
                raw_args = (
                    item.get("arguments", "{}")
                    if isinstance(item, dict) else getattr(item, "arguments", "{}")
                )
                try:
                    arguments = json.loads(raw_args or "{}")
                except (ValueError, TypeError) as exc:
                    raise ProviderResponseError(
                        f"malformed tool arguments for {name}: {exc}"
                    ) from exc
                if not isinstance(arguments, dict):
                    raise ProviderResponseError(
                        f"malformed tool arguments for {name}: not an object"
                    )
                return ModelAction(kind="tool_call", tool_name=name, arguments=arguments)
        texts: list[str] = []
        for item in output:
            item_type = item.get("type") if isinstance(item, dict) else getattr(item, "type", None)
            if item_type != "message":
                continue
            content = item.get("content", []) if isinstance(item, dict) else (getattr(item, "content", []) or [])
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") in ("output_text", "text"):
                        texts.append(block.get("text", ""))
                else:
                    text = getattr(block, "text", "")
                    if text:
                        texts.append(text)
        if texts:
            return ModelAction(kind="answer", text="".join(texts))
        if isinstance(response, dict) and response.get("output_text"):
            return ModelAction(kind="answer", text=str(response["output_text"]))
        output_text = getattr(response, "output_text", None)
        if output_text:
            return ModelAction(kind="answer", text=str(output_text))
        raise ProviderResponseError("provider returned no usable output")


@dataclass
class OpenAIChatCompletionsProvider(_OpenAIClientMixin):
    """OpenAI Chat Completions adapter behind the :class:`LLMProvider` interface.

    Same contract as :class:`OpenAIResponsesProvider` but talks to
    ``POST /v1/chat/completions``. Prefer this adapter for third-party
    OpenAI-compatible gateways whose ``/v1/responses`` translation is lossy.
    """

    async def next_action(
        self, context: Any, tools: list[dict[str, Any]]
    ) -> ModelAction:
        function_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters", {"type": "object"}),
                },
            }
            for t in tools
        ]
        try:
            completion = await self._client().chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_instructions},
                    *self._context_messages(context),
                ],
                tools=function_tools,
            )
        except Exception as exc:
            raise _client_error_message(exc) from exc
        return self.parse_completion(completion)

    @staticmethod
    def parse_completion(completion: Any) -> ModelAction:
        """Map a Chat Completions payload to a ModelAction (dicts or SDK objects)."""
        if isinstance(completion, dict):
            choices = completion.get("choices", [])
            message = choices[0].get("message", {}) if choices else {}
            tool_calls = message.get("tool_calls") or []
            content = message.get("content") or ""
        else:
            choices = getattr(completion, "choices", []) or []
            message = choices[0].message if choices else None
            tool_calls = getattr(message, "tool_calls", None) if message is not None else None
            content = getattr(message, "content", "") if message is not None else ""
        for call in tool_calls or []:
            if isinstance(call, dict):
                function = call.get("function", {})
                name, raw_args = function.get("name"), function.get("arguments", "{}")
            else:
                function = getattr(call, "function", None)
                name = getattr(function, "name", None)
                raw_args = getattr(function, "arguments", "{}")
            if not name:
                continue
            try:
                arguments = json.loads(raw_args or "{}")
            except (ValueError, TypeError) as exc:
                raise ProviderResponseError(
                    f"malformed tool arguments for {name}: {exc}"
                ) from exc
            if not isinstance(arguments, dict):
                raise ProviderResponseError(
                    f"malformed tool arguments for {name}: not an object"
                )
            return ModelAction(kind="tool_call", tool_name=name, arguments=arguments)
        if content and str(content).strip():
            return ModelAction(kind="answer", text=str(content))
        raise ProviderResponseError("provider returned no usable output")


def build_provider_from_env(client: Any = None) -> _OpenAIClientMixin:
    """Select the research LLM adapter from environment configuration."""
    import os

    kind = os.getenv("RESEARCH_PROVIDER", "responses").strip().lower()
    kwargs: dict[str, Any] = {
        "model": os.getenv("RESEARCH_MODEL", "gpt-5-mini"),
        "api_key": os.getenv("OPENAI_API_KEY"),
        "base_url": os.getenv("OPENAI_BASE_URL"),
        "client": client,
    }
    if kind in ("chat-completions", "chat_completions", "chat"):
        return OpenAIChatCompletionsProvider(**kwargs)
    return OpenAIResponsesProvider(**kwargs)
