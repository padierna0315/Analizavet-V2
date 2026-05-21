# Design: Patient Data Isolation Gatekeeper

## Technical Approach

Layered defense (Approach D from proposal). Layer 1 ships now: gatekeeper enforcement at every source boundary + temporal isolation in `ReceptionService.receive()` + quarantine table for rejected items. Name-only fallback paths for Fujifilm/Ozelle are removed entirely.

The gatekeeper fires AFTER `ProvenanceRecorder` captures raw data (preserving audit trail) but BEFORE data enters the matching pipeline. This ensures every rejected payload is traceable.

## Architecture Decisions

### Decision 1: SessionCodeExtractor location

| Option | Tradeoff | Decision |
|--------|----------|----------|
| `app/shared/session_code_extractor.py` | Shared, importable by all satellites | ✅ Adopted |
| Inline in each parser | Duplication, drift risk | Rejected |
| As mixin on parser classes | Over-engineering for one method | Rejected |

### Decision 2: Code extraction regex

| Option | Tradeoff | Decision |
|--------|----------|----------|
| `^[A-Z]\d+` | Catches "M5", "A105", "F2" — all historical patterns | ✅ Adopted |
| `^[A-Z]\d{1,2}$` | Current `_CODE_PATTERN` — too restrictive, misses "A105" | Rejected |
| `^[A-Z]\d+[\s-]?` | Catches "M5-KIARA", but strips separator we may need | Rejected — extract code, keep rest intact |

The pattern is `^[A-Z]\d+` — one uppercase letter followed by one or more digits at string START. The existing `_CODE_PATTERN = r'^[A-Z]\d{1,2}$'` must be widened.

### Decision 3: Extraction strategy per input format

- **"M5 KIARA"**: `split()[0]` → match → "M5"
- **"M5KIARA"**: `re.match(r'^([A-Z]\d+)', s)` → "M5"
- **"M5-KIARA"**: `re.match(r'^([A-Z]\d+)', s)` → "M5" (hyphen is not in `\d+`)
- **"KIARA"** (no code): `re.match(...)` → None → reject

### Decision 4: Gatekeeper call sites

| Source | Where gatekeeper fires | On failure |
|--------|----------------------|------------|
| Fujifilm | In `handle_uploaded_file()` case "fujifilm", AFTER `parse_fujifilm_message()` returns, before `process_fujifilm_message.send()` | Insert `DataQuarantine` row per failed reading; skip that reading |
| Ozelle | In `_async_process_pipeline()` (hl7_processor) AFTER `parse_hl7_message()` returns, before `_reception_service().receive()` | Insert `DataQuarantine` row; skip patient entirely |
| AppSheet | In `fetch_active_patients()`, AFTER provenance recording, before returning list | Filter invalid entries into quarantine list |

For live TCP flows (Ozelle MLLP, Fujifilm TCP), gatekeeper fires in the Dramatiq actor pipeline — not the TCP receiver — to avoid blocking the hot path.

### Decision 5: Quarantine → RawDataLog link

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Separate table, `raw_data_log_id` FK optional | Decoupled, no migration coupling, traceable via source+received_at | ✅ Adopted |
| Add status to RawDataLog and reuse | Schema coupling, changes existing audit model | Rejected |
| FK from DataQuarantine → RawDataLog (required) | Strong coupling, forces ordering (must RawDataLog exist first?) | Rejected |

`DataQuarantine` stores its own `raw_data` — duplication is acceptable because quarantine is admin-review data, not audit.

### Decision 6: Temporal check tolerance

5 seconds (`timedelta(seconds=5)`). Covers clock skew between machines and batch uploads where `received_at` is slightly before `created_at`. Higher ε would allow genuine "data revival" scenarios.

### Decision 7: Name-only fallback removal

Delete lines 216-286 (Fujifilm `.all() + len()==1`) and lines 287-354 (Ozelle `.all() + len()==1`) from `service.py`. These fallback paths are the root cause of Kiara/Rio.

## Data Flow

```
Source (Ozelle/Fujifilm/AppSheet)
  │
  ▼
ProvenanceRecorder ──► RawDataLog (audit, always recorded)
  │
  ▼
SessionCodeExtractor.extract()
  │
  ├── Code found? ──► proceeds to ReceptionService.receive()
  │                      │
  │                      ├── session_code match + temporal check ──► OK
  │                      │       received_at >= patient.created_at - 5s?
  │                      │       YES → attach data
  │                      │       NO  → quarantine (temporal_mismatch)
  │                      │
  │                      └── no match / new patient ──► create
  │
  └── No code? ──► DataQuarantine (pending)
                      │
                      ├── Admin force-match ──► session_code assigned, reprocess
                      ├── Admin discard ──► status=discarded
                      └── Admin retry ──► edit raw, revalidate
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `app/shared/models/data_quarantine.py` | Create | `DataQuarantine` SQLModel — `id`, `source`, `raw_data`, `received_at`, `rejection_reason`, `status` enum, `created_at`, `reviewed_at`, `reviewed_by`, `forced_session_code`, `patient_id` (nullable FK) |
| `app/services/session_code_extractor.py` | Create | `SessionCodeExtractor.extract(code_or_name: str) -> str \| None` |
| `app/domains/quarantine/router.py` | Create | HTMX endpoints: GET list, POST force-match, POST discard, POST retry |
| `app/templates/quarantine/list.html` | Create | Quarantine review page with per-row actions |
| `app/domains/reception/service.py` | Modify | Remove Fujifilm/Ozelle name-only fallback (lines 216-354); add temporal check after session_code match (line ~158) |
| `app/satellites/fujifilm/parser.py` | Modify | No structural change — gatekeeper runs in the pipeline, not inside parser |
| `app/satellites/ozelle/hl7_parser.py` | Modify | No structural change — gatekeeper runs in the pipeline, not inside parser |
| `app/services/appsheet.py` | Modify | Gatekeeper filter in `fetch_active_patients()` before returning list |
| `app/domains/reception/normalizer.py` | Modify | Widen `_CODE_PATTERN` from `^[A-Z]\d{1,2}$` to `^[A-Z]\d+$` |
| `app/tasks/hl7_processor.py` | Modify | Add gatekeeper call in `_async_process_pipeline()` after parse |
| `app/tasks/fujifilm_processor.py` | Modify | Add gatekeeper call in `process_fujifilm_message()` after parse |
| `app/shared/models/__init__.py` | Modify | Import `DataQuarantine` |
| `app/templates/base.html` | Modify | Add quarantine counter badge in navbar |
| `alembic/versions/` | Create | Migration for `dataquarantine` table |

## Interfaces / Contracts

```python
# app/services/session_code_extractor.py

