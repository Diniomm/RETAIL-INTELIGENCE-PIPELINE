"""
insights.py — rule-based insight detectors over metrics.json.

Reads:  data/derived/metrics.json   (config: paths.metrics)
Writes: data/derived/insights.json  (config: paths.insights)
"""
from __future__ import annotations

from src.utils import get_logger, load_config, load_json, save_json

log = get_logger("insights")


def _peak_hour(metrics: dict, multiplier: float) -> dict | None:
    by_hour = metrics["by_hour"]
    if not by_hour:
        return None
    counts = [h["journey_count"] for h in by_hour]
    weekly_avg = sum(counts) / len(counts)
    peak = max(by_hour, key=lambda h: h["journey_count"])
    if peak["journey_count"] < multiplier * weekly_avg:
        return None
    return {
        "id": "I001",
        "type": "peak_hour",
        "headline": f"Hour {peak['hour']:02d}:00 is the busiest hour ({peak['journey_count']} journeys vs weekly avg {weekly_avg:.0f})",
        "evidence": {"hour": peak["hour"], "journeys": peak["journey_count"], "weekly_avg": round(weekly_avg, 1)},
        "metric_refs": [f"by_hour[{peak['hour']}].journey_count", "volume.total_journeys"],
        "confidence": "high",
    }


def _quiet_hour(metrics: dict) -> dict | None:
    by_hour = metrics["by_hour"]
    if not by_hour:
        return None
    quiet = min(by_hour, key=lambda h: h["journey_count"])
    return {
        "id": "I002",
        "type": "quiet_hour",
        "headline": f"Hour {quiet['hour']:02d}:00 is the quietest hour ({quiet['journey_count']} journeys)",
        "evidence": {"hour": quiet["hour"], "journeys": quiet["journey_count"]},
        "metric_refs": [f"by_hour[{quiet['hour']}].journey_count"],
        "confidence": "high",
    }


def _hot_zone(metrics: dict) -> dict | None:
    by_zone = metrics["by_zone"]
    if not by_zone:
        return None
    hot = max(by_zone, key=lambda z: z["entries"])
    return {
        "id": "I003",
        "type": "hot_zone",
        "headline": f"Zone {hot['zone_id']} has the most entries ({hot['entries']}, {hot['share_pct']}% of total)",
        "evidence": {"zone_id": hot["zone_id"], "journeys": hot["entries"], "share_pct": hot["share_pct"]},
        "metric_refs": [f"by_zone[{hot['zone_id']}].entries", f"by_zone[{hot['zone_id']}].share_pct"],
        "confidence": "high",
    }


def _sticky_zone(metrics: dict) -> dict | None:
    by_zone = metrics["by_zone"]
    if not by_zone:
        return None
    avg_dwell = sum(z["avg_dwell_s"] for z in by_zone) / len(by_zone)
    sticky = max(by_zone, key=lambda z: z["avg_dwell_s"])
    if sticky["avg_dwell_s"] <= avg_dwell:
        return None
    return {
        "id": "I004",
        "type": "sticky_zone",
        "headline": f"Zone {sticky['zone_id']} has the highest avg dwell ({sticky['avg_dwell_s']:.0f}s vs network avg {avg_dwell:.0f}s)",
        "evidence": {"zone_id": sticky["zone_id"], "avg_dwell_s": sticky["avg_dwell_s"], "weekly_avg": round(avg_dwell, 1)},
        "metric_refs": [f"by_zone[{sticky['zone_id']}].avg_dwell_s"],
        "confidence": "medium",
    }


def _bounce_zone(metrics: dict, bounce_max_s: float) -> dict | None:
    by_zone = metrics["by_zone"]
    if not by_zone:
        return None
    total_entries = sum(z["entries"] for z in by_zone)
    avg_entries = total_entries / len(by_zone)
    candidates = [z for z in by_zone if z["avg_dwell_s"] < bounce_max_s and z["entries"] > avg_entries]
    if not candidates:
        return None
    bounce = max(candidates, key=lambda z: z["entries"])
    return {
        "id": "I005",
        "type": "bounce_zone",
        "headline": (
            f"Zone {bounce['zone_id']} has high traffic ({bounce['entries']} entries) "
            f"but very low dwell ({bounce['avg_dwell_s']:.0f}s) — possible layout or signage issue"
        ),
        "evidence": {"zone_id": bounce["zone_id"], "journeys": bounce["entries"], "avg_dwell_s": bounce["avg_dwell_s"]},
        "metric_refs": [f"by_zone[{bounce['zone_id']}].entries", f"by_zone[{bounce['zone_id']}].avg_dwell_s"],
        "confidence": "medium",
    }


def _demographic_skew(metrics: dict, skew_pp: float) -> dict | None:
    by_demo = metrics["by_demographic"]
    if not by_demo:
        return None
    total = sum(d["journeys"] for d in by_demo)
    if total == 0:
        return None
    expected_share = 100.0 / len(by_demo)
    for demo in by_demo:
        share = demo["journeys"] / total * 100
        delta = abs(share - expected_share)
        if delta >= skew_pp:
            return {
                "id": "I006",
                "type": "demographic_skew",
                "headline": (
                    f"{demo['gender']} / {demo['age_range']} accounts for {share:.1f}% of journeys "
                    f"(expected ~{expected_share:.1f}%)"
                ),
                "evidence": {
                    "gender": demo["gender"],
                    "age_range": demo["age_range"],
                    "journeys": demo["journeys"],
                    "share_pct": round(share, 1),
                    "delta_pp": round(delta, 1),
                },
                "metric_refs": ["by_demographic", "volume.total_journeys"],
                "confidence": "high",
            }
    return None


def _common_path(metrics: dict) -> dict | None:
    top = metrics["top_sequences"]
    if not top:
        return None
    seq = top[0]
    return {
        "id": "I007",
        "type": "common_path",
        "headline": f"Most common journey path is '{seq['sequence']}' ({seq['count']} occurrences)",
        "evidence": {"sequence": seq["sequence"], "count": seq["count"]},
        "metric_refs": ["top_sequences[0].sequence", "top_sequences[0].count"],
        "confidence": "high",
    }


def detect_insights(metrics: dict, cfg: dict) -> list[dict]:
    ic = cfg["insights"]
    detectors = [
        _peak_hour(metrics, ic["peak_hour_multiplier"]),
        _quiet_hour(metrics),
        _hot_zone(metrics),
        _sticky_zone(metrics),
        _bounce_zone(metrics, ic["bounce_dwell_max_s"]),
        _demographic_skew(metrics, ic["demographic_skew_pp"]),
        _common_path(metrics),
    ]
    return [d for d in detectors if d is not None]


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Detect rule-based insights from metrics.")
    parser.add_argument("--input", default=None, help="Path to metrics JSON (overrides config)")
    parser.add_argument("--output", default=None, help="Path for insights JSON (overrides config)")
    args = parser.parse_args()
    cfg = load_config()
    if args.input:
        cfg["paths"]["metrics"] = args.input
    if args.output:
        cfg["paths"]["insights"] = args.output
    metrics = load_json(cfg["paths"]["metrics"])
    insights = detect_insights(metrics, cfg)
    save_json(insights, cfg["paths"]["insights"])
    log.info("Detected %d insights; wrote to %s.", len(insights), cfg["paths"]["insights"])
