1\. Recommended Architecture

The pipeline is a one-way pipe with clean file handoffs. Each stage reads the previous artifact and writes a new one. No shared state, no circular dependencies.

events.csv ──► stitcher.py ──► journeys.csv

&#x20;                                   │

&#x20;                                   ▼

&#x20;                             analytics.py ──► metrics.json

&#x20;                                   │

&#x20;                                   ▼

&#x20;                             insights.py  ──► insights.json

&#x20;                                   │

&#x20;                                   ▼

&#x20;                             report.py    ──► weekly\_report.md

&#x20;                               (LLM here, gated to metrics+insights only)



evaluate.py ──► reads events.csv + journeys.csv ──► evaluation.json

The single most important architectural decision is the LLM only consumes JSON, never CSV, never journeys, never raw events. This is your headline defense point: the deterministic pipeline produces grounded numerical statements, and the LLM is reduced to a narrative renderer. Hallucination risk is structurally minimized rather than prompted away.

A second important decision: insights.py is rule-based, not LLM-based. The LLM does not "find" insights. It rewords them. This keeps the insight discovery deterministic and reproducible, which is exactly what the professor will probe.

Defense question to expect: "Why is insights.py not the LLM?" Answer: insights must be reproducible across runs; an LLM introduces stochasticity into the analytical layer; we want the LLM only at the prose boundary.

2\. Data Structures

events.csv (input): as given.

journeys.csv (per row = one reconstructed journey):



journey\_id (synthetic, e.g. J000123)

gender, age\_range (the bucket key)

entry\_ts, exit\_ts, duration\_s\_total

zone\_sequence (string, e.g. "Z01>Z03>Z07")

num\_events

completed (bool — did we observe an exit, or did we time-out?)

stitch\_confidence (low/medium/high — see heuristics below)



metrics.json: a flat, predictable schema. Suggest top-level keys:



period: {start, end, days}

volume: {total\_events, total\_journeys, completed\_journeys, completion\_rate}

by\_day: list of {date, journeys, avg\_duration\_s, peak\_hour}

by\_hour: list of {hour, journey\_count} (aggregated across week)

by\_zone: list of {zone\_id, entries, avg\_dwell\_s, share\_pct}

by\_demographic: list of {gender, age\_range, journeys, avg\_duration\_s}

top\_sequences: list of {sequence, count} (top-N most common zone paths, length 2–4)



insights.json: list of insight objects with explicit grounding:

{

&#x20; "id": "I001",

&#x20; "type": "peak\_hour" | "zone\_underperform" | "demographic\_skew" | ...,

&#x20; "headline": "Saturday 17:00–18:00 is the busiest hour of the week",

&#x20; "evidence": {"hour": 17, "day": "Saturday", "journeys": 412, "weekly\_avg": 89},

&#x20; "confidence": "high"

}

The evidence block is what the LLM must reference. If it's not in evidence, the LLM cannot say it.

weekly\_report.md: structured markdown — Exec Summary, Traffic Overview, Zone Performance, Demographics, Notable Patterns, Limitations.

3\. Suggested Heuristics

3.1 Stitching (the hardest part)

Use greedy demographic-bucketed temporal matching. For each (gender, age\_range) bucket independently:



Sort events by timestamp.

Maintain a queue of open journeys (entered, not yet exited).

For each incoming event:



entry → open a new journey.

linger → attach to the open journey in this bucket with the most recent activity, if the gap is below LINGER\_WINDOW (suggest 600 s = 10 min).

exit → close the open journey with the most recent activity, if the gap is below EXIT\_WINDOW (suggest 1200 s = 20 min).





Auto-close any journey idle longer than STALE\_TIMEOUT (suggest 1800 s = 30 min) as completed=False.



Why these thresholds:



10 min linger gap reflects realistic continuous shopping behaviour; longer and it's plausibly a different visit.

20 min exit gap is wider because exits may be detected after a final linger pause.

30 min stale timeout caps journey length to something defensible; longer journeys are statistically rare in retail (median visit ≈ 15–25 min in published studies).

