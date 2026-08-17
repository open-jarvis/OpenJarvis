# Kiosk Loopback Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow the local Kiosk browser to consume Kiosk events and submit consent without an API key while preserving authentication for every non-loopback client.

**Architecture:** Keep the exemption at the two existing server authentication boundaries. `AuthMiddleware` recognizes only loopback `/api/kiosk/*` requests, while `websocket_authorized()` gains an opt-in loopback allowance used only by `/v1/agents/events`; all other callers retain current behavior.

**Tech Stack:** Python 3.13, FastAPI/Starlette, pytest, OpenJarvis `EventBus`, Vision WebSocket at `ws://127.0.0.1:9876`.

## Global Constraints

- Trust only the socket peer address; never trust `Host`, `Origin`, `X-Forwarded-For`, or other forwarded headers.
- Exempt `/api/kiosk/*` HTTP traffic only for loopback peers.
- Exempt `/v1/agents/events` WebSocket traffic only for loopback peers and only through an explicit opt-in at that route.
- Preserve authentication for remote peers and every other `/v1/*`, `/api/*`, and `/metrics` route.
- Do not change Vision schema, FSM timing, Kiosk visuals, voice policy, model selection, or provider credentials.
- Preserve unrelated worktree state and stage only files listed in each task.

---

## File Map

- `src/openjarvis/server/auth_middleware.py`: owns HTTP API-key enforcement, loopback-address recognition, and the shared WebSocket authentication helper.
- `src/openjarvis/server/ws_bridge.py`: opts only the shared agent-event WebSocket into the loopback exemption.
- `tests/server/test_auth_middleware.py`: pins local Kiosk HTTP exemption and remote/non-Kiosk protection.
- `tests/server/test_websocket_auth.py`: pins opt-in loopback WebSocket behavior and route-level integration.
- No frontend source changes: the selected design intentionally lets the local Kiosk page remain tokenless.

### Task 1: Loopback HTTP Kiosk exemption

**Files:**
- Modify: `tests/server/test_auth_middleware.py`
- Modify: `src/openjarvis/server/auth_middleware.py`

**Interfaces:**
- Consumes: `is_loopback_host(host: str | None) -> bool`.
- Produces: `AuthMiddleware` behavior that bypasses API-key validation only for loopback `/api/kiosk/*` requests.

- [ ] **Step 1: Add the Kiosk route and failing HTTP tests**

Add a minimal route to `_make_app()`:

```python
    @app.post("/api/kiosk/respond")
    async def kiosk_respond():
        return {"ok": True}
```

Add tests using Starlette's explicit peer address support:

```python
    def test_loopback_kiosk_request_is_exempt(self):
        client = TestClient(
            _make_app("oj_sk_test123"),
            client=("127.0.0.1", 50000),
        )
        assert client.post("/api/kiosk/respond").status_code == 200

    def test_remote_kiosk_request_requires_auth(self):
        client = TestClient(
            _make_app("oj_sk_test123"),
            client=("203.0.113.10", 50000),
        )
        assert client.post("/api/kiosk/respond").status_code == 401

    def test_loopback_non_kiosk_api_still_requires_auth(self):
        client = TestClient(
            _make_app("oj_sk_test123"),
            client=("127.0.0.1", 50000),
        )
        assert client.get("/v1/models").status_code == 401
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
uv run pytest tests/server/test_auth_middleware.py -q
```

Expected: `test_loopback_kiosk_request_is_exempt` fails with status `401`; remote Kiosk and non-Kiosk protection tests pass.

- [ ] **Step 3: Implement the minimal HTTP exemption**

In `AuthMiddleware.dispatch()`, calculate the peer once and bypass validation only for the accepted path/address pair:

```python
        client_host = request.client.host if request.client is not None else None
        loopback_kiosk = (
            request.url.path.startswith("/api/kiosk/")
            and is_loopback_host(client_host)
        )
        if (
            self._api_key
            and self._requires_auth(request.url.path)
            and not loopback_kiosk
        ):
```

Do not inspect proxy headers and do not broaden `_requires_auth()`.

- [ ] **Step 4: Run focused HTTP tests and verify GREEN**

Run:

```bash
uv run pytest tests/server/test_auth_middleware.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit the HTTP boundary**

```bash
git add src/openjarvis/server/auth_middleware.py tests/server/test_auth_middleware.py
git commit -m "fix(kiosk): allow loopback consent without api key"
```

### Task 2: Opt-in loopback agent-event WebSocket

**Files:**
- Modify: `tests/server/test_websocket_auth.py`
- Modify: `src/openjarvis/server/auth_middleware.py`
- Modify: `src/openjarvis/server/ws_bridge.py`

**Interfaces:**
- Consumes: `is_loopback_host(host: str | None) -> bool` and the existing `websocket_authorized(websocket, expected_key)` call contract.
- Produces: `websocket_authorized(websocket, expected_key, *, allow_loopback=False) -> bool`; `/v1/agents/events` passes `allow_loopback=True`, while chat and other streams retain the default.

- [ ] **Step 1: Add failing helper tests**

Make `_ws()` supply a peer address without changing existing callers:

```python
def _ws(query=None, headers=None, client_host="203.0.113.10"):
    stub = MagicMock()
    stub.query_params = query or {}
    stub.headers = headers or {}
    stub.client = MagicMock(host=client_host)
    return stub
```

Add the opt-in behavior tests:

```python
    def test_loopback_allowed_when_explicitly_enabled(self):
        ws = _ws(client_host="127.0.0.1")
        assert websocket_authorized(ws, "sek", allow_loopback=True) is True

    def test_loopback_rejected_without_explicit_opt_in(self):
        ws = _ws(client_host="127.0.0.1")
        assert websocket_authorized(ws, "sek") is False

    def test_remote_rejected_when_loopback_is_enabled(self):
        ws = _ws(client_host="203.0.113.10")
        assert websocket_authorized(ws, "sek", allow_loopback=True) is False
