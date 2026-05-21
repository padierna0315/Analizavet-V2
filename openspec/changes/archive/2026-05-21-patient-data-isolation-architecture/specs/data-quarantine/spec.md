# Data Quarantine Specification

## Purpose

Provide a safe holding area for lab data that fails gatekeeper validation or temporal checks, preventing data loss while enabling admin review and correction.

## Requirements

### Requirement: DataQuarantine table

The system SHOULD provide a `DataQuarantine` model with these fields:

| Field | Type | Description |
|-------|------|-------------|
| `id` | int (PK, auto) | Primary key |
| `source` | str | Source system (appsheet, ozelle, fujifilm, manual) |
| `raw_data` | text | Original payload (JSON, HL7, or raw string) |
| `received_at` | datetime | When the data was received |
| `rejection_reason` | str | Why it was rejected (e.g. "missing_code", "temporal_mismatch") |
| `status` | enum | One of: pending, reviewed, discarded, forced |
| `created_at` | datetime | When quarantine record was created |

#### Scenario: Gatekeeper rejection stored

- GIVEN "KIARA" arrives from Fujifilm without a code prefix
- WHEN the gatekeeper rejects it
- THEN a DataQuarantine row is created with `status=pending`, `rejection_reason="missing_code"`, `raw_data` preserving the original message

### Requirement: Quarantine review UI

The system SHOULD provide an HTMX-based quarantine review page at `/reception/quarantine/` that lists quarantined items with:

- Status badge (pending/reviewed/discarded/forced)
- Source label
- Raw data preview (truncated)
- Received timestamp
- Rejection reason
- Action buttons per item

| Action | Behavior |
|--------|----------|
| Force match | Admin assigns a session_code → data reprocessed as if it arrived with that code. Status → `forced`. |
| Discard | Admin confirms data is garbage → Status → `discarded`. No reprocessing. |
| Retry | Admin edits the raw_string/code → validation re-runs. Status → `reviewed` if passes. |

#### Scenario: Force match by admin

- GIVEN a quarantined item with `raw_data="KIARA"`, `status=pending`
- WHEN an admin assigns session_code "M5" and clicks force-match
- THEN the data is reprocessed as if "M5 KIARA" arrived
- AND `status` is set to `forced`

#### Scenario: Discard by admin

- GIVEN a quarantined item with `status=pending`
- WHEN an admin clicks discard
- THEN the item status is set to `discarded`
- AND no reprocessing occurs

### Requirement: Logfire alerts

Logfire MUST fire an alert on every gatekeeper rejection. The alert MUST include source, patient identifier (truncated), and rejection reason.

### Requirement: Dashboard quarantine counter

The system SHOULD display a count of pending quarantine items in the dashboard header (e.g. "⚠ 3 quarantined"). Clicking navigates to the quarantine review page.
