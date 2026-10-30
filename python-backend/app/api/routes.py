import json
import logging
import smtplib
import secrets
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Annotated
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import get_db
from app.models.entities import (
    Conversation,
    Message,
    PasswordResetToken,
    User,
    UserSession,
    utc_now,
)
from app.schemas.api import (
    ChatRequest,
    ConversationCreate,
    ConversationOut,
    ConversationRename,
    Credentials,
    MessageOut,
    PasswordResetConfirm,
    PasswordResetRequest,
    UserOut,
)
from app.services.security import (
    get_current_session,
    get_current_user,
    hash_password,
    token_digest,
    verify_csrf_cookie,
    verify_password,
)

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)
Db = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentSession = Annotated[UserSession, Depends(get_current_session)]
_attempts: dict[str, list[float]] = {}


def check_auth_rate_limit(request: Request) -> None:
    address = request.client.host if request.client else "unknown"
    now = time.monotonic()
    attempts = [stamp for stamp in _attempts.get(address, []) if now - stamp < 60]
    if len(attempts) >= 10:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Try again shortly.")
    attempts.append(now)
    _attempts[address] = attempts


def set_session_cookies(response: Response, token: str, csrf_token: str) -> None:
    response.set_cookie(
        "louf_session",
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )
    response.set_cookie(
        "louf_csrf",
        csrf_token,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )


def new_user_session(db: Session, user: User) -> tuple[str, str]:
    token = secrets.token_urlsafe(48)
    csrf = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=token_digest(token),
            csrf_hash=token_digest(csrf),
            expires_at=datetime.now(timezone.utc)
            + timedelta(hours=settings.session_ttl_hours),
        )
    )
    db.commit()
    return token, csrf


def remove_expired_guest_accounts(db: Session) -> None:
    now = datetime.now(timezone.utc)
    for user in db.scalars(select(User).where(User.is_guest.is_(True))).all():
        if not any(
            session.expires_at.replace(tzinfo=timezone.utc) > now for session in user.sessions
        ):
            db.delete(user)
    db.commit()


def send_password_reset_email(email: str, token: str) -> None:
    if not settings.smtp_host or not settings.smtp_from_email:
        raise RuntimeError("SMTP_HOST and SMTP_FROM_EMAIL must be configured.")
    reset_url = f"{settings.frontend_base_url.rstrip('/')}/#reset_token={quote(token)}"
    message = EmailMessage()
    message["Subject"] = "Reset your LOUF AI password"
    message["From"] = settings.smtp_from_email
    message["To"] = email
    message.set_content(
        f"Use this link to reset your LOUF AI password. It expires in 30 minutes:\n\n{reset_url}\n\n"
        "If you did not request this, you can ignore this email."
    )
    if settings.smtp_use_tls:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
            client.starttls()
            if settings.smtp_username:
                client.login(settings.smtp_username, settings.smtp_password)
            client.send_message(message)
    else:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15) as client:
            if settings.smtp_username:
                client.login(settings.smtp_username, settings.smtp_password)
            client.send_message(message)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/auth/csrf")
def csrf_token(request: Request, response: Response, db: Db) -> dict[str, str]:
    session_token = request.cookies.get("louf_session")
    session = None
    if session_token:
        session = db.scalar(
            select(UserSession).where(UserSession.token_hash == token_digest(session_token))
        )
    if session and session.expires_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc):
        # The browser needs the CSRF value; keep only its digest in the database.
        csrf = request.cookies.get("louf_csrf")
        if csrf and token_digest(csrf) == session.csrf_hash:
            response.set_cookie(
                "louf_csrf",
                csrf,
                httponly=False,
                secure=settings.cookie_secure,
                samesite="lax",
                max_age=settings.session_ttl_hours * 3600,
                path="/",
            )
            return {"csrf_token": csrf}
    csrf = secrets.token_urlsafe(32)
    response.set_cookie(
        "louf_csrf",
        csrf,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=3600,
        path="/",
    )
    return {"csrf_token": csrf}


@router.post("/auth/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(
    data: Credentials,
    request: Request,
    response: Response,
    db: Db,
) -> User:
    verify_csrf_cookie(request)
    check_auth_rate_limit(request)
    email = str(data.email).strip().lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists.")
    user = User(email=email, password_hash=hash_password(data.password))
    db.add(user)
    db.flush()
    token, csrf = new_user_session(db, user)
    set_session_cookies(response, token, csrf)
    return user


