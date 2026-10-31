"""CLI: demo and report run offline; run is wired to the runner."""

import json

import provider_parity.cli as cli
from provider_parity.demo import demo_records
from provider_parity.runner import write_records


def test_cli_demo_markdown(capsys):
    assert cli.main(["demo"]) == 0
    out = capsys.readouterr().out
    assert "# Provider parity report" in out
    assert "DIVERGENT" in out


def test_cli_demo_json(capsys):
    assert cli.main(["demo", "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["metric"] == "provider_parity"


def test_cli_report_and_baseline_flip(tmp_path, capsys):
    path = tmp_path / "run.jsonl"
    write_records(path, demo_records())
    assert cli.main(["report", str(path)]) == 0
    out = capsys.readouterr().out
    assert "Baseline: **official**" in out
    assert cli.main(["report", str(path), "--baseline", "reseller"]) == 0
    out = capsys.readouterr().out
    assert "Baseline: **reseller**" in out


def test_cli_run_writes_records(tmp_path, monkeypatch, capsys):
    probes = tmp_path / "probes.jsonl"
    probes.write_text(
        json.dumps(
            {
                "id": "p1",
                "prompt": "What is 17 + 25?",
                "checker": {"type": "exact", "expected": "42"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    providers = tmp_path / "providers.json"
    providers.write_text(
        json.dumps(
            {
                "providers": [
                    {"name": "official", "base_url": "https://x.invalid/v1", "model": "m"}
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli,
        "run_probes",
        lambda probes_, providers_, timeout_s=60.0: demo_records(),
    )
    out_path = tmp_path / "run.jsonl"
    rc = cli.main(
        ["run", str(probes), "--providers", str(providers), "--out", str(out_path)]
    )
    assert rc == 0
    lines = out_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 20
    assert "wrote 20 record(s)" in capsys.readouterr().err


def test_cli_missing_files_return_2(tmp_path, capsys):
    assert cli.main(["report", str(tmp_path / "nope.jsonl")]) == 2
    assert "error:" in capsys.readouterr().err
