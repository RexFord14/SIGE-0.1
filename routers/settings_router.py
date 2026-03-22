"""
SIGE – Settings Router  /configuracion/
Gestión de: PIN de seguridad, cuentas bancarias del colegio,
            estadísticas de almacenamiento de imágenes
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from werkzeug.security import check_password_hash, generate_password_hash
from database import db
from auth import login_required, permission_required, current_user, audit
from services.image_service import get_storage_stats, cleanup_orphans

bp = Blueprint("settings", __name__, url_prefix="/configuracion")


@bp.route("/")
@login_required
@permission_required("admin", "view")
def index():
    user = current_user()
    with db() as conn:
        accounts = conn.execute(
            "SELECT * FROM bank_accounts ORDER BY bank, account_holder"
        ).fetchall()
        has_pin = conn.execute(
            "SELECT key FROM system_settings WHERE key='security_pin_hash'"
        ).fetchone() is not None
    stats = get_storage_stats()
    return render_template("settings/index.html",
        user=user, accounts=accounts, has_pin=has_pin, stats=stats)


@bp.route("/pin/cambiar", methods=["POST"])
@login_required
@permission_required("admin", "edit")
def change_pin():
    """
    Cambia el PIN de seguridad.
    Requiere PIN actual para confirmar (excepto si no hay PIN configurado).
    El nuevo PIN se guarda como hash Werkzeug en system_settings.
    NUNCA se guarda en texto plano ni en archivo separado.
    """
    user    = current_user()
    old_pin = request.form.get("old_pin", "")
    new_pin = request.form.get("new_pin", "")
    confirm = request.form.get("confirm_pin", "")

    if len(new_pin) != 4 or not new_pin.isdigit():
        flash("El PIN debe ser exactamente 4 dígitos", "error")
        return redirect(url_for("settings.index"))

    if new_pin != confirm:
        flash("Los PINs no coinciden", "error")
        return redirect(url_for("settings.index"))

    with db() as conn:
        existing = conn.execute(
            "SELECT value FROM system_settings WHERE key='security_pin_hash'"
        ).fetchone()

        # Si ya existe un PIN, verificar el actual
        if existing:
            if not check_password_hash(existing["value"], old_pin):
                flash("El PIN actual es incorrecto", "error")
                return redirect(url_for("settings.index"))

        new_hash = generate_password_hash(new_pin)
        conn.execute("""
            INSERT INTO system_settings(key, value, updated_at)
            VALUES('security_pin_hash', ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """, (new_hash,))
        audit(conn, "UPDATE", "admin", "system_settings", None,
              None, {"action": "pin_changed", "by": user["username"]})

    flash("PIN de seguridad actualizado", "success")
    return redirect(url_for("settings.index"))


@bp.route("/cuentas/nueva", methods=["POST"])
@login_required
@permission_required("admin", "edit")
def new_account():
    user = current_user()
    with db() as conn:
        conn.execute("""
            INSERT INTO bank_accounts
                (bank, account_number, account_holder, account_type, rif)
            VALUES (?,?,?,?,?)
        """, (
            request.form["bank"],
            request.form["account_number"],
            request.form["account_holder"],
            request.form.get("account_type", "CORRIENTE"),
            request.form.get("rif", ""),
        ))
        aid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        audit(conn, "INSERT", "admin", "bank_accounts", aid,
              None, {"bank": request.form["bank"],
                     "holder": request.form["account_holder"]})
    flash("Cuenta bancaria registrada", "success")
    return redirect(url_for("settings.index"))


@bp.route("/cuentas/<int:aid>/toggle", methods=["POST"])
@login_required
@permission_required("admin", "edit")
def toggle_account(aid):
    with db() as conn:
        conn.execute("UPDATE bank_accounts SET active=1-active WHERE id=?", (aid,))
    return redirect(url_for("settings.index"))


@bp.route("/imagenes/limpiar", methods=["POST"])
@login_required
@permission_required("admin", "edit")
def cleanup_images():
    with db() as conn:
        removed = cleanup_orphans(conn)
    flash(f"Limpieza completada: {removed} archivo(s) huérfano(s) eliminado(s)", "success")
    return redirect(url_for("settings.index"))