Bucketing by demographic reduces ambiguity drastically — same-bucket collisions are the residual error you'll acknowledge as a limitation.



Stitch confidence: assign per journey based on gap statistics:



high: all gaps < 5 min, demographic bucket low-density at the time

medium: gaps within thresholds but bucket had >1 open journey concurrently

low: at least one gap near the threshold, or bucket congested



This confidence field is gold for academic defense — it shows you understand that not all reconstructions are equally trustworthy.

Defense question to expect: "Why not the Hungarian algorithm / globally optimal assignment?" Answer: the problem is fundamentally underdetermined (no ID), so optimality is illusory — you'd be optimizing against an arbitrary cost function. Greedy + bucketing is the standard streaming approach, is O(N), is explainable, and produces results within tolerance of any optimum that isn't itself ground truth.

Defense question to expect: "What if two people with the same demographics are in the same zone simultaneously?" Answer: indistinguishable by design — this is a known limitation we report honestly in the technical report and surface via stitch\_confidence=low.

3.2 Insights (rule-based)

Pick 5–7 insight detectors. Each one is a small function. Suggested set:



Peak hour: top hour by journey count, compared to weekly mean (flag if >2× mean).

Quiet hour: bottom hour during open period.

Hot zone: zone with highest entry count.

Sticky zone: zone with highest avg dwell time vs network average.

Bounce zone: high entries, very low dwell — possible signage/layout issue.

Demographic skew: zone where one demographic's share deviates >X pp from the global share.

Common path: top 1–2 sequences of length 2–3.



Each detector returns an insight object only if it passes its threshold; otherwise nothing. This means insights.json is never padded — another defense point.

4\. Implementation Order



stitcher.py — hardest, most distinctive, most likely to leak time. Build first.

analytics.py — easy pandas groupbys once journeys exist.

insights.py — small, deterministic functions over metrics.

report.py + Ollama integration + prompt experiments.

evaluate.py — last code module; it depends on everything.

Technical report + prompt comparison doc — final 4–5 hours.



Rationale: build the artifact that produces the most downstream value first. If stitcher is wrong, everything downstream is wrong, so you want maximum time to iterate on it.

5\. Minimal Viable Strong Solution

This is what you must have at hour 23 to defend well:



stitcher works end-to-end on all 250k events, produces journeys with confidence labels, takes <60 s to run.

analytics produces the 6 metrics blocks above.

insights produces 5–7 grounded insights from rule-based detectors.

report uses Ollama with one strong "grounded" prompt that the LLM follows. Output is a real markdown report.

evaluate computes: completion rate, % low-confidence journeys, sensitivity of metrics to threshold changes (run stitcher with LINGER\_WINDOW ∈ {300, 600, 900} and report Δ in headline metrics — this is your robustness story).

prompt comparison: 3 prompts (naive / structured / grounded), same input, side-by-side outputs, short qualitative analysis showing the grounded prompt avoids hallucinated numbers. You don't need a fancy eval — a manual "did the LLM invent any number not present in the JSON?" check, done on each prompt's output, is sufficient and honest.

technical report: ≈ 4–6 pages covering architecture, heuristics with rationale, limitations, evaluation results, prompt engineering findings.



Anything beyond this is bonus.

6\. Common Pitfalls



Letting the LLM see CSV or journeys — kills your central architectural argument.

Over-tuning stitching thresholds against vibes — you'll have no defense. Document the thresholds, then justify with one sensitivity study in evaluate.py and stop touching them.

Hardcoded absolute paths — use a config.yaml or argparse with relative paths. The professor will try to re-run.

Timezone drift — pick one (UTC or local) at load time and stick with it. Wrong timezone shifts your peak hour and breaks every insight.

Forgetting to seed / making the pipeline non-deterministic — there's no randomness needed anywhere except possibly LLM temperature; set temperature=0 for the report.

Hallucinated insights from the LLM — guard against this with the grounded prompt requiring the LLM to cite metric keys, e.g. "every numerical claim must be traceable to a key in metrics.json or insights.json".

