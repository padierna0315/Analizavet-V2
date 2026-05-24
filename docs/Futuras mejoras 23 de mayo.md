# Futuras mejoras — 23 de mayo de 2026

## Contexto

Revisión de mantenibilidad del sistema Analizavet V2 (FastAPI + SQLModel + Dramatiq). Hallazgos de una exploración profunda del codebase luego de un burst de 8.178 líneas de cambios en los últimos 10 commits (provenance, quarantine, archivado, gatekeepers).

---

## 1. Centralizar lógica de flags en `clinical_standards.py`

### Situación actual

La evaluación de si un valor es ALTO, BAJO o NORMAL está duplicada en **tres lugares**:

| Archivo | Función | Qué hace |
|---|---|---|
| `clinical_standards.py` | *(ninguna)* | Solo datos + lookup helpers |
| `app/domains/taller/flagging.py` | `ClinicalFlaggingService.flag_value()` | 76 líneas. Resolve alias → busca range → compara min/max → retorna `FlagResult` |
| `app/shared/algorithms/registry.py` | `_determine_flag()` | 15 líneas. Mismo min/max comparison, retorna string |
| `app/shared/algorithms/registry.py` | `_build_reference_range()` | 11 líneas. Construye string `"min - max unit"` |
| `app/core/reference.py` | `get_reference_range()` | 27 líneas. Mismo lookup de range, formato casi idéntico |

### Problema

Si cambia un rango de referencia (ej: UREA felino ajustado), hay que tocar **3 archivos distintos**. Eso es boleto a bugs silenciosos. Además, `clinical_standards.py` debería ser la única fuente de verdad para TODO lo que es evaluación clínica.

### Propuesta

Agregar a `clinical_standards.py` dos funciones de puerta de entrada:

```python
SPECIES_MAP: Dict[str, str] = {
    "Canino": "canine", "Canina": "canine",
    "Felino": "feline", "Felina": "feline",
}

def get_reference_range(code: str, species: str) -> str:
    """Retorna string formateado 'min - max unit' o 'N/D'."""
    ...

def evaluate_flag(code: str, value: float, species: str) -> dict:
    """Evalúa un valor contra los rangos de referencia.
    
    Returns dict con: flag (ALTO/BAJO/NORMAL), reference_range, parameter_name, unit
    """
    ...
```

**Consumidores simplificados:**
- `ClinicalFlaggingService.flag_value()` → llama `evaluate_flag()` y construye el `FlagResult`
- `AlgorithmRegistry._determine_flag()` → `return evaluate_flag(code, value, species)["flag"]`
- `AlgorithmRegistry._build_reference_range()` → `return get_reference_range(code, species)`
- `core/reference.py` → delega directamente a `get_reference_range()`

### Ventaja

Un solo lugar para cambiar reglas de flagging. El JSON caliente (`data/clinical_standards.json`) sigue siendo la fuente de datos modificable desde la UI.

---

## 2. Partición de `ReceptionService` (928 líneas)

### Situación actual

`ReceptionService` tiene **7 responsabilidades mezcladas** en una sola clase:

1. Intake de pacientes (lookup, quarantine, registro) — `receive()` (~220 líneas)
2. Sincronización AppSheet — `sync_from_appsheet()` (~100 líneas)
3. Queries de sala de espera — `get_waiting_room_patients()`, `get_archived_patients()`, etc. (~180 líneas)
4. Merge de TestResults — `inject_patient_to_taller()` (~135 líneas)
5. Routing de archivos subidos — `handle_uploaded_file()` (~85 líneas)
6. Archivar/restaurar pacientes — `archive_all_active()`, etc. (~55 líneas)
7. Borrar pacientes — `delete_patient_from_waiting_room()` (~40 líneas)

### Problema

Cada nueva feature modifica `ReceptionService`. Merge conflicts, tests gigantes, y acoplamiento imposible de desenredar. `inject_patient_to_taller()` solo es 133 líneas de lógica de merge crítica que no tiene nada que ver con sincronización AppSheet.

### Propuesta: Estrategia Strangler Fig

Extraer responsabilidades **una por una**, manteniendo `ReceptionService` como **facade** que delega a los servicios especializados. Una vez que todo funcione, eliminar el facade si no es necesario.

**Orden de extracción (de menor riesgo a mayor):**

