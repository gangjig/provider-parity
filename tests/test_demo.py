"""The bundled demo: one faithful endpoint, one silently degraded."""

from importlib import resources
from pathlib import Path

import pytest

from provider_parity.compare import compare
from provider_parity.demo import DEMO_PROBES, demo_records
from provider_parity.probes import load_probes


def test_demo_official_passes_everything_reseller_drops_three():
    records = demo_records()
    official = [r for r in records if r.provider == "official"]
    reseller = [r for r in records if r.provider == "reseller"]
    assert len(official) == len(reseller) == 10
    assert all(r.success for r in official)
    assert sum(r.success for r in reseller) == 7


def test_demo_verdict_is_divergent_with_inflated_usage():
    report = compare(demo_records())
    (pair,) = report.pairs
    assert report.baseline == "official"
    assert pair.verdict == "DIVERGENT"
    assert pair.success_rate_delta == pytest.approx(-0.3)
    assert pair.outcome_agreement == pytest.approx(0.7)
    assert pair.completion_token_ratio >= 1.5
    assert pair.latency_ratio == pytest.approx(2.0)


def test_bundled_probe_suite_matches_demo_probes():
    path = Path(
        str(resources.files("provider_parity").joinpath("data/probes.jsonl"))
    )
    probes = load_probes(path)
    assert [p.id for p in probes] == [p.id for p in DEMO_PROBES]
