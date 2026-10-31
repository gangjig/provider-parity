"""Command line interface: provider-parity {run, report, demo}."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from .compare import build_insights, compare
from .demo import demo_records
from .probes import load_probes
from .report import render_json, render_markdown
from .runner import (
    DEFAULT_TIMEOUT_S,
    load_providers,
    load_records,
    run_probes,
    write_records,
)


def _load_prices(path: Optional[str]) -> Optional[dict[str, tuple[float, float]]]:
    if path is None:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = data.get("providers", data) if isinstance(data, dict) else {}
    prices: dict[str, tuple[float, float]] = {}
    for name, entry in entries.items():
        prices[name] = (float(entry["input_per_m"]), float(entry["output_per_m"]))
    return prices


def _render(records, baseline: Optional[str], prices, fmt: str) -> str:
    report = compare(records, baseline=baseline, prices=prices)
    insights = build_insights(report)
    if fmt == "json":
        return render_json(report, insights)
    return render_markdown(report, insights)


def _print_or_write(text: str, output: Optional[str]) -> None:
    if output:
        Path(output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def _add_format_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format",
        choices=("md", "json"),
        default="md",
        help="output format (default: md)",
    )
    parser.add_argument(
        "--output", metavar="FILE", help="write to FILE instead of stdout"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="provider-parity",
        description="Check whether the same model served by different "
        "providers is actually the same model.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser(
        "run", help="run a probe suite against the configured providers"
    )
    p_run.add_argument("probes", help="path to the probe suite (JSONL)")
    p_run.add_argument(
        "--providers",
        required=True,
        metavar="FILE",
        help="JSON file listing the provider endpoints",
    )
    p_run.add_argument(
        "--out",
        required=True,
        metavar="FILE",
        help="write the run log (JSONL) to FILE",
    )
    p_run.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        help="per-probe request timeout in seconds (default: %(default)s)",
    )

    p_report = sub.add_parser(
        "report", help="compare the providers in a run log"
    )
    p_report.add_argument("runlog", help="path to the run log (JSONL)")
    p_report.add_argument(
        "--baseline",
        help="reference provider (default: the first provider in the log)",
    )
    p_report.add_argument(
        "--prices",
        metavar="FILE",
        help="JSON price file ({provider: {input_per_m, output_per_m}}) "
        "enabling cost per successful probe",
    )
    _add_format_args(p_report)

    p_demo = sub.add_parser(
        "demo",
        help="report on simulated endpoints: one faithful, one silently "
        "degraded (no network, no keys)",
    )
    _add_format_args(p_demo)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            probes = load_probes(args.probes)
            providers = load_providers(args.providers)
            records = run_probes(probes, providers, timeout_s=args.timeout)
            write_records(args.out, records)
            failures = sum(1 for r in records if not r.success)
            print(
                f"wrote {len(records)} record(s) to {args.out} "
                f"({failures} failed probe(s), errors included)",
                file=sys.stderr,
            )
            return 0
        if args.command == "report":
            records = load_records(args.runlog)
            text = _render(
                records, args.baseline, _load_prices(args.prices), args.format
            )
            _print_or_write(text, args.output)
            return 0
        # demo
        text = _render(demo_records(), None, None, args.format)
        _print_or_write(text, args.output)
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
