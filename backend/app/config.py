"""Central configuration. Everything is env-driven; see .env.example."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # database
    database_url: str = (
        "postgresql+psycopg2://bhooshakti:bhooshakti@localhost:5432/bhooshakti"
    )

    # auth
    jwt_secret: str = "change-me-bhooshakti-demo-secret"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720
    demo_password: str = "demo1234"

    # mqtt
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_topic_prefix: str = "bhooshakti/sensors"
    mqtt_enabled: bool = True

    # api
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://localhost:8081,http://localhost:19006"

    # notifications
    notify_channels: str = "console,websocket,email,sms,push"
    alert_test_email: str = "abjgd108@gmail.com"
    public_dashboard_url: str = "http://localhost:5173"

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "BHOOSHAKTI AI <no-reply@bhooshakti.local>"
    smtp_starttls: bool = True

    sms_provider: str = "stub"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    msg91_auth_key: str = ""
    msg91_sender_id: str = ""
    alert_test_phone: str = "+910000000000"

    push_provider: str = "stub"
    expo_access_token: str = ""

    # weather (Open-Meteo)
    weather_provider: str = "open-meteo"        # open-meteo | simulated
    openmeteo_forecast_url: str = "https://api.open-meteo.com/v1/forecast"
    openmeteo_archive_url: str = "https://archive-api.open-meteo.com/v1/archive"
    weather_history_days: int = 30
    weather_forecast_days: int = 5
    # ERA5 archive lags real time by ~2 days; the forecast endpoint's past_days
    # covers the gap. Overlap by a day so the join never leaves a hole.
    weather_archive_lag_days: int = 3
    weather_timeout_s: int = 90
    weather_batch_size: int = 25

    # ml
    model_path: str = "ml/artifacts/susceptibility_xgb.joblib"
    model_meta_path: str = "ml/artifacts/model_meta.json"

    # demo
    demo_timeline_seconds: int = 60
    seed_random_state: int = 26001

    # ---------------------------------------------------------------- helpers
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def channel_list(self) -> list[str]:
        return [c.strip().lower() for c in self.notify_channels.split(",") if c.strip()]

    @property
    def model_file(self) -> Path:
        p = Path(self.model_path)
        return p if p.is_absolute() else BACKEND_DIR / p

    @property
    def model_meta_file(self) -> Path:
        p = Path(self.model_meta_path)
        return p if p.is_absolute() else BACKEND_DIR / p

    @property
    def upload_dir(self) -> Path:
        d = BACKEND_DIR / "uploads"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def use_real_weather(self) -> bool:
        return self.weather_provider.strip().lower() == "open-meteo"

    @property
    def email_configured(self) -> bool:
        """Real SMTP send is only attempted when a host is present."""
        return bool(self.smtp_host.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
