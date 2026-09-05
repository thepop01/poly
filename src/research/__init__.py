"""AI Research Hub domain package."""

from src.research.analytics import ResearchAnalytics, ResultSetAccessError
from src.research.context import ResearchContext, build_context
from src.research.contracts import PanelType, ResultKind, RunStatus
from src.research.llm import (
    FakeLLMProvider,
    ModelAction,
    OpenAIChatCompletionsProvider,
    OpenAIResponsesProvider,
    build_provider_from_env,
)
from src.research.orchestrator import ResearchOrchestrator, panel_key
from src.research.repository import ResearchRepository
from src.research.tools import TOOL_DEFINITIONS, execute_tool, tool_schemas

__all__ = [
    "ResearchAnalytics", "ResultSetAccessError", "ResearchContext", "build_context",
    "PanelType", "ResultKind", "RunStatus", "FakeLLMProvider", "ModelAction",
    "OpenAIChatCompletionsProvider", "OpenAIResponsesProvider",
    "build_provider_from_env", "ResearchOrchestrator", "panel_key",
    "ResearchRepository", "TOOL_DEFINITIONS", "execute_tool", "tool_schemas",
]
