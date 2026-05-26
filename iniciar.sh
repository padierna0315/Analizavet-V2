#!/bin/bash
# Analizavet V2 — Iniciador robusto y a prueba de balas
# Autor: Santiago | Uso: 1 veterinario, 2 máquinas
#
# Características:
# - Limpieza exhaustiva de procesos previos
# - Verificación paso a paso con rollback automático
# - Logs separados para cada servicio
# - Health checks reales antes de declarar éxito
# - Session marker actualizado (modo simple: data/jornada-session.json)

set -euo pipefail

# ═════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═════════════════════════════════════════════════════════════════════════════
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
LOGS_DIR="${APP_DIR}/logs"
mkdir -p "${LOGS_DIR}"

UVICORN_LOG="${LOGS_DIR}/uvicorn.log"
DRAMATIQ_LOG="${LOGS_DIR}/dramatiq.log"
REDIS_LOG="${LOGS_DIR}/redis.log"
PIDFILE="${LOGS_DIR}/analizavet.pid"

# Puertos
PORT_UVICORN=8000
PORT_REDIS=6379
PORT_OZELLE=6000
PORT_FUJIFILM=6001

# Timeouts (segundos)
TIMEOUT_REDIS=10
TIMEOUT_UVICORN=30
TIMEOUT_HEALTH=15

# ═════════════════════════════════════════════════════════════════════════════
# FUNCIONES AUXILIARES
# ═════════════════════════════════════════════════════════════════════════════

log() {
    echo "[$(date '+%H:%M:%S')] $*"
}

error() {
    echo "[$(date '+%H:%M:%S')] ❌ ERROR: $*" >&2
}

success() {
    echo "[$(date '+%H:%M:%S')] ✅ $*"
}

warn() {
    echo "[$(date '+%H:%M:%S')] ⚠️  $*"
}

