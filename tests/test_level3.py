import concurrent.futures
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "http://localhost:8000"
HEADERS = {"X-API-Key": os.environ["API_KEY"]}
ONE_SLOT = [{
    "id": "s1",
    "provider": "Dr Ade",
    "start": "2026-12-10T09:00:00Z",
    "end": "2026-12-10T09:30:00Z",
}]

failures = []


def check(label, got, expected):
    ok = got == expected
    print("PASS" if ok else "FAIL", "-", label, f"(got {got}, expected {expected})")
    if not ok:
        failures.append(label)


def reset(client, slots):
    r = client.post("/reset", json={"slots": slots})
    assert r.status_code == 200, r.text


def main():
    with httpx.Client(base_url=BASE_URL, headers=HEADERS, timeout=10) as client:

        # Cancellation
        reset(client, ONE_SLOT)
        r = client.post("/bookings", json={"slot_id": "s1", "name": "Ada Obi", "email": "ada@example.com"})
        check("book s1", r.status_code, 201)
        booking_id = r.json()["id"]

        r = client.delete(f"/bookings/{booking_id}")
        check("cancel booking", r.status_code, 200)
        check("cancelled status is set", r.json().get("status"), "cancelled")

        r = client.delete(f"/bookings/{booking_id}")
        check("cancel the same booking again", r.status_code, 409)

        r = client.delete("/bookings/00000000-0000-0000-0000-000000000000")
        check("cancel an unknown booking", r.status_code, 404)

        r = client.post("/bookings", json={"slot_id": "s1", "name": "Ben", "email": "ben@example.com"})
        check("rebook the freed slot", r.status_code, 201)

    # Concurrency: 20 people try to book one slot at the same moment
    with httpx.Client(base_url=BASE_URL, headers=HEADERS, timeout=10) as client:
        reset(client, ONE_SLOT)

    def book(i):
        r = httpx.post(
            f"{BASE_URL}/bookings",
            headers=HEADERS,
            json={"slot_id": "s1", "name": f"Patient {i}", "email": f"patient{i}@example.com"},
            timeout=10,
        )
        return r.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        codes = list(pool.map(book, range(20)))

    check("exactly one of 20 simultaneous bookings succeeds", codes.count(201), 1)
    check("the other 19 get 409", codes.count(409), 19)

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        sys.exit(1)
    print("All Level 3 checks passed")


if __name__ == "__main__":
    main()