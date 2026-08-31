from __future__ import annotations

from typing import Protocol

from mandatemend.config import settings
from mandatemend.schemas import FailureEvent, TypedDiagnosis


class Diagnoser(Protocol):
    def diagnose(self, event: FailureEvent) -> TypedDiagnosis: ...


def get_diagnoser(kind: str | None = None) -> Diagnoser:
    """Factory. `kind` in {auto, llm, heuristic}; None -> settings."""
    resolved = kind or settings.resolved_diagnoser()
    if resolved == "llm":
        from mandatemend.diagnosis.llm_diagnoser import LLMDiagnoser

        return LLMDiagnoser()
    from mandatemend.diagnosis.heuristic_diagnoser import HeuristicDiagnoser

    return HeuristicDiagnoser()
