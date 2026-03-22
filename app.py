"""
SIGE – Flask Application Entry Point

Responsabilidades de este archivo:
  1. Crear la instancia Flask y configurar secret_key
  2. Registrar todos los Blueprints (cada módulo es un Blueprint)
  3. Definir filtros Jinja2 globales (currency, date_fmt)
  4. Registrar handlers de errores 403 y 404
  5. Inicializar la DB y arrancar el servidor

DECISIÓN: secret_key hardcoded en desarrollo.
EN PRODUCCIÓN: cargar desde variable de entorno o archivo .env
  app.secret_key = os.environ.get('SIGE_SECRET', 'fallback_inseguro')
"""
import os
from flask import Flask, render_template
from database import init_db

app = Flask(__name__, template_folder="templates", static_folder="static")

# CRÍTICO: cambiar antes de producción
# Esta clave firma las cookies de sesión (itsdangerous HMAC)
app.secret_key = os.environ.get(
    "SIGE_SECRET_KEY",
    "SIGE_DEV_SECRET_2024_CAMBIA_EN_PRODUCCION"
)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10MB max upload

# ── Registrar Blueprints ──────────────────────────────────────────────────────
# Cada blueprint corresponde a un módulo funcional
from routers.auth_router      import bp as auth_bp
from routers.dashboard_router import bp as dashboard_bp
from routers.students_router  import bp as students_bp
from routers.finance_router   import bp as finance_bp
from routers.academic_router  import bp as academic_bp
from routers.admin_router     import bp as admin_bp
from routers.reports_router   import bp as reports_bp
from routers.profile_router   import bp as profile_bp
from routers.settings_router  import bp as settings_bp

app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(students_bp)
app.register_blueprint(finance_bp)
app.register_blueprint(academic_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(profile_bp)
app.register_blueprint(settings_bp)

# ── Filtros Jinja2 ────────────────────────────────────────────────────────────
@app.template_filter("currency")
def currency_filter(value):
    """Formatea número como Bs.1.234,56"""
    try:
        return f"Bs.{float(value):,.2f}"
    except (TypeError, ValueError):
        return "Bs.0,00"

@app.template_filter("date_fmt")
def date_fmt_filter(value):
    """Convierte YYYY-MM-DD a DD/MM/YYYY para display"""
    if not value:
        return "—"
    try:
        from datetime import datetime
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return str(value)

# ── Error handlers ────────────────────────────────────────────────────────────
@app.errorhandler(403)
def forbidden(e):
    return render_template("errors/403.html"), 403

@app.errorhandler(404)
def not_found(e):
    return render_template("errors/404.html"), 404

@app.errorhandler(413)
def too_large(e):
    from flask import flash, redirect, url_for
    flash("El archivo es demasiado grande (máximo 10MB)", "error")
    return redirect(url_for("finance.index"))

# ── Arranque ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    print("\n" + "="*60)
    print("  SIGE - Sistema Integral de Gestión Escolar")
    print("  Servidor corriendo en: http://127.0.0.1:5000")
    print("  Usuario: admin  |  Contraseña: Admin2024!")
    print("="*60 + "\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
