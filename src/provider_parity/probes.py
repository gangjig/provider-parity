"""Probe suites: fixed tasks with deterministic checkers.

A probe is one small task with one right answer, stated so a machine
can check it without an LLM judge:

    {"id": "arith-1", "prompt": "What is 17 + 25? Reply with only the number.",
     "checker": {"type": "exact", "expected": "42"}}

Checker types:

* `exact`      -- the response, stripped, equals `expected`.
* `contains`   -- the response contains `expected` as a substring.
* `regex`      -- `pattern` matches somewhere in the response.
* `json_field` -- the response parses as JSON and the dotted `field`
                  path (e.g. "answer" or "result.value") equals
                  `expected`.

Probes are deliberately small and factual: the point is not to rank
models but to catch *behavioral* differences between deployments that
claim to be the same model. A good probe suite mixes arithmetic,
recall, instruction-following and structured-output probes, so a
silently swapped or degraded deployment has nowhere to hide.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

PathLike = Union[str, Path]

CHECKER_TYPES = ("exact", "contains", "regex", "json_field")


@dataclass(frozen=True)
class Checker:
    type: str
    expected: Any = None
    pattern: Optional[str] = None
    field: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict, where: str = "checker") -> "Checker":
        if not isinstance(data, dict) or "type" not in data:
            raise ValueError(f"{where}: checker must be an object with a 'type'")
        kind = str(data["type"])
        if kind not in CHECKER_TYPES:
            raise ValueError(
                f"{where}: unknown checker type {kind!r}; "
                f"known types: {', '.join(CHECKER_TYPES)}"
            )
        checker = cls(
            type=kind,
            expected=data.get("expected"),
            pattern=data.get("pattern"),
            field=data.get("field"),
        )
        checker.validate(where)
        return checker

    def validate(self, where: str = "checker") -> None:
        if self.type in ("exact", "contains") and not isinstance(
            self.expected, str
        ):
            raise ValueError(
                f"{where}: {self.type} checker needs a string 'expected'"
            )
        if self.type == "regex":
            if not isinstance(self.pattern, str):
                raise ValueError(f"{where}: regex checker needs a 'pattern'")
            try:
                re.compile(self.pattern)
            except re.error as exc:
                raise ValueError(f"{where}: invalid regex: {exc}") from exc
        if self.type == "json_field":
            if not isinstance(self.field, str) or not self.field:
                raise ValueError(f"{where}: json_field checker needs a 'field'")
            if self.expected is None:
                raise ValueError(
                    f"{where}: json_field checker needs an 'expected' value"
                )

    def to_dict(self) -> dict:
        out: dict[str, Any] = {"type": self.type}
        if self.expected is not None:
            out["expected"] = self.expected
        if self.pattern is not None:
            out["pattern"] = self.pattern
        if self.field is not None:
            out["field"] = self.field
        return out


def _dig(data: Any, dotted: str) -> Any:
    current = data
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(dotted)
        current = current[part]
    return current


def run_checker(checker: Checker, text: str) -> bool:
    """True when the response `text` satisfies the checker."""
    if checker.type == "exact":
        return text.strip() == checker.expected
    if checker.type == "contains":
        return checker.expected in text
    if checker.type == "regex":
        return re.search(checker.pattern, text) is not None
    if checker.type == "json_field":
        try:
            data = json.loads(text.strip())
            return _dig(data, checker.field) == checker.expected
        except (json.JSONDecodeError, KeyError, TypeError):
            return False
    raise ValueError(f"unknown checker type {checker.type!r}")


@dataclass(frozen=True)
class Probe:
    id: str
    prompt: str
    checker: Checker

    @classmethod
    def from_dict(cls, data: dict, where: str = "probe") -> "Probe":
        for name in ("id", "prompt", "checker"):
            if name not in data:
                raise ValueError(f"{where}: missing field {name!r}")
        if not str(data["prompt"]).strip():
            raise ValueError(f"{where}: prompt must not be empty")
        return cls(
            id=str(data["id"]),
            prompt=str(data["prompt"]),
            checker=Checker.from_dict(data["checker"], where=f"{where} checker"),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "checker": self.checker.to_dict(),
        }


def load_probes(path: PathLike) -> list[Probe]:
    """Load a JSONL probe suite; ids must be unique."""
    probes: list[Probe] = []
    seen: set[str] = set()
    with Path(path).open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
            probe = Probe.from_dict(data, where=f"{path}:{lineno}")
            if probe.id in seen:
                raise ValueError(f"{path}:{lineno}: duplicate probe id {probe.id!r}")
            seen.add(probe.id)
            probes.append(probe)
    if not probes:
        raise ValueError(f"{path}: no probes found")
    return probes
