import secrets
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import API_KEY
from app.database import SessionLocal
from app.models import Booking, IdempotencyKey, RateLimitAttempt, Slot

app = FastAPI()


# Every error body must look like {"error": "..."}, as the spec requires
@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Level 2 check, applied to every endpoint
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


@app.post("/reset", dependencies=[Depends(require_api_key)])
async def reset(request: Request, db: Session = Depends(get_db)):
    body = await read_json(request)
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
async def create_booking(request: Request, db: Session = Depends(get_db)):
    body = await read_json(request)
    slot_id = str(body.get("slot_id", "")).strip()
    name = str(body.get("name", "")).strip()
    email = str(body.get("email", "")).strip().lower()

    # Level 2 will add the full validation rules here
    if db.get(Slot, slot_id) is None:
        raise HTTPException(status_code=404, detail="slot not found")

    booking = Booking(slot_id=slot_id, name=name, email=email, status="confirmed")
    db.add(booking)
    try:
        db.commit()
    except IntegrityError:
        # Level 3: the unique index rejects a second confirmed booking
        db.rollback()
        raise HTTPException(status_code=409, detail="slot already booked")
    db.refresh(booking)
    return booking_out(booking)


@app.get("/bookings/{booking_id}", dependencies=[Depends(require_api_key)])
def get_booking(booking_id: str, db: Session = Depends(get_db)):
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="booking not found")
    return booking_out(booking)