# provider-parity

**Is the model you are paying for the model you are actually getting?**

The same model name served through different providers is not
guaranteed to be the same model in practice: different quantization,
tokenizers, hidden system prompts, decoding defaults or outright
substitution can all sit behind an identical model string. This tool
checks, with evidence: it runs one fixed suite of small,
machine-checkable **probes** against two or more OpenAI-compatible
endpoints and reports how their behavior actually compares.

The motivation is not hypothetical. Vals AI's provider index (reported
in Latent Space AINews, 2026-10-24) found the same Kimi K3 scoring
**60.6% on legal tasks via Baseten vs 75.8% via Moonshot's own
endpoint** — a 15-point gap that the similar aggregate scores
concealed; Moonshot ended up publishing its own endpoint verifier.
`provider-parity` is the small, self-hostable version of that check:
your probes, your endpoints, a verdict you can re-run.

## Quickstart

No keys, no network — the demo compares two simulated endpoints, one
faithful and one silently degraded:

```bash
pip install -e .
provider-parity demo
```

```
| Provider | Probes | Success rate | Median latency | Mean completion tokens | Cost / successful probe |
|---|---:|---:|---:|---:|---:|
| official | 10 | 100% | 0.37s | 1.9 | — |
| reseller | 10 | 70% | 0.73s | 3.3 | — |

| Provider | Common probes | Δ success | Outcome agreement | Text agreement | Token ratio | Latency ratio | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| reseller | 10 | -30% | 70% | 70% | 2.00x | 2.00x | **DIVERGENT** |
```

Against real endpoints:

```bash
provider-parity run probes.jsonl --providers providers.json --out run.jsonl
provider-parity report run.jsonl
provider-parity report run.jsonl --prices prices.json   # add cost per successful probe
```

A starter probe suite (10 probes) ships in
`src/provider_parity/data/probes.jsonl`; write your own to match the
workload you actually care about — parity on *your* tasks is the
point.

## How it works

**Probes** are tiny tasks with deterministic checkers — no LLM judge.
Each probe is one JSONL line:

```json
{"id": "arith-1", "prompt": "What is 17 + 25? Reply with only the number.",
 "checker": {"type": "exact", "expected": "42"}}
```

Checker types: `exact` (stripped response equals), `contains`
(substring), `regex`, and `json_field` (response parses as JSON and a
dotted field path equals a value). Mix arithmetic, recall,
instruction-following and structured-output probes so a degraded
deployment has nowhere to hide.

**Providers** are configured by name, base URL and model; API keys are
referenced by environment-variable *name* and never stored:

```json
{"providers": [
  {"name": "official", "base_url": "https://api.example.com/v1",
   "model": "model-x", "api_key_env": "EXAMPLE_API_KEY"},
  {"name": "reseller", "base_url": "https://reseller.example/v1",
   "model": "model-x", "api_key_env": "RESELLER_API_KEY"}
]}
```

`run` sends each probe once per provider at temperature 0 and writes
a run log: per probe, per provider — pass/fail, response text, latency,
and token usage as reported by the endpoint. Transport failures are
recorded as failed probes, not fatal errors.

**Report** picks a baseline (default: the first provider in the log)
and compares every other provider against it:

- **Success-rate delta** and **outcome agreement** (fraction of common
  probes with the same pass/fail) measure behavioral parity.
- **Text agreement** (normalized texts identical) separates "different
  words, same capability" from "different capability".
- **Token and latency ratios** (medians, other / baseline) expose a
  different tokenizer, hidden verbosity, or a slower serving stack
  even when answers match.
- With `--prices`, **cost per successful probe** prices the gap.

Verdicts are heuristics over a finite probe set, not proof:

| Verdict | Condition | Reading |
|---|---|---|
| `PARITY` | \|Δ success\| ≤ 5% and agreement ≥ 95% | consistent with the same model + configuration |
| `SUSPECT` | \|Δ success\| ≤ 15% and agreement ≥ 85% | beyond comfortable sampling noise; look closer |
| `DIVERGENT` | anything worse | unlikely to be the same model, or the same configuration |

## Recreate this project from a prompt

> Write a small Python command-line tool, standard library only, that
> checks whether the same LLM served by different providers actually
> behaves like the same model. It runs a fixed suite of small probe
> tasks, each scored by a deterministic checker with no LLM judge,
> against two or more OpenAI-compatible endpoints at temperature zero,
> and logs every attempt (pass or fail, response text, latency, and
> token usage) to a JSONL run log. A report then compares each provider
> against a baseline over their shared probes: success-rate difference,
> agreement on outcomes and on normalized response text, token and
> latency ratios, and optionally cost per successful probe. Each
> provider gets a verdict of parity, suspect, or divergent from
> documented thresholds, and a demo with two simulated endpoints, one
> faithful and one silently degraded, runs the whole pipeline offline
> with no API keys.

## Limitations

- **Verdicts are evidence, not proof.** A PARITY verdict means "this
  probe suite could not tell them apart", not a cryptographic identity
  guarantee; a determined substitution that only differs off-probe
  will pass. Bigger, workload-shaped suites catch more.
- **Temperature 0 is not fully deterministic** on real serving stacks;
  thresholds are set above that noise floor, and borderline SUSPECT
  results deserve a re-run before conclusions.
- **Hidden configuration is inferred, not seen.** The tool observes
  behavior, usage and latency; it cannot directly read a provider's
  system prompt or quantization — it can only show you the fingerprints
  they leave.
- Probes are single-turn and text-only by design: this is a parity
  smoke test, not a capability benchmark.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e . pytest
python -m pytest        # 39 tests, fully offline
```

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 Gang Ji.
