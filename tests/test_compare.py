"""Comparison: verdicts, agreement, ratios, costs.

Records are built by hand so the arithmetic is exact: token counts and
latencies are round numbers, and success patterns are chosen to land
on specific verdict bands.
"""

import pytest

from provider_parity.compare import build_insights, compare, normalize_text
from provider_parity.runner import Record


def rec(provider, probe, success, text="", latency=1.0, ct=10, pt=20, error=None):
    return Record(
        provider=provider,
        probe_id=probe,
        success=success,
        latency_s=latency,
        prompt_tokens=pt,
        completion_tokens=ct,
        text=text,
        error=error,
    )


def suite(provider, n=10, fail=(), **kwargs):
    return [
        rec(provider, f"p{i}", i not in fail, text=f"answer-{i}", **kwargs)
        for i in range(n)
    ]


def test_identical_providers_are_parity():
    records = suite("official") + suite("mirror")
    report = compare(records)
    (pair,) = report.pairs
    assert report.baseline == "official"  # first provider in the log
    assert pair.verdict == "PARITY"
    assert pair.success_rate_delta == 0.0
    assert pair.outcome_agreement == 1.0
    assert pair.text_agreement == 1.0
    assert pair.completion_token_ratio == 1.0
    assert pair.latency_ratio == 1.0


def test_degraded_provider_is_divergent():
    records = suite("official") + suite("reseller", fail={2, 5, 8})
    report = compare(records)
    (pair,) = report.pairs
    assert pair.verdict == "DIVERGENT"
    assert pair.success_rate_delta == pytest.approx(-0.3)
    assert pair.outcome_agreement == pytest.approx(0.7)


def test_borderline_provider_is_suspect():
    # 20 probes: baseline fails only probe 0 (19/20 = 95%); reseller
    # fails 0, 1, 2 (17/20 = 85%) -> delta -0.10, agreement 18/20.
    records = suite("official", n=20, fail={0}) + suite(
        "reseller", n=20, fail={0, 1, 2}
    )
    report = compare(records)
    (pair,) = report.pairs
    # delta = 0.85 - 0.95 = -0.10 (in SUSPECT band); agreement: outcomes
    # differ on probes 1,2 -> 18/20 = 0.90 (in band).
    assert pair.success_rate_delta == pytest.approx(-0.10)
    assert pair.outcome_agreement == pytest.approx(0.90)
    assert pair.verdict == "SUSPECT"


def test_text_agreement_uses_normalization():
    records = [
        rec("official", "p0", True, text="Paris."),
        rec("mirror", "p0", True, text="  paris "),
    ]
    report = compare(records)
    (pair,) = report.pairs
    assert pair.text_agreement == 1.0
    assert normalize_text("The  Answer\nIs 42.") == "the answer is 42"


def test_token_and_latency_ratios_are_medians():
    records = suite("official", ct=10, latency=1.0) + suite(
        "verbose", ct=25, latency=0.5
    )
    report = compare(records)
    (pair,) = report.pairs
    assert pair.completion_token_ratio == pytest.approx(2.5)
    assert pair.latency_ratio == pytest.approx(0.5)
    insights = build_insights(report)
    assert any("2.50x the completion tokens" in text for text in insights)


def test_missing_usage_gives_none_ratios():
    records = suite("official") + suite("silent", ct=None, pt=None)
    report = compare(records)
    (pair,) = report.pairs
    assert pair.completion_token_ratio is None
    summary = report.summary_for("silent")
    assert summary.mean_completion_tokens is None


def test_no_common_probes_is_incomparable():
    records = [rec("a", "p1", True), rec("b", "p2", True)]
    report = compare(records)
    (pair,) = report.pairs
    assert pair.verdict == "INCOMPARABLE"
    assert pair.common_probes == 0


def test_compare_requires_two_providers_and_known_baseline():
    with pytest.raises(ValueError, match="at least two providers"):
        compare(suite("only"))
    with pytest.raises(ValueError, match="no records"):
        compare([])
    with pytest.raises(ValueError, match="has no records"):
        compare(suite("a") + suite("b"), baseline="ghost")


def test_explicit_baseline_flips_pairs():
    records = suite("official") + suite("reseller", fail={1})
    report = compare(records, baseline="reseller")
    (pair,) = report.pairs
    assert pair.other == "official"
    assert pair.success_rate_delta == pytest.approx(0.1)


def test_cost_per_successful_probe():
    prices = {"official": (10.0, 20.0), "reseller": (10.0, 20.0)}
    records = suite("official", n=2, pt=1_000_000, ct=0) + suite(
        "reseller", n=2, fail={1}, pt=1_000_000, ct=0
    )
    report = compare(records, prices=prices)
    official = report.summary_for("official")
    reseller = report.summary_for("reseller")
    # Each probe costs $10 (1M input tokens at $10/1M); official passes
    # both, reseller passes one of two.
    assert official.total_cost == pytest.approx(20.0)
    assert official.cost_per_successful_probe == pytest.approx(10.0)
    assert reseller.cost_per_successful_probe == pytest.approx(20.0)


def test_cost_skipped_when_usage_incomplete():
    prices = {"official": (10.0, 20.0), "reseller": (10.0, 20.0)}
    records = suite("official") + suite("reseller", ct=None)
    report = compare(records, prices=prices)
    assert report.summary_for("reseller").total_cost is None
    assert report.summary_for("official").total_cost is not None


def test_error_records_surface_in_summary_and_insights():
    records = suite("official", n=2) + [
        rec("flaky", "p0", False, error="TransportError: HTTP 503"),
        rec("flaky", "p1", True, text="answer-1"),
    ]
    report = compare(records)
    flaky = report.summary_for("flaky")
    assert flaky.errors == 1
    assert flaky.success_rate == 0.5
    # Latency median excludes the error record (latency 0.0 placeholder).
    assert flaky.median_latency_s == 1.0
    insights = build_insights(report)
    assert any("failed to answer 1 probe" in text for text in insights)
