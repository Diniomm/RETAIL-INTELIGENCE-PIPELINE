"""
analytics.py — compute metrics.json from journeys.csv (+ events.csv for raw zone counts).

Reads:  data/derived/journeys.csv  (config: paths.journeys)
        data/raw/events.csv        (config: paths.events)
Writes: data/derived/metrics.json  (config: paths.metrics)
"""
from __future__ import annotations

import pandas as pd

from src.utils import get_logger, load_config, load_events, save_json

log = get_logger("analytics")


def compute_metrics(cfg: dict) -> dict:
    top_n = cfg["insights"].get("top_sequences_n", 10)

    jdf = pd.read_csv(cfg["paths"]["journeys"], parse_dates=["entry_ts", "exit_ts"])
    edf = load_events(cfg["paths"]["events"])

    # Period
    period = {
        "start": jdf["entry_ts"].min().date().isoformat(),
        "end": jdf["exit_ts"].max().date().isoformat(),
        "days": (jdf["exit_ts"].max().date() - jdf["entry_ts"].min().date()).days + 1,
    }

    # Volume
    total = len(jdf)
    completed = int(jdf["completed"].sum())
    volume = {
        "total_events": int(len(edf)),
        "total_journeys": total,
        "completed_journeys": completed,
        "completion_rate": round(completed / total, 4) if total else 0.0,
    }

    # By day
    jdf["date"] = jdf["entry_ts"].dt.date.astype(str)
    jdf["hour"] = jdf["entry_ts"].dt.hour
    by_day_base = (
        jdf.groupby("date")
        .agg(journeys=("journey_id", "count"), avg_duration_s=("duration_s_total", "mean"))
        .reset_index()
    )
    peak_hour_by_day = (
        jdf.groupby(["date", "hour"]).size().reset_index(name="cnt")
    )
    peak_idx = peak_hour_by_day.groupby("date")["cnt"].idxmax()
    peak_hour_by_day = peak_hour_by_day.loc[peak_idx][["date", "hour"]].rename(columns={"hour": "peak_hour"})
    by_day_df = by_day_base.merge(peak_hour_by_day, on="date", how="left")
    by_day = [
        {
            "date": r["date"],
            "journeys": int(r["journeys"]),
            "avg_duration_s": round(float(r["avg_duration_s"]), 1),
            "peak_hour": int(r["peak_hour"]),
        }
        for _, r in by_day_df.iterrows()
    ]

    # By hour (aggregated across all days)
    by_hour_raw = jdf.groupby("hour").size().reset_index(name="journey_count")
    by_hour = [
        {"hour": int(r["hour"]), "journey_count": int(r["journey_count"])}
        for _, r in by_hour_raw.iterrows()
    ]

    # By zone — entry counts from events; dwell from linger events
    entry_events = edf[edf["event_type"] == "entry"]
    zone_entries = entry_events.groupby("zone_id").size().reset_index(name="entries")
    if "duration_s" in edf.columns:
        zone_dwell = (
            edf[edf["event_type"] == "linger"]
            .groupby("zone_id")["duration_s"]
            .mean()
            .reset_index(name="avg_dwell_s")
        )
    else:
        zone_dwell = pd.DataFrame(columns=["zone_id", "avg_dwell_s"])
    by_zone_df = zone_entries.merge(zone_dwell, on="zone_id", how="left").fillna(0.0)
    total_entries = int(by_zone_df["entries"].sum())
    by_zone = [
        {
            "zone_id": str(r["zone_id"]),
            "entries": int(r["entries"]),
            "avg_dwell_s": round(float(r["avg_dwell_s"]), 1),
            "share_pct": round(r["entries"] / total_entries * 100, 2) if total_entries else 0.0,
        }
        for _, r in by_zone_df.iterrows()
    ]

    # By demographic
    by_demo_raw = (
        jdf.groupby(["gender", "age_range"])
        .agg(journeys=("journey_id", "count"), avg_duration_s=("duration_s_total", "mean"))
        .reset_index()
    )
    by_demographic = [
        {
            "gender": r["gender"],
            "age_range": r["age_range"],
            "journeys": int(r["journeys"]),
            "avg_duration_s": round(float(r["avg_duration_s"]), 1),
        }
        for _, r in by_demo_raw.iterrows()
    ]

    # Top sequences
    seq_counts = jdf["zone_sequence"].value_counts().head(top_n)
    top_sequences = [{"sequence": seq, "count": int(cnt)} for seq, cnt in seq_counts.items()]

    return {
        "period": period,
        "volume": volume,
        "by_day": by_day,
        "by_hour": by_hour,
        "by_zone": by_zone,
        "by_demographic": by_demographic,
        "top_sequences": top_sequences,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Compute analytics metrics from journeys.")
    parser.add_argument("--input", default=None, help="Path to journeys CSV (overrides config)")
    parser.add_argument("--output", default=None, help="Path for metrics JSON (overrides config)")
    args = parser.parse_args()
    cfg = load_config()
    if args.input:
        cfg["paths"]["journeys"] = args.input
    if args.output:
        cfg["paths"]["metrics"] = args.output
    metrics = compute_metrics(cfg)
    save_json(metrics, cfg["paths"]["metrics"])
    log.info("Wrote metrics to %s.", cfg["paths"]["metrics"])