@router.post("/auth/guest", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_guest_session(
    request: Request,
    response: Response,
    db: Db,
) -> User:
    verify_csrf_cookie(request)
    check_auth_rate_limit(request)
    remove_expired_guest_accounts(db)
    user = User(
        email=f"guest+{secrets.token_urlsafe(18)}@guest.louf.invalid",
        password_hash=hash_password(secrets.token_urlsafe(32)),
        role="guest",
        is_guest=True,
    )
    db.add(user)
    db.flush()
    token, csrf = new_user_session(db, user)
    set_session_cookies(response, token, csrf)
    return user


@router.post("/auth/login", response_model=UserOut)
def login(data: Credentials, request: Request, response: Response, db: Db) -> User:
    verify_csrf_cookie(request)
    check_auth_rate_limit(request)
    user = db.scalar(select(User).where(User.email == str(data.email).strip().lower()))
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email or password is incorrect.")
    token, csrf = new_user_session(db, user)
    set_session_cookies(response, token, csrf)
    return user


@router.post("/auth/password-reset/request")
def request_password_reset(
    data: PasswordResetRequest,
    request: Request,
    db: Db,
) -> dict[str, str]:
    verify_csrf_cookie(request)
    check_auth_rate_limit(request)
    if not settings.smtp_host or not settings.smtp_from_email:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Password recovery is not configured. Set SMTP_HOST and SMTP_FROM_EMAIL, then retry.",
        )
    user = db.scalar(select(User).where(User.email == str(data.email).strip().lower()))
    if user and not user.is_guest:
        token = secrets.token_urlsafe(32)
        reset = PasswordResetToken(
            user_id=user.id,
            token_hash=token_digest(token),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        db.add(reset)
        db.commit()
        try:
            send_password_reset_email(user.email, token)
        except (OSError, smtplib.SMTPException, RuntimeError):
            db.delete(reset)
            db.commit()
            logger.exception("Could not send password reset email.")
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Could not send the recovery email. Check SMTP configuration and retry.",
            ) from None
    return {"message": "If that account exists, a password reset email has been sent."}


@router.post("/auth/password-reset/confirm")
def confirm_password_reset(
    data: PasswordResetConfirm,
    request: Request,
    db: Db,
) -> dict[str, str]:
    verify_csrf_cookie(request)
    reset = db.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_digest(data.token)
        )
    )
    if not reset or reset.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
        if reset:
            db.delete(reset)
            db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This password reset link is invalid or expired.")
    user = db.get(User, reset.user_id)
    if user is None or user.is_guest:
        db.delete(reset)
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This password reset link is invalid or expired.")
    user.password_hash = hash_password(data.password)
    db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id).delete()
    db.query(UserSession).filter(UserSession.user_id == user.id).delete()
    db.commit()
    return {"message": "Password updated. Sign in with your new password."}


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Db, session: CurrentSession) -> Response:
    verify_csrf_cookie(request)
    user = db.get(User, session.user_id)
    if user and user.is_guest:
        db.delete(user)
    else:
        db.delete(session)
    db.commit()
    response.delete_cookie("louf_session", path="/", secure=settings.cookie_secure, httponly=True)
    response.delete_cookie("louf_csrf", path="/", secure=settings.cookie_secure)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/users/me", response_model=UserOut)
def get_me(user: CurrentUser) -> User:
    return user


@router.delete("/users/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(request: Request, response: Response, db: Db, user: CurrentUser) -> Response:
    verify_csrf_cookie(request)
    db.delete(user)
    db.commit()
    response.delete_cookie("louf_session", path="/", secure=settings.cookie_secure, httponly=True)
    response.delete_cookie("louf_csrf", path="/", secure=settings.cookie_secure)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/models")
async def list_models() -> dict[str, object]:
    if not settings.bionic_api_base_url.strip():
        return {
            "connected": False,
            "provider": "Bionic",
            "models": [],
            "message": "Configure BIONIC_API_BASE_URL in python-backend\\.env to connect Bionic.",
        }
    url = f"{settings.bionic_api_base_url.rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {settings.bionic_api_key}"} if settings.bionic_api_key else {}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
    except (httpx.RequestError, httpx.HTTPStatusError, json.JSONDecodeError):
        return {
            "connected": False,
            "provider": "Bionic",
            "models": [],
            "message": "Bionic could not be reached. Check the endpoint, API key, and model API compatibility.",
        }
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        return {
            "connected": False,
            "provider": "Bionic",
            "models": [],
            "message": "Bionic returned an unexpected model-list response. The endpoint must support the OpenAI-compatible API.",
        }
    models = [
        {"name": item["id"], "size": None}
        for item in data["data"]
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]
    return {
        "connected": True,
        "provider": "Bionic",
        "models": models,
        "message": "No models are available from the configured Bionic endpoint." if not models else None,
    }


@router.get("/capabilities")
def capabilities() -> dict[str, object]:
    return {
        "chat": {
            "provider": "Bionic",
            "configured": bool(settings.bionic_api_base_url.strip()),
        },
        "images": {
            "configured": False,
            "available": False,
            "message": "No image-generation service is configured. Configure a compatible local provider to enable this feature.",
        },
        "videos": {
            "configured": False,
            "available": False,
            "message": "No video-generation service is configured. Configure a compatible inference service to enable this feature.",
        },
    }


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(db: Db, user: CurrentUser) -> list[Conversation]:
    return list(
        db.scalars(
            select(Conversation)
            .where(Conversation.user_id == user.id)
            .order_by(Conversation.updated_at.desc())
        ).all()
    )


