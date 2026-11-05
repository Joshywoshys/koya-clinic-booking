from urllib.parse import quote

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from app.config import API_KEY, PORT

router = APIRouter(include_in_schema=False)

# The page's server calls the real API endpoints on this same app and adds the key here.
# The browser never sees the key.
api = httpx.AsyncClient(base_url=f"http://127.0.0.1:{PORT}", timeout=15)


async def forward(method: str, path: str, *, params=None, body=None, headers=None):
    request_headers = {"X-API-Key": API_KEY}
    if headers:
        request_headers.update(headers)
    resp = await api.request(method, path, params=params, json=body, headers=request_headers)
    try:
        content = resp.json()
    except ValueError:
        content = {"error": "internal server error"}
    response_headers = {}
    if "Retry-After" in resp.headers:
        response_headers["Retry-After"] = resp.headers["Retry-After"]
    return JSONResponse(status_code=resp.status_code, content=content, headers=response_headers)


@router.get("/")
def home():
    return FileResponse("app/static/index.html")


@router.get("/static/{filename}")
def static_file(filename: str):
    if filename not in {"style.css", "script.js"}:
        return JSONResponse(status_code=404, content={"error": "not found"})
    return FileResponse(f"app/static/{filename}")


@router.get("/page/slots")
async def page_slots(request: Request):
    return await forward("GET", "/slots", params=dict(request.query_params))


@router.get("/page/bookings")
async def page_list(request: Request):
    return await forward("GET", "/bookings", params=dict(request.query_params))


@router.get("/page/bookings/{booking_id}")
async def page_get(booking_id: str):
    return await forward("GET", f"/bookings/{quote(booking_id, safe='')}")


@router.delete("/page/bookings/{booking_id}")
async def page_cancel(booking_id: str):
    return await forward("DELETE", f"/bookings/{quote(booking_id, safe='')}")


@router.post("/page/bookings")
async def page_book(request: Request):
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "request body must be valid JSON"})
    headers = {}
    key = request.headers.get("Idempotency-Key")
    if key:
        headers["Idempotency-Key"] = key
    return await forward("POST", "/bookings", body=body, headers=headers)