```

- [ ] **Step 2: Run helper tests and verify RED**

Run:

```bash
uv run pytest tests/server/test_websocket_auth.py::TestWebsocketAuthorizedHelper -q
```

Expected: calls with `allow_loopback=True` fail because the keyword argument is not implemented.

- [ ] **Step 3: Implement the opt-in helper**

Change the signature and add the narrow early return after the no-key case:

```python
def websocket_authorized(
    websocket,
    expected_key: str,
    *,
    allow_loopback: bool = False,
) -> bool:  # noqa: ANN001
    if not expected_key:
        return True
    client = getattr(websocket, "client", None)
    if allow_loopback and is_loopback_host(getattr(client, "host", None)):
        return True
```

Keep query-token and Bearer-token comparisons unchanged.

- [ ] **Step 4: Run helper tests and verify GREEN**

Run:

```bash
uv run pytest tests/server/test_websocket_auth.py::TestWebsocketAuthorizedHelper -q
```

Expected: all helper tests pass.

- [ ] **Step 5: Add the failing route integration test**

Replace the previous loopback rejection expectation for `TestAgentEventsAuth` with an event-delivery assertion:

```python
    def test_loopback_accepted_without_token(self):
        bus = EventBus()
        app = FastAPI()
        app.state.api_key = "secret"
        app.include_router(create_ws_router(bus))
        client = TestClient(app, client=("127.0.0.1", 50000))
        with client.websocket_connect("/v1/agents/events") as ws:
            bus.publish(EventType.AGENT_TICK_START, {"agent_id": "local-kiosk"})
            assert ws.receive_json()["data"]["agent_id"] == "local-kiosk"
```

Retain an explicit remote rejection test using `client=("203.0.113.10", 50000)`.

- [ ] **Step 6: Run the route test and verify RED**

Run:

```bash
uv run pytest tests/server/test_websocket_auth.py::TestAgentEventsAuth -q
```

Expected: the loopback tokenless connection is closed because `ws_bridge` has not opted in.

- [ ] **Step 7: Opt only the agent-event route into loopback access**

Change `src/openjarvis/server/ws_bridge.py`:

```python
        if not websocket_authorized(
            websocket,
            expected_key,
            allow_loopback=True,
        ):
```

Do not change `/v1/chat/stream` or any other caller.

- [ ] **Step 8: Run WebSocket auth tests and verify GREEN**

Run:

```bash
uv run pytest tests/server/test_websocket_auth.py tests/server/test_ws_bridge.py -q
```

Expected: all tests pass, including remote rejection and authenticated access.

- [ ] **Step 9: Commit the WebSocket boundary**

```bash
git add src/openjarvis/server/auth_middleware.py src/openjarvis/server/ws_bridge.py tests/server/test_websocket_auth.py
git commit -m "fix(kiosk): allow loopback event stream"
```

### Task 3: Verification and live Kiosk acceptance

**Files:**
- No source changes expected.
- Runtime processes: backend `:8000`, frontend Vite `:5173`, Vision WebSocket `:9876`.

**Interfaces:**
- Consumes: loopback HTTP/WebSocket exemptions from Tasks 1 and 2, existing Vision `person_near` schema, existing Kiosk FSM.
- Produces: fresh automated and live evidence for the selected design.

- [ ] **Step 1: Run the complete focused verification**

```bash
uv run pytest tests/server/test_auth_middleware.py tests/server/test_websocket_auth.py tests/server/test_ws_bridge.py -q
uv run ruff check src/openjarvis/server/auth_middleware.py src/openjarvis/server/ws_bridge.py tests/server/test_auth_middleware.py tests/server/test_websocket_auth.py
git diff --check HEAD~2..HEAD
```

Expected: tests and Ruff exit zero; diff check is clean.

- [ ] **Step 2: Build the frontend unchanged**

```bash
cd frontend
npm run build
```

Expected: build exits zero. This confirms the existing Kiosk browser code remains compatible with the server-side exemption.

- [ ] **Step 3: Restart the backend with Kiosk enabled**

Stop only the verified current backend PID. From the repository root, load provider credentials and start:

```bash
set -a
source /home/robber/Work/jarvis/OpenJarvis/.env
set +a
KIOSK_ENABLED=true \
KIOSK_VISION_URL=ws://127.0.0.1:9876 \
.venv/bin/jarvis serve \
  --host 127.0.0.1 \
  --port 8000 \
  --engine cloud \
  --model deepseek-v4-flash
```

Expected startup evidence includes `Kiosk subsystem started` and `VisionClient connected to ws://127.0.0.1:9876`.

- [ ] **Step 4: Verify local runtime endpoints without a token**

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/api/kiosk/state
```

Expected: health returns status `ok`; Kiosk state returns `{"ok":true,"running":true}` without an Authorization header.

- [ ] **Step 5: Run the original live acceptance loop**

Open `http://localhost:5173/kiosk`, hold a tracked person below 1 m for at least 2.4 seconds, and observe:

```text
idle -> approaching -> prompting
```

Expected: the existing Yes/No popup appears. Select each response in separate cycles and confirm `/api/kiosk/respond` returns HTTP 200. No API key is stored in or transmitted by the Kiosk frontend.

- [ ] **Step 6: Record exact final evidence**

Report the current HEAD, focused test count, build result, backend/frontend/Vision PIDs and ports, observed Vision distance, observed FSM transitions, and Yes/No response results. Report any unverified manual UI behavior explicitly rather than inferring it from server logs.
