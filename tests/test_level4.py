import os
import sys

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
    slots = [
        {
            "id": f"t{i}",
            "provider": "Dr Ade",
            "start": f"2026-12-{10 + i}T09:00:00Z",
            "end": f"2026-12-{10 + i}T09:30:00Z",
        }
        for i in range(4)
    ]

    with httpx.Client(base_url=BASE_URL, headers=HEADERS, timeout=10) as c:
        c.post("/reset", json={"slots": slots}).raise_for_status()

        # Idempotency: a retried request returns the original booking
        body = {"slot_id": "t0", "name": "Ada Obi", "email": "Ada@Example.com"}
        r1 = c.post("/bookings", json=body, headers={"Idempotency-Key": "key-1"})
        r2 = c.post("/bookings", json=body, headers={"Idempotency-Key": "key-1"})
        check("first keyed request returns 201", r1.status_code, 201)
        check("retry returns 201", r2.status_code, 201)
        check("retry returns the same booking id", r2.json()["id"], r1.json()["id"])

        # Same key, different body: must be rejected
        r3 = c.post(
            "/bookings",
            json={"slot_id": "t1", "name": "Ada Obi", "email": "ada@example.com"},
            headers={"Idempotency-Key": "key-1"},
        )
        check("same key with different body returns 422", r3.status_code, 422)

        # Pagination: Ada now has 4 bookings in total
        for sid in ["t1", "t2", "t3"]:
            c.post(
                "/bookings",
                json={"slot_id": sid, "name": "Ada Obi", "email": "ada@example.com"},
            ).raise_for_status()

        page1 = c.get("/bookings", params={"email": "ADA@example.com", "limit": 2}).json()
        check("page 1 has 2 bookings", len(page1["bookings"]), 2)
        check("page 1 has a next_cursor", page1["next_cursor"] is not None, True)

        page2 = c.get(
            "/bookings",
            params={"email": "ada@example.com", "limit": 2, "cursor": page1["next_cursor"]},
        ).json()
        check("page 2 has 2 bookings", len(page2["bookings"]), 2)
        check("last page has next_cursor null", page2["next_cursor"], None)

        ids = [b["id"] for b in page1["bookings"] + page2["bookings"]]
        check("pages contain 4 distinct bookings", len(set(ids)), 4)
        check("no duplicate booking from the retry", len(ids), 4)

        # Invalid inputs
        check("limit=0 returns 400", c.get("/bookings", params={"email": "ada@example.com", "limit": 0}).status_code, 400)
        check("limit=51 returns 400", c.get("/bookings", params={"email": "ada@example.com", "limit": 51}).status_code, 400)
        check("missing email returns 400", c.get("/bookings").status_code, 400)

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        sys.exit(1)
    print("All Level 4 checks passed")


if __name__ == "__main__":
    main()