class SessionCodeExtractor:
    """Extracts session code prefix from patient name strings."""

    PATTERN = re.compile(r'^([A-Z]\d+)')

    @staticmethod
    def extract(code_or_name: str) -> str | None:
        """Extract ^[A-Z]\d+ code prefix.
        
        "M5 KIARA"  → "M5"
        "M5KIARA"   → "M5"
        "M5-KIARA"  → "M5"
        "KIARA"     → None
        ""           → None
        """
        if not code_or_name or not code_or_name.strip():
            return None
        match = SessionCodeExtractor.PATTERN.match(code_or_name.strip())
        return match.group(1) if match else None
```

```python
# app/shared/models/data_quarantine.py

class QuarantineStatus(str, Enum):
    PENDING = "pending"
    REVIEWED = "reviewed"
    DISCARDED = "discarded"
    FORCED = "forced"

class DataQuarantine(SQLModel, table=True):
    __tablename__ = "dataquarantine"

    id: Optional[int] = Field(default=None, primary_key=True)
    source: str  # "ozelle" | "fujifilm" | "appsheet"
    raw_data: str  # Original payload (Text column)
    received_at: datetime
    rejection_reason: str  # "missing_code" | "invalid_code" | "temporal_mismatch"
    status: str = Field(default=QuarantineStatus.PENDING.value)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reviewed_at: Optional[datetime] = Field(default=None)
    reviewed_by: Optional[str] = Field(default=None)
    forced_session_code: Optional[str] = Field(default=None)  # Admin-assigned code
    patient_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("patient.id", ondelete="SET NULL"), nullable=True),
    )
```

```python
# Temporal check insertion in ReceptionService.receive() (after line ~158):

if existing_patient:
    # ── Temporal isolation check (R7) ──────────────────────────
    tolerance = timedelta(seconds=5)
    if raw_input.received_at < existing_patient.created_at - tolerance:
        logfire.alert(
            f"Temporal mismatch: data received {raw_input.received_at} "
            f"but patient created {existing_patient.created_at} "
            f"(session_code={lookup_code})"
        )
        # Insert quarantine record
        q = DataQuarantine(
            source=raw_input.source.value,
            raw_data=raw_input.raw_string,
            received_at=raw_input.received_at,
            rejection_reason="temporal_mismatch",
        )
        session.add(q)
        await session.commit()
        raise TemporalIsolationError(...)
    # ── end temporal check ─────────────────────────────────────
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `SessionCodeExtractor.extract()` | Parametrized: "M5 KIARA" → "M5", "KIARA" → None, "5M" → None, "A105" → "A105", "" → None |
| Unit | `DataQuarantine` model | Validation of status enum, default values, FK constraints |
| Unit | Temporal check logic | Mock `created_at` before/after `received_at` with 3s/5s/10s offsets |
| Integration | Gatekeeper in Ozelle pipeline | Full `parse_hl7_message()` + extractor with valid/invalid codes |
| Integration | Gatekeeper in Fujifilm pipeline | Full `parse_fujifilm_message()` + extractor with valid/invalid codes |
| Integration | `ReceptionService.receive()` without name fallback | Source=LIS_FUJIFILM with no session_code → creates new patient (no cross-contamination) |
| E2E | Admin quarantine review flow | HTMX: list pending → force-match → status=forced |
| E2E | Rejected data → quarantine row | Mock TCP input → check `DataQuarantine` table |

## Migration / Rollout

1. Create Alembic migration for `dataquarantine` table (reversible).
2. Deploy code changes behind no feature flag — gatekeeper enforcement is active immediately.
3. Monitor Logfire alerts for rejection volume. If operators report false positives:
   - Widen pattern from `^[A-Z]\d+` if needed (e.g., add `^[A-Z]\d{1,2}` as fallback).
   - Or increase temporal tolerance.
4. Quarantine UI deployed as additive — `/reception/quarantine/` endpoint does not change existing flows.

**Rollback**: Revert 5 files (service.py, normalizer.py, appsheet.py, hl7_processor.py, fujifilm_processor.py), reverse Alembic migration. No data loss because quarantine table only contains rejected items.

## Open Questions

- [ ] Should `SourceAdapter` (TCP layer) call the gatekeeper at the raw-message level, or is the Dramatiq-actor level sufficient? Current decision: actor level — keeps TCP hot path fast.
- [ ] What is the exact tolerance for temporal check in batch upload scenarios? 5s is the initial value — may need tuning in production.
