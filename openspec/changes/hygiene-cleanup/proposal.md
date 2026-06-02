# Proposal: Hygiene & Cleanup Audit

## Intent

Restore test suite reliability (75 broken), relocate root-level utility to `app/shared/`, and remove dead code from recent refactors.

## Scope

### In Scope
1. Fix ~75 AppSheet authority tests — fixtures need `appsheet_confirmed=True` before machine-source creation.
2. Move `clinical_standards.py` → `app/shared/` — update 51 imports, fix JSON data path, keep hot-reload.
3. Fix or delete `test_jornada_api.py` (broken import from modo-automático refactor).
4. Deduplicate `_KNOWN_SUFFIXES` / `_PART_PATTERN` from `taller/` (budget permitting).
5. Git hygiene — `git rm --cached` `.coverage`/`__pycache__`; update `.gitignore`.
6. Replace inline HTMX div at `reception/router.py:37`.

### Out of Scope
Copro/cito separation, auth, modo-automático, Alembic migrations, cross-domain coupling refactors.

## Capabilities

No spec-level behavior changes — pure refactor/cleanup.

### New Capabilities
None.

### Modified Capabilities
None.

## Approach

| Objective | Strategy |
|-----------|----------|
| Broken tests | Update factories with `appsheet_confirmed=True`. Add ~5 quarantine-scenario tests. No prod logic changes. |
| `clinical_standards.py` | Move file, mechanical replace on 51 imports. Fix data path via `Path(__file__).parent`. |
| `test_jornada_api.py` | Fix import or delete if vestigial. |
| Suffix dedup | Extract to `taller/_constants.py`, import in both sites. Last priority. |
| Git hygiene | Add patterns to `.gitignore`. `git rm --cached` tracked artifacts. |
| Inline div | Extract to template snippet or delete if dead. |

## Affected Areas

| Area | Impact |
|------|--------|
| `app/shared/clinical_standards.py` | New (relocated) |
| `tests/` (~45 files) | Modified — fixtures updated |
| `taller/service.py`, `taller/images.py` | Modified — suffix dedup |
| `reception/router.py` | Modified — inline div |
| `tests/integration/test_jornada_api.py` | Fixed or removed |
| `.gitignore` | Modified — new patterns |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| JSON path breaks hot-reload | Low | `Path(__file__).parent.resolve()` + integration test |
| Deduped constants diverge | Low | Single source + existing test coverage |
| 75-test batch masks regressions | Medium | Full suite before/after, verify no new failures |

## Rollback Plan

`git revert` on change commit. No schema changes — the root `clinical_standards.py` still exists until removal in the same commit.

## Dependencies

None.

## Success Criteria

- [ ] Full test suite: 0 failures, 0 errors
- [ ] `from app.shared.clinical_standards import ...` works at all 51 sites
- [ ] `data/clinical_standards.json` loads from new location (hot-reload intact)
- [ ] `test_jornada_api.py` collects + passes, or is deleted
- [ ] `.coverage` and `__pycache__` untracked
- [ ] Zero production behavior changes