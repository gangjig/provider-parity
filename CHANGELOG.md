# Changelog

## 0.1.0 — 2026-10-31

- **Initial release: probe-based parity reports for model providers.**
  `run` sends a JSONL probe suite (small tasks with deterministic
  checkers — exact, contains, regex, json_field; no LLM judge) to two
  or more OpenAI-compatible endpoints at temperature 0 and records
  every attempt — pass/fail, response text, latency, reported usage,
  transport errors included — in a JSONL run log. `report` compares
  each provider against a baseline over their common probes:
  success-rate delta, outcome agreement, normalized-text agreement,
  median completion-token and latency ratios, and cost per successful
  probe when a prices file is supplied. Each pair gets a heuristic
  verdict (PARITY / SUSPECT / DIVERGENT) from documented thresholds.
  `demo` runs the whole pipeline offline against two simulated
  endpoints — one faithful, one silently degraded (3 of 10 probes
  wrong, 2.00x reported completion tokens, 2.00x latency) — and the
  degraded one is correctly flagged DIVERGENT. Standard library only.
  Motivated by Vals AI's provider index, reported in Latent Space
  AINews (2026-10-24): the same Kimi K3 scored 60.6% on legal tasks
  via Baseten vs 75.8% via Moonshot's own endpoint:
  https://www.latent.space/p/ainews-kimi-31/
