"""Authentication, session management and RBAC"""
import jwt, datetime, functools
from flask import session, redirect, url_for, request, abort, g
from database import db

SECRET_KEY = "SIGE_SECRET_CHANGE_IN_PRODUCTION_2024"

def login_user(user_row):
    session.permanent = True
    session["user_id"] = user_row["id"]
    session["username"] = user_row["username"]
    session["full_name"] = user_row["full_name"]
    session["role_id"] = user_row["role_id"]

def logout_user():
    session.clear()

def current_user():
    if "user_id" not in session:
        return None
    return {"id": session["user_id"], "username": session["username"],
            "full_name": session["full_name"], "role_id": session["role_id"]}

def get_user_permissions(role_id):
    with db() as conn:
        rows = conn.execute("""
            SELECT p.module, p.action FROM permissions p
            JOIN role_permissions rp ON rp.permission_id = p.id
            WHERE rp.role_id = ?
        """, (role_id,)).fetchall()
    return {(r["module"], r["action"]) for r in rows}

def has_permission(module, action):
    user = current_user()
    if not user:
        return False
    perms = get_user_permissions(user["role_id"])
    return (module, action) in perms

def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not current_user():
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated

def permission_required(module, action):
    def decorator(f):
        @functools.wraps(f)
        def decorated(*args, **kwargs):
            if not current_user():
                return redirect(url_for("auth.login"))
            if not has_permission(module, action):
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator

def audit(conn, action, module, entity, entity_id=None, old_val=None, new_val=None):
    import json
    user = current_user()
    uid = user["id"] if user else None
    uname = user["username"] if user else "system"
    ip = request.remote_addr if request else "127.0.0.1"
    conn.execute("""
        INSERT INTO audit_log(user_id,username,action,module,entity,entity_id,old_value,new_value,ip_address)
        VALUES(?,?,?,?,?,?,?,?,?)
    """, (uid, uname, action, module, entity, entity_id,
          json.dumps(old_val) if old_val else None,
          json.dumps(new_val) if new_val else None, ip))
