"""Reproducible acquisition of the Phase 2 dataset — Telco Customer Churn.

PROJECT_PLAN.md §J (dataset strategy), §Phase 2 (Internal Gate 2B).

Downloads the raw CSV from an **immutable, commit-pinned** URL on IBM's own
GitHub organisation, verifies its SHA256 against the value recorded here and
in ``data/README.md``, and writes it — byte-for-byte, untouched — to the
canonical raw-data path from :mod:`harbor_vale.io_paths`.

Source (see data/README.md for full provenance):
    Publisher : IBM (Cognos Analytics / Watson Analytics sample data —
                "Telco Customer Churn", a fictional telco, 7043 customers).
    Mirror    : https://github.com/IBM/telco-customer-churn-on-icp4d
                (IBM's own GitHub org), Apache-2.0 licensed.
    File      : data/Telco-Customer-Churn.csv, added in a single commit and
                never modified since (verified via the GitHub commits API on
                2026-09-14). The URL below is pinned to that exact commit
                SHA, not to a branch — an immutable reference where one is
                available (PROJECT_PLAN.md §Phase 2 "prefer an immutable
                URL"). Because GitHub does not provide a cryptographic
                content-addressed URL, the SHA256 check below is the real
                integrity lock: it is verified on every run, both after a
                fresh download and against a file already on disk.

Usage:
    python scripts/download_data.py            # download if missing/invalid
    python scripts/download_data.py --force    # re-download unconditionally

Exit codes: 0 on success (file present and hash-verified), 1 on any network,
HTTP, or hash-mismatch failure. Errors are printed to stderr with enough
detail to diagnose (URL, HTTP status, expected vs. actual hash) but never
include credentials — this script needs none.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

# --- make the project importable without an install step -------------------
_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from harbor_vale.io_paths import DATA_RAW, RAW_TELCO_CHURN_CSV  # noqa: E402

# Immutable: raw.githubusercontent.com/<org>/<repo>/<commit-sha>/<path>
# Commit 1fd6fd7 is the *only* commit that has ever touched this file
# (`git log --follow` on IBM/telco-customer-churn-on-icp4d, verified
# 2026-09-14 via the GitHub commits API) — added once, never edited.
SOURCE_URL = (
    "https://raw.githubusercontent.com/IBM/telco-customer-churn-on-icp4d/"
    "1fd6fd70906479be1712e64cfc0ea89f58466629/data/Telco-Customer-Churn.csv"
)

# Locked at acquisition time (2026-09-14). Recorded independently in
# data/README.md — the two must agree; this is *the* integrity gate.
EXPECTED_SHA256 = (
    "16320c9c1ec72448db59aa0a26a0b95401046bef5d02fd3aeb906448e3055e91"
)

DEST_PATH: Path = RAW_TELCO_CHURN_CSV


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, dest: Path) -> None:
    import requests  # already a transitive dependency of crewai; no new pin

    try:
        response = requests.get(url, timeout=30)
    except requests.RequestException as exc:
        raise SystemExit(f"ERROR: network failure downloading {url}: {exc}") from exc

    if response.status_code != 200:
        raise SystemExit(
            f"ERROR: unexpected HTTP status {response.status_code} for {url} "
            f"(expected 200). The dataset may have moved or been removed."
        )

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.with_suffix(dest.suffix + ".part")
    tmp_path.write_bytes(response.content)
    tmp_path.replace(dest)  # atomic on the same filesystem


def acquire(force: bool = False) -> Path:
    """Ensure the raw dataset is present at :data:`DEST_PATH` with a verified hash.

    Idempotent: if the file already exists and its SHA256 already matches
    :data:`EXPECTED_SHA256`, no network request is made unless ``force=True``.
    Fails loudly (raises ``SystemExit``) on any network/HTTP/hash problem —
    never silently accepts changed or corrupted bytes.
    """
    if DEST_PATH.exists() and not force:
        actual = _sha256_of(DEST_PATH)
        if actual == EXPECTED_SHA256:
            print(f"OK: {DEST_PATH} already present, SHA256 verified.")
            return DEST_PATH
        print(
            f"NOTICE: {DEST_PATH} exists but its SHA256 does not match "
            f"(found {actual}, expected {EXPECTED_SHA256}). Re-downloading.",
            file=sys.stderr,
        )

    print(f"Downloading {SOURCE_URL} -> {DEST_PATH}")
    _download(SOURCE_URL, DEST_PATH)

    actual = _sha256_of(DEST_PATH)
    if actual != EXPECTED_SHA256:
        DEST_PATH.unlink(missing_ok=True)
        raise SystemExit(
            "ERROR: SHA256 mismatch after download — refusing to keep the "
            f"file.\n  expected: {EXPECTED_SHA256}\n  actual:   {actual}\n"
            "The upstream file may have changed. Do NOT silently accept "
            "this — verify the source and update EXPECTED_SHA256 only after "
            "confirming the change is legitimate."
        )

    print(f"OK: downloaded and verified SHA256 {actual}")
    return DEST_PATH


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-download even if a hash-valid copy already exists",
    )
    args = parser.parse_args()

    DATA_RAW.mkdir(parents=True, exist_ok=True)
    acquire(force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
