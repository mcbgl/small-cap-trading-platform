"""
AI integration layer -- confidence-based routing between local and cloud models.

Public API
----------
- ``AIRouter`` -- main entry point; routes tasks by tier with fallback.
- ``OllamaClient`` -- local Qwen inference (graceful when unavailable).
- ``ClaudeClient`` -- cloud Claude inference (Haiku / Sonnet / Opus).
- ``AnalysisTask`` / ``AnalysisTier`` -- enums for task classification.
- ``AIResponse`` -- unified response dataclass from all tiers.

Quick start::

    from src.services.ai import AIRouter, OllamaClient, ClaudeClient, AnalysisTask

    ollama = OllamaClient()
    claude = ClaudeClient()
    router = AIRouter(ollama, claude)

    result = await router.analyze(AnalysisTask.SENTIMENT, "ACME beat earnings estimates...")
"""

from src.services.ai.router import (
    AIRouter,
    AIResponse,
    AnalysisTask,
    AnalysisTier,
)
from src.services.ai.ollama_client import OllamaClient, OllamaResponse
from src.services.ai.claude_client import ClaudeClient, ClaudeResponse

__all__ = [
    "AIRouter",
    "AIResponse",
    "AnalysisTask",
    "AnalysisTier",
    "OllamaClient",
    "OllamaResponse",
    "ClaudeClient",
    "ClaudeResponse",
]
