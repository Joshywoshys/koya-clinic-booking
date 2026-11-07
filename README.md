# Clinic Booking API

A booking API and web page for a clinic. Patients see available appointment slots, book one, look up their bookings by email, reschedule, and cancel.

**Live:** https://koya-clinic-booking-rmgs.onrender.com

## Tech stack

- **Backend:** Python, FastAPI
- **Database:** PostgreSQL (hosted on Neon)
- **Frontend:** HTML, CSS and JavaScript, served by the same app
- **Hosting:** Render
- **Development:** GitHub Codespaces

## Project structure
- app/
- config.py reads DATABASE_URL and API_KEY from environment variables
- database.py database engine and session setup
- models.py tables: slots, bookings, idempotency keys, rate-limit attempts
- main.py API endpoints from the specification
- page.py web page routes; these call the API on the server with the key
- static/ index.html, style.css, script.js
- tests/ one test script per level
- requirements.txt
- .env.example template for required environment variables


## Running locally

1. Create a PostgreSQL database (for example, on Neon).
2. Copy `.env.example` to `.env` and set:
   - `DATABASE_URL`, using the form `postgresql+psycopg://user:password@host/dbname?sslmode=require`
   - `API_KEY`, a long random string, for example from `python -c "import secrets; print(secrets.token_urlsafe(32))"`
3. Install dependencies and start the server:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   uvicorn app.main:app --reload --port 8000
   ```

4. Open http://localhost:8000 for the web page.

## API

All endpoints except the web page require the `X-API-Key` header.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/reset` | Replace all slots and clear bookings |
| GET | `/slots` | List slots, optionally filtered by `provider` |
| POST | `/bookings` | Create a booking (supports `Idempotency-Key`) |
| GET | `/bookings/{id}` | Get one booking |
| DELETE | `/bookings/{id}` | Cancel a booking |
| GET | `/bookings?email=...` | List a person's bookings, paginated with `limit` and `cursor` |

Errors return `{"error": "<message>"}`.

Example:

```bash
curl -X POST http://localhost:8000/bookings \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"slot_id":"s1","name":"Ada Obi","email":"ada@example.com"}'
```

## How the five levels are met

- **Level 1, slots and bookings:** the endpoints above, with data stored in PostgreSQL so it persists between requests.
- **Level 2, authentication and validation:** every endpoint checks the API key in constant time. Bookings must include a name, a valid email and an existing slot that hasn't started. Names and emails are trimmed, and emails are lowercased.
- **Level 3, no double booking:** a unique database index on `slot_id`, applied only to confirmed bookings. Two simultaneous requests cannot both succeed. Cancelling frees the slot.
- **Level 4, retries and pagination:** `Idempotency-Key` values and a hash of the request body are stored. A repeated request returns the original response; the same key with a different body returns 422. Pagination uses a database sequence number as the cursor.
- **Level 5, rate limiting:** each attempt that includes an email is recorded, including failed ones. More than 5 attempts per minute returns 429 with `Retry-After`. A per-email lock keeps the count accurate under concurrent requests.

## Design notes

- **Rescheduling** is done on the page: it books the new slot first and cancels the old booking only after that succeeds.
- **Booking references** are short codes such as `KC-7K4P9QXA`, so patients can read and type them.
- **The web page's routes** (`/page/...`) are public, because a browser can't keep a secret. They call the protected API endpoints on the server, so the key is never sent to the browser. The specification's endpoints still require the key.

## Tests

With the server running and `API_KEY` set in the environment:

```bash
python tests/test_level5.py
python tests/test_level3.py
python tests/test_level4.py
```

Each script resets the data first. `test_level3.py` sends 20 simultaneous bookings and expects exactly one to succeed.
