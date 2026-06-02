# Proposal: Modo Automático (Headless Console Operator)

## Intent
Veterinario opera Analizavet V2 sin navegador — solo terminal. AppSheet sincroniza cada 30s, datos de máquinas se monitorean, cuarentenas reprocesadas, descargas por tecla 'r'.

## Scope

### In
1. Prompt "¿Modo automático?" en iniciar.sh — fork headless.
2. `app/auto_mode.py` — polling 30s AppSheet, monitoreo, key listener, descarga.
3. `GET /jornada/adelanto` — read-only, no limpia log.
4. `app/domains/auto/` — `GET /auto/status`.
5. Tecla 'r' → "ADELANTO o FINAL?" → .txt.

### Out
- UI web, adaptadores MLLP, Dramatiq, PDF, DB models.
- Dashboard TUI/ncurses.
- Sincronización AppSheet existente.

## Capabilities

### New
- `headless-console`: app/auto_mode.py.
- `jornada-adelanto`: GET /jornada/adelanto.
- `auto-status`: GET /auto/status.

### Modified
- `iniciar-script`: prompt + fork condicional.

## Approach

Mínima invasión DDD. 4 puntos:

1. **iniciar.sh**: tras verify_all, `read -p "¿Modo automático? [s/n]"`. Si 's', `tail -f uvicorn.log &` + `uv run python app/auto_mode.py`; salta open_browser.

2. **auto_mode.py** (httpx + select.select): bucle 30s llama `POST /reception/appsheet/sync`, `GET /auto/status`. `select.select` stdin detecta 'r' → pausa, prompt ADELANTO/FINAL, guarda .txt en `data/descargas/`.

3. **GET /jornada/adelanto**: `get_jornada_results()` + `format_report()`, omitir `clear_jornada_log()`. Header "HASTA AHORA".

4. **GET /auto/status**: JSON con `patients_waiting_count`, `jornada_entries`, `last_sync_at`, `last_reprocess_at`.

Cuarentena ya la maneja AppSheetService. auto_mode solo reporta.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `iniciar.sh` | Modified | Prompt + fork |
| `app/auto_mode.py` | **New** | Bucle headless |
| `app/domains/auto/` | **New** | router + init |
| `app/domains/jornada/router.py` | Modified | /jornada/adelanto |
| `app/domains/jornada/service.py` | Modified | wrapper sin clear |
| `app/main.py` | Modified | register auto |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Race web+consola | Low | Adelanto read-only. Final idempotente. |
| Tecla 'r' capturada | Low | select.select + termios raw mode. |
| Polling excede cuota AppSheet | Low | 30s = 120 req/h, límite ~200 req/h. |
| auto_mode.py sin supervisión | Med | Foreground, Ctrl+C detiene todo. |

## Rollback
- `git checkout iniciar.sh app/main.py app/domains/jornada/{router,service}.py`
- `git rm -r app/auto_mode.py app/domains/auto/`
- Sin DB migrations → inmediato.

## Dependencies
- httpx (existente), select + termios (stdlib).

## Success Criteria
- [ ] iniciar.sh modo 's' no abre navegador
- [ ] auto_mode.py sincroniza AppSheet cada 30s
- [ ] Consola reporta pacientes nuevos y reprocess
- [ ] 'r' → ADELANTO/FINAL → .txt guardado
- [ ] ADELANTO no limpia log; FINAL sí
- [ ] Tests (786) pasan
- [ ] Todo headless — sin browser
