# Analizavet V2

Aplicación de laboratorio clínico veterinario personal.
Desarrollada por Santiago (veterinario) para su uso exclusivo.

## Qué hace
- Recibe datos de analizadores de laboratorio (Ozelle HL7, Fujifilm) via MLLP TCP o archivo .txt
- Registra pacientes con sus resultados de laboratorio
- Procesa y despliega resultados en el Taller con valores de referencia y flags
- Genera PDFs de reportes clínicos por paciente

## Flujo de trabajo diario
1. Abrir `iniciar.sh` → la app arranca en http://localhost:8000
2. Opcionalmente: click en 🔴 del navbar para conectar las máquinas LIS (Ozelle puerto 6000, Fujifilm puerto 6001)
3. Subir archivos .txt manualmente (workaround hasta conectar máquinas en laboratorio)
4. Procesar pacientes en el Taller
5. Generar PDF por paciente al final de la jornada

## Stack técnico
- **Backend**: FastAPI + SQLModel + SQLite
- **Frontend**: HTMX + Jinja2 (sin JavaScript framework)
- **PDF**: WeasyPrint
- **Laboratorio**: Dramatiq + Redis (solo cuando MLLP activo), adaptadores Ozelle/Fujifilm
- **Entorno**: Python 3.11 + uv

## Arquitectura — Screaming Architecture
```
app/
├── domains/          # Un dominio = una carpeta con TODO lo suyo
│   ├── reception/    # Recepción de pacientes y uploads
│   ├── taller/       # Procesamiento de resultados de laboratorio
│   ├── patients/     # Gestión de pacientes
│   ├── reports/      # Generación de PDFs
│   ├── mllp/         # Control de máquinas LIS (botón navbar)
│   └── health/       # Health check
├── shared/           # Código compartido entre dominios
│   ├── models/       # Modelos SQLModel compartidos
│   └── algorithms/   # Algoritmos clínicos (valores de referencia, flags)
├── satellites/       # Adaptadores de máquinas (Ozelle HL7, Fujifilm)
├── tasks/            # Procesadores Dramatiq (MLLP)
├── templates/        # Templates Jinja2 por dominio
├── static/           # CSS, JS, imágenes
├── main.py           # Entry point FastAPI
├── database.py       # Configuración SQLite
├── config.py         # Dynaconf settings
└── mllp_state.py     # Estado compartido de máquinas LIS
```

## Configuración
Variables en `settings.toml`:
- `MLLP_ENABLED = false` — si true, arranca Redis + Dramatiq + adaptadores al inicio
- `LOGFIRE_ENABLED = false` — si true, activa observabilidad Logfire

## Iniciar la app
```bash
./iniciar.sh
```
Sin Redis, sin Dramatiq. Solo FastAPI. Si necesitas MLLP:
```bash
MLLP_ENABLED=true ./iniciar.sh
```
O usa el botón 🔴/🟢 en el navbar una vez que la app está corriendo.

## Estado actual (v0)
- ✅ Upload de archivos .txt (Ozelle y Fujifilm)
- ✅ Sala de espera (recepción de pacientes)
- ✅ Taller con valores de referencia y flags
- ✅ Generación de PDF por paciente
- ✅ Botón MLLP en navbar para conectar/desconectar máquinas
- ✅ Extracción y almacenamiento de imágenes de analizador
- 🔲 Integración MLLP TCP en laboratorio (pendiente prueba real)
- 🔲 Imágenes en PDF (pendiente decisión de diseño)
- 🔲 JSON "recepcionista" para bautizo de pacientes (pendiente formato con médicos)
- 🔲 Valores de referencia actualizados (en curso)
- 🔲 Plantilla visual del PDF (en curso)

## Pendientes conocidos
Ver issues en engram (#715 archivado, #717 archivado).

## Notas de desarrollo
- NO usar `--reload` con uvicorn — WeasyPrint es incompatible
- `uv run` para todos los comandos Python
- Tests automatizados: no existen aún — verificación manual
- Las imágenes de analizador se guardan en `images/` pero NO se incluyen en el PDF todavía
