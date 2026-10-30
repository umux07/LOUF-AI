# LOUF AI

LOUF AI is an assistant workspace with protected accounts, persistent conversations, streaming chat through a configurable Bionic-compatible API, and an honest connection status for image/video providers. It does **not** return synthetic AI or media results.

## Current implementation status

| Area | Status |
| --- | --- |
| Registration, login, temporary guest sessions, logout, session cookies, CSRF checks | Implemented |
| User-owned conversations, rename/delete, message history | Implemented |
| Password reset | Implemented; requires SMTP configuration |
| Bionic-compatible model discovery and streamed chat | Implemented; requires a configured OpenAI-compatible Bionic API endpoint |
| Responsive chat UI, model selector, history search, light/dark themes | Implemented |
| Account deletion and session/conversation cascade | Implemented |
| SQLite schema migration | Initial reversible Alembic migration included |
| Image/video inference, generation jobs, and media gallery | Pending provider integration; UI reports unavailable rather than showing fake output |
| Email verification, admin management, usage/audit dashboard | Pending |
| MySQL | Optional SQLAlchemy URL path; install the `mysql` extra and configure a MySQL URL |

The image and video screens are explicitly not generation tools yet. A local image/video backend, job lifecycle, and media persistence must be integrated and tested before those features can be considered complete.

Guest sessions use an isolated temporary account. Their conversations are deleted on sign-out; after expiration they are inaccessible and are purged on the next guest session start or expired-session request. Guest chats cannot be recovered or converted to a registered account.

## Requirements

- Node.js 22.12+ (the Vite 8 toolchain requires a recent Node release)
- Python 3.11+
- A Bionic deployment or model endpoint that supports the OpenAI-compatible `/models` and `/chat/completions` APIs

No model weights are downloaded automatically. The browser never calls the AI provider directly; provider credentials remain in the backend environment. The UI uses system fonts without loading third-party resources.

## Windows PowerShell setup

From the project root:

```powershell
Copy-Item .env.example python-backend\.env
# Edit python-backend\.env and set SECRET_KEY to a random value.
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e "python-backend[test]"
```

If PowerShell blocks activation, invoke the environment directly instead:

```powershell
.\.venv\Scripts\python.exe -m pip install -e "python-backend[test]"
```

Apply all schema migrations:

```powershell
Set-Location python-backend
..\.venv\Scripts\alembic.exe upgrade head
```

Start the backend from `python-backend`:

```powershell
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

In a second terminal:

```powershell
Set-Location frontend
npm.cmd install
npm.cmd run dev
```

Open the Vite URL shown in the terminal (normally `http://localhost:5173`). The frontend proxies `/api` to `http://127.0.0.1:8000`; set `API_PROXY_TARGET` before `npm.cmd run dev` to use a different local API URL.

## Bionic chat

Configure the Bionic deployment's OpenAI-compatible API base URL in `python-backend\.env`. Use the base URL ending in `/v1` (for example, `https://your-bionic-host.example/v1`), not a URL ending in `/models` or `/chat/completions`. Set `BIONIC_API_KEY` if that deployment requires bearer-token authentication. The backend requests `/models` to discover available models and streams chat from `/chat/completions`. Restart the backend after changing environment settings, then open **Settings** and choose **Check connection**.

Bionic deployments can expose different APIs and authentication schemes. This integration specifically requires an OpenAI-compatible `/models` response and streaming `/chat/completions` API. A deployment that does not provide those endpoints needs a provider-specific adapter before it will work. Do not put an API key in frontend code or share it in chat.

## Configuration

Edit `python-backend\.env`:

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Replace the development placeholder with a long random secret |
| `DATABASE_URL` | SQLAlchemy connection URL; defaults to a local SQLite database |
| `FRONTEND_ORIGINS` | Comma-separated allowed browser origins |
| `COOKIE_SECURE` | Set `true` when serving over HTTPS |
| `SESSION_TTL_HOURS` | Session lifetime |
| `BIONIC_API_BASE_URL` | Bionic OpenAI-compatible API base URL, ending in `/v1` |
| `BIONIC_API_KEY` | Optional bearer token; stored only in the backend environment |
| `BIONIC_TIMEOUT_SECONDS` | Maximum inference wait |
| `STORAGE_DIR` | Reserved for future media storage integration |
| `FRONTEND_BASE_URL` | Frontend URL used to create password reset links |
| `SMTP_HOST`, `SMTP_PORT` | SMTP server used for password recovery |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | Optional SMTP authentication |
| `SMTP_FROM_EMAIL` | Sender address for recovery messages |
| `SMTP_USE_TLS` | Use STARTTLS (`true`) or implicit TLS (`false`) |

For MySQL, install `python -m pip install -e ".[mysql]"` from `python-backend` and set a `mysql+pymysql://...` database URL. Back up databases before schema changes; migrations are explicit and the API does not create or drop tables at startup.

Password reset is available from the sign-in screen. Configure SMTP in `python-backend\.env`; reset tokens are single-use, expire after 30 minutes, and are stored only as keyed hashes. Password reset invalidates existing sessions. Without SMTP configuration, reset requests return an explicit service-unavailable error.

## Tests and build

```powershell
Set-Location python-backend
..\.venv\Scripts\python.exe -m pytest tests
Set-Location ..\frontend
npm.cmd run build
npm.cmd run lint
```

Automated tests use an isolated in-memory SQLite database. Real model tests require a reachable Bionic-compatible endpoint and a model enabled for that endpoint.

## Security notes

- Passwords use PBKDF2-HMAC-SHA256; raw session tokens are not stored in the database.
- Session cookies are HTTP-only and SameSite=Lax; unsafe API calls require a CSRF token.
- CORS origins are configurable. Keep them limited to trusted frontend origins.
- Set a strong `SECRET_KEY` and `COOKIE_SECURE=true` for HTTPS deployments.
- This project is not yet production-hardened: distributed rate limiting, account verification, admin role provisioning, audit records, upload validation, and media authorization remain to be implemented.
