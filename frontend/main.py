"""Minimal FastAPI proxy for a deployed A2A agent with Registered User Verification."""

import os
import uuid
import datetime
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

RESOURCE = os.environ["AGENT_ENGINE_RESOURCE_NAME"]
AGENT_DIRECTORY = os.environ.get("AGENT_DIRECTORY", "app")
LOCATION = RESOURCE.split("/locations/")[1].split("/")[0]

A2A_BASE = (
    f"https://{LOCATION}-aiplatform.googleapis.com/reasoningEngines/v1/"
    f"{RESOURCE}/api/a2a/{AGENT_DIRECTORY}"
)
A2A_CARD_URL = f"{A2A_BASE}/.well-known/agent-card.json"
_A2UI_MIME = "application/json+a2ui"

_creds, _ = google.auth.default(
    scopes=["https://www.googleapis.com/auth/cloud-platform"]
)

def _auth_headers() -> dict[str, str]:
    _creds.refresh(google.auth.transport.requests.Request())
    return {
        "Authorization": f"Bearer {_creds.token}",
        "Content-Type": "application/json",
    }

# Registered Users Database (Firestore with in-memory fallback)
FIRESTORE_PROJECT = os.environ.get("FIRESTORE_PROJECT", "qwiklabs-gcp-02-6a284814c841")
_firestore_db = None
try:
    from google.cloud import firestore
    _firestore_db = firestore.Client(project=FIRESTORE_PROJECT)
except Exception:
    pass

# Seed default demo account
_local_users = {
    "alex.runner@example.com": {
        "email": "alex.runner@example.com",
        "name": "Alex Runner",
        "password": "fitness2026",
    }
}

app = FastAPI()

@app.exception_handler(Exception)
async def _json_errors(request: Request, exc: Exception):
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

import json
import re

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


# --- USER AUTHENTICATION & REGISTRATION ENDPOINTS ---

@app.post("/auth/register")
async def register_user(req: Request):
    body = await req.json()
    email = body.get("email", "").strip().lower()
    password = body.get("password", "").strip()
    name = body.get("name", "").strip() or email.split("@")[0]

    if not email or not password:
        return JSONResponse(status_code=400, content={"error": "Email and password are required."})

    # Check if user exists in Firestore
    if _firestore_db:
        try:
            doc_ref = _firestore_db.collection("app_users").document(email)
            doc = doc_ref.get()
            if doc.exists:
                return JSONResponse(status_code=400, content={"error": "This email is already registered! Please sign in instead."})
            
            user_data = {
                "email": email,
                "name": name,
                "password": password,
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }
            doc_ref.set(user_data)
            return JSONResponse({"success": True, "message": "Registration successful!", "user": {"email": email, "name": name}})
        except Exception as e:
            pass

    # Fallback local store check
    if email in _local_users:
        return JSONResponse(status_code=400, content={"error": "This email is already registered! Please sign in instead."})
    
    _local_users[email] = {"email": email, "name": name, "password": password}
    return JSONResponse({"success": True, "message": "Registration successful!", "user": {"email": email, "name": name}})


@app.post("/auth/login")
async def login_user(req: Request):
    body = await req.json()
    email = body.get("email", "").strip().lower()
    password = body.get("password", "").strip()

    if not email or not password:
        return JSONResponse(status_code=400, content={"error": "Email and password are required."})

    # Verify user in Firestore
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
            if user_data.get("password") != password:
                return JSONResponse(status_code=401, content={"error": "Incorrect password. Please check your password and try again."})

            return JSONResponse({
                "success": True,
                "user": {"email": email, "name": user_data.get("name", email.split("@")[0])}
            })
        except Exception:
            pass

    # Fallback local store check
    if email not in _local_users:
        return JSONResponse(
            status_code=401,
            content={"error": f"No registered account found for '{email}'. Please click 'Register' to create your account first!"}
        )

    if _local_users[email]["password"] != password:
        return JSONResponse(status_code=401, content={"error": "Incorrect password. Please check your password and try again."})

    return JSONResponse({
        "success": True,
        "user": {"email": email, "name": _local_users[email]["name"]}
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
