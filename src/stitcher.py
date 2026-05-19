"""
stitcher.py — greedy demographic-bucketed temporal journey reconstruction.

Reads:  data/raw/events.csv        (config: paths.events)
Writes: data/derived/journeys.csv  (config: paths.journeys)
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from src.utils import get_logger, load_config, load_events

log = get_logger("stitcher")

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

EventType = Literal["entry", "linger", "exit"]
StitchConfidence = Literal["high", "medium", "low"]
CloseReason = Literal["exit", "stale", "end_of_data"]


@dataclass(frozen=True)
class Event:
    event_id: str
    timestamp: datetime
    zone_id: str
    event_type: EventType
    duration_s: Optional[float]
    gender: str
    age_range: str

    @property
    def bucket(self) -> tuple[str, str]:
        return (self.gender, self.age_range)


@dataclass
class ZoneVisit:
    zone_id: str
    enter_ts: datetime
    exit_ts: datetime
    dwell_s: float
    linger_events: int


@dataclass
class ActiveJourney:
    journey_id: str
    bucket: tuple[str, str]
    entry_ts: datetime
    last_ts: datetime
    current_zone: str
    events: list[Event] = field(default_factory=list)
    visits: list[ZoneVisit] = field(default_factory=list)
    max_gap_s: float = 0.0
    candidates_at_match: list[int] = field(default_factory=list)

    def can_accept(self, ev: Event, linger_window: int, exit_window: int) -> bool:
        gap = (ev.timestamp - self.last_ts).total_seconds()
        window = exit_window if ev.event_type == "exit" else linger_window
        return 0 <= gap <= window

    def is_stale(self, now: datetime, stale_timeout: int) -> bool:
        return (now - self.last_ts).total_seconds() > stale_timeout


@dataclass(frozen=True)
class Journey:
    journey_id: str
    gender: str
    age_range: str
    entry_ts: datetime
    exit_ts: datetime
    duration_s_total: float
    zone_sequence: str
    num_events: int
    num_zone_visits: int
    completed: bool
    close_reason: CloseReason
    stitch_confidence: StitchConfidence
    max_gap_s: float


# ---------------------------------------------------------------------------
# Confidence assignment
# ---------------------------------------------------------------------------

def _assign_confidence(aj: ActiveJourney, cfg: dict) -> StitchConfidence:
    linger_window = cfg["stitcher"]["linger_window"]
    congested = any(n > 1 for n in aj.candidates_at_match)
    near_threshold = aj.max_gap_s > linger_window * 0.8
    if near_threshold:
        return "low"
    if congested:
        return "medium"
    if aj.max_gap_s < 300:
        return "high"
    return "medium"


# ---------------------------------------------------------------------------
# Zone visit tracking helpers
# ---------------------------------------------------------------------------

def _open_zone_visit(aj: ActiveJourney, zone_id: str, ts: datetime) -> None:
    aj.visits.append(ZoneVisit(zone_id, ts, ts, 0.0, 0))
    aj.current_zone = zone_id


def _extend_zone_visit(aj: ActiveJourney, ts: datetime) -> None:
    if not aj.visits:
        return
    v = aj.visits[-1]
    aj.visits[-1] = ZoneVisit(v.zone_id, v.enter_ts, ts, (ts - v.enter_ts).total_seconds(), v.linger_events + 1)


def _close_zone_visit(aj: ActiveJourney, ts: datetime) -> None:
    if not aj.visits:
        return
    v = aj.visits[-1]
    aj.visits[-1] = ZoneVisit(v.zone_id, v.enter_ts, ts, max((ts - v.enter_ts).total_seconds(), 0.0), v.linger_events)


def _finalise_journey(aj: ActiveJourney, close_reason: CloseReason, cfg: dict) -> Journey:
    _close_zone_visit(aj, aj.last_ts)
    sequence = ">".join(v.zone_id for v in aj.visits) if aj.visits else aj.current_zone
    confidence = _assign_confidence(aj, cfg)
    return Journey(
        journey_id=aj.journey_id,
        gender=aj.bucket[0],
        age_range=aj.bucket[1],
        entry_ts=aj.entry_ts,
        exit_ts=aj.last_ts,
        duration_s_total=(aj.last_ts - aj.entry_ts).total_seconds(),
        zone_sequence=sequence,
        num_events=len(aj.events),
        num_zone_visits=len(aj.visits),
        completed=(close_reason == "exit"),
        close_reason=close_reason,
        stitch_confidence=confidence,
        max_gap_s=aj.max_gap_s,
    )


# ---------------------------------------------------------------------------
# Main stitching loop
# ---------------------------------------------------------------------------

def stitch(cfg: dict) -> list[Journey]:
    df = load_events(cfg["paths"]["events"])
    linger_window = cfg["stitcher"]["linger_window"]
    exit_window = cfg["stitcher"]["exit_window"]
    stale_timeout = cfg["stitcher"]["stale_timeout"]
    sweep_every = cfg["stitcher"]["sweep_every"]

    active: dict[tuple[str, str], list[ActiveJourney]] = {}
    journeys: list[Journey] = []
    journey_counter = 0

    for i, row in enumerate(df.itertuples(index=False)):
        ts = row.timestamp
        duration_s = float(row.duration_s) if hasattr(row, "duration_s") and row.duration_s is not None else None
        ev = Event(
            event_id=str(row.event_id),
            timestamp=ts,
            zone_id=str(row.zone_id),
            event_type=str(row.event_type),
            duration_s=duration_s,
            gender=str(row.gender),
            age_range=str(row.age_range),
        )
        bucket = ev.bucket
        bucket_list = active.setdefault(bucket, [])

        if ev.event_type == "entry":
            journey_counter += 1
            aj = ActiveJourney(
                journey_id=f"J{journey_counter:06d}",
                bucket=bucket,
                entry_ts=ts,
                last_ts=ts,
                current_zone=ev.zone_id,
                events=[ev],
            )
            _open_zone_visit(aj, ev.zone_id, ts)
            bucket_list.append(aj)
        else:
            candidates = [aj for aj in bucket_list if aj.can_accept(ev, linger_window, exit_window)]
            if candidates:
                target = max(candidates, key=lambda a: a.last_ts)
                gap = (ts - target.last_ts).total_seconds()
                target.max_gap_s = max(target.max_gap_s, gap)
                target.candidates_at_match.append(len(candidates))
                target.events.append(ev)

                if ev.zone_id != target.current_zone:
                    _close_zone_visit(target, ts)
                    _open_zone_visit(target, ev.zone_id, ts)
                elif ev.event_type == "linger":
                    _extend_zone_visit(target, ts)

                target.last_ts = ts

                if ev.event_type == "exit":
                    bucket_list.remove(target)
                    journeys.append(_finalise_journey(target, "exit", cfg))

        # Amortised stale sweep
        if i % sweep_every == 0:
            for b_list in active.values():
                stale = [aj for aj in b_list if aj.is_stale(ts, stale_timeout)]
                for aj in stale:
                    b_list.remove(aj)
                    journeys.append(_finalise_journey(aj, "stale", cfg))

    # Flush remaining open journeys at end of data
    for b_list in active.values():
        for aj in b_list:
            journeys.append(_finalise_journey(aj, "end_of_data", cfg))

    log.info("Stitched %d journeys from %d events.", len(journeys), len(df))
    return journeys


def save_journeys(journeys: list[Journey], path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "journey_id", "gender", "age_range", "entry_ts", "exit_ts",
        "duration_s_total", "zone_sequence", "num_events", "num_zone_visits",
        "completed", "close_reason", "stitch_confidence", "max_gap_s",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for j in journeys:
            writer.writerow({k: getattr(j, k) for k in fields})
    log.info("Wrote %d journeys to %s.", len(journeys), path)


if __name__ == "__main__":
    cfg = load_config()
    journeys = stitch(cfg)
    save_journeys(journeys, cfg["paths"]["journeys"])
