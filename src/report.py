"""
report.py — call Ollama with metrics + insights to produce a markdown report.

Usage:
  python -m src.report                                          # grounded → data/derived/weekly_report.md
  python -m src.report --prompt naive
  python -m src.report --prompt grounded --out outputs/reports/grounded.md
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.utils import call_ollama, get_logger, load_config, load_json

log = get_logger("report")

PROMPTS_DIR = Path("prompts")


def load_prompt(variant: str) -> str:
    path = PROMPTS_DIR / f"{variant}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def build_input(metrics: dict, insights: list) -> str:
    return json.dumps({"metrics": metrics, "insights": insights}, indent=2, default=str)


def run_report(cfg: dict, variant: str = "grounded", out: str | None = None) -> str:
    metrics = load_json(cfg["paths"]["metrics"])
    insights = load_json(cfg["paths"]["insights"])
    template = load_prompt(variant)
    data_str = build_input(metrics, insights)
    full_prompt = template.replace("{{DATA}}", data_str)

    llm_cfg = cfg["llm"]
    log.info("Calling Ollama model=%s variant=%s ...", llm_cfg["model"], variant)
    report_text = call_ollama(
        full_prompt, llm_cfg["model"], llm_cfg["endpoint"], llm_cfg["temperature"]
    )

    out_path = Path(out) if out else Path(cfg["paths"]["report"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report_text, encoding="utf-8")
    log.info("Wrote report to %s.", out_path)
    return report_text


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default="grounded", choices=["naive", "structured", "grounded"])
    parser.add_argument("--out", default=None, help="Override output path")
    args = parser.parse_args()
    cfg = load_config()
    run_report(cfg, variant=args.prompt, out=args.out)
