# Proposal: Patient Data Isolation Architecture

## Intent

Prevent patient data cross-contamination and "data revival" in the veterinary lab system. Data from one patient MUST NEVER attach to another, and old data MUST NOT silently attach to newly created patients.

The Kiara/Rio incident: Fujifilm data arrived without session_code, fell back to name-only matching, and `.first()` returned the wrong patient. The `reception-fallback-matching` spec partially fixes that, but the architecture lacks defense-in-depth.

## Scope

### In Scope
- Session code validation at EVERY data source entry point (Fujifilm, Ozelle, AppSheet, manual)
- Temporal isolation between incoming data and patient creation time
- Quarantine mechanism for data that fails validation
- Provenance tracking for machine-to-patient data lineage
- Audit trail and admin review for quarantined data
- Operational safety: changes deployable to a live system without downtime

### Out of Scope
- Database migration for existing contaminated data (manual cleanup)
- Patient merge/consolidation tool (separate concern)
- Changes to PDF or report generation
- UI redesign beyond quarantine review interface

## Capabilities

### New Capabilities
- `data-provenance-tracking`: Track every raw message from machine → parsed → stored, with status and audit trail
- `data-quarantine`: Quarantine and review interface for lab data that fails validation
- `code-validation-gatekeeper`: Enforce [Letter]+[Number] session_code format at every data source entry point

