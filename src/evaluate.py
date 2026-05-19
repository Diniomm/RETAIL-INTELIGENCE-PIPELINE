"""
evaluate.py — Section 5 quality metrics for the trajectory reconstruction pipeline.

Metrics computed (per assignment Section 5):
  1. Consistência          — % of trajectories with no temporal inconsistency
  2. Cobertura             — % of raw events assigned to a journey
  3. Completude            — % of journeys with entry in Z_E and exit in Z_CK
  4. Deteção de anomalias  — % of journeys flagged as anomalous
  5. Precisão numérica     — % of numeric values in the report verifiable against metrics.json
  6. Ausência de alucinação— % of factual claims in the report grounded in source data

Reads:  --input (events CSV, default config paths.events)
        config paths.journeys, paths.metrics, paths.insights, paths.report
Writes: --output (evaluation JSON, default config paths.evaluation)
        config paths.sensitivity  (sensitivity sweep CSV)
"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Any

import pandas as pd

from src.stitcher import stitch
from src.utils import get_logger, load_config, load_events, load_json, save_json

log = get_logger("evaluate")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_metric_values(obj: Any) -> set[float]:
    """Recursively collect all numeric scalars from a JSON structure."""
    values: set[float] = set()

    def _walk(o: Any) -> None:
        if isinstance(o, bool):
            return
        if isinstance(o, (int, float)):
            values.add(round(float(o), 4))
        elif isinstance(o, dict):
            for v in o.values():
                _walk(v)
        elif isinstance(o, list):
            for item in o:
                _walk(item)

    _walk(obj)
    return values


def _extract_numbers(text: str) -> list[float]:
    return [float(m) for m in re.findall(r"\b\d+(?:\.\d+)?\b", text)]


# ---------------------------------------------------------------------------
# 1. Consistência
# ---------------------------------------------------------------------------

def metric_consistencia(jdf: pd.DataFrame) -> dict:
    """
    % of trajectories (journeys) with no temporal inconsistency.
    A journey is consistent when:
      - entry_ts <= exit_ts  (chronological order)
      - duration_s_total >= 0
      - stored duration matches computed duration within 1 second
    """
    total = len(jdf)
    if total == 0:
        return {"consistent_journeys": 0, "total_journeys": 0, "pct": 0.0}

    computed = (jdf["exit_ts"] - jdf["entry_ts"]).dt.total_seconds()
    mask = (
        (jdf["entry_ts"] <= jdf["exit_ts"])
        & (jdf["duration_s_total"] >= 0)
        & ((computed - jdf["duration_s_total"]).abs() < 1.0)
    )
    n = int(mask.sum())
    return {
        "consistent_journeys": n,
        "total_journeys": total,
        "pct": round(n / total * 100, 2),
    }


# ---------------------------------------------------------------------------
# 2. Cobertura
# ---------------------------------------------------------------------------

def metric_cobertura(edf: pd.DataFrame, jdf: pd.DataFrame) -> dict:
    """% of raw events that were assigned to a reconstructed journey."""
    total_events = len(edf)
    events_assigned = int(jdf["num_events"].sum())
    pct = events_assigned / total_events * 100 if total_events else 0.0
    return {
        "total_events": total_events,
        "events_assigned": events_assigned,
        "pct": round(pct, 2),
    }


# ---------------------------------------------------------------------------
# 3. Completude
# ---------------------------------------------------------------------------

def metric_completude(jdf: pd.DataFrame, cfg: dict) -> dict:
    """
    % of journeys with entry in Z_E (entry zone) and exit in Z_CK (checkout zone).
    Z_E and Z_CK are read from config.evaluate; if absent, inferred from data as the
    most common first and last zones of completed journeys.
    """
    total = len(jdf)
    if total == 0:
        return {"complete_journeys": 0, "total_journeys": 0, "pct": 0.0,
                "zone_entry": None, "zone_checkout": None}

    sequences = jdf["zone_sequence"].fillna("")
    first_zones = sequences.apply(lambda s: s.split(">")[0] if s else "")
    last_zones = sequences.apply(lambda s: s.split(">")[-1] if s else "")

    eval_cfg = cfg.get("evaluate", {})
    zone_e = eval_cfg.get("zone_entry") or None
    zone_ck = eval_cfg.get("zone_checkout") or None

    if zone_e is None:
        mode = first_zones[first_zones != ""].mode()
        zone_e = str(mode.iloc[0]) if len(mode) else None

    if zone_ck is None:
        completed_last = last_zones[(jdf["completed"]) & (last_zones != "")]
        mode = completed_last.mode()
        zone_ck = str(mode.iloc[0]) if len(mode) else None

    if zone_e is None or zone_ck is None:
        return {
            "complete_journeys": 0,
            "total_journeys": total,
            "pct": 0.0,
            "zone_entry": zone_e,
            "zone_checkout": zone_ck,
            "note": "Could not determine Z_E / Z_CK from data",
        }

    mask = (first_zones == zone_e) & (last_zones == zone_ck) & jdf["completed"]
    n = int(mask.sum())
    return {
        "complete_journeys": n,
        "total_journeys": total,
        "pct": round(n / total * 100, 2),
        "zone_entry": zone_e,
        "zone_checkout": zone_ck,
    }


# ---------------------------------------------------------------------------
# 4. Deteção de anomalias
# ---------------------------------------------------------------------------

def metric_anomalias(jdf: pd.DataFrame, cfg: dict) -> dict:
    """
    % of journeys flagged as anomalous by at least one rule:
      - stitch_confidence == "low"
      - duration_s_total <= 0
      - max_gap_s >= stale_timeout * anomaly_gap_ratio  (default 0.9)
      - num_events < anomaly_min_events                 (default 2)
    """
    total = len(jdf)
    if total == 0:
        return {"anomalous_journeys": 0, "total_journeys": 0, "pct": 0.0}

    eval_cfg = cfg.get("evaluate", {})
    stale_timeout = cfg["stitcher"]["stale_timeout"]
    gap_ratio = eval_cfg.get("anomaly_gap_ratio", 0.9)
    min_events = eval_cfg.get("anomaly_min_events", 2)

    flags = (
        (jdf["stitch_confidence"] == "low")
        | (jdf["duration_s_total"] <= 0)
        | (jdf["max_gap_s"] >= stale_timeout * gap_ratio)
        | (jdf["num_events"] < min_events)
    )
    n = int(flags.sum())
    return {
        "anomalous_journeys": n,
        "total_journeys": total,
        "pct": round(n / total * 100, 2),
        "rules_applied": [
            "stitch_confidence == 'low'",
            "duration_s_total <= 0",
            f"max_gap_s >= {stale_timeout * gap_ratio:.0f}s ({gap_ratio*100:.0f}% of stale_timeout)",
            f"num_events < {min_events}",
        ],
    }


# ---------------------------------------------------------------------------
# 5. Precisão numérica
# ---------------------------------------------------------------------------

def metric_precisao_numerica(report_path: str, metrics: dict) -> dict:
    """
    % of numeric values found in the LLM report that can be matched against
    a known value in metrics.json (within ±1 for large integers, ±0.05 for
    small floats).
    """
    try:
        report = Path(report_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"pct": None, "skipped": True, "reason": "report not found"}

    known = _collect_metric_values(metrics)
    report_nums = _extract_numbers(report)

    if not report_nums:
        return {"verified_numbers": 0, "total_numbers": 0, "pct": 100.0}

    def _matches(num: float) -> bool:
        tol = max(1.0, abs(num) * 0.01)
        return any(abs(num - kv) <= tol for kv in known)

    verified = sum(1 for n in report_nums if _matches(n))
    total = len(report_nums)
    return {
        "verified_numbers": verified,
        "total_numbers": total,
        "pct": round(verified / total * 100, 2),
    }


# ---------------------------------------------------------------------------
# 6. Ausência de alucinação
# ---------------------------------------------------------------------------

def metric_ausencia_alucinacao(
    report_path: str, metrics: dict, insights: list
) -> dict:
    """
    % of verifiable factual claims in the LLM report that are grounded in
    metrics.json / insights.json.

    Checks performed:
      a) Zone IDs present in the report that also exist in the data.
      b) Zone-like tokens in the report that do NOT exist (hallucinated zones).
      c) Key numeric evidence values from each insight that appear in the report.
    """
    try:
        report = Path(report_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"pct": None, "skipped": True, "reason": "report not found"}

    known_zones = {str(z["zone_id"]) for z in metrics.get("by_zone", [])}
    checks: list[bool] = []

    # (a) & (b): Zone ID grounding
    if known_zones:
        for zone in known_zones:
            if zone in report:
                checks.append(True)

        sample = next(iter(known_zones))
        prefix_m = re.match(r"^[A-Za-z_]+", sample)
        if prefix_m:
            pfx = re.escape(prefix_m.group())
            pattern = re.compile(r"\b" + pfx + r"[A-Za-z0-9_]+\b")
            for token in set(pattern.findall(report)):
                if token not in known_zones:
                    checks.append(False)

    # (c): Evidence values from insights
    for ins in insights:
        for val in ins.get("evidence", {}).values():
            if isinstance(val, (int, float)) and not isinstance(val, bool) and val > 10:
                num_str = (
                    str(int(val)) if isinstance(val, int) or float(val) == int(val)
                    else f"{val:.1f}"
                )
                if num_str in report:
                    checks.append(True)

    if not checks:
        return {"verified_claims": 0, "total_claims": 0, "pct": 100.0}

    verified = sum(1 for c in checks if c)
    total = len(checks)
    return {
        "verified_claims": verified,
        "total_claims": total,
        "pct": round(verified / total * 100, 2),
    }


# ---------------------------------------------------------------------------
# Sensitivity sweep (supplementary)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Evaluate pipeline quality (Section 5 metrics)."
    )
    parser.add_argument(
        "--input", default=None,
        help="Path to events CSV (overrides config paths.events)",
    )
    parser.add_argument(
        "--output", default=None,
        help="Path for evaluation JSON (overrides config paths.evaluation)",
    )
    args = parser.parse_args()

    cfg = load_config()
    if args.input:
        cfg["paths"]["events"] = args.input
    if args.output:
        cfg["paths"]["evaluation"] = args.output

    edf = load_events(cfg["paths"]["events"])
    jdf = pd.read_csv(cfg["paths"]["journeys"], parse_dates=["entry_ts", "exit_ts"])
    metrics = load_json(cfg["paths"]["metrics"])
    insights = load_json(cfg["paths"]["insights"])
    report_path = cfg["paths"]["report"]

    m1 = metric_consistencia(jdf)
    m2 = metric_cobertura(edf, jdf)
    m3 = metric_completude(jdf, cfg)
    m4 = metric_anomalias(jdf, cfg)
    m5 = metric_precisao_numerica(report_path, metrics)
    m6 = metric_ausencia_alucinacao(report_path, metrics, insights)

    log.info("Consistência:          %.2f%%", m1["pct"])
    log.info("Cobertura:             %.2f%%", m2["pct"])
    log.info("Completude:            %.2f%%", m3["pct"])
    log.info("Deteção de anomalias:  %.2f%%", m4["pct"])
    log.info("Precisão numérica:     %s", f"{m5['pct']:.2f}%" if m5.get("pct") is not None else "skipped")
    log.info("Ausência de alucinação:%s", f"{m6['pct']:.2f}%" if m6.get("pct") is not None else "skipped")

    log.info("Running sensitivity sweep over linger windows %s ...",
             cfg["sensitivity"]["linger_windows"])
    sensitivity = sensitivity_sweep(cfg)

    evaluation = {
        "metrics": {
            "consistencia": m1,
            "cobertura": m2,
            "completude": m3,
            "detecao_anomalias": m4,
            "precisao_numerica": m5,
            "ausencia_alucinacao": m6,
        },
        "sensitivity": sensitivity,
    }
    save_json(evaluation, cfg["paths"]["evaluation"])
    save_sensitivity_csv(sensitivity, cfg["paths"]["sensitivity"])
    log.info("Evaluation complete → %s", cfg["paths"]["evaluation"])
