"""Application configuration via pydantic-settings v2."""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class GCPSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GCP_", env_file=".env", extra="ignore")

    project_id: str = Field(default="", description="GCP project ID")
    dataset_id: str = Field(default="", description="Source BigQuery dataset")
    location: str = Field(default="US", description="BigQuery location")
    dq_dataset: str = Field(default="dq_observability", description="DQ output dataset")
    dataplex_enabled: bool = Field(default=False, description="Enable Dataplex integration")
    dataplex_location: str = Field(default="us-central1")


class GeminiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GEMINI_", env_file=".env", extra="ignore")

    api_key: str = Field(default="", description="Gemini API key")
    model: str = Field(default="gemini-2.5-flash-lite", description="Default Gemini model")
    max_tokens: int = Field(default=8192, description="Max output tokens")
    timeout: float = Field(default=120.0, description="API request timeout in seconds")


class SlackSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SLACK_", env_file=".env", extra="ignore")

    webhook_url: Optional[str] = Field(default=None, description="Slack incoming webhook URL")
    bot_token: Optional[str] = Field(default=None, description="Slack bot token")
    channel: str = Field(default="#data-quality-alerts")


class EmailSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    sendgrid_api_key: Optional[str] = Field(default=None, alias="SENDGRID_API_KEY")
    from_email: str = Field(default="dq-alerts@example.com", alias="ALERT_EMAIL_FROM")
    to_emails: str = Field(default="", alias="ALERT_EMAIL_TO")

    @field_validator("to_emails", mode="before")
    @classmethod
    def parse_to_emails(cls, v: str) -> str:
        return v or ""

    @property
    def to_email_list(self) -> list[str]:
        return [e.strip() for e in self.to_emails.split(",") if e.strip()]


class AirflowSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AIRFLOW_", env_file=".env", extra="ignore")

    webserver_url: str = Field(default="http://localhost:8080")
    username: str = Field(default="admin")
    password: str = Field(default="admin")
    dag_bucket: str = Field(default="")


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_key: str = Field(default="changeme", alias="API_KEY")
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    environment: str = Field(default="development", alias="ENVIRONMENT")

    gcp: GCPSettings = Field(default_factory=GCPSettings)
    gemini: GeminiSettings = Field(default_factory=GeminiSettings)
    slack: SlackSettings = Field(default_factory=SlackSettings)
    email: EmailSettings = Field(default_factory=EmailSettings)
    airflow: AirflowSettings = Field(default_factory=AirflowSettings)


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Return cached application settings."""
    return AppSettings()
