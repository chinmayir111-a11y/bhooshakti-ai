"""Feature contract shared by training and inference.

Both paths MUST build frames through `build_frame` so the column order and
encoding can never drift between `scripts/train.py` and the live API.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import pandas as pd

NUMERIC_FEATURES = [
    "rainfall_24h",
    "rainfall_72h",
    "antecedent_rain_15d",
    "soil_moisture_pct",
    "slope_deg",
    "aspect_sin",
    "aspect_cos",
    "elevation_m",
]

CATEGORICAL_FEATURES = ["lithology", "land_cover"]

ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

# Human-readable labels for the contributing-factor text.
FEATURE_LABELS = {
    "rainfall_24h": "24-hour rainfall",
    "rainfall_72h": "72-hour rainfall",
    "antecedent_rain_15d": "15-day antecedent rainfall",
    "soil_moisture_pct": "soil moisture",
    "slope_deg": "slope angle",
    "aspect_sin": "slope aspect",
    "aspect_cos": "slope aspect",
    "elevation_m": "elevation",
    "lithology": "lithology",
    "land_cover": "land cover",
}

LITHOLOGY_LABELS = {
    "phyllite_schist": "weathered phyllite–schist",
    "sandstone_shale": "sandstone–shale sequence",
    "quartzite": "quartzite",
    "gneiss": "gneiss",
    "limestone": "limestone",
    "granite": "granite",
    "alluvium_terrace": "alluvial terrace material",
}

LAND_COVER_LABELS = {
    "dense_forest": "dense forest",
    "open_forest": "open forest",
    "tea_plantation": "tea plantation",
    "terrace_agriculture": "terrace agriculture",
    "built_up": "built-up slope",
    "scrub_grassland": "scrub / grassland",
    "barren_rock": "barren rock",
}


@dataclass
class FeatureRow:
    """One zone at one instant, as the model sees it."""

    rainfall_24h: float
    rainfall_72h: float
    antecedent_rain_15d: float
    soil_moisture_pct: float
    slope_deg: float
    aspect_deg: float
    elevation_m: float
    lithology: str
    land_cover: str

    def encoded(self) -> dict:
        d = asdict(self)
        aspect = d.pop("aspect_deg")
        d["aspect_sin"] = math.sin(math.radians(aspect))
        d["aspect_cos"] = math.cos(math.radians(aspect))
        return d


def build_frame(rows: list[FeatureRow]) -> pd.DataFrame:
    """Encode rows into the exact column order the pipeline expects."""
    df = pd.DataFrame([r.encoded() for r in rows])
    for col in NUMERIC_FEATURES:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
    for col in CATEGORICAL_FEATURES:
        df[col] = df[col].astype(str)
    return df[ALL_FEATURES]
