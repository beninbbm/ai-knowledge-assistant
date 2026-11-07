"""All configuration in one place, read from environment variables or the repo-root .env file."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://rag:rag@localhost:5432/rag"
    test_database_url: str = "postgresql+asyncpg://rag:rag@localhost:5432/rag_test"

    ollama_url: str = "http://localhost:11434"
    chat_model: str = "llama3.1:8b"
    embed_model: str = "nomic-embed-text"

    jwt_secret: str = "change-me"
    # How long a login lasts before you must sign in again (8 hours).
    jwt_lifetime_seconds: int = 8 * 60 * 60
    upload_dir: Path = Path("data/uploads")

    @property
    def upload_path(self) -> Path:
        """Upload dir resolved against the repo root, so it works from any working directory."""
        return self.upload_dir if self.upload_dir.is_absolute() else REPO_ROOT / self.upload_dir


settings = Settings()