# Matar proceso por nombre (con fuerza si es necesario)
kill_by_name() {
    local name="$1"
    local pids
    pids=$(pgrep -f "$name" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        log "   Matando procesos '$name' (PIDs: $pids)..."
        echo "$pids" | xargs kill -TERM 2>/dev/null || true
        sleep 1
        # Verificar si todavía viven
        local survivors
        survivors=$(pgrep -f "$name" 2>/dev/null || true)
        if [ -n "$survivors" ]; then
            log "   Forzando matanza de '$name' (PIDs: $survivors)..."
            echo "$survivors" | xargs kill -KILL 2>/dev/null || true
        fi
    fi
}

# Verificar si un puerto está libre
is_port_free() {
    local port="$1"
    ! lsof -ti :"$port" > /dev/null 2>&1
}

# Esperar a que un puerto esté libre
wait_for_port_free() {
    local port="$1"
    local timeout="${2:-5}"
    local waited=0
    while ! is_port_free "$port" && [ "$waited" -lt "$timeout" ]; do
        sleep 0.5
        waited=$((waited + 1))
    done
    is_port_free "$port"
}

# Verificar si Redis responde
redis_ping() {
    python3 -c "import redis; print(redis.Redis(host='localhost', port=${PORT_REDIS}).ping())" 2>/dev/null | grep -q "True"
}

# Verificar health del servidor
server_health() {
    curl -sf http://localhost:${PORT_UVICORN}/health > /dev/null 2>&1
}

# Guardar PIDs
save_pid() {
    local name="$1"
    local pid="$2"
    echo "${name}:${pid}" >> "$PIDFILE"
}

# Leer PID por nombre
read_pid() {
    local name="$1"
    grep "^${name}:" "$PIDFILE" 2>/dev/null | cut -d: -f2 | tail -1
}

# Rollback: matar todo lo que iniciamos
rollback() {
    error "Iniciando rollback — matando servicios iniciados..."
    if [ -f "$PIDFILE" ]; then
        while IFS=: read -r name pid; do
            if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
                log "   Matando $name (PID: $pid)..."
                kill -TERM "$pid" 2>/dev/null || true
                sleep 1
                kill -KILL "$pid" 2>/dev/null || true
            fi
        done < "$PIDFILE"
        rm -f "$PIDFILE"
    fi
    # Limpiar contenedor Redis
    podman rm -f redis-analizavet 2>/dev/null || true
    error "Rollback completo. Saliendo."
}

# ═════════════════════════════════════════════════════════════════════════════
# LIMPIEZA EXHAUSTIVA
# ═════════════════════════════════════════════════════════════════════════════

cleanup() {
    log "🧹 Limpieza exhaustiva..."
    
    # Limpiar archivo de PIDs previo
    rm -f "$PIDFILE"
    
    # Matar procesos por nombre (con variaciones posibles)
    kill_by_name "uvicorn.*app.main"
    kill_by_name "dramatiq.*broker"
    kill_by_name "dramatiq.*WorkerProcess"
    
    # Liberar puertos específicos
    for port in "$PORT_UVICORN" "$PORT_REDIS" "$PORT_OZELLE" "$PORT_FUJIFILM" 9191 9200; do
        if ! is_port_free "$port"; then
            local pids
            pids=$(lsof -ti tcp:"$port" 2>/dev/null || true)
            if [ -n "$pids" ]; then
                log "   Liberando puerto $port (PIDs: $pids)..."
                echo "$pids" | xargs kill -KILL 2>/dev/null || true
            fi
        fi
    done
    
    # Esperar a que los puertos estén realmente libres
    local all_free=true
    for port in "$PORT_UVICORN" "$PORT_REDIS"; do
        if ! wait_for_port_free "$port" 5; then
            warn "Puerto $port sigue ocupado después de limpieza"
            all_free=false
        fi
    done
    
    # Limpiar contenedor Redis previo
    if podman ps -a --format "{{.Names}}" 2>/dev/null | grep -q "redis-analizavet"; then
        log "   Eliminando contenedor Redis anterior..."
        podman rm -f redis-analizavet > /dev/null 2>&1 || true
    fi
    
    if [ "$all_free" = true ]; then
        success "Limpieza completa"
    else
        warn "Algunos puertos no se liberaron completamente"
    fi
}

# ═════════════════════════════════════════════════════════════════════════════
# VERIFICACIONES PREVIAS
# ═════════════════════════════════════════════════════════════════════════════

prechecks() {
    log "🔍 Verificaciones previas..."
    
    cd "$APP_DIR"
    
    # Verificar directorio
    if [ ! -f "app/main.py" ]; then
        error "No se encontró app/main.py — ¿estás en el directorio correcto?"
        exit 1
    fi
    
    # Verificar uv
    if ! command -v uv &> /dev/null; then
        error "'uv' no encontrado. Instálalo: curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi
    
    # Verificar .venv
    if [ ! -d ".venv" ]; then
        warn "Entorno virtual no encontrado. Creando..."
        uv venv .venv
    fi
    
    # Verificar dependencias Python
    if ! uv run python -c "import fastapi" 2>/dev/null; then
        warn "Dependencias Python no instaladas. Instalando..."
        uv sync
    fi
    
    # Verificar Podman o Redis nativo
    if command -v podman &> /dev/null; then
        success "Podman disponible"
    elif command -v redis-server &> /dev/null; then
        success "Redis nativo disponible"
    else
        error "Se requiere Podman O redis-server. Instala: sudo dnf install podman"
        exit 1
    fi
    
    success "Verificaciones OK"
}

# ═════════════════════════════════════════════════════════════════════════════
# INICIAR REDIS
# ═════════════════════════════════════════════════════════════════════════════

start_redis() {
    log "🟥 Iniciando Redis..."
    
    if command -v redis-server &> /dev/null && redis-cli ping &> /dev/null; then
        success "Redis nativo ya está corriendo"
        return 0
    fi
    
    if command -v podman &> /dev/null; then
        # Usar Podman
        podman run -d --replace --name redis-analizavet \
            -p "${PORT_REDIS}:${PORT_REDIS}" \
            docker.io/redis:7-alpine > /dev/null 2>&1
        
        # Esperar a que Redis responda
        local waited=0
        while ! redis_ping && [ "$waited" -lt "$TIMEOUT_REDIS" ]; do
            sleep 0.5
            waited=$((waited + 1))
        done
        
        if redis_ping; then
            success "Redis corriendo (Podman)"
            return 0
        else
            error "Redis no respondió después de ${TIMEOUT_REDIS}s"
            return 1
        fi
    fi
    
    error "No se pudo iniciar Redis"
    return 1
}

# ═════════════════════════════════════════════════════════════════════════════
# INICIAR DRAMATIQ
# ═════════════════════════════════════════════════════════════════════════════

start_dramatiq() {
    log "🎭 Iniciando worker de Dramatiq..."
    
    # Verificar que Redis esté vivo
    if ! redis_ping; then
        error "Redis no está disponible — no se puede iniciar Dramatiq"
        return 1
    fi
    
    # Iniciar con nohup para que sobreviva a la terminal
    nohup bash -c "cd '${APP_DIR}' && DRAMATIQ_PROMETHEUS_PORT=-1 .venv/bin/dramatiq app.tasks.broker:broker --threads 1" \
        > "$DRAMATIQ_LOG" 2>&1 &
    local pid=$!
    
    # Esperar a que el proceso esté realmente vivo
    local waited=0
    while ! kill -0 "$pid" 2>/dev/null && [ "$waited" -lt 5 ]; do
        sleep 0.5
        waited=$((waited + 1))
    done
    
    if kill -0 "$pid" 2>/dev/null; then
        save_pid "dramatiq" "$pid"
        success "Dramatiq iniciado (PID: $pid)"
        
        # Esperar a que los workers estén listos
        sleep 2
        if grep -q "Worker process is ready" "$DRAMATIQ_LOG" 2>/dev/null; then
            success "Workers de Dramatiq listos"
        else
            warn "Dramatiq inició pero workers pueden no estar listos todavía"
        fi
        
        return 0
    else
        error "Dramatiq falló al iniciar. Ver log: $DRAMATIQ_LOG"
        return 1
    fi
}

# ═════════════════════════════════════════════════════════════════════════════
# INICIAR SERVIDOR FASTAPI
# ═════════════════════════════════════════════════════════════════════════════

start_server() {
    log "🌐 Iniciando servidor FastAPI..."
    
    # Verificar que el puerto esté libre
    if ! is_port_free "$PORT_UVICORN"; then
        error "Puerto $PORT_UVICORN sigue ocupado después de limpieza"
        return 1
    fi
    
    # Iniciar con nohup para que sobreviva a la terminal
    nohup bash -c "cd '${APP_DIR}' && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT_UVICORN} --log-level info" \
        > "$UVICORN_LOG" 2>&1 &
    local pid=$!
    
    # Esperar a que el proceso esté vivo
    local waited=0
    while ! kill -0 "$pid" 2>/dev/null && [ "$waited" -lt 5 ]; do
        sleep 0.5
        waited=$((waited + 1))
    done
    
    if ! kill -0 "$pid" 2>/dev/null; then
        error "Uvicorn falló al iniciar. Ver log: $UVICORN_LOG"
        return 1
    fi
    
    save_pid "uvicorn" "$pid"
    log "   Uvicorn iniciado (PID: $pid), esperando health check..."
    
    # Esperar health check
    waited=0
    while ! server_health && [ "$waited" -lt "$TIMEOUT_HEALTH" ]; do
        sleep 0.5
        waited=$((waited + 1))
    done
    
    if server_health; then
        success "Servidor FastAPI corriendo en http://localhost:${PORT_UVICORN}"
        return 0
    else
        error "Servidor no respondió al health check después de ${TIMEOUT_HEALTH}s"
        error "Ver log: $UVICORN_LOG"
        return 1
    fi
}

# ═════════════════════════════════════════════════════════════════════════════
# VERIFICACIÓN FINAL
# ═════════════════════════════════════════════════════════════════════════════

verify_all() {
    log "🔍 Verificación final..."
    local all_ok=true
    
    # Verificar Redis
    if redis_ping; then
        success "Redis OK"
    else
        error "Redis NO responde"
        all_ok=false
    fi
    
    # Verificar Dramatiq (por PID)
    local dramatiq_pid
    dramatiq_pid=$(read_pid "dramatiq")
    if [ -n "$dramatiq_pid" ] && kill -0 "$dramatiq_pid" 2>/dev/null; then
        success "Dramatiq OK (PID: $dramatiq_pid)"
    else
        error "Dramatiq NO está corriendo"
        all_ok=false
    fi
    
    # Verificar servidor
    if server_health; then
        success "FastAPI OK"
        # Mostrar respuesta del health check
        local health_response
        health_response=$(curl -s http://localhost:${PORT_UVICORN}/health)
        log "   Health: $health_response"
    else
        error "FastAPI NO responde"
        all_ok=false
    fi
    
    if [ "$all_ok" = true ]; then
        return 0
    else
        return 1
    fi
}

# ═════════════════════════════════════════════════════════════════════════════
# ABrir NAVEGADOR
# ═════════════════════════════════════════════════════════════════════════════

open_browser() {
    log "🦊 Abriendo navegador..."
    
    local url="http://localhost:${PORT_UVICORN}"
    
    # Intentar varios navegadores
    if command -v firefox &> /dev/null; then
        nohup firefox --new-tab "$url" > /dev/null 2>&1 &
        success "Firefox abierto"
    elif command -v chromium-browser &> /dev/null; then
        nohup chromium-browser --new-tab "$url" > /dev/null 2>&1 &
        success "Chromium abierto"
    elif command -v google-chrome &> /dev/null; then
        nohup google-chrome --new-tab "$url" > /dev/null 2>&1 &
        success "Chrome abierto"
    elif command -v xdg-open &> /dev/null; then
        nohup xdg-open "$url" > /dev/null 2>&1 &
        success "Navegador por defecto abierto"
    else
        warn "No se encontró navegador. Abre manualmente: $url"
    fi
}

# ═════════════════════════════════════════════════════════════════════════════
# DETENER SERVICIOS (Ctrl+C)
# ═════════════════════════════════════════════════════════════════════════════

stop_all() {
    log ""
    log "🛑 Deteniendo servicios..."
    
    # Matar procesos guardados
    if [ -f "$PIDFILE" ]; then
        while IFS=: read -r name pid; do
            if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
                log "   Deteniendo $name (PID: $pid)..."
                kill -TERM "$pid" 2>/dev/null || true
            fi
        done < "$PIDFILE"
        sleep 1
        # Forzar si es necesario
        while IFS=: read -r name pid; do
            if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
                log "   Forzando $name (PID: $pid)..."
                kill -KILL "$pid" 2>/dev/null || true
            fi
        done < "$PIDFILE"
        rm -f "$PIDFILE"
    fi
    
    # Limpiar Redis
    podman rm -f redis-analizavet > /dev/null 2>&1 || true
    
    success "Servicios detenidos"
}

# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════

main() {
    # Si no hay terminal (doble clic en GUI), abrir en Konsole
    if [ ! -t 0 ]; then
        if command -v konsole &> /dev/null; then
            konsole --noclose -e "$0" "$@"
            exit 0
        else
            xterm -e "$0" "$@"
            exit 0
        fi
    fi
    
    # Banner
    echo ""
    echo "╔══════════════════════════════════════════════════════════════════╗"
    echo "║  🚀 Analizavet V2 — Iniciador Robusto                          ║"
    echo "║  Modo: $(if command -v podman &>/dev/null; then echo "Podman"; else echo "Nativo"; fi) | Usuario: 1 | Máquinas: 2            ║"
    echo "╚══════════════════════════════════════════════════════════════════╝"
    echo ""
    
    # Trap para detener todo al salir (Ctrl+C)
    trap 'stop_all; exit 0' SIGINT SIGTERM EXIT
    
    # 1. LIMPIEZA
    cleanup
    
    # 2. VERIFICACIONES
    prechecks || { error "Verificaciones fallidas"; exit 1; }
    
    # 3. INICIAR SERVICIOS (con rollback si algo falla)
    start_redis || { rollback; exit 1; }
    start_dramatiq || { rollback; exit 1; }
    start_server || { rollback; exit 1; }
    
    # 4. VERIFICACIÓN FINAL
    if ! verify_all; then
        error "Verificación final falló"
        rollback
        exit 1
    fi
    
    # 5. ABRIR NAVEGADOR
    open_browser
    
    # 6. MARCAR INICIO DE SESIÓN (modo simple: tocar archivo jornada-session.json)
    if [ ! -f "${APP_DIR}/data/jornada-session.json" ]; then
        echo '[]' > "${APP_DIR}/data/jornada-session.json"
        log "📄 Archivo de jornada inicializado"
    fi
    
    # Banner final
    echo ""
    echo "╔══════════════════════════════════════════════════════════════════╗"
    echo "║  ✅ SISTEMA LISTO                                               ║"
    echo "║                                                                 ║"
    echo "║  🌐 http://localhost:${PORT_UVICORN}                                    ║"
    echo "║  📋 Logs: ${LOGS_DIR}/                                    ║"
    echo "║                                                                 ║"
    echo "║  Presiona Ctrl+C para detener todo                              ║"
    echo "╚══════════════════════════════════════════════════════════════════╝"
    echo ""
    
    # Mantener script vivo mostrando logs
    log "📊 Mostrando logs de uvicorn (Ctrl+C para detener)..."
    echo "─────────────────────────────────────────────────────────────────────"
    tail -f "$UVICORN_LOG" 2>/dev/null &
    local tail_pid=$!
    
    # Esperar Ctrl+C
    wait
}

# Ejecutar
main "$@"
