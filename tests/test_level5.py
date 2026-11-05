import os
import sys
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "http://localhost:8000"
HEADERS = {"X-API-Key": os.environ["API_KEY"]}
failures = []


def check(label, got, expected):
    ok = got == expected
    print("PASS" if ok else "FAIL", "-", label, f"(got {got}, expected {expected})")
    if not ok:
        failures.append(label)


def main():
    slots = [{
        "id": "r1",
        "provider": "Dr Ade",
        "start": "2026-12-10T09:00:00Z",
        "end": "2026-12-10T09:30:00Z",
    }]

    with httpx.Client(base_url=BASE_URL, headers=HEADERS, timeout=10) as c:
        c.post("/reset", json={"slots": slots}).raise_for_status()

        # Five attempts are allowed. Failed ones count too, so send invalid bodies.
        bad = {"slot_id": "r1", "name": "Spammer", "email": "spam@example.com", "x": 1}
        bad["name"] = ""
        codes = [c.post("/bookings", json=bad).status_code for _ in range(5)]
        check("first five attempts are not rate limited", codes, [400] * 5)

        r6 = c.post("/bookings", json=bad)
        check("sixth attempt returns 429", r6.status_code, 429)
        retry_after = r6.headers.get("Retry-After")
        check("Retry-After header is present", retry_after is not None, True)
        check(
            "Retry-After is a whole number of seconds",
            retry_after is not None and retry_after.isdigit(),
            True,
        )
        if retry_after and retry_after.isdigit():
            check("Retry-After is between 1 and 60", 1 <= int(retry_after) <= 60, True)

        # Other emails are not affected
        other = c.post(
            "/bookings",
            json={"slot_id": "r1", "name": "Ada", "email": "ada@example.com"},
        )
        check("a different email is not rate limited", other.status_code, 201)

        # Rate limit counts even valid attempts for the same email
        r_still = c.post(
            "/bookings",
            json={"slot_id": "r1", "name": "Spammer", "email": "spam@example.com"},
        )
        check("same email is still blocked", r_still.status_code, 429)

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        sys.exit(1)
    print("All Level 5 checks passed")


if __name__ == "__main__":
    main()