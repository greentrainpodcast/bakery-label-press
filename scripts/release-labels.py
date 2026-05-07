"""Release-labels orchestrator — runs in GitHub Actions on repository_dispatch.

Steps:
  1. Refresh OAuth access token from the stored refresh token.
  2. Read the configured tab from the Sheet via Sheets API → CSV.
  3. Call scripts/build-labels.py to render dist/labels.html + dist/labels.pdf.
  4. Upload the PDF and a CSV snapshot to the Drive folder.
  5. Append a result row to the release_history tab in the same Sheet.

On failure: still appends a row to release_history with status=failed, so the
client can see what happened from inside the Sheet without opening GitHub.

Required env vars (all set by .github/workflows/build-labels.yml):
  REQUEST_ID, SHEET_ID, TAB, REQUESTED_BY
  GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, GOOGLE_OAUTH_REFRESH_TOKEN
  LULLY_DRIVE_FOLDER_ID
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
INPUT_CSV = ROOT / "data" / "_release-input.csv"
DIST = ROOT / "dist"

REQUIRED_ENV = (
    "REQUEST_ID", "SHEET_ID", "TAB", "REQUESTED_BY",
    "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET",
    "GOOGLE_OAUTH_REFRESH_TOKEN", "LULLY_DRIVE_FOLDER_ID",
)

# ----- helpers -----

def _env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"Missing env var {name}")
    return v


def _refresh_access_token() -> str:
    r = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id":     _env("GOOGLE_OAUTH_CLIENT_ID"),
            "client_secret": _env("GOOGLE_OAUTH_CLIENT_SECRET"),
            "refresh_token": _env("GOOGLE_OAUTH_REFRESH_TOKEN"),
            "grant_type":    "refresh_token",
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _read_sheet_as_csv(token: str, sheet_id: str, tab: str) -> str:
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{tab}"
    r = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        params={"majorDimension": "ROWS", "valueRenderOption": "UNFORMATTED_VALUE"},
        timeout=30,
    )
    r.raise_for_status()
    rows = r.json().get("values", [])
    if not rows:
        raise RuntimeError(f"Tab {tab!r} is empty")
    out = io.StringIO()
    csv.writer(out).writerows(rows)
    return out.getvalue()


def _upload_to_drive(token: str, folder_id: str, name: str,
                     content_bytes: bytes, mime_type: str) -> dict:
    metadata = {"name": name, "parents": [folder_id]}
    boundary = "-------lully-labels-boundary-7e3f2d"
    body = (
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        + json.dumps(metadata)
        + f"\r\n--{boundary}\r\n"
        f"Content-Type: {mime_type}\r\n\r\n"
    ).encode("utf-8") + content_bytes + f"\r\n--{boundary}--".encode("utf-8")

    r = requests.post(
        "https://www.googleapis.com/upload/drive/v3/files",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/related; boundary={boundary}",
        },
        params={"uploadType": "multipart", "fields": "id,webViewLink,name"},
        data=body,
        timeout=120,
    )
    r.raise_for_status()
    return r.json()


def _append_history_row(token: str, sheet_id: str, row: list) -> None:
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}"
        "/values/release_history!A1:append"
    )
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
        json={"values": [row]},
        timeout=30,
    )
    r.raise_for_status()


def _count_active(csv_text: str) -> int:
    return sum(
        1 for r in csv.DictReader(io.StringIO(csv_text))
        if (r.get("active") or "").strip().lower() in {"x", "true", "1", "y", "yes"}
    )


# ----- main -----

def main() -> int:
    for v in REQUIRED_ENV:
        _env(v)
    sheet_id     = os.environ["SHEET_ID"]
    tab          = os.environ["TAB"]
    request_id   = os.environ["REQUEST_ID"]
    requested_by = os.environ["REQUESTED_BY"]
    folder_id    = os.environ["LULLY_DRIVE_FOLDER_ID"]

    started_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    token = _refresh_access_token()

    try:
        csv_text = _read_sheet_as_csv(token, sheet_id, tab)
        INPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
        INPUT_CSV.write_text(csv_text, encoding="utf-8")
        num_active = _count_active(csv_text)

        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build-labels.py"),
             "--source", str(INPUT_CSV), "--pdf"],
            check=True,
        )

        pdf_path = DIST / "labels.pdf"
        if not pdf_path.exists():
            raise RuntimeError("build-labels.py did not produce dist/labels.pdf")

        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
        pdf = _upload_to_drive(token, folder_id, f"lully-labels-{stamp}.pdf",
                               pdf_path.read_bytes(), "application/pdf")
        snap = _upload_to_drive(token, folder_id, f"lully-labels-{stamp}.csv",
                                csv_text.encode("utf-8"), "text/csv")

        _append_history_row(token, sheet_id, [
            started_at,
            requested_by,
            pdf.get("webViewLink", ""),
            snap.get("webViewLink", ""),
            num_active,
            "success",
            f"request_id={request_id}",
        ])
        print(f"✓ Released {pdf.get('name')} ({num_active} labels)")
        return 0

    except Exception as e:  # noqa: BLE001 — we want to log every failure
        traceback.print_exc()
        try:
            _append_history_row(token, sheet_id, [
                started_at,
                requested_by,
                "",
                "",
                0,
                "failed",
                f"request_id={request_id}; error={type(e).__name__}: {e}"[:500],
            ])
        except Exception:
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
