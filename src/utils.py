"""Shared helpers: config loading, I/O, logging, Ollama client."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import yaml


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def get_logger(name: str) -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger(name)


def save_json(data: Any, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def load_json(path: str | Path) -> Any:
    with open(path) as f:
        return json.load(f)


def load_events(path: str | Path):
    """Load and validate events.csv; returns a sorted DataFrame."""
    import pandas as pd

    df = pd.read_csv(path)
    before = len(df)
    df = df.dropna(subset=["event_id", "timestamp", "zone_id", "event_type"])
    df = df.drop_duplicates(subset=["event_id"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    log = get_logger("utils")
    log.info("Loaded %d events (%d dropped).", len(df), before - len(df))
    return df


def call_ollama(prompt: str, model: str, endpoint: str, temperature: float = 0) -> str:
    import requests

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }
    resp = requests.post(endpoint, json=payload, timeout=300)
    resp.raise_for_status()
    return resp.json()["response"]
