"""AI evaluation runner: golden dataset → scored report.

Usage: uv run python -m evals.run [--dataset evals/datasets/golden.yaml]

- temporal cases run deterministically (no LLM) — must pass 100%.
- injection cases are a HARD GATE — any failure exits non-zero.
- extraction_live cases run against the configured LLM endpoint and report
  pass/fail per expectation; they are skipped (not failed) when no endpoint
  is reachable, so CI stays usable offline.
"""

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from app.services.extraction.injection import detect_injection
from app.services.temporal.normalizer import normalize_when

DEFAULT_DATASET = Path(__file__).parent / "datasets" / "golden.yaml"


def run_temporal(case: dict) -> tuple[bool, str]:
    expect = case["expect"]
    result = normalize_when(
        case["when_text"],
        reference=datetime.fromisoformat(case["reference"]),
        tz_name="Asia/Jakarta",
    )
    if expect.get("unresolved"):
        return (
            result.normalized_at is None,
            f"resolved to {result.normalized_at} but must stay unresolved",
        )
    if expect.get("recurrence"):
        return (result.is_recurrence, "not detected as recurrence")
    if result.normalized_at is None:
        return False, "failed to resolve"
    local = result.normalized_at.astimezone(ZoneInfo("Asia/Jakarta"))
    if expect.get("date") and local.date().isoformat() != expect["date"]:
        return False, f"date {local.date()} != {expect['date']}"
    if expect.get("hour_local") is not None and local.hour != expect["hour_local"]:
        return False, f"hour {local.hour} != {expect['hour_local']}"
    if expect.get("confidence_min") is not None and result.confidence < expect["confidence_min"]:
        return False, f"confidence {result.confidence} < {expect['confidence_min']}"
    if expect.get("confidence_max") is not None and result.confidence > expect["confidence_max"]:
        return False, f"confidence {result.confidence} > {expect['confidence_max']}"
    if "explicit" in expect and result.explicit != expect["explicit"]:
        return False, f"explicit={result.explicit} != {expect['explicit']}"
    return True, ""


def run_injection(case: dict) -> tuple[bool, str]:
    flags = detect_injection(case["text"])
    minimum = case["expect"].get("flags_min", 1)
    return (len(flags) >= minimum, f"{len(flags)} flags (expected >= {minimum}): {flags}")


def run_extraction_live(case: dict) -> tuple[bool, str, bool]:
    """Returns (passed, detail, skipped)."""
    from app.agents.llm_client import LLMClient, LLMError
    from app.agents.router import ModelRouter
    from app.services.extraction.pipeline import _extract_chunk
    from app.services.extraction.verify import quote_in_text

    client = LLMClient()
    if not client.available():
        return True, "LLM not reachable — skipped", True

    class _Chunk:
        text = case["text"]
        id = None
        page = 1

    class _Doc:
        user_id = None
        id = None

    try:
        extraction = _extract_chunk(None, ModelRouter(client), _Doc, _Chunk)
    except LLMError as exc:
        return False, f"LLM error: {exc}", False

    expect = case["expect"]
    # Quote-verified facts only — same rule as production.
    dates = [d for d in extraction.dates if quote_in_text(d.get("quote", ""), case["text"])]
    tasks = [t for t in extraction.tasks if quote_in_text(t.get("quote", ""), case["text"])]
    commitments = [
        c for c in extraction.commitments if quote_in_text(c.get("quote", ""), case["text"])
    ]

    checks = []
    if "deadlines_min" in expect:
        checks.append((len(dates) >= expect["deadlines_min"], f"dates {len(dates)} < min"))
    if "deadlines_max" in expect:
        checks.append((len(dates) <= expect["deadlines_max"], f"dates {len(dates)} > max"))
    if "tasks_min" in expect:
        checks.append((len(tasks) >= expect["tasks_min"], f"tasks {len(tasks)} < min"))
    if "tasks_max" in expect:
        checks.append((len(tasks) <= expect["tasks_max"], f"tasks {len(tasks)} > max"))
    if "commitments_min" in expect:
        checks.append(
            (len(commitments) >= expect["commitments_min"], f"commitments {len(commitments)} < min")
        )
    if "commitments_max" in expect:
        checks.append(
            (len(commitments) <= expect["commitments_max"], f"commitments {len(commitments)} > max")
        )
    if "deadline_date" in expect and dates:
        normalized = normalize_when(
            dates[0].get("when_text", ""),
            reference=datetime.fromisoformat("2026-09-02T10:00:00+07:00"),
            tz_name="Asia/Jakarta",
        )
        got = (
            normalized.normalized_at.astimezone(ZoneInfo("Asia/Jakarta")).date().isoformat()
            if normalized.normalized_at
            else None
        )
        checks.append((got == expect["deadline_date"], f"normalized date {got} != {expect['deadline_date']}"))

    failed = [detail for ok, detail in checks if not ok]
    return (not failed, "; ".join(failed), False)


def main(dataset_path: str | None = None) -> int:
    dataset = yaml.safe_load((Path(dataset_path) if dataset_path else DEFAULT_DATASET).read_text())
    results = {"pass": 0, "fail": 0, "skip": 0}
    hard_gate_failed = False

    for case in dataset["cases"]:
        kind = case["kind"]
        skipped = False
        if kind == "temporal":
            ok, detail = run_temporal(case)
        elif kind == "injection":
            ok, detail = run_injection(case)
            if not ok:
                hard_gate_failed = True
        elif kind == "extraction_live":
            ok, detail, skipped = run_extraction_live(case)
        else:
            print(f"?? unknown kind {kind} for {case['id']}")
            continue

        if skipped:
            results["skip"] += 1
            status = "SKIP"
        elif ok:
            results["pass"] += 1
            status = "PASS"
        else:
            results["fail"] += 1
            status = "FAIL"
        mark = "✔" if status == "PASS" else ("–" if status == "SKIP" else "✘")
        print(f"{mark} {status:4} [{kind:15}] {case['id']}" + (f" — {detail}" if detail and not ok else ""))

    print(
        f"\nEval summary: {results['pass']} passed, {results['fail']} failed, "
        f"{results['skip']} skipped"
    )
    if hard_gate_failed:
        print("HARD GATE FAILED: injection defense regressed.")
        return 2
    if results["fail"]:
        return 1
    return 0


if __name__ == "__main__":
    path = sys.argv[sys.argv.index("--dataset") + 1] if "--dataset" in sys.argv else None
    sys.exit(main(path))
