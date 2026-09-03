"""Onboarding seed: register a demo user and upload the sample corpus.

Usage: cd apps/api && uv run python scripts/seed.py [--api http://localhost:8000]
"""

import argparse
import sys
from pathlib import Path

import httpx

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
CORPUS = ["ml_syllabus.md", "assignment4.txt", "schedule.csv"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--email", default="demo@secondbrain.dev")
    parser.add_argument("--password", default="demo-password-1")
    args = parser.parse_args()

    client = httpx.Client(base_url=args.api, timeout=60)
    register = client.post(
        "/auth/register",
        json={
            "email": args.email,
            "password": args.password,
            "display_name": "Demo User",
        },
    )
    if register.status_code == 409:
        print("user exists — logging in")
        client.post("/auth/login", json={"email": args.email, "password": args.password})
    elif register.status_code != 201:
        print(f"register failed: {register.status_code} {register.text[:200]}")
        return 1

    files = [
        ("files", (name, (FIXTURES / name).read_bytes(), "application/octet-stream"))
        for name in CORPUS
        if (FIXTURES / name).exists()
    ]
    response = client.post("/inbox/upload", files=files)
    if response.status_code != 201:
        print(f"upload failed: {response.status_code} {response.text[:200]}")
        return 1
    for item in response.json():
        state = "duplicate" if item["duplicate"] else "queued"
        print(f"  {item['filename']}: {state}")
    print("Seed complete — start the worker (make workers) to process the corpus.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
