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
    # Context window in tokens: everything the model reads (instructions, sources,
    # question) plus what it writes must fit. Ollama defaults to a small window and
    # SILENTLY cuts off the start of longer prompts, so we always set it explicitly.
    chat_num_ctx: int = 8192
    chat_max_answer_tokens: int = 1024
    chat_temperature: float = 0.1  # low = focused and consistent; high = more creative
    chat_timeout_seconds: float = 300.0
    embed_model: str = "nomic-embed-text"
    # Must match the embedding model's output size (nomic-embed-text: 768). Changing it
    # needs a database migration, since the vector column has a fixed size.
    embed_dimensions: int = 768
    embed_batch_size: int = 32
    # nomic-embed-text was trained with these task prefixes; other models may use none.
    embed_document_prefix: str = "search_document: "
    embed_query_prefix: str = "search_query: "

    # Limits (per user). Questions cover /ask, /ask/stream and conversation messages.
    rate_limit_questions_per_minute: int = 10
    rate_limit_uploads_per_hour: int = 60
    max_pdf_pages: int = 1000
    # A .docx is a zip file; refuse ones that would expand to more than this when opened
    # (a "zip bomb" can be tiny on disk but huge in memory).
    max_docx_uncompressed_bytes: int = 200 * 1024 * 1024

    # Logging. Question text is only logged when explicitly enabled (it may be sensitive).
    log_level: str = "INFO"
    log_question_text: bool = False

    # Search: how many candidates each method (vector, keyword) proposes, and how many
    # fused results are returned.
    search_candidates: int = 20
    # 5 chosen by evaluation (scripts/evaluate.py): same accuracy as 8 on the golden
    # questions, ~35% faster to the first word, with headroom over 3.
    search_top_k: int = 5

    jwt_secret: str = "change-me"
    # How long a login lasts before you must sign in again (8 hours).
    jwt_lifetime_seconds: int = 8 * 60 * 60
    upload_dir: Path = Path("data/uploads")
    max_upload_bytes: int = 25 * 1024 * 1024  # 25 MB

    # Chunking: target size and overlap between neighbouring chunks, in (estimated) tokens.
    chunk_target_tokens: int = 500
    chunk_overlap_tokens: int = 75

    @property
    def upload_path(self) -> Path:
        """Upload dir resolved against the repo root, so it works from any working directory."""
        return self.upload_dir if self.upload_dir.is_absolute() else REPO_ROOT / self.upload_dir


settings = Settings()
