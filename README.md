# LOUF AI

LOUF AI is an assistant workspace with protected accounts, persistent conversations, streaming chat through a configurable Bionic-compatible API, and local ComfyUI image/video generation. It does **not** return synthetic AI or media results.

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
| ComfyUI image/video generation jobs and private media gallery | Implemented; requires configured API-format workflows and compatible installed models |
| Email verification, admin management, usage/audit dashboard | Pending |
| MySQL | Optional SQLAlchemy URL path; install the `mysql` extra and configure a MySQL URL |

Image and video generation use a local ComfyUI server. Each feature needs an API-format workflow exported from ComfyUI and a prompt node ID/input configured on the backend. Jobs are polled from the browser, and generated files are stored under `STORAGE_DIR` and served only to their owning account.

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
| `STORAGE_DIR` | Private on-disk storage root for generated media |
| `COMFYUI_API_BASE_URL` | Local ComfyUI HTTP API URL, usually `http://127.0.0.1:8188` |
| `COMFYUI_IMAGE_WORKFLOW_PATH` | Path to an API-format ComfyUI image workflow JSON file |
| `COMFYUI_IMAGE_PROMPT_NODE_ID` | Node ID in that workflow whose input receives the prompt |
| `COMFYUI_IMAGE_PROMPT_INPUT` | Prompt input name on the configured image node; defaults to `text` |
| `COMFYUI_VIDEO_WORKFLOW_PATH` | Path to an API-format ComfyUI video workflow JSON file |
| `COMFYUI_VIDEO_PROMPT_NODE_ID` | Node ID in that workflow whose input receives the prompt |
| `COMFYUI_VIDEO_PROMPT_INPUT` | Prompt input name on the configured video node; defaults to `text` |
| `COMFYUI_TIMEOUT_SECONDS` | Timeout for ComfyUI API and output retrieval |
| `COMFYUI_MAX_OUTPUT_BYTES` | Maximum size of a generated file (default 100 MiB) |
| `FRONTEND_BASE_URL` | Frontend URL used to create password reset links |
| `SMTP_HOST`, `SMTP_PORT` | SMTP server used for password recovery |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | Optional SMTP authentication |
| `SMTP_FROM_EMAIL` | Sender address for recovery messages |
| `SMTP_USE_TLS` | Use STARTTLS (`true`) or implicit TLS (`false`) |

For MySQL, install `python -m pip install -e ".[mysql]"` from `python-backend` and set a `mysql+pymysql://...` database URL. Back up databases before schema changes; migrations are explicit and the API does not create or drop tables at startup.

Password reset is available from the sign-in screen. Configure SMTP in `python-backend\.env`; reset tokens are single-use, expire after 30 minutes, and are stored only as keyed hashes. Password reset invalidates existing sessions. Without SMTP configuration, reset requests return an explicit service-unavailable error.

## Local image and video generation

Install and start ComfyUI separately, then install the model checkpoints and custom nodes required by your workflows. Export each workflow using ComfyUI's **Save (API Format)** option. Configure the API endpoint and both workflow entries in `python-backend\.env`; an image or video workflow can be omitted if that capability is not needed. For each workflow, set the prompt node ID and its prompt input name (commonly `text`). The backend replaces that input with the submitted prompt and sends the workflow to ComfyUI's `/prompt` API.

Example:

```dotenv
COMFYUI_API_BASE_URL=http://127.0.0.1:8188
COMFYUI_IMAGE_WORKFLOW_PATH=C:\ComfyUI\workflows\louf-image-api.json
COMFYUI_IMAGE_PROMPT_NODE_ID=6
COMFYUI_IMAGE_PROMPT_INPUT=text
COMFYUI_VIDEO_WORKFLOW_PATH=C:\ComfyUI\workflows\louf-video-api.json
COMFYUI_VIDEO_PROMPT_NODE_ID=6
COMFYUI_VIDEO_PROMPT_INPUT=text
```

Paths are read by the backend process, so the files must be accessible to its OS account. ComfyUI workflows are user-provided; ensure each workflow writes an image (`png`, `jpg`, `webp`, or `gif`) or video (`mp4`, `webm`, `mov`, `mkv`, or `gif`) output. LOUF polls ComfyUI history, downloads the completed media into an account-scoped directory under `STORAGE_DIR`, and serves it only after checking the signed-in owner. Applying the new media-job database migration is required: run `alembic upgrade head` from `python-backend`.

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
