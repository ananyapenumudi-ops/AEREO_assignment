import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'certificates.db'}")
    output_dir: Path = Path(os.getenv("OUTPUT_DIR", str(BASE_DIR / "generated")))
    max_recipients_per_job: int = int(os.getenv("MAX_RECIPIENTS_PER_JOB", "5000"))
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(2 * 1024 * 1024)))
    worker_threads: int = int(os.getenv("WORKER_THREADS", "4"))
    run_jobs_inline: bool = os.getenv("RUN_JOBS_INLINE", "0") == "1"


settings = Settings()
