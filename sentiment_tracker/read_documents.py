"""Stage 1: read earnings documents into a flat statements.csv.

Reads every file in ``data/transcripts/`` whose name matches
``<company>_<YYYY><H1|H2|Q1-Q4>.<ext>``, extracts text (pdfplumber for
.pdf, plain read for .txt), splits on blank lines into paragraphs, and
keeps paragraphs between 100 and 2000 characters.

Output: ``data/statements.csv`` with columns
``company, period, statement_index, text``.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parent
TRANSCRIPTS_DIR = PROJECT_ROOT / "data" / "transcripts"
STATEMENTS_CSV = PROJECT_ROOT / "data" / "statements.csv"

MIN_LEN = 100
MAX_LEN = 2000

FILENAME_RE = re.compile(r"^(popmart|funko)_(\d{4})(H[12]|Q[1-4])\.(pdf|txt)$", re.IGNORECASE)

VALID_EXTS = {".pdf", ".txt"}


def _parse_filename(name: str) -> tuple[str, str, str] | None:
    """Return (company, period, ext) or None if the name doesn't match."""
    match = FILENAME_RE.match(name)
    if not match:
        return None
    company, year, half_or_q, ext = match.groups()
    return company.lower(), f"{year}{half_or_q.upper()}", ext.lower()


def _read_pdf(path: Path) -> str:
    import pdfplumber  # lazy import

    chunks: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            try:
                text = page.extract_text() or ""
            except Exception as exc:  # pragma: no cover — malformed pages
                print(f"  [warn] page extract failed in {path.name}: {exc}")
                text = ""
            if text:
                chunks.append(text)
    return "\n\n".join(chunks)


def _read_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _split_paragraphs(text: str) -> Iterable[str]:
    # Normalize line endings, then split on one-or-more blank lines.
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for chunk in re.split(r"\n\s*\n", normalized):
        cleaned = " ".join(chunk.split())  # collapse internal whitespace
        if MIN_LEN <= len(cleaned) <= MAX_LEN:
            yield cleaned


def run() -> int:
    """Read every transcript, write statements.csv. Returns row count."""
    if not TRANSCRIPTS_DIR.exists():
        raise FileNotFoundError(
            f"{TRANSCRIPTS_DIR} does not exist. Create it and drop the "
            "12 earnings documents in (see README)."
        )

    files = sorted(TRANSCRIPTS_DIR.iterdir())
    files = [f for f in files if f.is_file() and f.suffix.lower() in VALID_EXTS]
    if not files:
        raise FileNotFoundError(
            f"No .pdf or .txt files in {TRANSCRIPTS_DIR}."
        )

    STATEMENTS_CSV.parent.mkdir(parents=True, exist_ok=True)
    rows_written = 0
    files_processed = 0
    files_skipped = 0

    with STATEMENTS_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["company", "period", "statement_index", "text"])

        for path in files:
            parsed = _parse_filename(path.name)
            if parsed is None:
                print(f"  [skip] {path.name}: filename doesn't match "
                      "<company>_<YYYY><H1|H2|Q1-Q4>.<ext>")
                files_skipped += 1
                continue

            company, period, ext = parsed
            try:
                raw_text = _read_pdf(path) if ext == "pdf" else _read_txt(path)
            except Exception as exc:
                print(f"  [skip] {path.name}: read failed: {exc}")
                files_skipped += 1
                continue

            file_rows = 0
            for idx, paragraph in enumerate(_split_paragraphs(raw_text)):
                writer.writerow([company, period, idx, paragraph])
                file_rows += 1
                rows_written += 1

            files_processed += 1
            print(f"  {path.name}: company={company}, period={period}, "
                  f"{file_rows} paragraphs")

    print(f"Stage 1 done. {files_processed} files processed "
          f"({files_skipped} skipped), {rows_written} paragraphs written to "
          f"{STATEMENTS_CSV.relative_to(PROJECT_ROOT)}")
    return rows_written


if __name__ == "__main__":
    run()
