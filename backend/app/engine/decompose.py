"""Turn a human request into structured subtasks.

Two paths, both labeled in the result so the UI can say which one ran:
- "llm": Claude with structured outputs (needs ANTHROPIC_API_KEY or an
  `ant auth login` profile).
- "rules": transparent keyword rules. Always available, used as fallback.
"""
from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from ..config import settings
from .graph import CycleError, assert_acyclic

log = logging.getLogger(__name__)

Role = Literal["frontend", "backend", "testing", "reviewer"]


class SubtaskSpec(BaseModel):
    title: str = Field(max_length=300)
    description: str = ""
    role: Role
    kind: Literal["feature", "investigation", "test", "review", "merge"] = "feature"
    priority: Literal["low", "medium", "high"] = "medium"
    depends_on: list[int] = Field(default_factory=list, description="indices of earlier subtasks")
    requires_approval: bool = False


class Decomposition(BaseModel):
    summary: str
    subtasks: list[SubtaskSpec]
    source: str = "rules"


_SYSTEM = """You are the coordinator of a small software team with four AI
specialists: frontend, backend, testing, reviewer. Decompose the user's
request into 2-6 concrete subtasks for those roles.

Rules:
- depends_on holds indices (0-based) of earlier subtasks in your list.
- Investigation first when the request mentions a bug.
- Testing tasks (kind "test") must depend on the implementation they verify.
- The final integration/merge-like step must set requires_approval true.
- Keep titles short and imperative."""


def _validate(dec: Decomposition) -> Decomposition:
    n = len(dec.subtasks)
    edges = []
    for i, st in enumerate(dec.subtasks):
        for d in st.depends_on:
            if not (0 <= d < n) or d == i:
                raise ValueError(f"subtask {i} has invalid dependency index {d}")
            edges.append((i, d))
    assert_acyclic(edges)
    return dec


def llm_decompose(request_text: str) -> Decomposition | None:
    import os

    if not os.environ.get("ANTHROPIC_API_KEY"):
        # Explicit key only: predictable behaviour (and spend) in demos/tests.
        return None
    try:
        import anthropic

        client = anthropic.Anthropic()
        response = client.messages.parse(
            model=settings.anthropic_model,
            max_tokens=16000,
            system=_SYSTEM,
            messages=[{"role": "user", "content": request_text}],
            output_format=Decomposition,
        )
        dec = response.parsed_output
        dec.source = "llm"
        return _validate(dec)
    except CycleError as e:
        log.warning("LLM produced a cyclic task graph, falling back to rules: %s", e)
        return None
    except Exception as e:  # no key, network, refusal, bad schema -> honest fallback
        log.warning("LLM decomposition unavailable (%s), falling back to rules", e)
        return None


def rule_decompose(request_text: str) -> Decomposition:
    text = request_text.lower()
    bug = any(w in text for w in ("bug", "crash", "fix", "broken", "error", "investigate"))
    frontend = any(w in text for w in ("ui", "page", "form", "frontend", "screen", "button", "login"))
    backend = any(w in text for w in ("api", "endpoint", "backend", "database", "auth", "login", "server"))

    subtasks: list[SubtaskSpec] = []
    if bug:
        subtasks.append(SubtaskSpec(
            title="Investigate and reproduce the reported problem",
            description=f"Reproduce and locate the cause. Request: {request_text}",
            role="backend" if backend or not frontend else "frontend",
            kind="investigation", priority="high",
        ))
    impl_deps = [0] if bug else []
    impl_indices: list[int] = []
    if backend or not frontend:
        subtasks.append(SubtaskSpec(
            title="Implement the backend change",
            description=f"Implement server-side work for: {request_text}",
            role="backend", depends_on=list(impl_deps),
        ))
        impl_indices.append(len(subtasks) - 1)
    if frontend:
        subtasks.append(SubtaskSpec(
            title="Implement the frontend change",
            description=f"Implement UI work for: {request_text}",
            role="frontend",
            depends_on=impl_indices[:1] or list(impl_deps),
        ))
        impl_indices.append(len(subtasks) - 1)
    subtasks.append(SubtaskSpec(
        title="Write and run tests for the change",
        description="Add tests covering the change, run them, report real output.",
        role="testing", kind="test", depends_on=list(impl_indices),
    ))
    subtasks.append(SubtaskSpec(
        title="Review and approve the combined change",
        description="Review the diff and test evidence; request changes or approve for merge.",
        role="reviewer", kind="review",
        depends_on=[len(subtasks) - 1], requires_approval=True,
    ))
    return _validate(Decomposition(
        summary=f"Rule-based plan for: {request_text[:140]}",
        subtasks=subtasks, source="rules",
    ))


def decompose(request_text: str) -> Decomposition:
    return llm_decompose(request_text) or rule_decompose(request_text)
