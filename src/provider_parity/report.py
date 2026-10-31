"""Render a parity report as a Markdown table or as JSON."""

from __future__ import annotations

import json
from typing import Optional

from .compare import PairComparison, ParityReport, ProviderSummary


def _money(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"${value:,.4f}"


def _seconds(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}s"


def _ratio(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}x"


def _pct(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{value:.0%}"


def _signed_pct(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{value:+.0%}"


def render_markdown(report: ParityReport, insights: list[str]) -> str:
    lines = [
        "# Provider parity report",
        "",
        f"Baseline: **{report.baseline}**. Verdicts are heuristics over "
        f"a finite probe set, not proof of model identity.",
        "",
        "| Provider | Probes | Success rate | Median latency | "
        "Mean completion tokens | Cost / successful probe |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for s in report.summaries:
        tokens = (
            f"{s.mean_completion_tokens:.1f}"
            if s.mean_completion_tokens is not None
            else "—"
        )
        lines.append(
            f"| {s.provider} | {s.probes} | {s.success_rate:.0%} | "
            f"{_seconds(s.median_latency_s)} | {tokens} | "
            f"{_money(s.cost_per_successful_probe)} |"
        )
    if report.pairs:
        lines += [
            "",
            "## Against the baseline",
            "",
            "| Provider | Common probes | Δ success | Outcome agreement | "
            "Text agreement | Token ratio | Latency ratio | Verdict |",
            "|---|---:|---:|---:|---:|---:|---:|---|",
        ]
        for p in report.pairs:
            lines.append(
                f"| {p.other} | {p.common_probes} | "
                f"{_signed_pct(p.success_rate_delta)} | "
                f"{_pct(p.outcome_agreement)} | {_pct(p.text_agreement)} | "
                f"{_ratio(p.completion_token_ratio)} | "
                f"{_ratio(p.latency_ratio)} | **{p.verdict}** |"
            )
    if insights:
        lines += ["", "## Insights", ""]
        lines += [f"- {text}" for text in insights]
    return "\n".join(lines) + "\n"


def _summary_dict(s: ProviderSummary) -> dict:
    return {
        "provider": s.provider,
        "probes": s.probes,
        "successes": s.successes,
        "success_rate": round(s.success_rate, 4),
        "errors": s.errors,
        "median_latency_s": (
            round(s.median_latency_s, 4) if s.median_latency_s is not None else None
        ),
        "mean_completion_tokens": (
            round(s.mean_completion_tokens, 2)
            if s.mean_completion_tokens is not None
            else None
        ),
        "total_cost_usd": (
            round(s.total_cost, 6) if s.total_cost is not None else None
        ),
        "cost_per_successful_probe_usd": (
            round(s.cost_per_successful_probe, 6)
            if s.cost_per_successful_probe is not None
            else None
        ),
    }


def _pair_dict(p: PairComparison) -> dict:
    return {
        "provider": p.other,
        "baseline": p.baseline,
        "common_probes": p.common_probes,
        "success_rate_delta": (
            round(p.success_rate_delta, 4)
            if p.success_rate_delta is not None
            else None
        ),
        "outcome_agreement": (
            round(p.outcome_agreement, 4)
            if p.outcome_agreement is not None
            else None
        ),
        "text_agreement": (
            round(p.text_agreement, 4) if p.text_agreement is not None else None
        ),
        "completion_token_ratio": (
            round(p.completion_token_ratio, 4)
            if p.completion_token_ratio is not None
            else None
        ),
        "latency_ratio": (
            round(p.latency_ratio, 4) if p.latency_ratio is not None else None
        ),
        "verdict": p.verdict,
    }


def report_to_dict(report: ParityReport, insights: list[str]) -> dict:
    return {
        "metric": "provider_parity",
        "baseline": report.baseline,
        "providers": [_summary_dict(s) for s in report.summaries],
        "pairs": [_pair_dict(p) for p in report.pairs],
        "insights": insights,
    }


def render_json(report: ParityReport, insights: list[str]) -> str:
    return json.dumps(report_to_dict(report, insights), indent=2) + "\n"
