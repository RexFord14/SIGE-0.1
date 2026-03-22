from flask import Blueprint, render_template, request, redirect, url_for, flash
from werkzeug.security import check_password_hash, generate_password_hash
from database import db
from auth import login_required, current_user, audit

bp = Blueprint("profile", __name__, url_prefix="/perfil")

@bp.route("/cambiar-clave", methods=["GET","POST"])
@login_required
def change_password():
    user = current_user()
    if request.method == "POST":
        old_pw = request.form.get("old_password","")
        new_pw = request.form.get("new_password","")
        confirm = request.form.get("confirm_password","")
        if new_pw != confirm:
            flash("Las contraseñas nuevas no coinciden", "error")
            return redirect(url_for("profile.change_password"))
        if len(new_pw) < 8:
            flash("La contraseña debe tener al menos 8 caracteres", "error")
            return redirect(url_for("profile.change_password"))
        with db() as conn:
            row = conn.execute("SELECT password_hash FROM users WHERE id=?", (user["id"],)).fetchone()
            if not check_password_hash(row["password_hash"], old_pw):
                flash("La contraseña actual es incorrecta", "error")
                return redirect(url_for("profile.change_password"))
            conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                (generate_password_hash(new_pw), user["id"]))
            audit(conn, "UPDATE", "admin", "users", user["id"], None, {"action":"password_change"})
            flash("Contraseña actualizada exitosamente", "success")
            return redirect(url_for("dashboard.index"))
    return render_template("change_password.html", user=user)
