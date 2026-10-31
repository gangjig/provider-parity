"""Compare run logs: is it really the same model on every endpoint?

One provider is the *baseline* (the reference deployment -- by default
the first provider in the log). Every other provider is compared
against it over the probes both answered:

* **success-rate delta** -- how much of the probe suite the provider
  passes, relative to the baseline.
* **outcome agreement** -- on what fraction of common probes the two
  providers agree on pass/fail.
* **text agreement** -- on what fraction their (normalized) response
  texts are identical; meaningful for short-answer probes.
* **token and latency ratios** -- median per-probe completion tokens
  and latency, other / baseline. A different tokenizer, hidden system
  prompt or verbosity setting shows up here even when answers match.

The verdict is a heuristic over a finite probe set, not a proof:

* `PARITY`    -- |delta| <= 0.05 and outcome agreement >= 0.95:
                 consistent with the same model and configuration.
* `SUSPECT`   -- |delta| <= 0.15 and outcome agreement >= 0.85:
                 differences beyond what temperature-0 sampling noise
                 comfortably explains; worth a closer look.
* `DIVERGENT` -- anything worse: unlikely to be the same model, or
                 the same configuration of it.

Temperature 0 is not fully deterministic on real serving stacks, so
small disagreements are expected; the thresholds are set well above
that noise floor.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Iterable, Optional

from .runner import Record

PARITY_MAX_SUCCESS_DELTA = 0.05
PARITY_MIN_AGREEMENT = 0.95
SUSPECT_MAX_SUCCESS_DELTA = 0.15
SUSPECT_MIN_AGREEMENT = 0.85

VERDICT_PARITY = "PARITY"
VERDICT_SUSPECT = "SUSPECT"
VERDICT_DIVERGENT = "DIVERGENT"
VERDICT_INCOMPARABLE = "INCOMPARABLE"


def normalize_text(text: str) -> str:
    """Lowercase, collapse whitespace, drop trailing periods -- the
    comparison form for text agreement, so 'Paris.' and 'paris' count
    as the same answer."""
    return " ".join(text.lower().split()).rstrip(".")


@dataclass
class ProviderSummary:
    provider: str
    probes: int = 0
    successes: int = 0
    errors: int = 0  # records that are transport failures
    median_latency_s: Optional[float] = None
    mean_completion_tokens: Optional[float] = None
    total_cost: Optional[float] = None
    cost_per_successful_probe: Optional[float] = None

    @property
    def success_rate(self) -> float:
        if self.probes == 0:
            return 0.0
        return self.successes / self.probes


@dataclass
class PairComparison:
    baseline: str
    other: str
    common_probes: int
    success_rate_delta: Optional[float]  # other - baseline
    outcome_agreement: Optional[float]
    text_agreement: Optional[float]
    completion_token_ratio: Optional[float]
    latency_ratio: Optional[float]
    verdict: str


@dataclass
class ParityReport:
    baseline: str
    summaries: list[ProviderSummary]  # baseline first, then by name
    pairs: list[PairComparison]

    def summary_for(self, provider: str) -> ProviderSummary:
        return next(s for s in self.summaries if s.provider == provider)


def _verdict(delta: Optional[float], agreement: Optional[float]) -> str:
    if delta is None or agreement is None:
        return VERDICT_INCOMPARABLE
    if abs(delta) <= PARITY_MAX_SUCCESS_DELTA and agreement >= PARITY_MIN_AGREEMENT:
        return VERDICT_PARITY
    if (
        abs(delta) <= SUSPECT_MAX_SUCCESS_DELTA
        and agreement >= SUSPECT_MIN_AGREEMENT
    ):
        return VERDICT_SUSPECT
    return VERDICT_DIVERGENT


def _summarize(
    provider: str,
    records: list[Record],
    prices: Optional[dict[str, tuple[float, float]]],
) -> ProviderSummary:
    summary = ProviderSummary(provider=provider, probes=len(records))
    summary.successes = sum(1 for r in records if r.success)
    summary.errors = sum(1 for r in records if r.error is not None)
    latencies = [r.latency_s for r in records if r.error is None]
    summary.median_latency_s = (
        statistics.median(latencies) if latencies else None
    )
    completions = [
        r.completion_tokens for r in records if r.completion_tokens is not None
    ]
    summary.mean_completion_tokens = (
        sum(completions) / len(completions) if completions else None
    )
    if prices is not None and provider in prices:
        priced = [
            r
            for r in records
            if r.prompt_tokens is not None and r.completion_tokens is not None
        ]
        if len(priced) == len(records) and records:
            input_per_m, output_per_m = prices[provider]
            summary.total_cost = sum(
                (r.prompt_tokens * input_per_m + r.completion_tokens * output_per_m)
                / 1_000_000.0
                for r in priced
            )
            if summary.successes:
                summary.cost_per_successful_probe = (
                    summary.total_cost / summary.successes
                )
    return summary


def _compare_pair(
    baseline: str,
    other: str,
    by_probe: dict[str, dict[str, Record]],
    summaries: dict[str, ProviderSummary],
) -> PairComparison:
    base_records = by_probe[baseline]
    other_records = by_probe[other]
    common = sorted(set(base_records) & set(other_records))
    if not common:
        return PairComparison(
            baseline=baseline,
            other=other,
            common_probes=0,
            success_rate_delta=None,
            outcome_agreement=None,
            text_agreement=None,
            completion_token_ratio=None,
            latency_ratio=None,
            verdict=VERDICT_INCOMPARABLE,
        )
    outcome_matches = sum(
        1 for pid in common if base_records[pid].success == other_records[pid].success
    )
    text_matches = sum(
        1
        for pid in common
        if normalize_text(base_records[pid].text)
        == normalize_text(other_records[pid].text)
    )
    token_ratios = [
        other_records[pid].completion_tokens / base_records[pid].completion_tokens
        for pid in common
        if base_records[pid].completion_tokens
        and other_records[pid].completion_tokens is not None
    ]
    latency_ratios = [
        other_records[pid].latency_s / base_records[pid].latency_s
        for pid in common
        if base_records[pid].latency_s > 0 and other_records[pid].latency_s > 0
    ]
    delta = (
        summaries[other].success_rate - summaries[baseline].success_rate
    )
    agreement = outcome_matches / len(common)
    return PairComparison(
        baseline=baseline,
        other=other,
        common_probes=len(common),
        success_rate_delta=delta,
        outcome_agreement=agreement,
        text_agreement=text_matches / len(common),
        completion_token_ratio=(
            statistics.median(token_ratios) if token_ratios else None
        ),
        latency_ratio=(
            statistics.median(latency_ratios) if latency_ratios else None
        ),
        verdict=_verdict(delta, agreement),
    )


def compare(
    records: Iterable[Record],
    baseline: Optional[str] = None,
    prices: Optional[dict[str, tuple[float, float]]] = None,
) -> ParityReport:
    """Build the parity report for a run log. `prices` optionally maps
    provider name -> (input, output) USD per 1M tokens; providers
    without complete usage data are left unpriced rather than priced
    on partial data."""
    records = list(records)
    if not records:
        raise ValueError("no records: the run log is empty")
    providers_in_order: list[str] = []
    by_probe: dict[str, dict[str, Record]] = {}
    grouped: dict[str, list[Record]] = {}
    for record in records:
        if record.provider not in grouped:
            grouped[record.provider] = []
            by_probe[record.provider] = {}
            providers_in_order.append(record.provider)
        grouped[record.provider].append(record)
        by_probe[record.provider][record.probe_id] = record
    if len(providers_in_order) < 2:
        raise ValueError(
            "parity needs records from at least two providers; "
            f"found only {providers_in_order[0]!r}"
        )
    if baseline is None:
        baseline = providers_in_order[0]
    elif baseline not in grouped:
        raise ValueError(
            f"baseline provider {baseline!r} has no records; "
            f"providers present: {', '.join(providers_in_order)}"
        )
    summaries = {
        name: _summarize(name, grouped[name], prices)
        for name in providers_in_order
    }
    ordered_summaries = [summaries[baseline]] + [
        summaries[name] for name in sorted(grouped) if name != baseline
    ]
    pairs = [
        _compare_pair(baseline, name, by_probe, summaries)
        for name in sorted(grouped)
        if name != baseline
    ]
    return ParityReport(
        baseline=baseline, summaries=ordered_summaries, pairs=pairs
    )


def build_insights(report: ParityReport) -> list[str]:
    """Short human-readable takeaways that fall out of the comparisons."""
    insights: list[str] = []
    base = report.summary_for(report.baseline)
    for pair in report.pairs:
        other = report.summary_for(pair.other)
        if pair.verdict == VERDICT_INCOMPARABLE:
            insights.append(
                f"{pair.other} shares no probes with {pair.baseline}: "
                f"the two runs are not comparable."
            )
            continue
        insights.append(
            f"{pair.other} vs {pair.baseline}: {pair.verdict} -- "
            f"success {other.success_rate:.0%} vs {base.success_rate:.0%} "
            f"({pair.success_rate_delta:+.0%}), outcome agreement "
            f"{pair.outcome_agreement:.0%} over {pair.common_probes} "
            f"common probe(s)."
        )
        if (
            pair.text_agreement is not None
            and pair.outcome_agreement is not None
            and pair.outcome_agreement - pair.text_agreement >= 0.3
        ):
            insights.append(
                f"{pair.other} reaches the same pass/fail outcomes as "
                f"{pair.baseline} but with different wording (text "
                f"agreement {pair.text_agreement:.0%}): that pattern "
                f"points to different decoding or hidden prompting "
                f"rather than different capability."
            )
        if pair.completion_token_ratio is not None and (
            pair.completion_token_ratio >= 1.5
            or pair.completion_token_ratio <= 0.67
        ):
            insights.append(
                f"{pair.other} reports {pair.completion_token_ratio:.2f}x "
                f"the completion tokens of {pair.baseline} per probe: a "
                f"different tokenizer, or hidden verbosity, is inflating "
                f"its usage independent of answer quality."
            )
    for summary in report.summaries:
        if summary.errors:
            insights.append(
                f"{summary.provider} failed to answer {summary.errors} "
                f"probe(s) at all (transport errors); those probes count "
                f"as failures in its success rate."
            )
    return insights
