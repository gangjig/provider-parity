"""Run a probe suite against provider endpoints and record the results.

Providers are OpenAI-compatible chat-completions endpoints, configured
in a JSON file:

    {"providers": [
      {"name": "official", "base_url": "https://api.example.com/v1",
       "model": "model-x", "api_key_env": "EXAMPLE_API_KEY"},
      {"name": "reseller", "base_url": "https://reseller.example/v1",
       "model": "model-x", "api_key_env": "RESELLER_API_KEY"}
    ]}

`api_key_env` names an environment variable holding the key; the key
itself never appears in configs, run logs or reports. Each probe is
sent once per provider at temperature 0. Every attempt -- success,
wrong answer, or transport error -- becomes one JSONL record:

    {"provider": "reseller", "probe_id": "arith-1", "success": false,
     "latency_s": 1.234, "prompt_tokens": 21, "completion_tokens": 3,
     "text": "41", "error": null}

The runner applies the probe's checker itself, so a run log is a
self-contained record of *behavior*, ready for `compare`.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional, Union

from .probes import Probe, run_checker

PathLike = Union[str, Path]

DEFAULT_TIMEOUT_S = 60.0


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    model: str
    api_key_env: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict, where: str = "provider") -> "ProviderConfig":
        for name in ("name", "base_url", "model"):
            if name not in data:
                raise ValueError(f"{where}: missing field {name!r}")
        return cls(
            name=str(data["name"]),
            base_url=str(data["base_url"]).rstrip("/"),
            model=str(data["model"]),
            api_key_env=(
                str(data["api_key_env"]) if data.get("api_key_env") else None
            ),
        )


def load_providers(path: PathLike) -> list[ProviderConfig]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = data.get("providers", data) if isinstance(data, dict) else data
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{path}: expected a non-empty 'providers' list")
    providers = [
        ProviderConfig.from_dict(entry, where=f"{path} provider {i}")
        for i, entry in enumerate(entries)
    ]
    names = [p.name for p in providers]
    if len(set(names)) != len(names):
        raise ValueError(f"{path}: provider names must be unique")
    return providers


@dataclass(frozen=True)
class RawResponse:
    text: str
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    latency_s: float


# A transport answers one probe on one provider. Tests and the demo
# substitute fakes; the default transport speaks HTTP.
Transport = Callable[[ProviderConfig, Probe, float], RawResponse]


class TransportError(RuntimeError):
    pass


def http_transport(
    provider: ProviderConfig, probe: Probe, timeout_s: float
) -> RawResponse:
    """POST the probe to the provider's /chat/completions endpoint."""
    api_key = None
    if provider.api_key_env:
        api_key = os.environ.get(provider.api_key_env)
        if not api_key:
            raise TransportError(
                f"environment variable {provider.api_key_env} is not set "
                f"(API key for provider {provider.name!r})"
            )
    body = json.dumps(
        {
            "model": provider.model,
            "messages": [{"role": "user", "content": probe.prompt}],
            "temperature": 0,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{provider.base_url}/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise TransportError(f"HTTP {exc.code} from {provider.name}") from exc
    except urllib.error.URLError as exc:
        raise TransportError(f"cannot reach {provider.name}: {exc.reason}") from exc
    latency_s = time.monotonic() - started
    try:
        text = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise TransportError(
            f"malformed chat-completions response from {provider.name}"
        ) from exc
    usage = payload.get("usage") or {}
    return RawResponse(
        text=str(text),
        prompt_tokens=(
            int(usage["prompt_tokens"])
            if usage.get("prompt_tokens") is not None
            else None
        ),
        completion_tokens=(
            int(usage["completion_tokens"])
            if usage.get("completion_tokens") is not None
            else None
        ),
        latency_s=latency_s,
    )


@dataclass(frozen=True)
class Record:
    provider: str
    probe_id: str
    success: bool
    latency_s: float
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    text: str = ""
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "probe_id": self.probe_id,
            "success": self.success,
            "latency_s": round(self.latency_s, 4),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "text": self.text,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict, where: str = "record") -> "Record":
        for name in ("provider", "probe_id", "success", "latency_s"):
            if name not in data:
                raise ValueError(f"{where}: missing field {name!r}")
        return cls(
            provider=str(data["provider"]),
            probe_id=str(data["probe_id"]),
            success=bool(data["success"]),
            latency_s=float(data["latency_s"]),
            prompt_tokens=(
                int(data["prompt_tokens"])
                if data.get("prompt_tokens") is not None
                else None
            ),
            completion_tokens=(
                int(data["completion_tokens"])
                if data.get("completion_tokens") is not None
                else None
            ),
            text=str(data.get("text", "")),
            error=(str(data["error"]) if data.get("error") else None),
        )


def run_probes(
    probes: Iterable[Probe],
    providers: Iterable[ProviderConfig],
    transport: Transport = http_transport,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> list[Record]:
    """Run every probe against every provider. Transport failures are
    recorded (success=False, error set), never raised: a provider that
    cannot answer a probe has failed that probe, and the report should
    show it rather than the run dying halfway."""
    records: list[Record] = []
    for provider in providers:
        for probe in probes:
            try:
                raw = transport(provider, probe, timeout_s)
            except Exception as exc:  # noqa: BLE001 - recorded, not raised
                records.append(
                    Record(
                        provider=provider.name,
                        probe_id=probe.id,
                        success=False,
                        latency_s=0.0,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue
            records.append(
                Record(
                    provider=provider.name,
                    probe_id=probe.id,
                    success=run_checker(probe.checker, raw.text),
                    latency_s=raw.latency_s,
                    prompt_tokens=raw.prompt_tokens,
                    completion_tokens=raw.completion_tokens,
                    text=raw.text,
                )
            )
    return records


def write_records(path: PathLike, records: Iterable[Record]) -> None:
    with Path(path).open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")


def load_records(path: PathLike) -> list[Record]:
    records: list[Record] = []
    with Path(path).open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
            records.append(Record.from_dict(data, where=f"{path}:{lineno}"))
    if not records:
        raise ValueError(f"{path}: no records found")
    return records
