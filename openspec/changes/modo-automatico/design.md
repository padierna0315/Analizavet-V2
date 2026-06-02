# Design: Modo Automático (Headless Console Operator)

## Technical Approach

Minimal headless extension to the existing FastAPI app. A synchronous foreground script (`auto_mode.py`) polls `POST /reception/appsheet/sync` every 30s, fetches `GET /auto/status`, and listens for 'r' keypress to generate jornada reports. Four backend touchpoints: new `auto/` domain (status endpoint), new `jornada/adelanto` endpoint (read-only), quarantine reprocess trigger in AppSheetSyncService, and iniciar.sh fork.

## Architecture Decisions

### Stdin capture

| Alternative | Tradeoff | Decision |
|---|---|---|
| `select.select` + `termios` + `tty.setraw` | stdlib, Unix-only, no extra deps | ✅ **Chosen** |
| `asyncio` + `aioconsole` | External dep, adds async complexity | ❌ Rejected |
| `keyboard` library | Needs sudo/root, not portable | ❌ Rejected |

**Rationale**: Target is Linux-only. Raw mode enables single keypress detection without Enter. Zero dependencies.

### HTTP client

| Alternative | Tradeoff | Decision |
|---|---|---|
| `httpx.Client` (sync) | Simple blocking calls, already a dep | ✅ **Chosen** |
| `httpx.AsyncClient` | Overkill for a linear loop | ❌ Rejected |
| `urllib.request` | stdlib but verbose, no connection pooling | ❌ Rejected |

### Polling interval

| Alternative | Tradeoff | Decision |
|---|---|---|
| 30s default, env var override | Tuneable without code changes | ✅ **Chosen** |
| Hardcoded 30s | Simple but inflexible | ❌ Rejected |
| settings.toml entry | More ceremony for same result | ❌ Rejected |

**Rationale**: 30s = 120 req/h, well within AppSheet's ~200 req/h limit. Env var `AUTO_POLL_INTERVAL` for tuning.

### State tracking

| Alternative | Tradeoff | Decision |
|---|---|---|
| In-memory counters | Single-process, sufficient | ✅ **Chosen** |
| Redis / SQLite | Overengineered for a foreground script | ❌ Rejected |

**Rationale**: Script is a single foreground process. On restart it starts fresh — no persistence needed.

### Quarantine auto-reprocess

| Alternative | Tradeoff | Decision |
|---|---|---|
| `reprocess_quarantined.send(q.id)` in `_link_quarantined_items()` | Fire-and-forget via existing Dramatiq actor | ✅ **Chosen** |
| auto_mode.py calls separate endpoint | Couples the polling script to reprocess logic | ❌ Rejected |
| Sync endpoint returns list, caller triggers | Breaks existing contract, more moving parts | ❌ Rejected |

**Rationale**: Dramatiq actor already exists with proper error handling. Sending a message is one line, zero behavioral change to the sync response.

### Jornada adelanto

| Alternative | Tradeoff | Decision |
|---|---|---|
| New endpoint reusing `get_jornada_results()` + `format_report()` | 3 lines, zero new logic | ✅ **Chosen** |
| New standalone function | Duplicates existing logic | ❌ Rejected |

### File download location

| Alternative | Tradeoff | Decision |
|---|---|---|
| `data/descargas/{timestamp}.txt` | Clearly scoped, auto-created | ✅ **Chosen** |
| `data/` directly | Risk of clashing with existing files | ❌ Rejected |
| `logs/` | Mixing downloads with logs | ❌ Rejected |

## Data Flow

