from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings. Every value can be overridden with an env var
    prefixed with CERT_, e.g. CERT_DATABASE_URL=postgresql://..."""

    model_config = SettingsConfigDict(env_prefix="CERT_", env_file=".env")

    database_url: str = "sqlite:///./certificates.db"
    output_dir: Path = Path("generated_certificates")

    # Upper bound on recipients in a single request. Protects the API from
    # unbounded payloads; large batches can be split into several jobs.
    max_recipients_per_job: int = 1000

    # Number of jobs processed in parallel by the background worker pool.
    max_workers: int = 2

    # When True, jobs are processed inside the request instead of in the
    # background. Used by the test-suite to make results deterministic.
    sync_processing: bool = False

    default_issuer: str = "Certificate Authority"


settings = Settings()
