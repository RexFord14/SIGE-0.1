"""
SIGE - Admin Router  /administracion/  v1.4
Cambios:
  - Redirige a #hash correcto tras cada POST (usuario cae en la pestaña correcta)
  - Eliminada pestaña Secciones (ya no existen desde v1.3)
  - Seeding de materias por curriculo venezolano al crear un curso sin materias
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from werkzeug.security import generate_password_hash
from database import db
from auth import login_required, permission_required, current_user, audit

bp = Blueprint("admin", __name__, url_prefix="/administracion")

# Curriculo base por tipo de nivel y grado
_CURRICULUM_PRIMARY_1_3 = ['Matemáticas','Lengua y Literatura','Ciencias Naturales',
                           'Ciencias Sociales','Educación Física','Arte']
_CURRICULUM_PRIMARY_4_6 = ['Matemáticas','Lengua y Literatura','Ciencias Naturales',
                           'Ciencias Sociales','Educación Física','Arte','Inglés']
_CURRICULUM_SECONDARY_1_3 = ['Matemáticas','Castellano','Inglés','Biología',
                             'Historia','Geografía','Informática','Educación Física']
_CURRICULUM_SECONDARY_4_5 = ['Matemáticas','Castellano','Inglés','Física','Química',
                             'Biología','Historia','Filosofía','Educación Física']


def _seed_subjects(conn, course_id, level, grade):
    """Agrega materias del currículo venezolano si el curso no tiene ninguna."""
    existing = conn.execute(
        "SELECT COUNT(*) as n FROM subjects WHERE course_id=?", (course_id,)
    ).fetchone()["n"]
    if existing > 0:
        return
    if level == 'PRIMARY':
        subjects = _CURRICULUM_PRIMARY_4_6 if grade >= 4 else _CURRICULUM_PRIMARY_1_3
    else:
        subjects = _CURRICULUM_SECONDARY_4_5 if grade >= 4 else _CURRICULUM_SECONDARY_1_3
    for name in subjects:
        conn.execute("INSERT INTO subjects(name,course_id) VALUES(?,?)", (name, course_id))


@bp.route("/")
@login_required
@permission_required("admin", "view")
def index():
    user = current_user()
    with db() as conn:
        users = conn.execute("""
            SELECT u.*, r.label as role_label FROM users u
            JOIN roles r ON r.id=u.role_id ORDER BY u.full_name
        """).fetchall()
        roles = conn.execute("SELECT * FROM roles ORDER BY label").fetchall()
        school_years = conn.execute("SELECT * FROM school_years ORDER BY name DESC").fetchall()
        courses = conn.execute("""
            SELECT c.*, COUNT(sub.id) as num_subjects
            FROM courses c LEFT JOIN subjects sub ON sub.course_id=c.id
            GROUP BY c.id ORDER BY c.level DESC, c.grade
        """).fetchall()
        subjects = conn.execute("""
            SELECT sub.*, c.name as course_name FROM subjects sub
            JOIN courses c ON c.id=sub.course_id
            ORDER BY c.level DESC, c.grade, sub.name
        """).fetchall()
        lapsos = conn.execute("""
            SELECT l.*, sy.name as year_name FROM lapsos l
            JOIN school_years sy ON sy.id=l.school_year_id
            ORDER BY sy.name, l.name
        """).fetchall()
    return render_template("admin/index.html",
        user=user, users=users, roles=roles,
        school_years=school_years, courses=courses,
        subjects=subjects, lapsos=lapsos)


# ── USUARIOS ──────────────────────────────────────────────────────────────────

@bp.route("/usuario/nuevo", methods=["POST"])
@login_required
@permission_required("admin", "edit")
def new_user():
    with db() as conn:
        try:
            conn.execute("""
                INSERT INTO users(username, password_hash, full_name, role_id)
                VALUES(?,?,?,?)
            """, (request.form["username"],
                  generate_password_hash(request.form["password"]),
                  request.form["full_name"],
                  request.form["role_id"]))
            flash("Usuario creado correctamente", "success")
        except Exception:
            flash("El nombre de usuario ya existe", "error")
    return redirect(url_for("admin.index") + "#users")


@bp.route("/usuario/<int:uid>/reset", methods=["POST"])
@login_required
@permission_required("admin", "edit")
def reset_password(uid):
    new_pw = request.form.get("new_password", "")
    if len(new_pw) < 8:
        flash("La contraseña debe tener al menos 8 caracteres", "error")
        return redirect(url_for("admin.index") + "#users")
    with db() as conn:
        conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                     (generate_password_hash(new_pw), uid))
    flash("Contraseña actualizada", "success")
    return redirect(url_for("admin.index") + "#users")


@bp.route("/usuario/<int:uid>/toggle", methods=["POST"])
@login_required
@permission_required("admin", "edit")
def toggle_user(uid):
    with db() as conn:
        conn.execute("UPDATE users SET active=1-active WHERE id=?", (uid,))
    return redirect(url_for("admin.index") + "#users")


# ── AÑO ESCOLAR ───────────────────────────────────────────────────────────────

@bp.route("/anio/nuevo", methods=["POST"])
@login_required
@permission_required("admin", "edit")
def new_year():
    with db() as conn:
        try:
            conn.execute(
                "INSERT INTO school_years(name) VALUES(?)",
                (request.form["name"],)
            )
            flash("Año escolar creado", "success")
        except Exception:
            flash("Ya existe un año escolar con ese nombre", "error")
    return redirect(url_for("admin.index") + "#years")


@bp.route("/anio/<int:yid>/activate", methods=["POST"])
@login_required
@permission_required("admin", "edit")
def activate_year(yid):
    with db() as conn:
        conn.execute("UPDATE school_years SET active=0")
        conn.execute("UPDATE school_years SET active=1 WHERE id=?", (yid,))
    flash("Año escolar activado", "success")
    return redirect(url_for("admin.index") + "#years")


# ── LAPSOS ────────────────────────────────────────────────────────────────────

@bp.route("/lapso/nuevo", methods=["POST"])
@login_required
@permission_required("admin", "edit")
def new_lapso():
    with db() as conn:
        try:
            conn.execute(
                "INSERT INTO lapsos(school_year_id,name,start_date,end_date) VALUES(?,?,?,?)",
                (request.form["school_year_id"],
                 request.form["name"],
                 request.form.get("start_date") or None,
                 request.form.get("end_date") or None)
            )
            flash(f"Lapso '{request.form['name']}' creado", "success")
        except Exception as e:
            flash(f"Error al crear lapso: {e}", "error")
    return redirect(url_for("admin.index") + "#lapsos")


@bp.route("/lapso/<int:lid>/delete", methods=["POST"])
@login_required
@permission_required("admin", "edit")
def delete_lapso(lid):
    with db() as conn:
        try:
            # Verificar si tiene notas
            has_grades = conn.execute(
                "SELECT COUNT(*) as n FROM grades WHERE lapso_id=?", (lid,)
            ).fetchone()["n"]

            if has_grades:
                flash("No se puede eliminar: el lapso tiene notas registradas.", "error")
            else:
                # Importante: Si no tiene notas, eliminamos su plan de evaluación primero
                conn.execute("DELETE FROM activity_types WHERE lapso_id=?", (lid,))
                # Luego eliminamos el lapso
                conn.execute("DELETE FROM lapsos WHERE id=?", (lid,))
                flash("Lapso eliminado correctamente.", "success")
        except Exception as e:
            flash(f"Error inesperado al eliminar: {str(e)}", "error")
            
    return redirect(url_for("admin.index") + "#lapsos")


# ── CURSOS ────────────────────────────────────────────────────────────────────

@bp.route("/curso/nuevo", methods=["POST"])
@login_required
@permission_required("admin", "edit")
def new_course():
    level = request.form.get("level", "PRIMARY")
    try:
        grade = int(request.form.get("grade", 1))
    except ValueError:
        grade = 1

    if level == "PRIMARY":
        suffixes = ["1er", "2do", "3er", "4to", "5to", "6to"]
        if grade < 1 or grade > 6:
            flash("Grado inválido para Primaria", "error")
            return redirect(url_for("admin.index") + "#courses")
        name = f"{suffixes[grade-1]} Grado"
    else:
        suffixes = ["1er", "2do", "3er", "4to", "5to"]
        if grade < 1 or grade > 5:
            flash("Año inválido para Secundaria", "error")
            return redirect(url_for("admin.index") + "#courses")
        name = f"{suffixes[grade-1]} Año"

    with db() as conn:
        try:
            # Verificar si ya existe este curso
            exists = conn.execute(
                "SELECT COUNT(*) as n FROM courses WHERE level=? AND grade=?", (level, grade)
            ).fetchone()["n"]
            
            if exists > 0:
                flash(f"El curso '{name}' ya existe en el sistema.", "error")
                return redirect(url_for("admin.index") + "#courses")

            conn.execute(
                "INSERT INTO courses(name,level,grade) VALUES(?,?,?)",
                (name, level, grade)
            )
            cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            _seed_subjects(conn, cid, level, grade)
            flash(f"Curso '{name}' creado con materias por defecto", "success")
        except Exception as e:
            flash(f"Error: {e}", "error")
    return redirect(url_for("admin.index") + "#courses")


# ── MATERIAS ──────────────────────────────────────────────────────────────────

@bp.route("/curso/<int:cid>/delete", methods=["POST"])
@login_required
@permission_required("admin", "edit")
def delete_course(cid):
    pin = request.form.get("delete_pin", "")
    
    with db() as conn:
        setting = conn.execute("SELECT value FROM system_settings WHERE key='security_pin_hash'").fetchone()
        from werkzeug.security import check_password_hash
        if not setting or not check_password_hash(setting["value"], pin):
            flash("PIN incorrecto para eliminar curso", "error")
            return redirect(url_for("admin.index") + "#courses")
            
        course = conn.execute("SELECT name FROM courses WHERE id=?", (cid,)).fetchone()
        if not course:
            flash("Curso no encontrado", "error")
            return redirect(url_for("admin.index") + "#courses")
            
        # Verificar si hay estudiantes inscritos
        students = conn.execute("""
            SELECT COUNT(*) as n FROM students s
            JOIN sections sec ON sec.id=s.section_id
            WHERE sec.course_id=?
        """, (cid,)).fetchone()["n"]
        
        if students > 0:
            flash(f"No se puede eliminar: el curso {course['name']} tiene {students} estudiante(s) inscrito(s).", "error")
            return redirect(url_for("admin.index") + "#courses")
            
        # Borrado en cascada (seguro porque no hay estudiantes)
        conn.execute("DELETE FROM activity_types WHERE subject_id IN (SELECT id FROM subjects WHERE course_id=?)", (cid,))
        conn.execute("DELETE FROM subjects WHERE course_id=?", (cid,))
        conn.execute("DELETE FROM sections WHERE course_id=?", (cid,))
        conn.execute("DELETE FROM courses WHERE id=?", (cid,))
        
        flash(f"Curso {course['name']} eliminado correctamente.", "success")
        
    return redirect(url_for("admin.index") + "#courses")

@bp.route("/materia/nueva", methods=["POST"])
@login_required
@permission_required("admin", "edit")
def new_subject():
    name      = request.form.get("name", "").strip()
    course_id = request.form.get("course_id", "")
    if not name or not course_id:
        flash("Nombre y curso son obligatorios", "error")
        return redirect(url_for("admin.index") + "#subjects")
    with db() as conn:
        conn.execute("INSERT INTO subjects(name,course_id) VALUES(?,?)", (name, course_id))
    flash(f"Materia '{name}' agregada", "success")
    return redirect(url_for("admin.index") + "#subjects")


@bp.route("/materia/<int:sid>/delete", methods=["POST"])
@login_required
@permission_required("admin", "edit")
def delete_subject(sid):
    with db() as conn:
        has_grades = conn.execute(
            "SELECT COUNT(*) as n FROM grades WHERE subject_id=?", (sid,)
        ).fetchone()["n"]
        if has_grades:
            flash("No se puede eliminar: tiene notas registradas", "error")
        else:
            conn.execute("DELETE FROM subjects WHERE id=?", (sid,))
            conn.execute("DELETE FROM activity_types WHERE subject_id=?", (sid,))
            flash("Materia eliminada", "success")
    return redirect(url_for("admin.index") + "#subjects")


# ── AUDIT LOG ─────────────────────────────────────────────────────────────────

@bp.route("/auditoria")
@login_required
@permission_required("admin", "view")
def audit_log():
    user = current_user()
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) as n FROM audit_log").fetchone()["n"]
        logs = conn.execute("""
            SELECT al.*, u.full_name as user_fullname FROM audit_log al
            LEFT JOIN users u ON u.id=al.user_id
            ORDER BY al.timestamp DESC LIMIT 200
        """).fetchall()
    return render_template("admin/audit_log.html", user=user, logs=logs,
                           total=total, per_page=200, current_page=1)
