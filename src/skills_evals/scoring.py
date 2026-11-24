from __future__ import annotations

from typing import Any


def mechanical_format_result(output: str, expected: dict[str, Any]) -> dict[str, Any]:
    """Check only mechanically verifiable presentation constraints."""
    constraints = expected.get("mechanical", {})
    word_count = len(output.split())
    max_words = constraints.get("max_words")
    required_sections = constraints.get("required_sections", [])
    # Section headings are exact, case-insensitive lines. Their content is not scored here.
    headings = {
        line.strip().lstrip("# ").rstrip(":").casefold()
        for line in output.splitlines()
        if line.strip()
    }
    missing_sections = [
        section for section in required_sections if section.casefold() not in headings
    ]
    over_limit = max_words is not None and word_count > max_words
    passed = not over_limit and not missing_sections
    return {
        "score": 1.0 if passed else 0.0,
        "metadata": {
            "reason": (
                "All mechanical format constraints passed."
                if passed
                else "; ".join(
                    ([f"{word_count} words exceeds limit {max_words}"] if over_limit else [])
                    + (["missing required headings: " + ", ".join(missing_sections)] if missing_sections else [])
                )
            ),
            "word_count": word_count,
            "max_words": max_words,
            "missing_sections": missing_sections,
        },
    }


def mechanical_format(output: str, expected: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return {"name": "mechanical_format", **mechanical_format_result(str(output or ""), expected or {})}
