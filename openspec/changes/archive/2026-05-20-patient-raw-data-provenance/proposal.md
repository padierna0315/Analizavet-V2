# Proposal: Raw Data Provenance System

## Intent

Raw source data is lost after parsing — can't debug or replay what the machine sent. Add a "black box" recorder.

## Scope

### In Scope
- `RawDataLog` table: raw payload per source → patient/test-result
- Capture hooks at 3 sources (AppSheet, Ozelle, Fujifilm)
- Async writes — never block live processing
- Raw data view in patient card
- Archive: rows survive retirement

### Out of Scope
- Gatekeeper/temporal isolation, replay engine, retention, encryption

## Capabilities

### New Capabilities
- `raw-data-provenance`: capture, store, and view raw incoming messages per patient per source

### Modified Capabilities
- None — pure additive, no spec-level behavior changes

## Approach

**Table**: Single `RawDataLog(id, patient_id[nullable], test_result_id[nullable], source, raw_payload TEXT, content_type, received_at, captured_at)`. JSON blob, polymorphic by `source`.

**Capture**:
| Source | Hook | Mechanism |
|--------|------|-----------|
| AppSheet | `fetch_active_patients()` after `.json()` | Sync write, same session |
| Ozelle | `process_hl7_message` actor | Fire-and-forget Dramatiq actor |
| Fujifilm | `FujifilmAdapter._process_message()` | Same fire-and-forget |

**Performance**: Ozelle/Fujifilm writes are fully async via separate Dramatiq actor — never blocks the pipeline. AppSheet writes same session, no extra commit.

**Linking**: `patient_id` starts NULL (raw often arrives before patient exists). Backfill at archive time. No FK cascade — raw data survives deletion.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `app/shared/models/raw_data_log.py` | New | Model |
| `app/satellites/ozelle/mllp_server.py` | Mod | Capture raw HL7 |
| `app/satellites/fujifilm/adapter.py` | Mod | Capture raw line |
| `app/services/appsheet.py` | Mod | Capture raw JSON |
| `app/tasks/hl7_processor.py` | Mod | Recording actor |
| `app/tasks/fujifilm_processor.py` | Mod | Recording actor |
| `app/domains/provenance/` | New | `ProvenanceRecorder` |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| KB/day payload storage | Low | ~300KB/day at 100 patients — negligible |
| NULL patient_id FKs | Low | Nullable, no FK cascade |
| Queue overload | Low | Best-effort actor, no retries |

## Rollback Plan

1. Remove recording actors — recordings stop
2. Drop `RawDataLog` table
3. No side effects on processed data

## Dependencies

- Alembic migration
- Dramatiq (already present)

## Success Criteria

- [ ] Every incoming message has a corresponding `RawDataLog` row
- [ ] UI displays raw payload per source per patient
- [ ] `PatientArchive` retirement includes associated raw data
- [ ] Zero throughput regression on live reception pipeline (logfire timing)