```
iniciar.sh ── ¿Modo automático? ──→ [s] ──→ auto_mode.py (foreground)
                                              │
                                              ├─ 30s loop ──→ POST /reception/appsheet/sync
                                              │                  └─ AppSheetSyncService.sync_from_appsheet()
                                              │                      └─ _link_quarantined_items()
                                              │                           └─ reprocess_quarantined.send(id)
                                              │
                                              ├─ GET /auto/status ──→ JSON status
                                              │
                                              ├─ [r] key ──→ "¿ADELANTO o FINAL?"
                                              │                ├─ ADELANTO → GET /jornada/adelanto → print
                                              │                └─ FINAL   → GET /jornada/resumen → save .txt
                                              │
                                              └─ Ctrl+C ──→ clean exit, restore terminal
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `app/auto_mode.py` | **Create** | Foreground loop: poll, key listener, download reports |
| `app/domains/auto/__init__.py` | **Create** | Package init |
| `app/domains/auto/router.py` | **Create** | `GET /auto/status` with DB counts |
| `app/domains/jornada/router.py` | **Modify** | Add `GET /jornada/adelanto` (read-only, no clear) |
| `app/domains/reception/appsheet_service.py` | **Modify** | Add `reprocess_quarantined.send()` after each link |
| `app/main.py` | **Modify** | Register `auto_router` |
| `iniciar.sh` | **Modify** | Prompt after verify_all, fork or normal flow |

## Interfaces / Contracts

### `GET /auto/status`
```json
{
  "patients_waiting_count": 5,
  "jornada_entries": 3,
  "last_sync_at": "2026-06-02T10:30:00Z",
  "last_reprocess_at": "2026-06-02T10:30:05Z"
}
```

### `GET /jornada/adelanto`
- Same plain-text format as `/jornada/resumen` — `get_jornada_results()` + `format_report()`
- Header: `X-Jornada-Mode: HASTA-AHORA`
- MUST NOT call `clear_jornada_log()`

### `app/auto_mode.py` — key functions

```python
def _setup_stdin() -> tuple:          # Save termios attrs, set raw mode
def _restore_stdin(saved: tuple):     # Restore original terminal attrs
def _check_keypress() -> str | None:  # select.select on stdin, return 'r' or None
def _fetch_sync(client: httpx.Client) -> int:  # POST /reception/appsheet/sync
def _fetch_status(client: httpx.Client) -> dict:  # GET /auto/status
def _handle_report(client: httpx.Client, mode: str) -> None:  # adelanto print / final save
def main():                           # Loop: poll → keypress → handle
```

### Quarantine reprocess trigger (in `_link_quarantined_items`)

```python
# After status is set to "forced":
from app.tasks.quarantine_reprocess import reprocess_quarantined
reprocess_quarantined.send(q.id)  # fire-and-forget via Dramatiq
```

### iniciar.sh modification (pseudocode)

```bash
# After verify_all (step 4):
read -p "¿Modo automático? [s/N] " modo
if [[ "$modo" =~ ^[sS]$ ]]; then
    tail -f "$UVICORN_LOG" &
    uv run python app/auto_mode.py
    # On exit: skip open_browser, skip final tail -f
else
    open_browser
    tail -f "$UVICORN_LOG" &
    wait
fi
```

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | `GET /auto/status` counts | Mock Patient count + DataQuarantine count queries, assert JSON shape |
| Unit | `GET /jornada/adelanto` idempotency | Call twice, assert same content, log file unchanged |
| Unit | Quarantine reprocess trigger | Mock `reprocess_quarantined.send`, assert called for each linked item |
| Integration | auto_mode loop (mocked HTTP) | Responde `httpx` calls to sync + status endpoints, assert loop behavior |
| Shell | iniciar.sh 's' path | Mock verify_all, assert `uv run python app/auto_mode.py` is called |
| Shell | iniciar.sh Enter path | Mock verify_all, assert `open_browser` is called |
| Regression | All existing tests | `pytest -v --cov=app --cov-report=term-missing -p pytest_playwright` |

## Migration / Rollout

**No migration required.** All changes are additive:
- New endpoints don't affect existing routes
- Quarantine reprocess trigger is additive (already-linked items won't re-link — status is `forced`)
- iniciar.sh change is conditional — default (Enter) behavior is unchanged
- `data/descargas/` auto-created on first download via `pathlib.Path.mkdir(parents=True, exist_ok=True)`

## Open Questions

None. All design decisions resolved.
