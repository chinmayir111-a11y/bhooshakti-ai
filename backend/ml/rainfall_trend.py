"""24-hour rainfall outlook per zone.

Deliberately modest: an exponentially-weighted trend on the recent hourly
series, with a Holt (double exponential smoothing) fit from statsmodels when
there is enough history and it converges. Falls back cleanly, because a
forecast that crashes is worse than a forecast that is merely blunt.

This is a NOWCAST OVER SIMULATED DATA, not a meteorological product.
"""
from __future__ import annotations

import warnings

import numpy as np

try:  # statsmodels is optional at runtime; the EWMA fallback is always available
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    _HAS_STATSMODELS = True
except Exception:  # pragma: no cover - exercised only when the wheel is absent
    _HAS_STATSMODELS = False


FORECAST_HORIZON_HOURS = 24
MIN_HISTORY_HOURS = 48


# A storm's hourly intensity dies away rather than persisting at its peak.
# Without a decay this steep, a nowcast started at the peak of a monsoon spell
# extrapolates to physically absurd 24h totals.
HOURLY_DECAY = 0.82
ABSOLUTE_CEILING_MM = 250.0


def _ewma_forecast(hourly: np.ndarray, horizon: int) -> float:
    """Persistence-with-decay: recent intensity, damped over the horizon."""
    if hourly.size == 0:
        return 0.0
    weights = np.exp(np.linspace(-2.5, 0.0, min(hourly.size, 12)))
    recent = hourly[-weights.size:]
    intensity = float(np.average(recent, weights=weights))

    # Direction of travel over the last 12h vs the 12h before it.
    if hourly.size >= 24:
        trend = float(hourly[-12:].mean() - hourly[-24:-12].mean())
    else:
        trend = 0.0

    total = 0.0
    level = intensity
    for _ in range(horizon):
        level = max(0.0, level + 0.35 * trend)
        total += level
        trend *= 0.85          # damp the trend out over the horizon
        level *= HOURLY_DECAY  # storms decay
    return float(total)


def _plausible_ceiling(series: np.ndarray, horizon: int) -> float:
    """Cap the outlook at slightly above the wettest `horizon` this zone has
    actually recorded. A nowcast may exceed the observed record a little; it may
    not invent a total the zone has never come close to."""
    if series.size < horizon:
        return ABSOLUTE_CEILING_MM
    cumulative = np.concatenate(([0.0], np.cumsum(series)))
    rolling = cumulative[horizon:] - cumulative[:-horizon]
    observed_max = float(rolling.max()) if rolling.size else 0.0
    return float(min(1.15 * observed_max + 5.0, ABSOLUTE_CEILING_MM))


def forecast_24h(hourly_rainfall_mm: list[float] | np.ndarray,
                 horizon: int = FORECAST_HORIZON_HOURS) -> tuple[float, str]:
    """Return (expected mm over the next `horizon` hours, method used)."""
    series = np.asarray(list(hourly_rainfall_mm), dtype=float)
    series = np.nan_to_num(series, nan=0.0, posinf=0.0, neginf=0.0)

    persistence = max(0.0, _ewma_forecast(series, horizon))
    ceiling = _plausible_ceiling(series, horizon)

    if series.size < MIN_HISTORY_HOURS or not _HAS_STATSMODELS:
        return round(min(persistence, ceiling), 1), "ewma"

    # Holt on a 3-hour rolling mean: raw hourly rainfall is too spiky for a
    # smoother to fit anything meaningful.
    kernel = np.ones(3) / 3.0
    smoothed = np.convolve(series, kernel, mode="valid")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = ExponentialSmoothing(
                smoothed,
                trend="add",
                damped_trend=True,
                seasonal=None,
                initialization_method="estimated",
            ).fit(optimized=True)
            pred = np.asarray(fit.forecast(horizon), dtype=float)
        if not np.all(np.isfinite(pred)):
            raise ValueError("non-finite forecast")

        total = float(np.clip(pred, 0.0, None).sum())
        # The smoother has no notion that rain stops. Hold it to the damped
        # persistence estimate and to what this zone has actually recorded.
        total = min(total, 1.2 * persistence + 10.0, ceiling)
        return round(max(total, 0.0), 1), "holt_damped"
    except Exception:
        return round(min(persistence, ceiling), 1), "ewma"


def seasonal_normal_72h(hourly_rainfall_mm: list[float] | np.ndarray) -> float:
    """This zone's own typical 72h total, from its available history.

    The median of the rolling 72h sums, so a single monsoon spell in the window
    does not drag the 'normal' up to meet itself.
    """
    series = np.asarray(list(hourly_rainfall_mm), dtype=float)
    series = np.nan_to_num(series, nan=0.0)
    if series.size < 72:
        return max(float(series.sum()), 1.0)
    cumulative = np.concatenate(([0.0], np.cumsum(series)))
    rolling = cumulative[72:] - cumulative[:-72]
    return max(float(np.median(rolling)), 1.0)


def window_totals(hourly_rainfall_mm: list[float] | np.ndarray) -> dict[str, float]:
    """Trailing 24h / 72h / 15-day totals from an hourly series (oldest first)."""
    series = np.asarray(list(hourly_rainfall_mm), dtype=float)
    series = np.nan_to_num(series, nan=0.0)

    def tail(hours: int) -> float:
        return round(float(series[-hours:].sum()) if series.size else 0.0, 1)

    return {
        "rainfall_24h": tail(24),
        "rainfall_72h": tail(72),
        "antecedent_rain_15d": tail(24 * 15),
    }
