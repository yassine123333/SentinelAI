from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass
class PromptInjectionAssessment:
    risk_level: str
    score: int
    reasons: list[str]
    sanitized_query: str
    blocked_for_llm: bool


INJECTION_RULES: list[tuple[re.Pattern[str], int, str]] = [
    (re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", re.IGNORECASE), 4, "Instruction override attempt"),
    (re.compile(r"(reveal|show|print)\s+(the\s+)?(system|developer)\s+prompt", re.IGNORECASE), 4, "Prompt exfiltration attempt"),
    (re.compile(r"jailbreak|do\s+anything\s+now|dan\s+mode", re.IGNORECASE), 4, "Jailbreak phrasing"),
    (re.compile(r"tool\s*call|function\s*call|execute\s+command|run\s+shell", re.IGNORECASE), 3, "Tool-execution coercion"),
    (re.compile(r"bypass|disable\s+safety|disable\s+guardrail", re.IGNORECASE), 3, "Safety bypass attempt"),
    (re.compile(r"<\s*system\s*>|<\s*assistant\s*>|```", re.IGNORECASE), 2, "Role/code-fence structuring attempt"),
]


def assess_prompt_injection(query: str) -> PromptInjectionAssessment:
    cleaned = _sanitize(query)
    score = 0
    reasons: list[str] = []

    for pattern, weight, reason in INJECTION_RULES:
        if pattern.search(cleaned):
            score += weight
            reasons.append(reason)

    if len(cleaned) > 2000:
        score += 2
        reasons.append("Excessive prompt length")

    risk_level = "low"
    blocked_for_llm = False
    if score >= 7:
        risk_level = "high"
        blocked_for_llm = True
    elif score >= 4:
        risk_level = "medium"

    return PromptInjectionAssessment(
        risk_level=risk_level,
        score=score,
        reasons=reasons,
        sanitized_query=cleaned,
        blocked_for_llm=blocked_for_llm,
    )


def _sanitize(text: str) -> str:
    printable = "".join(char for char in text if char.isprintable())
    normalized = re.sub(r"\s+", " ", printable).strip()
    return normalized[:3000]
