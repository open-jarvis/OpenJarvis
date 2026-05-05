
from __future__ import annotations

import os
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow


SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/business.manage",
]


def main() -> None:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()

    if not client_id or not client_secret:
        raise SystemExit("Missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET.")

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    if not creds.refresh_token:
        raise SystemExit("No refresh token returned. Re-run with prompt=consent or remove old app grant in Google Account permissions.")

    out = Path("outputs/google-token")
    out.mkdir(parents=True, exist_ok=True)
    (out / "new-google-refresh-token.txt").write_text(creds.refresh_token, encoding="utf-8")

    print()
    print("[OK] New Google refresh token generated")
    print("[OK] Saved to outputs/google-token/new-google-refresh-token.txt")
    print()
    print("Set it permanently with:")
    print(f'setx GOOGLE_REFRESH_TOKEN "{creds.refresh_token}"')
    print()
    print("Then close PowerShell, open a new PowerShell window, and rerun Serena Google checks.")


if __name__ == "__main__":
    main()
