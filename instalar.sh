#!/usr/bin/env bash
# ================================================================
#  SIGE v1.0 — Instalador automático
#  Probado en: Ubuntu 20.04+, Debian 11+, Arch Linux, Kali Linux
# ================================================================
set -e

GREEN='\033[0;32m'; GOLD='\033[0;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $1"; }
info() { echo -e "${GOLD}→${NC} $1"; }
err()  { echo -e "${RED}✗ ERROR:${NC} $1"; exit 1; }

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║        SIGE — Sistema Integral de Gestión Escolar        ║"
echo "║                  Instalador v1.0                         ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Detect Python ─────────────────────────────────────────────────────────────
PYTHON=""
for cmd in python3.12 python3.11 python3.10 python3; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done
[ -z "$PYTHON" ] && err "Python 3.10+ no encontrado. Instálalo con: sudo apt install python3"
PY_VER=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
ok "Python encontrado: $PYTHON ($PY_VER)"

# ── Virtual environment ───────────────────────────────────────────────────────
VENV_DIR="$(dirname "$0")/venv"
if [ ! -d "$VENV_DIR" ]; then
    info "Creando entorno virtual..."
    $PYTHON -m venv "$VENV_DIR" || err "No se pudo crear venv. Instala: sudo apt install python3-venv"
    ok "Entorno virtual creado en $VENV_DIR"
else
    ok "Entorno virtual existente reutilizado"
fi

source "$VENV_DIR/bin/activate"

# ── Install dependencies ──────────────────────────────────────────────────────
info "Instalando dependencias Python..."
pip install --quiet --upgrade pip
pip install --quiet \
    flask==3.1.0 \
    werkzeug==3.1.0 \
    reportlab==4.4.0 \
    cryptography>=42.0.0 \
    itsdangerous>=2.0.0

ok "Dependencias instaladas"

# ── Initialize database ───────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -f "sige.db" ]; then
    info "Inicializando base de datos..."
    python3 seed_demo.py
    ok "Base de datos creada con datos de prueba"
else
    info "Base de datos existente detectada — omitiendo inicialización"
fi

# ── Create run script ─────────────────────────────────────────────────────────
cat > "$SCRIPT_DIR/arrancar.sh" << 'INNER'
#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/venv/bin/activate"
cd "$SCRIPT_DIR"
echo ""
echo "  SIGE — Sistema Integral de Gestión Escolar"
echo "  ──────────────────────────────────────────"
echo "  URL:       http://127.0.0.1:5000"
echo "  Red local: http://$(hostname -I | awk '{print $1}'):5000"
echo "  Usuario:   admin"
echo "  Clave:     Admin2024!"
echo ""
exec python3 app.py
INNER
chmod +x "$SCRIPT_DIR/arrancar.sh"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║                  INSTALACIÓN COMPLETA                   ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo -e "  Para arrancar el sistema:"
echo -e "  ${GOLD}./arrancar.sh${NC}"
echo ""
echo -e "  Acceso: ${GREEN}http://127.0.0.1:5000${NC}"
echo -e "  Usuario: ${GREEN}admin${NC}  |  Clave: ${GREEN}Admin2024!${NC}"
echo ""
