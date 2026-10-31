"""Rendering: Markdown tables and JSON carry the same verdicts."""

import json

from provider_parity.compare import build_insights, compare
from provider_parity.demo import demo_records
from provider_parity.report import render_json, render_markdown


def test_markdown_report():
    report = compare(demo_records())
    md = render_markdown(report, build_insights(report))
    assert "# Provider parity report" in md
    assert "Baseline: **official**" in md
    assert "| reseller |" in md
    assert "**DIVERGENT**" in md
    # No prices were given: cost column is the em-dash, never a fake $0.
    assert "$0.0000" not in md


def test_json_report():
    report = compare(demo_records())
    data = json.loads(render_json(report, build_insights(report)))
    assert data["metric"] == "provider_parity"
    assert data["baseline"] == "official"
    (pair,) = data["pairs"]
    assert pair["provider"] == "reseller"
    assert pair["verdict"] == "DIVERGENT"
    assert pair["success_rate_delta"] == -0.3
    providers = {p["provider"]: p for p in data["providers"]}
    assert providers["official"]["success_rate"] == 1.0
    assert providers["reseller"]["success_rate"] == 0.7
    assert providers["official"]["cost_per_successful_probe_usd"] is None