Over-engineering insights as ML — explicit rules with thresholds are stronger academically here because they are inspectable and defensible.

Not handling malformed/duplicate events — add a tiny validation step in stitcher (drop nulls, deduplicate on event\_id, log counts) and report the counts in the technical report. Honesty about data quality is a free defense point.

Building a fancy CLI — python src/stitcher.py etc. is fine. A Makefile or a single run\_all.py is the most you need.

Tweaking the prompt forever — set a 90-minute hard timebox on prompt iteration.



7\. Suggested Repository Structure

project/

├── README.md                      # how to reproduce, in one page

├── requirements.txt

├── config.yaml                    # thresholds, paths, model name

├── run\_all.py                     # orchestrates the 5 scripts in order

├── data/

│   ├── raw/events.csv

│   └── derived/

│       ├── journeys.csv

│       ├── metrics.json

│       ├── insights.json

│       └── weekly\_report.md

├── src/

│   ├── stitcher.py

│   ├── analytics.py

│   ├── insights.py

│   ├── report.py

│   ├── evaluate.py

│   └── utils.py                   # io helpers, logging, config loader

├── prompts/

│   ├── naive.txt

│   ├── structured.txt

│   └── grounded.txt

├── docs/

│   ├── technical\_report.md

│   └── prompt\_comparison.md

└── outputs/

&#x20;   ├── evaluation.json

&#x20;   └── reports/                   # one .md per prompt variant

Skip tests/ unless you have spare hours at the end; a single smoke test inside run\_all.py (assert files exist, assert journey count > 0) is enough.

8\. Suggested requirements.txt

pandas>=2.0

numpy>=1.24

pyyaml

python-dateutil

requests

tabulate

That's it. No scikit-learn, no networkx, no plotly. If you want a chart in the report, do it once in matplotlib at the very end and skip it if time-pressed. Adding a heavy dep at hour 20 will burn an hour you don't have.

Ollama is called via requests.post to http://localhost:11434/api/generate — no SDK needed.

9\. Realistic 23-Hour Execution Strategy

BlockHoursWorkSetup0–1.5Repo scaffold, config.yaml, load events.csv, quick EDA (counts per zone, per hour, per demographic). Decide timezone.Stitcher1.5–6Implement greedy bucketed stitching + confidence labels. Eyeball outputs on a 1-day slice before running on full week.Analytics6–8.5Pandas groupbys → metrics.json. Schema-test by hand.Insights8.5–10.55–7 rule-based detectors → insights.json.Report v110.5–13Ollama wiring + grounded prompt. Get one acceptable report end-to-end.Prompt experiments13–15Naive vs structured vs grounded; save all three outputs.Evaluate15–17Completion rate, low-confidence share, threshold sensitivity.Tech report17–20Write technical\_report.md. Use real numbers from evaluation.json.Prompt doc20–21Write prompt\_comparison.md with the three outputs and your analysis.End-to-end + polish21–22.5Run run\_all.py from clean state. Fix anything broken. README pass.Defense prep22.5–23Read your own technical report. List the 5 hardest questions and your answers.

Hard rule: if you're behind by hour 10, cut the third prompt variant and ship 2. If behind by hour 15, cut one insight detector. Never cut evaluate.py or the technical report. A working pipeline with no evaluation reads as weaker than a slightly leaner pipeline with honest evaluation.



Top defense questions you should rehearse answers to:



