import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).parent

# Clave secreta para sesiones - en producción usar variable de entorno
SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))

# Clave AES-256 para encriptación de datos sensibles
# En producción, generar una vez y guardar en variable de entorno
AES_KEY_HEX = os.environ.get(
    "AES_KEY",
    "4a8f3c2e1d9b7a6f5e4d3c2b1a0f9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2"  # 64 hex chars = 32 bytes
)

DATABASE_URL = f"sqlite:///{BASE_DIR}/sige.db"

EXPORTS_DIR = BASE_DIR / "exports"
EXPORTS_DIR.mkdir(exist_ok=True)

TEMPLATES_DIR = BASE_DIR / "templates"

SESSION_MAX_AGE = 28800  # 8 horas

APP_NAME = "SIGE - Sistema Integral de Gestión Escolar"
APP_VERSION = "1.0.0"

# Configuración del colegio (editable desde settings)
DEFAULT_SCHOOL_NAME = "Unidad Educativa"
DEFAULT_SCHOOL_RIF = "J-00000000-0"
DEFAULT_NOTA_MINIMA = 10.0
DEFAULT_ESCALA_MAXIMA = 20.0
