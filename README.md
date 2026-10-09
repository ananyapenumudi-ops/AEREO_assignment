# Bulk Certificate Generator

![tests](https://github.com/ananyapenumudi-ops/AEREO_assignment/actions/workflows/tests.yml/badge.svg)

A FastAPI backend that takes a list of recipients (as JSON or a CSV file), generates a PDF certificate for each one in the background, and lets you track progress and download the results, either one by one or as a ZIP.

Stack: **Python 3.11+, FastAPI, SQLAlchemy 2, SQLite (or Postgres), ReportLab, pytest**

```
app/
  main.py         app setup, startup hook
  api.py          all HTTP endpoints
  jobs.py         creating jobs + the background worker
  recipients.py   row validation and CSV parsing
  generator.py    the certificate template (ReportLab)
  fonts/          bundled OFL fonts used by the template
  models.py       Job and Certificate tables
  schemas.py      request/response models
  db.py, config.py
tests/
samples/          example JSON request and CSV file
```

## Setup

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Nothing else is needed. By default it uses a SQLite file (`certificates.db`) and writes PDFs to `generated/`, both created on first start.

Optional settings, read from environment variables (`.env.example` lists them with their defaults; the app does not load a `.env` file by itself):

| Variable | Default | |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./certificates.db` | any SQLAlchemy URL |
| `OUTPUT_DIR` | `./generated` | where PDFs are stored |
| `MAX_RECIPIENTS_PER_JOB` | `5000` | |
| `MAX_UPLOAD_BYTES` | `2097152` (2 MB) | largest CSV accepted by `/jobs/upload` |
| `WORKER_THREADS` | `4` | how many jobs can run at the same time |

To use Postgres instead:

```bash
docker compose up -d
export DATABASE_URL=postgresql+psycopg://certs:certs@localhost:5432/certs
```

## Running

```bash
uvicorn app.main:app --reload
```

Interactive docs are at http://127.0.0.1:8000/docs, where every endpoint can be tried from the browser.

## Running tests

```bash
pytest
```

They also run on GitHub Actions for every push, on SQLite (Python 3.11 and 3.13) and on a real Postgres 16 database. To run them against your own Postgres locally, set `TEST_DATABASE_URL`. Note that it drops and recreates the tables. The tests use a fresh temporary database and output folder each time, and run jobs inline so they don't have to wait on a background thread.

## Using the API

### 1. Submit a job

JSON:

```bash
curl -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -d @samples/job.json
```

```json
{
  "course_name": "DGCA Small Category Drone Pilot Training",
  "issued_on": "2026-10-04",
  "issued_by": "Skyline Drone Academy",
  "recipients": [
    {"name": "Ananya Penumudi", "email": "ananya@example.com"},
    {"name": "Rahul Varma", "email": "rahul@example.com"},
    {"name": "Sneha Reddy", "email": "sneha-at-example.com"}
  ]
}
```

Or CSV (needs `name` and `email` columns, other columns are ignored, max 2 MB):

```bash
curl -X POST http://127.0.0.1:8000/jobs/upload \
  -F "file=@samples/participants.csv" \
  -F "course_name=DGCA Small Category Drone Pilot Training" \
  -F "issued_by=Skyline Drone Academy"
```

Both return `202 Accepted` right away:

```json
{
  "id": "8ee37c9b-7ba1-4d74-b731-8b1ca796a028",
  "status": "pending",
  "total": 3,
  "queued": 2,
  "invalid": 1,
  "status_url": "/jobs/8ee37c9b-7ba1-4d74-b731-8b1ca796a028"
}
```

### 2. Check progress

```bash
curl http://127.0.0.1:8000/jobs/<job_id>
```

```json
{
  "id": "8ee37c9b-...",
  "status": "completed_with_errors",
  "total": 3,
  "progress": {"pending": 0, "generated": 2, "failed": 0, "invalid": 1, "percent_complete": 100.0},
  "problems": [
    {
      "certificate_id": "e0d0b908-...",
      "row_number": 3,
      "name": "Sneha Reddy",
      "email": "sneha-at-example.com",
      "status": "invalid",
      "error": "'sneha-at-example.com' is not a valid email address"
    }
  ],
  ...
}
```

Job status is one of `pending`, `processing`, `completed`, `completed_with_errors` or `failed`.
`problems` lists every row that didn't produce a certificate, with its row number so it can be fixed in the source sheet.

If some certificates `failed` during generation, `POST /jobs/{id}/retry` re-runs just those rows. Already generated certificates are left alone.

### 3. Get the certificates

| | |
|---|---|
| `GET /jobs/{id}/certificates` | rows of the job, 100 per page by default (`?limit=` up to 1000, `?offset=`); filter with `?status=generated` (or `failed`, `invalid`, `pending`). The total count is in the `X-Total-Count` header |
| `GET /jobs/{id}/download` | ZIP of all generated PDFs (409 while the job is still running) |
| `POST /jobs/{id}/retry` | regenerate only the `failed` certificates |
| `GET /certificates/{id}` | one certificate's details |
| `GET /certificates/{id}/download` | the PDF itself |
| `GET /verify/{code}` | check that a certificate is genuine using the code printed on it |

## Design decisions

**Background processing with a thread pool.** `POST /jobs` saves the job, hands its id to a `ThreadPoolExecutor` and returns 202 straight away, so a request with thousands of recipients doesn't time out. The client then polls `GET /jobs/{id}`. I picked an in-process pool over Celery + Redis because it needs no extra services to run or review, and the work here is short. Each PDF takes a few milliseconds, and 300 certificates finish in about 2 seconds locally. The cost is that jobs only run inside the API process. If this had to scale across several machines, I'd move `process_job` behind a real queue (Celery/RQ with Redis). The function already takes only a job id and reads everything from the DB, so that change stays small.

**The database is the source of truth, not memory.** Every certificate is its own row with a status, and it's committed as soon as it's generated. That gives live progress for free, and it means a restart doesn't lose work. On startup, `resume_unfinished_jobs()` re-queues any job left in `pending`/`processing`, and since the worker only picks up `pending` rows, nothing gets generated twice. The progress counts are calculated with a `GROUP BY` on the certificate rows rather than kept as counters on the job, so they can't drift.

**Two levels of validation.**
- *Whole-request problems* such as a missing `course_name`, an empty recipient list, more than `MAX_RECIPIENTS_PER_JOB` rows, or a malformed body return **422** and nothing is created.
- *Single-row problems* such as a blank name, a missing or badly formatted email, or a duplicate email in the same job don't reject the request. The row is stored as `invalid` with the reason, and every other row still gets generated. With a 500-person list, one typo shouldn't block 499 certificates, and the organiser gets the exact row number to fix.

Names and emails are whitespace-normalised first, and duplicate emails are compared case-insensitively.

**Generation failures stay isolated.** Each certificate is generated in its own `try/except` and its own DB session. If one fails (a bad font, a disk error, anything), that row becomes `failed` with the error message, any half-written file is deleted, and the loop carries on. The job ends as `completed_with_errors`. It only ends as `failed` if nothing at all could be generated.

**`invalid` vs `failed`.** I kept these separate on purpose. `invalid` means the input data was bad and the client needs to fix it. `failed` means our side broke while generating, so retrying could work, which is what `POST /jobs/{id}/retry` does. It resets `failed` rows to `pending` and queues the job again. Since the worker only ever picks up `pending` rows, this reuses the normal processing path with no special case.

**Certificate template.** There's a single fixed landscape A4 layout drawn with ReportLab. I kept the same visual language as my other project, Elementium: a cream card on grid paper, cocoa outlines with hard offset shadows, and a scalloped seal. It uses Fraunces for the name and title, Lora for body text and Courier Prime for labels. The fonts are bundled in `app/fonts/` (all SIL Open Font License), so every PDF looks the same on any machine. No HTML-to-PDF engine is needed, which avoids system dependencies like wkhtmltopdf or Chrome. Long names and course titles shrink to fit on one line rather than overflowing. Each certificate gets a random 10-character verification code that's printed on it and checked by `/verify/{code}`.

**Files on disk, metadata in the DB.** PDFs are saved under `generated/<job_id>/<certificate_id>.pdf`, and the DB stores the path. Using ids instead of names in file paths avoids collisions and any path problems from user input. Readable names like `0001_Ananya_Penumudi.pdf` are only used when downloading.

**SQLite by default.** It means zero setup for whoever runs this. It runs in WAL mode so the API can read progress while a worker is writing. Switching to Postgres only takes setting `DATABASE_URL`, with no code changes, and CI runs the full test suite against Postgres to prove it. Running on Postgres caught one real difference: SQLite ignores column lengths, so a very long name or email worked there but crashed Postgres. Over-long values are now rejected by validation, and stored values are cut to fit their columns. Tables are created with `create_all` on startup. In a real deployment I'd use Alembic migrations instead.

## Things I'd add next

- Move generation to Celery/RQ and the PDFs to object storage (S3) for multi-server deployments
- Build the ZIP once when a job finishes instead of in memory on every download (fine for a few thousand small PDFs, but it doesn't scale forever)
- Authentication, so jobs belong to an organisation
- Email each recipient their certificate
