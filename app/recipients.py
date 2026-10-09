import csv
import io
import re

MAX_NAME_LENGTH = 80  # longer names don't fit on the certificate
MAX_EMAIL_LENGTH = 254

# basic shape check only: something@domain.tld
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def clean(value) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def check_recipient(name: str, email: str, seen_emails: set[str]) -> str | None:
    """Returns the reason a row is invalid, or None if it's fine."""
    if not name:
        return "name is required"
    if len(name) > MAX_NAME_LENGTH:
        return f"name is longer than {MAX_NAME_LENGTH} characters"
    if not any(ch.isalpha() for ch in name):
        return "name must contain at least one letter"

    if not email:
        return "email is required"
    if len(email) > MAX_EMAIL_LENGTH:
        return f"email is longer than {MAX_EMAIL_LENGTH} characters"
    if not EMAIL_RE.match(email):
        return f"'{email}' is not a valid email address"

    if email.lower() in seen_emails:
        return f"duplicate email '{email}' in this job"
    seen_emails.add(email.lower())
    return None


def parse_csv(content: bytes) -> list[dict]:
    try:
        text = content.decode("utf-8-sig")  # -sig drops the BOM Excel adds
    except UnicodeDecodeError:
        raise ValueError("CSV must be UTF-8 encoded")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV file is empty")

    headers = {h.strip().lower(): h for h in reader.fieldnames if h}
    missing = [col for col in ("name", "email") if col not in headers]
    if missing:
        raise ValueError(f"CSV is missing column(s): {', '.join(missing)}")

    rows = []
    for row in reader:
        name, email = row.get(headers["name"]), row.get(headers["email"])
        if clean(name) or clean(email):
            rows.append({"name": name, "email": email})

    if not rows:
        raise ValueError("CSV has no recipient rows")
    return rows
