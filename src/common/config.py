from pathlib import Path

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class JiraConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JIRA_INDEXER_", env_file=".env", extra="ignore")
    jira_url: AnyHttpUrl
    jira_token: SecretStr
    jql: str = "project = RKMI ORDER BY updated ASC"
    overlap_seconds: int = Field(default=300, ge=0)
    page_size: int = Field(default=100, ge=1, le=1000)


class VespaConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INCIDENT_VESPA_", env_file=".env", extra="ignore")
    url: AnyHttpUrl = AnyHttpUrl("http://localhost:8080")
    timeout: float = Field(default=30, gt=0)


class EmbedderConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INCIDENT_EMBEDDER_", env_file=".env", extra="ignore")
    base_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8000/v1")
    api_key: SecretStr = SecretStr("")
    model: str = ""
    dimensions: int = Field(default=2560, gt=0)
    prefix: str = ""
    batch_size: int = Field(default=32, gt=0)
    timeout: float = Field(default=120, gt=0)


class RuntimeConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INCIDENT_", env_file=".env", extra="ignore")
    lock_file: Path = Path("/tmp/incident-vectorizer/index.lock")
