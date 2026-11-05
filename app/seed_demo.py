import os

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "http://localhost:8000"
HEADERS = {"X-API-Key": os.environ["API_KEY"]}

PROVIDERS = ["Dr Ade", "Dr Sarah"]
slots = [
    {
        "id": f"demo{i}",
        "provider": PROVIDERS[i % 2],
        "start": f"2026-12-{10 + i}T09:00:00Z",
        "end": f"2026-12-{10 + i}T09:30:00Z",
    }
    for i in range(10)
]

with httpx.Client(base_url=BASE_URL, headers=HEADERS, timeout=10) as client:
    client.post("/reset", json={"slots": slots}).raise_for_status()

    # Book the first five. Each uses a different email so the rate limit isn't hit.
    for i in range(5):
        r = client.post("/bookings", json={
            "slot_id": f"demo{i}",
            "name": f"Demo Patient {i + 1}",
            "email": f"demo{i + 1}@example.com",
        })
        r.raise_for_status()
        print(f"Booked demo{i}, reference: {r.json()['id']}")

print("Done: demo0 to demo4 are booked, demo5 to demo9 are free.")