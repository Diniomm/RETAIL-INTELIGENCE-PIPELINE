# Retail Intelligence Pipeline

Reconstructs anonymous customer journeys from raw detection events and produces a weekly analytics report using a local LLM.

**Python version:** 3.11 recommended (3.10 also works)

---

## Setup

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

Start Ollama in a separate terminal and pull the model once:

```bash
ollama serve
ollama pull llama3.1:8b
```

Place the input data:

```
data/raw/events.csv
```

---

## Run

Run the full pipeline end-to-end:

```bash
python run_all.py
```

Or run each stage individually in the same order:

```bash
python -m src.stitcher
python -m src.analytics
python -m src.insights
python -m src.report --prompt grounded
python -m src.evaluate
```

Generate all three prompt variants for the comparison doc:

```bash
python -m src.report --prompt naive       --out outputs/reports/naive.md
python -m src.report --prompt structured  --out outputs/reports/structured.md
python -m src.report --prompt grounded    --out outputs/reports/grounded.md
```

---

## Expected outputs

| File | Produced by |
|---|---|
| `data/derived/journeys.csv` | `stitcher` |
| `data/derived/metrics.json` | `analytics` |
| `data/derived/insights.json` | `insights` |
| `data/derived/weekly_report.md` | `report` |
| `outputs/evaluation.json` | `evaluate` |
| `outputs/sensitivity.csv` | `evaluate` |
| `outputs/reports/{naive,structured,grounded}.md` | `report` (manual) |

---

## Configuration

All thresholds, file paths, and the LLM model name live in `config.yaml`. Nothing is hardcoded in the source files.

Key stitching thresholds:

| Parameter | Default | Meaning |
|---|---|---|
| `linger_window` | 600 s | Max gap to attach a linger event to an open journey |
| `exit_window` | 1200 s | Max gap to close an open journey on an exit event |
| `stale_timeout` | 1800 s | Auto-close journeys idle longer than this |

---

## Pipeline architecture

```
events.csv ──► stitcher.py ──► journeys.csv
                                    │
                                    ▼
                              analytics.py ──► metrics.json
                                    │
                                    ▼
                              insights.py  ──► insights.json
                                    │
                                    ▼
                              report.py    ──► weekly_report.md
                            (LLM sees only metrics + insights JSON)


evaluate.py ──► events.csv + journeys.csv ──► evaluation.json + sensitivity.csv
```

The LLM only ever receives `metrics.json` and `insights.json` — never raw events or journeys. All insight discovery is deterministic and rule-based; the LLM is a narrative renderer only.
