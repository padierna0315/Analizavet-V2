#!/bin/bash
set -e

MLLP_ENABLED="${MLLP_ENABLED:-false}"

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

echo "🚀 Iniciando Analizavet V2 (Fase Desarrollo - uv)"

# 0. Instalar dependencias del sistema (WeasyPrint, etc)
if command -v apt-get &> /dev/null; then
    echo "🔍 Verificando dependencias del sistema (Debian/Ubuntu)..."
    if ! dpkg -s libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 libffi-dev shared-mime-info curl &> /dev/null; then
        echo "📦 Instalando dependencias del sistema (requiere contraseña de administrador)..."
        sudo apt-get update && sudo apt-get install -y libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 libffi-dev shared-mime-info curl
    else
        echo "✅ Dependencias del sistema OK"
    fi
elif command -v dnf &> /dev/null; then
    echo "🔍 Verificando dependencias del sistema (Fedora)..."
    if ! rpm -q cairo pango pango-devel gdk-pixbuf2 libffi-devel shared-mime-info curl &> /dev/null; then
        echo "📦 Instalando dependencias del sistema (requiere contraseña de administrador)..."
        sudo dnf install -y cairo pango pango-devel gdk-pixbuf2 libffi-devel shared-mime-info curl
    else
        echo "✅ Dependencias del sistema OK"
    fi
fi

# 1. Verificar/instalar uv
if ! command -v uv &> /dev/null; then
    echo "📦 Instalando uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source $HOME/.cargo/env
fi

# 2. Verificar Python 3.11
if ! uv run python --version | grep -q "3.11"; then
    echo "⚠️  Requiere Python 3.11. Instalando..."
    uv python install 3.11
fi

# 3. Crear entorno virtual si no existe
if [ ! -d ".venv" ]; then
    echo "🔧 Creando entorno virtual..."
    uv venv .venv
fi

# 4. Instalar dependencias desde pyproject.toml (uv.lock gestiona versiones exactas)
echo "📥 Instalando dependencias..."
uv sync

# 4.1 Configurar archivo de secretos
if [ ! -f ".secrets.toml" ]; then
    echo "🔑 Configurando archivo de secretos inicial..."
    if [ -f ".secrets.toml.example" ]; then
        cp .secrets.toml.example .secrets.toml
    else
        touch .secrets.toml
    fi
fi

# 4.2 Descargar navegadores para Playwright (necesario para los tests E2E)
echo "🌐 Verificando navegadores de Playwright para tests..."
uv run playwright install chromium

# 4.3 Inicializar/Actualizar Base de Datos
echo "🗄️ Actualizando esquema de base de datos..."
uv run alembic upgrade head

# 5. Verificar que existe la carpeta static (CRITICAL per skill-santiago Leccion #1)
if [ ! -d "app/static" ]; then
    echo "📁 Creando directorio static/..."
    mkdir -p app/static/css app/static/js app/static/images
fi

# 6. Crear directorio images si no existe
if [ ! -d "images" ]; then
    echo "📁 Creando directorio images/..."
    mkdir -p images
fi

# 7. Verificar Redis para Dramatiq
if [ "$MLLP_ENABLED" = "true" ]; then
    echo "🔍 Verificando Redis..."
    if ! redis-cli ping &> /dev/null; then
        echo "⚠️  Redis no está corriendo. Iniciando Redis..."
        redis-server --daemonize yes
        sleep 2
        if redis-cli ping | grep -q "PONG"; then
            echo "✅ Redis iniciado correctamente"
        else
            echo "❌ No se pudo iniciar Redis. Instálalo con: sudo apt install redis-server"
            exit 1
        fi
    else
        echo "✅ Redis ya está corriendo"
    fi
fi

# 8. Limpiar puertos 9191/9200 (Prometheus middleware) antes de iniciar worker
if [ "$MLLP_ENABLED" = "true" ]; then
    echo "Limpiando puertos 9191/9200..."
    lsof -ti:9191 -ti:9200 2>/dev/null | xargs -r kill 2>/dev/null || fuser -k 9191/tcp 9200/tcp 2>/dev/null || true
fi

# 9. Iniciar Dramatiq worker en segundo plano
if [ "$MLLP_ENABLED" = "true" ]; then
    echo "🎭 Iniciando worker de Dramatiq..."
    uv run dramatiq app.tasks.broker:broker --threads 2 &
    DRAMATIQ_PID=$!
    sleep 3

    # Verify Dramatiq is running
    if kill -0 $DRAMATIQ_PID 2>/dev/null; then
        echo "✅ Worker de Dramatiq iniciado (PID: $DRAMATIQ_PID)"
    else
        echo "❌ Worker de Dramatiq falló al iniciar"
        exit 1
    fi
fi

# 9. Iniciar servidor FastAPI
echo "🌐 Iniciando servidor FastAPI..."
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 &
SERVER_PID=$!
sleep 3

# Verify uvicorn is running
if kill -0 $SERVER_PID 2>/dev/null; then
    echo "✅ Proceso FastAPI iniciado (PID: $SERVER_PID)"
else
    echo "❌ Proceso FastAPI falló al iniciar"
    exit 1
fi

# Verify uvicorn responds to health checks
echo "⏳ Esperando servidor..."
for i in {1..30}; do
    if curl -s http://localhost:8000/health &> /dev/null; then
        echo "✅ Servidor FastAPI corriendo en http://localhost:8000"
        echo "🔥 Logfire activo — observa los logs en esta terminal"
        break
    fi
    sleep 0.5
done

# 11. Abrir Firefox (sin bloquear terminal - skill-santiago Regla #4)
echo "🦊 Abriendo navegador..."
nohup firefox --new-tab http://localhost:8000 > /dev/null 2>&1 &

echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║  ✅ Analizavet V2 corriendo en http://localhost:8000   ║"
echo "║                                                         ║"
echo "║  Para detener:                                         ║"
echo "║    - Presiona Ctrl+C para detener todo                  ║"
echo "║    - O ejecuta: kill $SERVER_PID $DRAMATIQ_PID          ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

# Mantener script vivo
trap "echo ''; echo '🛑 Deteniendo servicios...'; kill $SERVER_PID $DRAMATIQ_PID 2>/dev/null || true; exit 0" SIGINT SIGTERM
wait $SERVER_PID