| Orden | Nuevo módulo | Métodos extraídos | Riesgo |
|---|---|---|---|
| 1 | `patient_archive.py` | `archive_all_active`, `restore_all_archived`, `restore_single_archived` | Bajo — solo UPDATEs de status |
| 2 | `waiting_room_queries.py` | `get_waiting_room_patients`, `get_archived_patients`, `get_single_patient_for_card` | Bajo — solo lecturas |
| 3 | `appsheet_sync.py` | `sync_from_appsheet`, `clear_all_active_patients` | Medio — lógica aislada de AppSheet |
| 4 | `file_upload_handler.py` | `handle_uploaded_file` | Medio — routing de archivos, ya tiene match/case |
| 5 | `test_result_merge.py` | `inject_patient_to_taller` | Medio-alto — lógica compleja pero bien encapsulada |
| 6 | `patient_intake.py` | `receive`, `_try_link_raw_data`, temporal isolation check | Alto — el core, dejar para último |

**Patrón por extracción:**

```python
# Paso 1: Crear clase especializada
class PatientArchiveService:
    async def archive_all_active(self, session): ...

# Paso 2: ReceptionService delega (facade)
class ReceptionService:
    def __init__(self):
        self._archive = PatientArchiveService()
    
    async def archive_all_active(self, session):
        return await self._archive.archive_all_active(session)

# Paso 3: Correr tests. Si pasan → siguiente extracción.
```

**Regla de oro:** Cada extracción debe ser **un commit separado** con tests pasando. No un PR monolítico.

---

## 3. Separación de capas

### Problema A: Service importa tasks directamente

`ReceptionService.handle_uploaded_file()` importa `app.tasks.hl7_processor` y en algunos caminos llama `_async_process_pipeline()` directamente, salteándose la cola de Dramatiq.

**Opción A (abstracta):** Crear un `TaskDispatcher` con interfaz abstracta. Mucho código ceremonial para un sistema de un solo desarrollador.

**Opción B (pragmática):** Mover la decisión de "¿proceso inline o por cola?" del **service** al **router**. El router conoce los tasks (es de infraestructura), el service no debería. El service solo recibe datos ya parseados.

**Recomendación:** Opción B. Menos código, mismo resultado, sin abstracciones innecesarias.

### Problema B: Routers construyen HTML inline

Los routers (`reception/router.py`, `main.py`) construyen strings HTML con f-strings en vez de usar Jinja2 templates (que ya están configurados en `app/templates/`).

**Ejemplo de smell:**
```python
cards_html += f"""
<div class="patient-card" ...>
  <p><strong>...</p>
"""
```

**Fix:** Usar `Jinja2Templates` consistentemente. Los routers solo validan input → llaman service → retornan `TemplateResponse`.

---

## 4. Otras mejoras identificadas

### `clinical_standards.py` — separar datos de lógica

El archivo tiene ~1400 líneas de dicts de datos embebidos en Python + funciones de lookup + I/O de JSON al importar. 

**Problema:** `VETERINARY_STANDARDS` es mutable global state. Si un test o handler llama `load_standards_from_json()`, afecta TODAS las requests concurrentes.

**Fix:** Mover los dicts hardcodeados a `data/clinical_standards.json` (ya existe parcialmente). El `.py` solo debe tener funciones de lookup. El JSON es read-only en runtime.

### Lazy imports en `ReceptionService`

```python
# Esto aparece en sync_from_appsheet (línea 348)
from app.domains.reception.baul import _normalize_for_comparison
```

Los imports lazy son señal de **circular dependencies**. Hay que resolver el acoplamiento circular, no esconderlo.

### Session marker basado en archivo

`app/domains/jornada/service.py` usa `/tmp/analizavet-session-start` como marcador de sesión. Rompe en:
- Despliegues containerizados (`/tmp` es efímero)
- Múltiples workers
- Reinicios del servidor

**Fix:** Tabla `jornada_session` en la base de datos, o Redis (ya está disponible para Dramatiq).

---

## Prioridad sugerida

1. **Centralizar flags** — cambio acotado, alto impacto en corrección, bajo riesgo.
2. **Extraer `patient_archive.py`** — más simple de todos, entrena el patrón Strangler Fig.
3. **Extraer `waiting_room_queries.py`** — solo lecturas, sin side effects.
4. **Mover HTML inline a templates** — hygiene técnica, previene XSS y mejora mantenibilidad.
5. **Extraer `appsheet_sync.py` y `file_upload_handler.py`** — responsabilidades bien delimitadas.
6. **Extraer `test_result_merge.py`** — lógica crítica, necesita tests dedicados.
7. **Extraer `patient_intake.py`** — el core, dejar para cuando todo lo demás esté estable.

---

## Score actual: 6.5 / 10

**Fortalezas:** Testing sólido, estructura de dominios clara, disciplina SDD/OpenSpec.
**Deuda:** God object (`ReceptionService`), duplicación de lógica de flags, violaciones de capas, acreción de features sin refactorización compensatoria.

**Meta:** Llegar a 8.5/10 después de completar items 1-5.