@router.post(
    "/conversations", response_model=ConversationOut, status_code=status.HTTP_201_CREATED
)
def create_conversation(
    data: ConversationCreate, request: Request, db: Db, user: CurrentUser
) -> Conversation:
    verify_csrf_cookie(request)
    conversation = Conversation(user_id=user.id, title=data.title.strip())
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def owned_conversation(db: Session, user_id: str, conversation_id: str) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        )
    )
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found.")
    return conversation


@router.patch("/conversations/{conversation_id}", response_model=ConversationOut)
def rename_conversation(
    conversation_id: str,
    data: ConversationRename,
    request: Request,
    db: Db,
    user: CurrentUser,
) -> Conversation:
    verify_csrf_cookie(request)
    conversation = owned_conversation(db, user.id, conversation_id)
    conversation.title = data.title.strip()
    conversation.updated_at = utc_now()
    db.commit()
    db.refresh(conversation)
    return conversation


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_conversation(
    conversation_id: str, request: Request, response: Response, db: Db, user: CurrentUser
) -> Response:
    verify_csrf_cookie(request)
    conversation = owned_conversation(db, user.id, conversation_id)
    db.delete(conversation)
    db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def list_messages(conversation_id: str, db: Db, user: CurrentUser) -> list[Message]:
    owned_conversation(db, user.id, conversation_id)
    return list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        ).all()
    )


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    data: ChatRequest,
    request: Request,
    db: Db,
    user: CurrentUser,
) -> StreamingResponse:
    verify_csrf_cookie(request)
    conversation = owned_conversation(db, user.id, conversation_id)
    model_response = await list_models()
    available = {item["name"] for item in model_response["models"]}
    if not model_response["connected"]:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            model_response["message"] or "Bionic is unavailable. Check its configuration and retry.",
        )
    if data.model not in available:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The selected model is not available from Bionic. Select an available model.",
        )

    history = list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        ).all()
    )
    user_message = Message(conversation_id=conversation_id, role="user", content=data.prompt)
    db.add(user_message)
    if conversation.title == "New conversation":
        conversation.title = data.prompt.strip().splitlines()[0][:80]
    conversation.updated_at = utc_now()
    db.commit()

    messages: list[dict[str, str]] = []
    if data.system_instructions:
        messages.append({"role": "system", "content": data.system_instructions})
    messages.extend({"role": msg.role, "content": msg.content} for msg in history[-30:])
    messages.append({"role": "user", "content": data.prompt})
    chat_url = f"{settings.bionic_api_base_url.rstrip('/')}/chat/completions"
    payload = {"model": data.model, "messages": messages, "stream": True}
    headers = {"Authorization": f"Bearer {settings.bionic_api_key}"} if settings.bionic_api_key else {}

    async def stream():
        answer: list[str] = []
        failure: str | None = None
        try:
            timeout = httpx.Timeout(settings.bionic_timeout_seconds, connect=5)
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", chat_url, json=payload, headers=headers) as upstream:
                    upstream.raise_for_status()
                    async for line in upstream.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        event_data = line[6:]
                        if event_data == "[DONE]":
                            break
                        item = json.loads(event_data)
                        if not isinstance(item, dict):
                            raise json.JSONDecodeError("Expected an object", event_data, 0)
                        if item.get("error"):
                            raise ValueError("Bionic reported a streaming error.")
                        choices = item.get("choices")
                        content = ""
                        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                            delta = choices[0].get("delta", {})
                            if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                                content = delta["content"]
                        if content:
                            answer.append(content)
                            yield f"data: {json.dumps({'delta': content})}\n\n"
                        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                            if choices[0].get("finish_reason") is not None:
                                break
        except ValueError:
            failure = "Bionic returned an invalid streaming response. Check its API compatibility and retry."
        except (httpx.RequestError, httpx.HTTPStatusError, json.JSONDecodeError, AttributeError) as error:
            logger.warning("Bionic chat request failed: %s", error)
            failure = "The Bionic model request failed. Check the endpoint, credentials, and selected model, then retry."
        if failure:
            yield f"data: {json.dumps({'error': failure})}\n\n"
            return
        if not answer:
            yield f"data: {json.dumps({'error': 'The model returned an empty response.'})}\n\n"
            return
        try:
            assistant = Message(
                conversation_id=conversation_id,
                role="assistant",
                content="".join(answer),
                model=data.model,
            )
            db.add(assistant)
            conversation.updated_at = utc_now()
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            yield f"data: {json.dumps({'error': 'The response was generated but could not be saved. Check database health and retry.'})}\n\n"
            return
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
