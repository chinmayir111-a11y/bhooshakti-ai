"""Backtest scoring: did the alert fire before the landslide, and how early?

Pure functions over a replayed risk timeline [(timestamp, risk_score), ...].
Tested in tests/test_backtest.py.

Definitions (stated in README "Backtest on real landslides" too):

  threshold      the HIGH band (risk >= 50), which is when the live system
                 issues an alert
  reference      the event time if the record has one, otherwise the START of
                 the local event day — a warning only counts as "before" if it
                 beat the whole day
  first alert    the start of the continuous HIGH run that is in progress at,
                 or begins within, the look-back window (72 h before the
                 reference up to the end of the event day). A run that began
                 earlier is followed back to where it began — that is when the
                 alert would actually have gone out.
  warned_before  first alert <= reference           lead = reference - first alert
  same_day       reference < first alert < day end  (time unknown: honest bucket)
  missed         never HIGH in the window
  false alarm    a non-event / dry window that reaches HIGH at any hour
"""
from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median
from typing import Sequence

from .fusion import SEVERITY_BANDS

HIGH = next(t for t, label in SEVERITY_BANDS if label == "HIGH")
LOOKBACK_H = 72

Timeline = Sequence[tuple[datetime, float]]


def first_alert(timeline: Timeline, window_start: datetime, window_end: datetime,
                threshold: float = HIGH) -> datetime | None:
    hit = None
    for i, (ts, score) in enumerate(timeline):
        if window_start <= ts < window_end and score >= threshold:
            hit = i
            break
    if hit is None:
        return None
    while hit > 0 and timeline[hit - 1][1] >= threshold:
        hit -= 1
    return timeline[hit][0]


def evaluate_event(timeline: Timeline, reference: datetime, day_end: datetime,
                   threshold: float = HIGH, lookback_h: int = LOOKBACK_H) -> dict:
    start = reference - timedelta(hours=lookback_h)
    first = first_alert(timeline, start, day_end, threshold)
    in_window = [(ts, s) for ts, s in timeline if start <= ts < day_end]
    peak_ts, peak = max(in_window, key=lambda t: t[1]) if in_window else (None, 0.0)
    if first is None:
        outcome, lead = "missed", None
    elif first <= reference:
        outcome, lead = "warned_before", round((reference - first).total_seconds() / 3600.0, 1)
    else:
        outcome, lead = "same_day", round((reference - first).total_seconds() / 3600.0, 1)
    return {"outcome": outcome, "lead_hours": lead,
            "first_alert": first.isoformat() if first else None,
            "peak_score": round(peak, 1), "peak_at": peak_ts.isoformat() if peak_ts else None}


def evaluate_window(timeline: Timeline, threshold: float = HIGH) -> dict:
    high = [ts for ts, s in timeline if s >= threshold]
    return {"false_alarm": bool(high), "hours_high": len(high),
            "first_alert": high[0].isoformat() if high else None,
            "peak_score": round(max((s for _, s in timeline), default=0.0), 1)}


def summarise(events: list[dict], non_event: list[dict], dry: list[dict]) -> dict:
    n = len(events)
    before = [e for e in events if e["outcome"] == "warned_before"]
    same = [e for e in events if e["outcome"] == "same_day"]
    missed = [e for e in events if e["outcome"] == "missed"]
    leads = [e["lead_hours"] for e in before]
    fa_ne = sum(w["false_alarm"] for w in non_event)
    fa_dry = sum(w["false_alarm"] for w in dry)
    return {
        "events": n,
        "warned_before": len(before),
        "warned_same_day": len(same),
        "missed": len(missed),
        "median_lead_hours": round(median(leads), 1) if leads else None,
        "non_event_windows": len(non_event),
        "non_event_false_alarms": fa_ne,
        "dry_windows": len(dry),
        "dry_false_alarms": fa_dry,
        "headline": (f"Warned before {len(before)} of {n} held-out landslides"
                     + (f" (median {median(leads):.0f} h ahead)" if leads else "")
                     + f"; {len(same)} more on the same day; {len(missed)} missed. "
                     f"False alarms: {fa_ne} of {len(non_event)} same-season non-event windows, "
                     f"{fa_dry} of {len(dry)} dry-season windows."),
    }


# ---------------------------------------------------------------------------
# Baseline: the simple rule a judge will ask about
# ---------------------------------------------------------------------------
# "Alert when 24 h rain >= T24 OR 72 h rain >= T72." The two thresholds are
# chosen once, on the TRAINING samples only (the same positives and negatives
# the model learns from), by Youden's J = hit rate - false-alarm rate. The rule
# is then replayed through exactly the same scoring as the model.

RULE_T24_GRID = tuple(range(10, 305, 5))
RULE_T72_GRID = tuple(range(20, 510, 10))


def rule_fires(r24: float, r72: float, t24: float, t72: float) -> bool:
    return r24 >= t24 or r72 >= t72


def choose_rule(r24: Sequence[float], r72: Sequence[float], labels: Sequence[int]) -> dict:
    pos = [i for i, y in enumerate(labels) if y == 1]
    neg = [i for i, y in enumerate(labels) if y == 0]
    if not pos or not neg:
        raise ValueError("need positive and negative training samples")
    best = None
    for t24 in RULE_T24_GRID:
        for t72 in RULE_T72_GRID:
            tpr = sum(rule_fires(r24[i], r72[i], t24, t72) for i in pos) / len(pos)
            fpr = sum(rule_fires(r24[i], r72[i], t24, t72) for i in neg) / len(neg)
            j = tpr - fpr
            if best is None or j > best["youden_j"] + 1e-12:
                best = {"t24": t24, "t72": t72, "youden_j": round(j, 4),
                        "train_hit_rate": round(tpr, 3), "train_false_alarm_rate": round(fpr, 3)}
    return best
