"""Enterprise FastAPI proxy for NovaSmart Fitness Coach with JWT Auth, Password Hashing, Rate Limiting & Security Headers."""

import os
import uuid
import time
import json
import re
import datetime
import hashlib
import hmac
import base64
import logging
from typing import Optional

import google.auth
import google.auth.transport.requests
import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.types import (
    AgentCard,
    FilePart,
    Message,
    Part,
    Role,
    TaskArtifactUpdateEvent,
    TaskStatusUpdateEvent,
    TextPart,
    TransportProtocol,
)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("novasmart")

RESOURCE = os.environ["AGENT_ENGINE_RESOURCE_NAME"]
AGENT_DIRECTORY = os.environ.get("AGENT_DIRECTORY", "app")
LOCATION = RESOURCE.split("/locations/")[1].split("/")[0]

A2A_BASE = (
    f"https://{LOCATION}-aiplatform.googleapis.com/reasoningEngines/v1/"
    f"{RESOURCE}/api/a2a/{AGENT_DIRECTORY}"
)
A2A_CARD_URL = f"{A2A_BASE}/.well-known/agent-card.json"
_A2UI_MIME = "application/json+a2ui"

# JWT Secret & Salt Configuration
JWT_SECRET = os.environ.get("JWT_SECRET", "novasmart-enterprise-secret-key-2026")

_creds, _ = google.auth.default(
    scopes=["https://www.googleapis.com/auth/cloud-platform"]
)

def _auth_headers() -> dict[str, str]:
    _creds.refresh(google.auth.transport.requests.Request())
    return {
        "Authorization": f"Bearer {_creds.token}",
        "Content-Type": "application/json",
    }

# Cryptographic Password Hashing (SHA-256 + HMAC Salt)
def hash_password(password: str) -> str:
    salt = "novasmart_salt_2026"
    return hashlib.sha256((password + salt).encode('utf-8')).hexdigest()

def verify_password(password: str, hashed: str) -> bool:
    return hmac.compare_digest(hash_password(password), hashed)

# Standard Library Cryptographic JWT Generator & Verifier
def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('utf-8')

def b64url_decode(data: str) -> bytes:
    padding = '=' * (4 - (len(data) % 4))
    return base64.urlsafe_b64encode(base64.urlsafe_b64decode(data + padding))

def create_jwt_token(email: str, name: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": email,
        "name": name,
        "iat": int(time.time()),
        "exp": int(time.time()) + 86400  # 24 hours
    }
    
    hdr_b64 = b64url_encode(json.dumps(header).encode('utf-8'))
    payload_b64 = b64url_encode(json.dumps(payload).encode('utf-8'))
    
    signature_input = f"{hdr_b64}.{payload_b64}".encode('utf-8')
    signature = hmac.new(JWT_SECRET.encode('utf-8'), signature_input, hashlib.sha256).digest()
    sig_b64 = b64url_encode(signature)
    
    return f"{hdr_b64}.{payload_b64}.{sig_b64}"

def decode_jwt_token(token: str) -> Optional[dict]:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        hdr_b64, payload_b64, sig_b64 = parts
        
        signature_input = f"{hdr_b64}.{payload_b64}".encode('utf-8')
        expected_sig = hmac.new(JWT_SECRET.encode('utf-8'), signature_input, hashlib.sha256).digest()
        
        if not hmac.compare_digest(b64url_encode(expected_sig), sig_b64):
            return None
            
        padding = '=' * (4 - (len(payload_b64) % 4))
        payload_bytes = base64.urlsafe_b64decode(payload_b64 + padding)
        payload = json.loads(payload_bytes.decode('utf-8'))
        
        if payload.get("exp", 0) < time.time():
            return None
            
        return payload
    except Exception:
        return None

# Registered Users Database (Firestore with local fallback)
FIRESTORE_PROJECT = os.environ.get("FIRESTORE_PROJECT", "qwiklabs-gcp-02-6a284814c841")
_firestore_db = None
try:
    from google.cloud import firestore
    _firestore_db = firestore.Client(project=FIRESTORE_PROJECT)
    logger.info("Connected to Google Cloud Firestore successfully.")
except Exception as e:
    logger.warning(f"Firestore initialization fallback: {e}")

_local_users = {
    "alex.runner@example.com": {
        "email": "alex.runner@example.com",
        "name": "Alex Runner",
        "password_hash": hash_password("fitness2026"),
    }
}

# Rate Limiter Store: IP -> list of timestamps
_rate_limit_store: dict[str, list[float]] = {}
RATE_LIMIT_WINDOW = 60  # seconds
MAX_REQUESTS_PER_WINDOW = 35

