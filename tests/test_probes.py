"""Probe suites and checkers: small tasks, deterministic grading."""

import json

import pytest

from provider_parity.probes import Checker, Probe, load_probes, run_checker


def test_exact_checker_strips_whitespace():
    checker = Checker("exact", expected="42")
    assert run_checker(checker, " 42 ")
    assert not run_checker(checker, "41")


def test_contains_checker():
    checker = Checker("contains", expected="Paris")
    assert run_checker(checker, "The answer is Paris.")
    assert not run_checker(checker, "London")


def test_regex_checker():
    checker = Checker("regex", pattern=r"\b\d{4}\b")
    assert run_checker(checker, "in the year 2026")
    assert not run_checker(checker, "no digits here")


def test_json_field_checker_top_and_nested():
    top = Checker("json_field", expected=7, field="answer")
    assert run_checker(top, '{"answer": 7}')
    assert not run_checker(top, '{"answer": 5}')
    nested = Checker("json_field", expected="x", field="result.value")
    assert run_checker(nested, '{"result": {"value": "x"}}')
    assert not run_checker(nested, '{"result": {}}')


def test_json_field_checker_rejects_non_json():
    checker = Checker("json_field", expected=7, field="answer")
    assert not run_checker(checker, "the answer is 7")


def test_checker_validation():
    with pytest.raises(ValueError, match="unknown checker type"):
        Checker.from_dict({"type": "fuzzy"})
    with pytest.raises(ValueError, match="string 'expected'"):
        Checker.from_dict({"type": "exact"})
    with pytest.raises(ValueError, match="invalid regex"):
        Checker.from_dict({"type": "regex", "pattern": "([bad"})
    with pytest.raises(ValueError, match="'field'"):
        Checker.from_dict({"type": "json_field", "expected": 1})
    with pytest.raises(ValueError, match="'expected'"):
        Checker.from_dict({"type": "json_field", "field": "a"})


def _write(tmp_path, lines):
    path = tmp_path / "probes.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _line(pid, prompt="Q?", checker=None):
    return json.dumps(
        {
            "id": pid,
            "prompt": prompt,
            "checker": checker or {"type": "exact", "expected": "42"},
        }
    )


def test_load_probes_roundtrip(tmp_path):
    path = _write(tmp_path, [_line("a"), _line("b")])
    probes = load_probes(path)
    assert [p.id for p in probes] == ["a", "b"]
    assert probes[0].checker.type == "exact"


def test_load_probes_rejects_duplicates_and_empty(tmp_path):
    with pytest.raises(ValueError, match="duplicate probe id"):
        load_probes(_write(tmp_path, [_line("a"), _line("a")]))
    with pytest.raises(ValueError, match="must not be empty"):
        load_probes(_write(tmp_path, [_line("a", prompt="  ")]))
    with pytest.raises(ValueError, match="invalid JSON"):
        load_probes(_write(tmp_path, ["{not json"]))


def test_probe_from_dict_missing_fields():
    with pytest.raises(ValueError, match="missing field"):
        Probe.from_dict({"id": "x"})
