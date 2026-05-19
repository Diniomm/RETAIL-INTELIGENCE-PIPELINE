"""
evaluate.py — pipeline evaluation: coverage, confidence distribution, threshold sensitivity.

Reads:  data/raw/events.csv, data/derived/journeys.csv
Writes: outputs/evaluation.json, outputs/sensitivity.csv
"""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from src.stitcher import save_journeys, stitch
from src.utils import get_logger, load_config, load_events, save_json

log = get_logger("evaluate")


def compute_coverage(edf: pd.DataFrame, jdf: pd.DataFrame) -> dict:
    total_events = len(edf)
    events_in_journeys = int(jdf["num_events"].sum())
    return {
        "total_events": int(total_events),
        "events_assigned": events_in_journeys,
        "coverage_rate": round(events_in_journeys / total_events, 4) if total_events else 0.0,
    }


def confidence_distribution(jdf: pd.DataFrame) -> dict:
    total = len(jdf)
    dist = jdf["stitch_confidence"].value_counts().to_dict()
    return {
        k: {"count": int(v), "pct": round(v / total * 100, 2)}
        for k, v in dist.items()
    }


def close_reason_distribution(jdf: pd.DataFrame) -> dict:
    total = len(jdf)
    dist = jdf["close_reason"].value_counts().to_dict()
    return {
        k: {"count": int(v), "pct": round(v / total * 100, 2)}
        for k, v in dist.items()
    }


def sensitivity_sweep(cfg: dict) -> list[dict]:
    windows = cfg["sensitivity"]["linger_windows"]
    base_window = cfg["stitcher"]["linger_window"]
    results = []

    for w in windows:
        cfg_copy = {**cfg, "stitcher": {**cfg["stitcher"], "linger_window": w}}
        journeys = stitch(cfg_copy)
        jdf = pd.DataFrame([j.__dict__ for j in journeys])
        total = len(journeys)
        completed = int(jdf["completed"].sum()) if total else 0
        low_conf = int((jdf["stitch_confidence"] == "low").sum()) if total else 0
        results.append({
            "linger_window": w,
            "total_journeys": total,
            "completed_journeys": completed,
            "completion_rate": round(completed / total, 4) if total else 0.0,
            "low_confidence_pct": round(low_conf / total * 100, 2) if total else 0.0,
            "delta_journeys_vs_base": None,
        })
        log.info(
            "Sensitivity w=%d: %d journeys, %.1f%% completed.",
            w, total, completed / total * 100 if total else 0,
        )

    base = next((r for r in results if r["linger_window"] == base_window), None)
    if base:
        base_total = base["total_journeys"]
        for r in results:
            r["delta_journeys_vs_base"] = r["total_journeys"] - base_total

    return results


def save_sensitivity_csv(rows: list[dict], path: str) -> None:
    if not rows:
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    log.info("Wrote sensitivity table to %s.", path)


if __name__ == "__main__":
    cfg = load_config()
    edf = load_events(cfg["paths"]["events"])
    jdf = pd.read_csv(cfg["paths"]["journeys"], parse_dates=["entry_ts", "exit_ts"])

    coverage = compute_coverage(edf, jdf)
    conf_dist = confidence_distribution(jdf)
    close_dist = close_reason_distribution(jdf)

    log.info("Running sensitivity sweep over linger windows %s ...", cfg["sensitivity"]["linger_windows"])
    sensitivity = sensitivity_sweep(cfg)

    evaluation = {
        "coverage": coverage,
        "confidence_distribution": conf_dist,
        "close_reason_distribution": close_dist,
        "sensitivity": sensitivity,
    }
    save_json(evaluation, cfg["paths"]["evaluation"])
    save_sensitivity_csv(sensitivity, cfg["paths"]["sensitivity"])
    log.info("Evaluation complete.")
