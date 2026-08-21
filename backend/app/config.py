"""Runtime configuration. Secrets come from the environment / .env — never
from the repository."""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_ROOT / ".env", BACKEND_ROOT.parent / ".env"),
        env_prefix="NEXA_",
        extra="ignore",
    )

    app_name: str = "Nexa"
    data_dir: Path = BACKEND_ROOT.parent / "dataset"
    # Which mailbox in the export to analyse ("tester", "senior", "junior").
    # Empty picks the inbox registered against the cards.
    mailbox: str = ""
    outbox_dir: Path = BACKEND_ROOT / "outbox"
    log_dir: Path = BACKEND_ROOT / "logs"

    database_url: str = "postgresql://nexa:nexa@localhost:55432/nexa"

    ai_url: str = "http://localhost:11434"
    ai_model: str = "gemma4:latest"
    # Which transport talks to the model: "ollama", "openai" (any
    # OpenAI-compatible endpoint), or "auto" — decided from the URL shape and
    # whether a key is configured, then confirmed by probing.
    ai_provider: str = "auto"
    # Hosted endpoints need a bearer token. It lives in the environment only;
    # nothing here is ever committed, logged or sent to the browser.
    ai_api_key: str = ""
    # "auto" assumes an OpenAI-compatible endpoint can call tools and drops to
    # JSON routing if it rejects the schema. "true"/"false" force the tier.
    ai_native_tools: str = "auto"
    offline_mode: bool = False
    llm_timeout_seconds: float = 120.0
    # This is an AI product: the model is expected to be up. Transport
    # failures are retried, and an outage is reported as an outage rather
    # than quietly degrading into template answers.
    ai_retries: int = 2
    ai_retry_backoff_seconds: float = 0.75

    # Mail settings must come from .env / environment. Outbox delivery is
    # disabled so a confirmed send either reaches SMTP or fails loudly.
    mail_mode: str
    mail_to: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    smtp_starttls: bool
    smtp_ssl: bool
    smtp_timeout_seconds: float

    # Overriding "today" keeps dispute-deadline countdowns deterministic in tests.
    today_override: date | None = None

    # Vietnamese answers lead with đồng. The source data is USD, so the ₫ figure
    # is a declared conversion at this configured rate — never presented as a
    # bank rate, and always marked approximate.
    usd_vnd_rate: float = 26_000.0
    show_vnd: bool = True

    # Daily re-scan. Uses the same code path as the manual scan, so it inherits
    # the no-duplicate-alerts behaviour.
    scheduler_enabled: bool = True
    scan_hour: int = 7

    # YOPmail ingestion runs inside this application process. APScheduler
    # launches the Node scraper from the backend, without machine crontab.
    yopmail_enabled: bool = True
    yopmail_user: str = "wealifytester"
    yopmail_mailbox: str = "tester"
    yopmail_hour: int = 7
    yopmail_minute: int = 10
    yopmail_node: str = "node"
    yopmail_scraper_dir: Path = BACKEND_ROOT.parent / "scripts" / "yopmail_scraper"
    yopmail_limit: int = 0
    yopmail_delay_ms: int = 800
    yopmail_require_unlocked: bool = True

    cors_origins: list[str] = Field(default_factory=lambda: [
        "http://localhost:3000", "http://127.0.0.1:3000",
    ])

    @property
    def meta_path(self) -> Path:
        return self.data_dir / "account_meta.json"

    @property
    def cards_path(self) -> Path:
        return self.data_dir / "cards.csv"

    @property
    def owner_email(self) -> str:
        """The one and only address a report may ever be sent to.

        Read from whichever file the active dataset states it in: the generated
        layout puts it in `account_meta.json`, the Wealify export registers it
        against the cards. An empty string is returned rather than a guess —
        `mailer.assert_owner` then refuses to send at all, which is the right
        failure for a feature that must never mail a stranger.
        """
        try:
            return json.loads(self.meta_path.read_text())["owner_email"]
        except (OSError, KeyError, json.JSONDecodeError):
            pass
        if self.cards_path.exists():
            # Imported here, not at module scope: the engine imports this module.
            from .engine.loader_wlf import _owner_email, read_csv

            try:
                return _owner_email(read_csv(self.cards_path))
            except OSError:
                return ""
        return ""

    def today(self) -> date:
        return self.today_override or date.today()


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.outbox_dir.mkdir(parents=True, exist_ok=True)
    s.log_dir.mkdir(parents=True, exist_ok=True)
    return s


settings = get_settings()
