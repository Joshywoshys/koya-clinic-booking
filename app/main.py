import base64
import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import API_KEY
from app.database import SessionLocal
from app.models import Booking, IdempotencyKey, RateLimitAttempt, Slot

app = FastAPI()

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
RATE_LIMIT_MAX = 5
RATE_LIMIT_WINDOW = timedelta(minutes=1)


# Every error body must look like {"error": "..."}, as the spec requires
@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail},
        headers=getattr(exc, "headers", None),
    )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Level 2: every endpoint requires the API key
def require_api_key(x_api_key: str | None = Header(default=None)):
    if x_api_key is None or not secrets.compare_digest(
        x_api_key.encode(), API_KEY.encode()
    ):
        raise HTTPException(status_code=401, detail="missing or invalid API key")


# Read the body ourselves so bad input returns the spec's 400, not FastAPI's 422
async def read_json(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")
    return body


# Async dependency: reads the body on the event loop, then hands it to a sync endpoint
async def get_body(request: Request) -> dict:
    return await read_json(request)


def parse_time(value) -> datetime:
    if not isinstance(value, str):
        raise ValueError("time must be a string")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def booking_out(b: Booking) -> dict:
    return {
        "id": b.id,
        "slot_id": b.slot_id,
        "name": b.name,
        "email": b.email,
        "status": b.status,
        "created_at": iso(b.created_at),
    }


def check_rate_limit(db: Session, email: str) -> None:
    """Level 5: at most 5 attempts per email per minute. Every attempt is recorded,
    including failed ones, so the count lives in the database and survives restarts."""
    # Serialise attempts for the same email so two requests can't both slip under the limit
    db.execute(select(func.pg_advisory_xact_lock(func.hashtext(email))))

    now = datetime.now(timezone.utc)
    window_start = now - RATE_LIMIT_WINDOW
    recent = db.scalars(
        select(RateLimitAttempt.attempted_at)
        .where(RateLimitAttempt.email == email, RateLimitAttempt.attempted_at > window_start)
        .order_by(RateLimitAttempt.attempted_at)
    ).all()

    if len(recent) >= RATE_LIMIT_MAX:
        # Wait until the oldest attempt in the window expires
        retry_after = int((recent[0] + RATE_LIMIT_WINDOW - now).total_seconds()) + 1
        db.rollback()
        raise HTTPException(
            status_code=429,
            detail="too many booking attempts for this email, try again later",
            headers={"Retry-After": str(max(1, retry_after))},
        )

    db.add(RateLimitAttempt(email=email, attempted_at=now))
    db.commit()


@app.post("/reset", dependencies=[Depends(require_api_key)])
def reset(body: dict = Depends(get_body), db: Session = Depends(get_db)):
    raw_slots = body.get("slots")
    if not isinstance(raw_slots, list):
        raise HTTPException(status_code=400, detail="slots must be a list")

    new_slots = []
    for raw in raw_slots:
        try:
            new_slots.append(
                Slot(
                    id=str(raw["id"]),
                    provider=str(raw["provider"]),
                    start=parse_time(raw["start"]),
                    end=parse_time(raw["end"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            raise HTTPException(
                status_code=400, detail="each slot needs id, provider, start and end"
            )

    # Bookings reference slots, so they must be deleted first
    db.execute(delete(RateLimitAttempt))
    db.execute(delete(IdempotencyKey))
    db.execute(delete(Booking))
    db.execute(delete(Slot))
    db.add_all(new_slots)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="slot ids must be unique")
    return {"ok": True, "slots": len(new_slots)}


@app.get("/slots", dependencies=[Depends(require_api_key)])
def list_slots(provider: str | None = None, db: Session = Depends(get_db)):
    query = select(Slot).order_by(Slot.start, Slot.id)
    if provider is not None:
        query = query.where(Slot.provider == provider)
    slots = db.scalars(query).all()

    booked = set(
        db.scalars(select(Booking.slot_id).where(Booking.status == "confirmed")).all()
    )
    return {
        "slots": [
            {
                "id": s.id,
                "provider": s.provider,
                "start": iso(s.start),
                "end": iso(s.end),
                "available": s.id not in booked,
            }
            for s in slots
        ]
    }


@app.post("/bookings", status_code=201, dependencies=[Depends(require_api_key)])
def create_booking(
    body: dict = Depends(get_body),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    slot_id = body.get("slot_id")
    name = body.get("name")
    email = body.get("email")

    # Level 5 counts every attempt that names an email, including ones that fail validation
    if isinstance(email, str) and email.strip():
        check_rate_limit(db, email.strip().lower())

    # Level 2: required fields must be non-empty strings
    if not all(isinstance(v, str) for v in (slot_id, name, email)):
        raise HTTPException(status_code=400, detail="slot_id, name and email are required")

    slot_id = slot_id.strip()
    name = name.strip()
    email = email.strip().lower()

    if not slot_id or not name or not email:
        raise HTTPException(status_code=400, detail="slot_id, name and email are required")
    if not EMAIL_PATTERN.match(email):
        raise HTTPException(status_code=400, detail="email is not valid")

    # Level 4: fingerprint the request so reusing a key with a different body is detected
    request_hash = hashlib.sha256(json.dumps([slot_id, name, email]).encode()).hexdigest()

    if idempotency_key:
        saved = db.get(IdempotencyKey, idempotency_key)
        if saved is not None:
            if saved.request_hash != request_hash:
                raise HTTPException(
                    status_code=422,
                    detail="Idempotency-Key was already used with a different request",
                )
            return JSONResponse(status_code=saved.status_code, content=saved.response_body)

    slot = db.get(Slot, slot_id)
    if slot is None:
        raise HTTPException(status_code=404, detail="slot not found")
    if slot.start <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="slot has already started")

    booking = Booking(slot_id=slot_id, name=name, email=email, status="confirmed")
    db.add(booking)
    try:
        db.commit()
    except IntegrityError:
        # Level 3: the unique index rejects a second confirmed booking
        db.rollback()
        raise HTTPException(status_code=409, detail="slot already booked")
    db.refresh(booking)
    response = booking_out(booking)

    if idempotency_key:
        db.add(
            IdempotencyKey(
                key=idempotency_key,
                request_hash=request_hash,
                status_code=201,
                response_body=response,
            )
        )
        db.commit()
    return response


@app.get("/bookings", dependencies=[Depends(require_api_key)])
def list_bookings(
    email: str | None = None,
    limit: str = "10",
    cursor: str | None = None,
    db: Session = Depends(get_db),
):
    if email is None or not email.strip():
        raise HTTPException(status_code=400, detail="email is required")
    email = email.strip().lower()

    if not limit.isdigit() or not (1 <= int(limit) <= 50):
        raise HTTPException(status_code=400, detail="limit must be an integer from 1 to 50")
    page_size = int(limit)

    # The cursor encodes the seq of the last booking on the previous page
    after = 0
    if cursor is not None:
        try:
            after = int(base64.urlsafe_b64decode(cursor).decode())
        except Exception:
            raise HTTPException(status_code=400, detail="invalid cursor")

    rows = db.scalars(
        select(Booking)
        .where(Booking.email == email, Booking.seq > after)
        .order_by(Booking.seq)
        .limit(page_size + 1)
    ).all()

    page = rows[:page_size]
    next_cursor = None
    if len(rows) > page_size:
        next_cursor = base64.urlsafe_b64encode(str(page[-1].seq).encode()).decode()

    return {"bookings": [booking_out(b) for b in page], "next_cursor": next_cursor}


@app.get("/bookings/{booking_id}", dependencies=[Depends(require_api_key)])
def get_booking(booking_id: str, db: Session = Depends(get_db)):
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="booking not found")
    return booking_out(booking)


@app.delete("/bookings/{booking_id}", dependencies=[Depends(require_api_key)])
def cancel_booking(booking_id: str, db: Session = Depends(get_db)):
    result = db.execute(
        update(Booking)
        .where(Booking.id == booking_id, Booking.status == "confirmed")
        .values(status="cancelled")
    )
    db.commit()

    if result.rowcount == 0:
        if db.get(Booking, booking_id) is None:
            raise HTTPException(status_code=404, detail="booking not found")
        raise HTTPException(status_code=409, detail="booking already cancelled")

    return booking_out(db.get(Booking, booking_id))



from app.page import router as page_router

app.include_router(page_router)