How do you know your journeys are correct? (You don't — you measure plausibility and report confidence.)

Why this stitching heuristic and not optimization? (Underdetermined problem, O(N), explainable.)

How do you prevent LLM hallucination? (Architectural gate: LLM only sees JSON; prompt forbids unsupported claims; manual audit in prompt comparison.)

What are your method's failure modes? (Same-bucket collisions, threshold sensitivity at boundaries, demographic misclassification upstream.)

How reproducible is this? (Deterministic pipeline, temperature=0 LLM, fixed thresholds in config, single run\_all.py.)









Repository Structure

retail-intelligence/

├── README.md

├── requirements.txt

├── config.yaml

├── run\_all.py

│

├── data/

│   ├── raw/

│   │   └── events.csv

│   └── derived/

│       ├── journeys.csv

│       ├── metrics.json

│       ├── insights.json

│       └── weekly\_report.md

│

├── src/

│   ├── \_\_init\_\_.py

│   ├── stitcher.py

│   ├── analytics.py

│   ├── insights.py

│   ├── report.py

│   ├── evaluate.py

│   └── utils.py

│

├── prompts/

│   ├── naive.txt

│   ├── structured.txt

│   └── grounded.txt

│

├── outputs/

│   ├── evaluation.json

│   ├── sensitivity.csv

│   └── reports/

│       ├── naive.md

│       ├── structured.md

│       └── grounded.md

│

└── docs/

&#x20;   ├── technical\_report.md

&#x20;   └── prompt\_comparison.md

Folder and Module Responsibilities

Root level. README.md documents how to reproduce in one page — install, run, expected outputs. requirements.txt pins dependencies. config.yaml centralises every threshold, path, and the LLM model name; this is your single defense point for reproducibility — "every magic number lives in config.yaml and is versioned in git." run\_all.py orchestrates the five stages in order with a single command, and prints stage timings (useful evidence for the technical report).

data/raw/ holds the input CSV exactly as received, never modified. data/derived/ holds the four canonical pipeline artifacts — these are the contract between stages. Anything written here should be regeneratable from events.csv alone by re-running run\_all.py. Keeping raw and derived separate matters because the professor will check that you don't mutate inputs.

src/stitcher.py — single responsibility: read events.csv, output journeys.csv. Implements the greedy demographic-bucketed temporal matching from the previous plan, plus the stitch\_confidence field. Thresholds read from config.yaml. No analytics inside.

src/analytics.py — single responsibility: read journeys.csv (and optionally events.csv for raw counts that survive stitching), output metrics.json. Pure pandas groupbys, no heuristics, no thresholds. If a number depends on a threshold, that number belongs in insights.py, not here. This separation is important: metrics are facts about the reconstruction, insights are interpretations.

src/insights.py — single responsibility: read metrics.json, output insights.json. Contains 5–7 small detector functions (peak hour, sticky zone, bounce zone, demographic skew, etc.) each returning either an insight dict or nothing. Each insight carries its evidence block. No LLM here — this is deterministic by design.

src/report.py — single responsibility: read metrics.json + insights.json, call Ollama, write a markdown report. Takes a --prompt {naive,structured,grounded} flag. The default writes to data/derived/weekly\_report.md using the grounded prompt; with --variant set, it also writes to outputs/reports/<variant>.md for the prompt comparison. This is the only module that talks to the LLM. That fact alone is a defense point.

src/evaluate.py — reads events.csv, journeys.csv, and the timing log from run\_all.py, writes outputs/evaluation.json plus outputs/sensitivity.csv. Computes coverage, completion rate, confidence distribution, and the threshold sensitivity sweep (rerun stitcher at LINGER\_WINDOW ∈ {300, 600, 900} and report Δ on headline metrics).

src/utils.py — kept deliberately small. Suggested contents: load\_config(path), load\_events(path) with schema validation, save\_json / load\_json, get\_logger(name), call\_ollama(prompt, model, temperature=0). Resist the urge to split this into io.py + llm.py + config.py; for a 23-hour project, one focused utility module is more honest about scope.

prompts/ — three text files, one per variant. Storing prompts as files (not as Python string literals) makes the prompt comparison clean: the comparison doc can quote them directly, you can diff them in git, and report.py is just a thin runner. Each file should declare the role, the input schema it will receive, the structure of the output, and (for grounded.txt) the no-hallucination contract.

outputs/ — anything generated for the report and defense, as opposed to anything consumed by another pipeline stage. evaluation.json for the technical report's numbers, sensitivity.csv for a table you can paste in, reports/ for the three prompt variants you'll compare.

docs/ — technical\_report.md (\~4–6 pages: architecture, heuristics with rationale, evaluation, limitations) and prompt\_comparison.md (the three prompts, their outputs, a short qualitative analysis of which hallucinated and which stayed grounded).

File Naming Conventions

Folders and Python files in snake\_case. JSON and CSV outputs in snake\_case with no version suffixes (versioning lives in git, not filenames). Prompts named by strategy, not by version number, because the comparison doc refers to them by strategy. No dates in filenames anywhere — that's git's job.

requirements.txt

pandas>=2.0,<3.0

numpy>=1.24

pyyaml>=6.0

python-dateutil>=2.8

requests>=2.31

tabulate>=0.9

That's everything. requests handles Ollama via its HTTP API at http://localhost:11434/api/generate — no need for the ollama Python SDK, which is an extra moving part. tabulate is for rendering markdown tables in the report. If you decide late to add one chart in the technical report, install matplotlib ad hoc; don't add it preemptively.

README Execution Commands

bash# 1. Environment setup

python -m venv .venv

source .venv/bin/activate           # Windows: .venv\\Scripts\\activate

pip install -r requirements.txt



\# 2. Start Ollama (in a separate terminal) and pull the model once

ollama serve

ollama pull llama3.1:8b



\# 3. Place the input data

\#    Copy your events.csv into data/raw/events.csv



\# 4. Run the full pipeline end-to-end

python run\_all.py



\# 5. Or run stages individually (same order as run\_all.py)

python -m src.stitcher

python -m src.analytics

python -m src.insights

python -m src.report --prompt grounded

python -m src.evaluate



\# 6. Generate the three prompt variants for the comparison doc

python -m src.report --prompt naive       --out outputs/reports/naive.md

python -m src.report --prompt structured  --out outputs/reports/structured.md

python -m src.report --prompt grounded    --out outputs/reports/grounded.md

Using python -m src.<module> rather than python src/<module>.py is the small detail that keeps imports clean once utils.py is shared across modules — no sys.path hacks needed.

Suggested Python Version

Python 3.11. It's stable, widely available on Linux/macOS/Windows, fully compatible with pandas 2.x and modern type hints, and noticeably faster than 3.10 for pandas workloads (relevant when you re-run the stitcher three times for the sensitivity sweep). Avoid 3.12 only because some peripheral libraries occasionally lag; 3.10 is also acceptable if that's what your environment already has. Pin the version in the README so the professor can reproduce.



What I'm deliberately leaving out for the 23-hour budget: no tests/ folder (one inline smoke assertion in run\_all.py is enough), no Makefile, no Dockerfile, no pyproject.toml (a flat requirements.txt is more honest about the project's scope), no notebooks/ checked into git (use one locally for EDA, don't ship it). If you finish ahead of schedule, a single smoke-test file is the first thing to add — everything else above is gold-plating that hurts more than it helps on defense.





Two-Tier Design

The data models split into two layers, and keeping them separate is itself a defense point:



Internal dataclasses (Event, ActiveJourney, Journey, ZoneVisit) — used in Python code during stitching and analytics, with explicit types and a small amount of behaviour.

External JSON shapes (Metrics, Insight) — TypedDicts that describe the contract between pipeline stages and the LLM. They serialize directly to JSON.



This separation matters because the JSON-facing shapes are the only thing the LLM ever sees, so they should be designed as a documentation artifact, not as an internal representation.



Event

pythonfrom dataclasses import dataclass

from datetime import datetime

from typing import Literal, Optional



EventType = Literal\["entry", "linger", "exit"]



@dataclass(frozen=True)

class Event:

&#x20;   event\_id: str

&#x20;   timestamp: datetime

&#x20;   zone\_id: str

&#x20;   event\_type: EventType

&#x20;   duration\_s: Optional\[float]

&#x20;   gender: str

&#x20;   age\_range: str



&#x20;   @property

&#x20;   def bucket(self) -> tuple\[str, str]:

&#x20;       return (self.gender, self.age\_range)

Why each field: event\_id is the dedup key and the traceable identifier — if a journey's events are ever audited, you can name them. timestamp is the central ordering signal; parse it once at load and never touch the string form again. zone\_id drives spatial logic. event\_type dispatches the stitcher's action (open / append / close). duration\_s is Optional because entries and exits often have no duration; mishandling this is a common bug. gender and age\_range together form bucket, which is computed once per event and used as the primary partition key during stitching.

Why frozen=True: events are immutable inputs. Freezing them prevents accidental in-place mutation during stitching (a real risk when you start attaching events to journeys) and makes them hashable for set-based dedup if needed.



ZoneVisit

python@dataclass

class ZoneVisit:

&#x20;   zone\_id: str

&#x20;   enter\_ts: datetime

&#x20;   exit\_ts: datetime

&#x20;   dwell\_s: float

&#x20;   linger\_events: int

Why this exists separately from Event: a "zone visit" is the analytical unit, not the detection unit. A single visit to a zone may comprise several linger events plus the entry detection. Collapsing consecutive same-zone events into one ZoneVisit is what makes top\_sequences in metrics.json meaningful — Z1>Z1>Z1>Z2 is one transition, not three.

Why fields: enter\_ts and exit\_ts are the bounds; dwell\_s is precomputed (avoiding repeated subtraction in analytics); linger\_events is a small data-quality signal (a visit with zero linger events but a long dwell may indicate missed detections — useful for evaluation).



ActiveJourney (in-flight)

python@dataclass

class ActiveJourney:

&#x20;   journey\_id: str

&#x20;   bucket: tuple\[str, str]            # (gender, age\_range)

&#x20;   entry\_ts: datetime

&#x20;   last\_ts: datetime                  # most recent event timestamp

&#x20;   current\_zone: str                  # for transition detection

&#x20;   events: list\[Event]

&#x20;   visits: list\[ZoneVisit]

&#x20;   max\_gap\_s: float = 0.0             # running max gap, feeds confidence

&#x20;   candidates\_at\_match: list\[int] = None  # bucket size at each match decision



&#x20;   def can\_accept(self, ev: Event, linger\_window: int, exit\_window: int) -> bool:

&#x20;       gap = (ev.timestamp - self.last\_ts).total\_seconds()

&#x20;       window = exit\_window if ev.event\_type == "exit" else linger\_window

&#x20;       return 0 <= gap <= window



&#x20;   def is\_stale(self, now: datetime, stale\_timeout: int) -> bool:

&#x20;       return (now - self.last\_ts).total\_seconds() > stale\_timeout

Why each field:



last\_ts is the single most important field. Greedy matching ranks candidates by recency, and stale detection compares against it. Without it you'd have to scan events\[-1] on every comparison.

current\_zone enables transition detection (event.zone != current\_zone ⇒ close previous ZoneVisit, open new one). Without it you cannot construct a clean zone sequence.

events and visits are kept separate because they live at different abstraction levels (raw detections vs analytical units) and both are needed at close time.

max\_gap\_s is the seed for stitch\_confidence — high confidence means small gaps throughout.

candidates\_at\_match records how ambiguous the assignment decision was at each step. If at any point more than one journey in the bucket was within window, this journey is marked low confidence. This is your honest-uncertainty mechanism, and it's the kind of detail that wins defense points.



Why methods on the dataclass: can\_accept and is\_stale are policy-bearing predicates that the stitcher will call hundreds of thousands of times. Putting them on the class keeps the stitcher's main loop readable and makes the thresholds the only parameters in play — easy to grep, easy to vary in the sensitivity sweep.



Journey (final, written to journeys.csv)

pythonStitchConfidence = Literal\["high", "medium", "low"]

CloseReason = Literal\["exit", "stale", "end\_of\_data"]



@dataclass(frozen=True)

class Journey:

&#x20;   journey\_id: str

&#x20;   gender: str

&#x20;   age\_range: str

&#x20;   entry\_ts: datetime

&#x20;   exit\_ts: datetime

&#x20;   duration\_s\_total: float

&#x20;   zone\_sequence: str          # "Z01>Z03>Z07"

&#x20;   num\_events: int

&#x20;   num\_zone\_visits: int

&#x20;   completed: bool             # True iff close\_reason == "exit"

&#x20;   close\_reason: CloseReason

&#x20;   stitch\_confidence: StitchConfidence

&#x20;   max\_gap\_s: float

Why this is a separate type from ActiveJourney: the in-flight version carries scaffolding (the events list, the candidate counts) that the analytics layer should not have to think about. The frozen, flat Journey is what serializes to CSV and what every downstream stage reads. Mixing the two leaks stitcher concerns into analytics — a small architectural smell that grows fast.

Why close\_reason is exposed: the evaluation report should be able to say "73% of journeys closed by an explicit exit signal, 24% timed out, 3% remained open at end of data." That's a concrete data-quality statement and exactly what the professor will ask about.

Why max\_gap\_s survives to the final record: it lets analytics compute things like "median worst-gap among low-confidence journeys" without re-deriving anything. Keep cheap derived numbers; recompute expensive ones.



Metrics (JSON shape)

pythonfrom typing import TypedDict



class Period(TypedDict):

&#x20;   start: str           # ISO date

&#x20;   end: str

&#x20;   days: int



class Volume(TypedDict):

&#x20;   total\_events: int

&#x20;   total\_journeys: int

&#x20;   completed\_journeys: int

&#x20;   completion\_rate: float



class DayStat(TypedDict):

&#x20;   date: str

&#x20;   journeys: int

&#x20;   avg\_duration\_s: float

&#x20;   peak\_hour: int



class HourStat(TypedDict):

&#x20;   hour: int

&#x20;   journey\_count: int



class ZoneStat(TypedDict):

&#x20;   zone\_id: str

&#x20;   entries: int

&#x20;   avg\_dwell\_s: float

&#x20;   share\_pct: float



class DemographicStat(TypedDict):

&#x20;   gender: str

&#x20;   age\_range: str

&#x20;   journeys: int

&#x20;   avg\_duration\_s: float



class SequenceStat(TypedDict):

&#x20;   sequence: str        # "Z01>Z03>Z07"

&#x20;   count: int



class Metrics(TypedDict):

&#x20;   period: Period

&#x20;   volume: Volume

&#x20;   by\_day: list\[DayStat]

&#x20;   by\_hour: list\[HourStat]

&#x20;   by\_zone: list\[ZoneStat]

&#x20;   by\_demographic: list\[DemographicStat]

&#x20;   top\_sequences: list\[SequenceStat]

Why TypedDict and not dataclass: this object's primary identity is JSON. It's written by analytics.py, read by insights.py, and read by the LLM in report.py. Keeping it as a TypedDict makes the JSON ↔ Python correspondence one-to-one with no .to\_dict() ceremony. The shape is the documentation.

Why these specific top-level sections: each section answers one class of question the LLM might need — overall volume, time patterns (day and hour), spatial patterns (zone), demographic patterns, and behavioural patterns (sequence). If the report ever wants a number, it must exist under one of these keys. This finite, flat enumeration is what lets you tell the LLM in the grounded prompt: "every numerical claim must reference a key in this object."



Insight (JSON shape)

pythonInsightType = Literal\[

&#x20;   "peak\_hour", "quiet\_hour", "hot\_zone", "sticky\_zone",

&#x20;   "bounce\_zone", "demographic\_skew", "common\_path",

]



class Evidence(TypedDict, total=False):

&#x20;   # only the relevant subset of keys is set per insight type

&#x20;   hour: int

&#x20;   day: str

&#x20;   zone\_id: str

&#x20;   journeys: int

&#x20;   avg\_dwell\_s: float

&#x20;   weekly\_avg: float

&#x20;   share\_pct: float

&#x20;   delta\_pp: float

&#x20;   sequence: str

&#x20;   count: int



class Insight(TypedDict):

&#x20;   id: str                       # "I001", "I002", ...

&#x20;   type: InsightType

&#x20;   headline: str                 # human-readable, deterministic

&#x20;   evidence: Evidence

&#x20;   metric\_refs: list\[str]        # e.g. \["by\_hour\[17].journey\_count", "volume.total\_journeys"]

&#x20;   confidence: Literal\["high", "medium", "low"]

Why evidence is a structured object, not free text: the LLM should be able to consume the number, not parse it out of a sentence. The headline is convenient prose; the evidence is the grounding.

Why metric\_refs matters: these are dotted paths back into metrics.json. They serve two purposes: (1) any auditor — including the professor — can verify each insight by checking the referenced metric, and (2) the grounded prompt can be written as "you may only state numerical claims that are present in either evidence or one of the metric\_refs paths". This converts hallucination-prevention from a soft prompt instruction into a structural check you can verify after the fact.

Why confidence: mirrors the journey-level confidence. A peak\_hour insight built on a day with 90% low-confidence journeys deserves a lower confidence label than one built on high-confidence data. The LLM can be told to soften language for low-confidence insights — "may indicate" instead of "shows".



Active Trajectory Tracking

The data structure for tracking open journeys is the inner loop of the stitcher. The simple, fast version is one dict keyed by demographic bucket:

pythonactive: dict\[tuple\[str, str], list\[ActiveJourney]]

For each incoming event:



Look up active\[event.bucket] — typically a list of length 0–20, never the whole population.

Filter by can\_accept(event, ...) — the predicate on ActiveJourney.

Among candidates, pick the one with the maximum last\_ts (most recent activity = strongest temporal match).

Record len(candidates) on that journey's candidates\_at\_match — this is what later determines confidence.

Append the event and update last\_ts and current\_zone.



Why this representation: bucket-keyed dicts give O(1) lookup, and within-bucket lists are short enough that linear scans are cheaper than maintaining a sorted structure. Tried-and-true streaming pattern; no heap, no priority queue, no custom container.

Periodic stale sweep: every few hundred events, iterate all buckets and close any journey where is\_stale(current\_event.timestamp, STALE\_TIMEOUT). Sweeping every event is wasteful; never sweeping causes the dict to grow without bound. The sweep keeps active bounded by roughly the number of people inside the store at any moment — a small, well-behaved number.



Overlap Prevention

Three distinct overlap concerns, with one mechanism each:



Two journeys claiming the same event. Prevented structurally: greedy assignment consumes each event exactly once. No two journeys can ever reference the same event\_id.

One journey in two zones at once. Prevented by current\_zone on ActiveJourney. Same-zone events extend the current ZoneVisit; different-zone events close it and open a new one. There is no representation in which a journey is in two zones simultaneously — it's not expressible in the data model.

Two open journeys in the same bucket competing for an event. This is irreducible ambiguity from the lack of person\_id. The data model handles it by recording candidates\_at\_match and downgrading stitch\_confidence to low when the count exceeds 1. You don't prevent this overlap — you measure it.



The third item is your honest-limitation talking point: "We do not pretend to disambiguate same-bucket concurrency; we measure it and propagate it to confidence labels and into evaluation.json."



Efficient Chronological Processing

Three rules carry the performance and correctness story:



Sort once. Sort the entire events DataFrame by timestamp at load, then iterate in order. Never look backward, never re-sort. With 250k events this is sub-second in pandas.

Single pass. Every event is processed exactly once. No nested loops over events. The stitcher's outer loop is O(N); within each iteration the inner work scans only one bucket, whose size is bounded by concurrent occupancy.

Amortised cleanup. The stale sweep runs every K events (a K=500 is fine) rather than on each event. This is the standard amortisation pattern for streaming algorithms and keeps the inner loop tight.



Why this matters for defense: the professor may ask "why does this scale?" The answer is grounded: sorted single-pass over N events, with O(occupancy) per-event work and O(N/K) amortised sweep work, giving overall O(N log N) dominated by the initial sort. No ML, no clever data structures, easy to explain at the whiteboard.



What I am deliberately not adding: no Pydantic, no \_\_post\_init\_\_ validators, no custom \_\_repr\_\_s, no inheritance hierarchies, no enums beyond Literal types. Each of these adds a small amount of code and a non-trivial amount of cognitive load during defense. The plain dataclass + TypedDict combination here is the simplest representation that still gives you typed structure, JSON serializability, and clear handoffs between stages.

