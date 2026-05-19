"""
run_all.py — orchestrates the five pipeline stages in order.
Usage: python run_all.py
"""
import subprocess
import sys
import time
from pathlib import Path

STAGES = [
    ("stitcher",  "src.stitcher"),
    ("analytics", "src.analytics"),
    ("insights",  "src.insights"),
    ("report",    "src.report"),
    ("evaluate",  "src.evaluate"),
]

TIMINGS: dict[str, float] = {}


def run_stage(name: str, module: str) -> None:
    print(f"\n{'='*60}")
    print(f"  Stage: {name}")
    print(f"{'='*60}")
    t0 = time.perf_counter()
    result = subprocess.run([sys.executable, "-m", module], check=False)
    elapsed = time.perf_counter() - t0
    TIMINGS[name] = round(elapsed, 2)
    if result.returncode != 0:
        print(f"[FAIL] {name} exited with code {result.returncode}")
        sys.exit(result.returncode)
    print(f"[OK]   {name} completed in {elapsed:.1f}s")


def smoke_test() -> None:
    derived = Path("data/derived")
    required = ["journeys.csv", "metrics.json", "insights.json", "weekly_report.md"]
    for fname in required:
        fpath = derived / fname
        assert fpath.exists(), f"Missing expected output: {fpath}"
    import pandas as pd
    journeys = pd.read_csv(derived / "journeys.csv")
    assert len(journeys) > 0, "journeys.csv is empty — stitcher produced no journeys"
    print("\n[SMOKE] All expected outputs present and non-empty.")


if __name__ == "__main__":
    total_start = time.perf_counter()
    for stage_name, stage_module in STAGES:
        run_stage(stage_name, stage_module)
    smoke_test()
    total = time.perf_counter() - total_start
    print(f"\n{'='*60}")
    print("  Pipeline complete")
    print(f"  Total time: {total:.1f}s")
    print(f"  Stage timings: {TIMINGS}")
    print(f"{'='*60}")
