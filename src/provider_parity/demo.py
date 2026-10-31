"""Simulated endpoints for `provider-parity demo` -- no keys, no network.

Two fake providers serve the same ten-probe suite:

* `official` answers every probe correctly, with prompt-proportional
  latency and usage counted from the actual texts.
* `reseller` claims to serve the same model but silently degrades:
  it gets three probes wrong (a structured-output probe, a recall
  probe and a geography probe), reports 1.6x the completion tokens
  for everything, and answers at twice the latency.

The expected report verdict is DIVERGENT for `reseller` vs `official`
(70% vs 100% success, 70% outcome agreement). The simulation is
illustrative: real deployments differ in messier ways, which is the
point of running the real `run` command against them.
"""

from __future__ import annotations

from .probes import Checker, Probe
from .runner import ProviderConfig, RawResponse, Record, run_probes

DEMO_PROBES: list[Probe] = [
    Probe(
        "arith-1",
        "What is 17 + 25? Reply with only the number.",
        Checker("exact", expected="42"),
    ),
    Probe(
        "capital-1",
        "What is the capital of France? Reply with only the city name.",
        Checker("contains", expected="Paris"),
    ),
    Probe(
        "json-1",
        'Reply with only a JSON object: {"answer": <the number of days in a week>}',
        Checker("json_field", expected=7, field="answer"),
    ),
    Probe(
        "translate-1",
        "Translate 'thank you' into German. Reply with only the translation.",
        Checker("contains", expected="Danke"),
    ),
    Probe(
        "symbol-1",
        "What is the chemical symbol for gold? Reply with only the symbol.",
        Checker("exact", expected="Au"),
    ),
    Probe(
        "planet-1",
        "Name the planet known as the Red Planet. Reply with only the name.",
        Checker("contains", expected="Mars"),
    ),
    Probe(
        "sides-1",
        "How many sides does a hexagon have? Reply with only the number.",
        Checker("exact", expected="6"),
    ),
    Probe(
        "json-2",
        'Reply with only a JSON object: {"capital": <the capital of Japan>}',
        Checker("json_field", expected="Tokyo", field="capital"),
    ),
    Probe(
        "ocean-1",
        "What is the largest ocean on Earth? Reply with only its name.",
        Checker("contains", expected="Pacific"),
    ),
    Probe(
        "reverse-1",
        "Spell the word 'necessary' backwards. Reply with only the reversed word.",
        Checker("exact", expected="yrassecen"),
    ),
]

OFFICIAL_ANSWERS: dict[str, str] = {
    "arith-1": "42",
    "capital-1": "Paris",
    "json-1": '{"answer": 7}',
    "translate-1": "Danke",
    "symbol-1": "Au",
    "planet-1": "Mars",
    "sides-1": "6",
    "json-2": '{"capital": "Tokyo"}',
    "ocean-1": "Pacific Ocean",
    "reverse-1": "yrassecen",
}

# The probes the reseller silently gets wrong.
DEGRADED_ANSWERS: dict[str, str] = {
    "json-1": '{"answer": 5}',
    "planet-1": "Venus",
    "ocean-1": "Atlantic Ocean",
}

DEMO_PROVIDERS: list[ProviderConfig] = [
    ProviderConfig("official", "demo://official", "model-x"),
    ProviderConfig("reseller", "demo://reseller", "model-x"),
]


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


def fake_transport(
    provider: ProviderConfig, probe: Probe, timeout_s: float
) -> RawResponse:
    text = OFFICIAL_ANSWERS[probe.id]
    latency_s = 0.35 + len(probe.prompt) / 4000.0
    completion_tokens = _tokens(text)
    if provider.name == "reseller":
        text = DEGRADED_ANSWERS.get(probe.id, text)
        completion_tokens = max(1, round(_tokens(text) * 1.6))
        latency_s *= 2.0
    return RawResponse(
        text=text,
        prompt_tokens=_tokens(probe.prompt),
        completion_tokens=completion_tokens,
        latency_s=latency_s,
    )


def demo_records() -> list[Record]:
    return run_probes(DEMO_PROBES, DEMO_PROVIDERS, transport=fake_transport)
