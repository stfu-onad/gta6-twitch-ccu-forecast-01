"""gta6-twitch-ccu-forecast-01 entry: median launch-day shape forecaster.

Forecasts Grand Theft Auto VI's launch-day Twitch concurrent viewers, hour by
hour (hours 2..24 of the release day, UTC), as five quantiles per hour.

Method: the launch-day shape of past big console launches is far more
informative than assuming hour 1's count persists. For each comparable launch
with a complete release day (hourly viewers > 0 for every hour 1..24 of its
day_start UTC day), take the log-ratios ln(v_h / v_1) for h = 2..24. Per hour,
the median of those log-ratios is the shape's centre and the empirical
quantiles at the scored levels are its spread; the spread is shrunk halfway
toward the median (x0.5) because the raw cross-launch spread is wider than a
single launch's own hour-to-hour variation. The forecast is hour 1's print p
times exp of the shrunk log-quantile, rounded to 2 decimals.

Deterministic, standard library only, no network, no clock, no randomness.
Reads $MAKEFUN_INPUT_DIR (else /input/) for every *.in file in name order and
writes $MAKEFUN_OUTPUT_DIR (else /output/)/<id>.out for each.
"""

import json
import math
import os
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

# The quantile levels the contest scores, in the order each row lists them.
LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# The standard normal's quantile at each level (house-baseline fallback only).
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]
# Spread of the baseline fallback, in natural-log units per square-root hour.
BASELINE_SIGMA = 0.15
# How far the empirical cross-launch spread is shrunk toward the median.
SPREAD_SCALE = 0.5
# Minimum complete comparables per hour for the empirical shape to be trusted:
# with fewer, the per-hour quantiles come from one or two launches only, so
# the hour falls back to the house baseline's shape instead.
MIN_COMPLETE = 3
# Viewer counts are capped by the contest's output limit.
MAX_VIEWERS = 1_000_000_000


def round2(x: float) -> float | int:
    """x rounded to 2 decimals, half up, as JavaScript's Math.round(x * 100) / 100."""
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if value.is_integer() else value


def quantile(sorted_vals: list, tau: float) -> float:
    """Linear-interpolation quantile of an already-sorted list."""
    if not sorted_vals:
        return 0.0
    n = len(sorted_vals)
    pos = tau * (n - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def comparable_log_ratios(case: dict) -> dict:
    """Per hour h = 2..24: the list of ln(v_h / v_1) over comparables whose
    release day is complete (hourly viewers > 0 for every hour 1..24 of the
    comparable's day_start UTC day)."""
    ratios = {h: [] for h in range(2, 25)}
    for comp in case.get("comparables", []):
        hourly = {row["from"]: row["viewers"] for row in comp.get("hourly", [])}
        try:
            base = datetime.fromisoformat(comp["day_start"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        vals = {}
        complete = True
        for h in range(1, 25):
            key = (base + timedelta(hours=h - 1)).strftime("%Y-%m-%dT%H:00:00Z")
            v = hourly.get(key)
            if v is None or v <= 0:
                complete = False
                break
            vals[h] = v
        if not complete:
            continue
        v1 = vals[1]
        for h in range(2, 25):
            ratios[h].append(math.log(vals[h] / v1))
    return ratios


def hour_quantiles(p: float, h: int, ratios: list) -> list:
    """The five quantiles of hour h's viewers from this hour's log-ratios."""
    vals = sorted(ratios)
    med = statistics.median(vals)
    qs = []
    prev = None
    for tau in LEVELS:
        q = med + (quantile(vals, tau) - med) * SPREAD_SCALE
        value = round2(min(max(p * math.exp(q), 1.0), MAX_VIEWERS))
        # Quantiles must be non-decreasing; rounding can only break that by a cent.
        if prev is not None and value < prev:
            value = prev
        qs.append(value)
        prev = value
    return qs


def baseline_quantiles(p: float, h: int) -> list:
    """The house baseline's shape (flat at hour 1, widening spread): used only
    when an hour has fewer than MIN_COMPLETE complete comparables."""
    qs = []
    prev = None
    for z in Z:
        value = round2(min(max(p * math.exp(z * BASELINE_SIGMA * math.sqrt(h - 1)), 1.0), MAX_VIEWERS))
        if prev is not None and value < prev:
            value = prev
        qs.append(value)
        prev = value
    return qs


def forecast_case(case: dict, name: str) -> dict:
    if case["levels"] != LEVELS:
        raise ValueError(f"{name} asks for levels {case['levels']}, not {LEVELS}")
    first = next((k for k in case["known"] if k["hour"] == 1), None)
    if first is None:
        raise ValueError(f"{name} has no hour-1 print")
    p = max(1, first["viewers"])
    ratios = comparable_log_ratios(case)
    hours = []
    for row in case["forecast"]:
        h = row["hour"]
        if len(ratios[h]) >= MIN_COMPLETE:
            qs = hour_quantiles(p, h, ratios[h])
        else:
            qs = baseline_quantiles(p, h)
        hours.append({"hour": h, "q": qs})
    return {"hours": hours}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Every case file, in name order, so two runs write the same bytes.
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