### Modified Capabilities
- `reception-fallback-matching`: Add temporal cross-check to matching logic (data cannot attach to a patient created after the data's timestamp)

## Architectural Approaches

### Approach A — Gatekeeper Pattern (Code-First Enforcement)

**Concept**: Every parser rejects data that lacks a valid `^[A-Z]\d+$` code prefix. No code = no entry. Data is either dropped (with logfire alert) or routed to quarantine.

**Changes**:
- `satellites/fujifilm/parser.py`: validate `patient_name` starts with `^[A-Z]\d+\s+.+`. If not, return empty list + logfire error.
- `satellites/ozelle/hl7_parser.py`: validate `sample_id` (PID[3] or extracted prefix) matches `^[A-Z]\d+$`. If not, raise `HL7ParsingError`.
- `domains/reception/normalizer.py`: `_extract_name_and_code` already validates; make it a REJECTION gate, not a silent None.
- `domains/reception/service.py`: remove the Fujifilm/Ozelle name-only fallback paths entirely (lines 186–316). If no session_code, no match.

| Pros | Cons |
|------|------|
| Zero ambiguity — if data has no code, it's stopped | Breaking change for operators who forget to prefix |
| Simplest code change (parser-only, no schema changes) | Legitimate data without codes is silently dropped |
| Prevents Kiara/Rio at the boundary | Fujifilm data without code requires operator retraining |
| No DB migration needed | Operator MUST ALWAYS prefix the name — human error risk |

**Complexity**: Low (pure validation logic, no DB changes)
**Risk**: Medium-High (breaking for existing workflow — data is dropped, not caught)
**Would prevent Kiara/Rio?**: YES — Fujifilm data without "M5 KIARA" prefix would be rejected entirely

---

### Approach B — Temporal Isolation + Source Binding

**Concept**: Lab data can ONLY attach to a patient if the patient existed (was created in DB) BEFORE the data's `received_at` timestamp. A ±ε tolerance for real-time TCP (same-second matching). Source binding: Fujifilm `internal_id` + Ozelle `sample_id` are tracked to prevent replay.

**Changes**:
- Add `patient_created_at` check to `service.py` `receive()`: when matching by session_code, verify `received_at >= patient.created_at - timedelta(seconds=5)`.
- Add `DataReceipt` table: `(id, source, internal_id, session_code, raw_hash, received_at, patient_id FK nullable, status)`.
- On data arrival INSERT receipt with `status=pending`, then on successful match UPDATE `patient_id`. If no match within X hours, flag `status=orphan`.
- For Fujifilm: `internal_id` is globally unique per patient + machine run. Track it — reject if same internal_id already bound to a DIFFERENT patient.

| Pros | Cons |
|------|------|
| Prevents "data revival" by design — 4-day-old data cannot attach to new patient | Requires schema migration (new table) |
| Source binding prevents replay attacks / duplicate processing | Slightly more complex matching logic |
| Orphan detection gives operators visibility | Temporal window needs tuning for batch uploads |
| Backward compatible — existing data works, new data gets receipts | Minor latency on INSERT for every incoming message |

**Complexity**: Medium-High (new table, new matching logic, migration)
**Risk**: Low-Medium (additive — existing paths unchanged, new constraints only active for new data)
**Would prevent Kiara/Rio?**: PARTIAL + CONDITIONAL — only if the data's `received_at` falls outside the patient's temporal window. If same-day, the temporal check alone wouldn't catch it. Source binding (internal_id tracking) would.

---

### Approach C — Data Provenance Pipeline (Full Audit Trail)

**Concept**: Every raw message from every machine is recorded in a `DataProvenance` table before any processing. The pipeline becomes: raw → store → validate → match → enrich. All steps are logged with timestamps. Failed validations are visible in an admin panel.

**Changes**:
- New model `DataProvenance`: `(id, source, raw_message TEXT, raw_hash, internal_id, session_code, patient_id FK nullable, received_at, parsed_at, status: pending|matched|quarantined|rejected, rejection_reason, matched_at, matched_by: code|name|temporal)`
- Insert BEFORE any processing (at TCP adapter level for Fujifilm, at HL7 receipt for Ozelle)
- `service.py` `receive()` reads FROM provenance, not directly from parser
- Quarantine: status=quarantined data is visible in a new `/reception/quarantine` endpoint
- Admin: review, force-match, or purge quarantined items

| Pros | Cons |
|------|------|
| Complete audit trail — every datapoint traceable to its raw message | Highest implementation cost |
| Quarantine prevents data loss (unlike Approach A) | Requires migration AND new UI |
| Temporal + code + source binding all in one | Storage overhead for raw messages (text) |
| Admin review for edge cases — non-breaking | Operator workflow change (quarantine review becomes a step) |

**Complexity**: High (new models, new endpoints, new UI, migration)
**Risk**: Low (additive — existing processing unchanged, new data only)
**Would prevent Kiara/Rio?**: YES — data without code goes to quarantine, not to name matching. Admin reviews and either adds code or discards.

---

### Approach D — Layered Defense (RECOMMENDED)

**Concept**: Combine the three approaches above into deployable layers. Layer 1 ships first (highest impact, lowest risk), Layer 2 ships next, Layer 3 when UI resources are available.

**Layer 1 — Code Rejection + Temporal Check (ship immediately)**:
- Gate at parsers: reject `patient_name` without `^[A-Z]\d+` prefix for Fujifilm and Ozelle (gatekeeper).
- In `service.py` `receive()`, add temporal cross-check: `received_at >= patient.created_at`.
- Remove name-only fallback entirely from Fujifilm/Ozelle paths. If no session_code match, create a NEW patient (don't reuse by name).
- **Logfire alert on every rejection** so operators know instantly.

**Layer 2 — Data Receipt Tracking (ship after 1 stabilizes)**:
- `DataReceipt` table: captures every incoming message BEFORE processing.
- Fields: `(id, source, internal_id, session_code, raw_preview, received_at, status, patient_id, rejection_reason)`.
- No raw full text (keeps storage low), just enough for traceability.
- `status=quarantined` for failed validations.

**Layer 3 — Quarantine UI (ship when needed)**:
- Simple Jinja2/HTMX page: list quarantined items, show code + patient_name + received_at.
- Actions: "Force match to patient X", "Discard", "Edit session_code and retry".
- Uses existing HTMX patterns already in the codebase.

| Pros | Cons |
|------|------|
| Ship Layer 1 TODAY — minimal code changes, immediate protection | Layer 1 means data without codes creates NEW patients (more DB rows) |
| Incremental: each layer adds defense without breaking previous | Quarantine UI is extra work (but optional) |
| Temporal check costs almost nothing (add one condition) | Requires operator discipline on code prefixes |
| Name-only fallback removal directly prevents the Kiara/Rio class | Existing data with same names + no codes will create duplicates (but that's CORRECT behavior — no cross-contamination) |

**Complexity**: Low (Layer 1) → Medium (Layer 2) → Medium-High (Layer 3)
**Risk**: Low (each layer is additive, existing data paths preserved as fallback)
**Would prevent Kiara/Rio?**: YES — Layer 1 alone prevents it. No name-only fallback = no cross-contamination.

## Recommended Approach: Layered Defense (D)

### Why This One

1. **Livesystem safety**: Layer 1 changes are minimal and reversible. The parser gate + temporal check + name-fallback removal touch ~50 lines of code. No migration. No new tables. If something goes wrong, revert 3 files.

2. **Directly prevents the incident class**: The root cause was name-only matching. Removing it for machine sources (Fujifilm, Ozelle) eliminates the attack surface. The code-must-exist-and-match-first is the only path.

3. **Handles "data revival"**: The temporal check (`received_at >= patient.created_at`) prevents old data from attaching to new patients. If an archived patient is restored, `created_at` stays the same (it's never updated on restore), so old data still matches.

4. **No data loss**: Unlike pure Gatekeeper (A), which silently drops, our fallback when there's no code → CREATE a new patient. The data is stored (to a new patient), not lost. The quarantine layer (2-3) gives operators a tool to fix it post-hoc.

5. **Operator-friendly transition**: Existing operators prefixing "M5 KIARA" continue to work exactly the same. Only the edge case of "KIARA" without code changes behavior (creates a new patient instead of contaminating M5).

### Risk & Rollback

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Operator forgets code → duplicate patient instead of cross-contamination | Medium | Logfire alert + quarantine UI (Layer 2-3) lets them fix it |
| Temporal check too aggressive for batch uploads | Low | Use `received_at` per-record, not per-batch; ε=5s tolerance |
| Revert: restore name-fallback path and remove temporal check | Trivial | Revert 3 files, no data loss |

## Success Criteria

- [ ] Fujifilm data without `^[A-Z]\d+` code prefix creates a NEW patient (no cross-contamination)
- [ ] Ozelle data without valid session_code creates a NEW patient (no cross-contamination)
- [ ] Lab data with `received_at` older than `patient.created_at` is REJECTED (temporal check)
- [ ] Existing "M5 KIARA" / "F3 RIO" flow is UNCHANGED (code present → match by code)
- [ ] Logfire alert fires on every rejection/fallback-to-new-patient
- [ ] All existing tests pass; new tests cover temporal rejection and code-gate rejection
- [ ] Quarantine UI (Layer 3) lists rejected items with review actions
