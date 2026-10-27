# LOUF AI

LOUF AI is a local-first assistant workspace. The current implementation includes protected accounts, persistent conversations, streamed chat through Ollama, and an honest connection status for image/video providers. It does **not** return synthetic AI or media results.

## Current implementation status

| Area | Status |
| --- | --- |
| Registration, login, logout, session cookies, password hashing, CSRF checks | Implemented |
| User-owned conversations, rename/delete, message history | Implemented |
| Local Ollama discovery and streamed chat | Implemented; requires Ollama and an installed model |
| Responsive chat UI, model selector, history search, light/dark themes | Implemented |
| Account deletion and session/conversation cascade | Implemented |
| SQLite schema migration | Initial reversible Alembic migration included |
| Image/video inference, generation jobs, and media gallery | Pending provider integration; UI reports unavailable rather than showing fake output |
| Password reset, email verification, admin management, usage/audit dashboard | Pending |
| MySQL | Optional SQLAlchemy URL path; install the `mysql` extra and configure a MySQL URL |

The image and video screens are explicitly not generation tools yet. A local image/video backend, job lifecycle, and media persistence must be integrated and tested before those features can be considered complete.

## Requirements

- Node.js 22.12+ (the Vite 8 toolchain requires a recent Node release)
- Python 3.11+
- Ollama for actual local chat, plus a model you choose to download

No model weights are downloaded automatically. The browser never calls an external AI API, and the UI uses system fonts without loading third-party resources.

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

Apply the initial schema migration:

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

Open the Vite URL shown in the terminal (normally `http://localhost:5173`). The frontend proxies `/api` to `http://127.0.0.1:8000`.

## Ollama chat

1. Install and start Ollama using its official Windows installer.
2. In PowerShell, explicitly download a small model, for example:

   ```powershell
   ollama pull llama3.2:1b
   ```

3. Open **Settings** in LOUF AI and use **Check connection**. Select the installed model in the chat composer.

The model's speed, memory requirements, and output quality depend on the device. The application does not guarantee that a model will fit or run quickly on integrated graphics. If Ollama is down or a model is missing, the request fails with an actionable message and no assistant response is fabricated.

The target development machine is described as an i3-1315U with Intel UHD graphics and about 8 GB RAM. This project has not benchmarked that hardware; treat even small quantized models as potentially slow and monitor available memory.

## Configuration

Edit `python-backend\.env`:

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Replace the development placeholder with a long random secret |
| `DATABASE_URL` | SQLAlchemy connection URL; defaults to a local SQLite database |
| `FRONTEND_ORIGINS` | Comma-separated allowed browser origins |
| `COOKIE_SECURE` | Set `true` when serving over HTTPS |
| `SESSION_TTL_HOURS` | Session lifetime |
| `OLLAMA_BASE_URL` | Local Ollama URL |
| `OLLAMA_TIMEOUT_SECONDS` | Maximum inference wait |
| `STORAGE_DIR` | Reserved for future media storage integration |

For MySQL, install `python -m pip install -e ".[mysql]"` from `python-backend` and set a `mysql+pymysql://...` database URL. Back up databases before schema changes; migrations are explicit and the API does not create or drop tables at startup.

## Tests and build

```powershell
Set-Location python-backend
..\.venv\Scripts\python.exe -m pytest tests
Set-Location ..\frontend
npm.cmd run build
npm.cmd run lint
```

Automated tests use an isolated in-memory SQLite database. Real model tests require a running Ollama instance and a model installed by the user.

## Security notes

- Passwords use PBKDF2-HMAC-SHA256; raw session tokens are not stored in the database.
- Session cookies are HTTP-only and SameSite=Lax; unsafe API calls require a CSRF token.
- CORS origins are configurable. Keep them limited to trusted frontend origins.
- Set a strong `SECRET_KEY` and `COOKIE_SECURE=true` for HTTPS deployments.
- This project is not yet production-hardened: distributed rate limiting, account verification/reset workflows, admin role provisioning, audit records, upload validation, and media authorization remain to be implemented.