app = FastAPI(title="NovaSmart Fitness Coach Gateway API")

# Rate Limiting & Security Middleware
@app.middleware("http")
async def security_and_rate_limit_middleware(request: Request, call_next):
    start_time = time.time()
    client_ip = request.client.host if request.client else "unknown"

    # Enforce Rate Limiting
    if request.url.path.startswith("/chat") or request.url.path.startswith("/auth"):
        now = time.time()
        timestamps = _rate_limit_store.get(client_ip, [])
        valid_timestamps = [ts for ts in timestamps if now - ts < RATE_LIMIT_WINDOW]
        
        if len(valid_timestamps) >= MAX_REQUESTS_PER_WINDOW:
            return JSONResponse(
                status_code=429,
                content={"error": "Rate limit exceeded. Please wait a minute before sending more requests."}
            )
        
        valid_timestamps.append(now)
        _rate_limit_store[client_ip] = valid_timestamps

    response = await call_next(request)

    # Security Headers & Response Time
    process_time = (time.time() - start_time) * 1000
    response.headers["X-Process-Time"] = f"{process_time:.2f}ms"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"

    logger.info(f"{request.method} {request.url.path} - {response.status_code} [{process_time:.2f}ms]")
    return response


@app.exception_handler(Exception)
async def _json_errors(request: Request, exc: Exception):
    logger.error(f"Unhandled Exception: {exc}")
    return JSONResponse(
        status_code=200,
        content={
            "parts": [{"kind": "text", "text": f"Error: {type(exc).__name__}: {exc}"}]
        },
    )

_contexts: dict[str, str] = {}
_card: AgentCard | None = None

async def _get_card(client: httpx.AsyncClient) -> AgentCard:
    global _card
    if _card is None:
        resp = await client.get(A2A_CARD_URL)
        resp.raise_for_status()
        card = AgentCard(**resp.json())
        card.url = A2A_BASE
        _card = card
    return _card

_DATAPART_RE = re.compile(r"<a2a_datapart_json>(.*?)</a2a_datapart_json>", re.DOTALL)

def _extract_parts(parts: list) -> list[dict]:
    out: list[dict] = []
    for p in parts:
        root = getattr(p, "root", p)
        text = getattr(root, "text", None) if not isinstance(root, dict) else root.get("text")
        data = getattr(root, "data", None) if not isinstance(root, dict) else root.get("data")

        if text:
            if "<a2a_datapart_json>" in text:
                matches = _DATAPART_RE.findall(text)
                for m in matches:
                    try:
                        payload = json.loads(m.strip())
                        meta = payload.get("metadata") or {}
                        mime = meta.get("mimeType") if isinstance(meta, dict) else None
                        if mime == _A2UI_MIME and "data" in payload:
                            out.append({"kind": "a2ui", "data": payload["data"]})
                    except Exception:
                        pass
                clean_text = _DATAPART_RE.sub("", text).strip()
                if clean_text and not clean_text.startswith("Cannot add session to memory"):
                    out.append({"kind": "text", "text": clean_text})
            else:
                if not text.startswith("Cannot add session to memory"):
                    out.append({"kind": "text", "text": text})
        elif data is not None:
            meta = (getattr(root, "metadata", None) if not isinstance(root, dict) else root.get("metadata")) or {}
            mime = meta.get("mimeType") if isinstance(meta, dict) else None
            if mime == _A2UI_MIME:
                out.append({"kind": "a2ui", "data": data})
        elif isinstance(root, FilePart):
            uri = getattr(getattr(root, "file", None), "uri", None)
            if uri:
                out.append({"kind": "text", "text": uri})
    return out


# --- ENTERPRISE AUTHENTICATION ENDPOINTS ---

@app.post("/auth/register")
async def register_user(req: Request):
    body = await req.json()
    email = body.get("email", "").strip().lower()
    password = body.get("password", "").strip()
    name = body.get("name", "").strip() or email.split("@")[0]

    if not email or not password:
        return JSONResponse(status_code=400, content={"error": "Email and password are required."})

    hashed = hash_password(password)

    if _firestore_db:
        try:
            doc_ref = _firestore_db.collection("app_users").document(email)
            doc = doc_ref.get()
            if doc.exists:
                return JSONResponse(status_code=400, content={"error": "This email is already registered! Please sign in instead."})
            
            user_data = {
                "email": email,
                "name": name,
                "password_hash": hashed,
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }
            doc_ref.set(user_data)
            token = create_jwt_token(email, name)
            return JSONResponse({
                "success": True,
                "message": "Registration successful!",
                "token": token,
                "user": {"email": email, "name": name}
            })
        except Exception as e:
            logger.error(f"Firestore registration error: {e}")

    if email in _local_users:
        return JSONResponse(status_code=400, content={"error": "This email is already registered! Please sign in instead."})
    
    _local_users[email] = {"email": email, "name": name, "password_hash": hashed}
    token = create_jwt_token(email, name)
    return JSONResponse({
        "success": True,
        "message": "Registration successful!",
        "token": token,
        "user": {"email": email, "name": name}
    })


