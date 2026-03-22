from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import check_password_hash, generate_password_hash
from database import db
from auth import login_user, logout_user, current_user, login_required, audit

bp = Blueprint("auth", __name__)

@bp.route("/login", methods=["GET","POST"])
def login():
    if current_user():
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        with db() as conn:
            user = conn.execute("SELECT * FROM users WHERE username=? AND active=1", (username,)).fetchone()
            if user and check_password_hash(user["password_hash"], password):
                login_user(user)
                audit(conn, "LOGIN", "auth", "users", user["id"])
                return redirect(url_for("dashboard.index"))
            flash("Usuario o contraseña incorrectos", "error")
    return render_template("login.html")

@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