@app.post("/auth/login")
async def login_user(req: Request):
    body = await req.json()
    email = body.get("email", "").strip().lower()
    password = body.get("password", "").strip()

    if not email or not password:
        return JSONResponse(status_code=400, content={"error": "Email and password are required."})

    if _firestore_db:
        try:
            doc_ref = _firestore_db.collection("app_users").document(email)
            doc = doc_ref.get()
            if not doc.exists:
                return JSONResponse(
                    status_code=401,
                    content={"error": f"No registered account found for '{email}'. Please click 'Register' to create your account first!"}
                )
            
            user_data = doc.to_dict()
            stored_hash = user_data.get("password_hash") or hash_password(user_data.get("password", ""))
            
            if not verify_password(password, stored_hash):
                return JSONResponse(status_code=401, content={"error": "Incorrect password. Please check your password and try again."})

            token = create_jwt_token(email, user_data.get("name", email.split("@")[0]))
            return JSONResponse({
                "success": True,
                "token": token,
                "user": {"email": email, "name": user_data.get("name", email.split("@")[0])}
            })
        except Exception as e:
            logger.error(f"Firestore login error: {e}")

    if email not in _local_users:
        return JSONResponse(
            status_code=401,
            content={"error": f"No registered account found for '{email}'. Please click 'Register' to create your account first!"}
        )

    user_info = _local_users[email]
    stored_hash = user_info.get("password_hash") or hash_password(user_info.get("password", ""))

    if not verify_password(password, stored_hash):
        return JSONResponse(status_code=401, content={"error": "Incorrect password. Please check your password and try again."})

    token = create_jwt_token(email, user_info["name"])
    return JSONResponse({
        "success": True,
        "token": token,
        "user": {"email": email, "name": user_info["name"]}
    })


@app.post("/chat")
async def chat(req: Request):
    body = await req.json()
    message = body.get("message", "")
    user_id = body.get("user_id") or "web-user"
    parts: list[dict] = []

    async with httpx.AsyncClient(headers=_auth_headers(), timeout=120) as client:
        card = await _get_card(client)
        factory = ClientFactory(
            ClientConfig(
                supported_transports=[
                    TransportProtocol.jsonrpc,
                    TransportProtocol.http_json,
                ],
                httpx_client=client,
            )
        )
        a2a_client = factory.create(card)

        msg = Message(
            message_id=str(uuid.uuid4()),
            role=Role.user,
            parts=[Part(root=TextPart(text=message))],
            context_id=_contexts.get(user_id),
        )

        last_task = None
        async for event in a2a_client.send_message(msg):
            if not isinstance(event, tuple):
                continue
            task, update = event
            if task is not None:
                last_task = task
                if getattr(task, "context_id", None):
                    _contexts[user_id] = task.context_id

            if isinstance(update, TaskArtifactUpdateEvent):
                if getattr(update, "artifact", None) and getattr(update.artifact, "parts", None):
                    parts.extend(_extract_parts(update.artifact.parts))
            elif isinstance(update, TaskStatusUpdateEvent):
                msg_obj = getattr(update.status, "message", None) if getattr(update, "status", None) else None
                if msg_obj and getattr(msg_obj, "parts", None):
                    role = getattr(msg_obj, "role", None)
                    if role not in (Role.user, "user"):
                        parts.extend(_extract_parts(msg_obj.parts))

        if not parts and last_task is not None:
            history = getattr(last_task, "history", None) or []
            for hmsg in reversed(history):
                role = getattr(hmsg, "role", None)
                if role in (Role.agent, "agent"):
                    hparts = getattr(hmsg, "parts", None) or []
                    extracted = _extract_parts(hparts)
                    if extracted:
                        parts.extend(extracted)
                        break

            if not parts:
                for artifact in getattr(last_task, "artifacts", None) or []:
                    parts.extend(_extract_parts(artifact.parts))

    if not parts:
        parts = [{"kind": "text", "text": "(The agent didn't return a reply.)"}]
    return JSONResponse({"parts": parts})


app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
