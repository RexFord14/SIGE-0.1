"""
SIGE – Academic Router  /academico/  v1.4

CAMBIO v1.4:
  - grades(): elimina selector de sección completamente.
    El flujo es: seleccionar grado/año + lapso → aparecen TODOS los
    estudiantes del grado con TODAS las materias del curso en una
    sola tabla. Sin pasos intermedios.
  - attendance(): mismo cambio, course_id en vez de section_id.
  - assign_section(): sin cambios (ya usa course_id desde v1.3).
  - No se tocan las secciones en DB (compatibilidad), pero el usuario
    nunca las ve. Internamente los estudiantes siguen vinculados a una
    sección, que a su vez pertenece a un course_id.
"""
import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import db
from auth import login_required, permission_required, current_user, audit

bp = Blueprint("academic", __name__, url_prefix="/academico")


# ─────────────────────────────── HELPERS ─────────────────────────────────────

def _get_courses_with_students(conn, sy_id):
    """Retorna cursos que tienen al menos un estudiante activo."""
    return conn.execute("""
        SELECT c.id, c.name, c.level, c.grade,
               COUNT(DISTINCT s.id) as num_students
        FROM courses c
        INNER JOIN sections sec ON sec.course_id=c.id
            AND (sec.school_year_id=? OR ? IS NULL)
        INNER JOIN students s ON s.section_id=sec.id
            AND s.status NOT IN ('RETIRADO','EGRESADO')
        GROUP BY c.id
        ORDER BY c.level DESC, c.grade ASC
    """, (sy_id, sy_id)).fetchall()


def _get_all_courses(conn, sy_id):
    """Todos los cursos, tengan o no estudiantes."""
    return conn.execute("""
        SELECT c.id, c.name, c.level, c.grade,
               COUNT(DISTINCT s.id) as num_students
        FROM courses c
        LEFT JOIN sections sec ON sec.course_id=c.id
            AND (sec.school_year_id=? OR ? IS NULL)
        LEFT JOIN students s ON s.section_id=sec.id
            AND s.status NOT IN ('RETIRADO','EGRESADO')
        GROUP BY c.id
        ORDER BY c.level DESC, c.grade ASC
    """, (sy_id, sy_id)).fetchall()


def _students_of_course(conn, course_id, sy_id):
    """Todos los estudiantes activos de un grado/año."""
    return conn.execute("""
        SELECT s.id, s.first_name, s.last_name, s.status
        FROM students s
        JOIN sections sec ON sec.id=s.section_id
        WHERE sec.course_id=?
          AND (sec.school_year_id=? OR ? IS NULL)
          AND s.status NOT IN ('RETIRADO','EGRESADO')
        ORDER BY s.last_name, s.first_name
    """, (course_id, sy_id, sy_id)).fetchall()


# ─────────────────────────────── INDEX ───────────────────────────────────────

@bp.route("/")
@login_required
@permission_required("academic", "view")
def index():
    user = current_user()
    with db() as conn:
        sy = conn.execute("SELECT * FROM school_years WHERE active=1").fetchone()
        sy_id = sy["id"] if sy else None

        courses = _get_all_courses(conn, sy_id)

        unassigned = conn.execute("""
            SELECT COUNT(*) as n FROM students
            WHERE section_id IS NULL AND status NOT IN ('RETIRADO','EGRESADO')
        """).fetchone()["n"]

        lapsos = conn.execute("""
            SELECT l.* FROM lapsos l
            JOIN school_years sy ON sy.id=l.school_year_id
            WHERE sy.active=1 ORDER BY l.name
        """).fetchall() if sy else []

        config = conn.execute("""
            SELECT ec.* FROM evaluation_config ec
            JOIN school_years sy ON sy.id=ec.school_year_id WHERE sy.active=1
        """).fetchone() if sy else None

    primary   = [c for c in courses if c["level"] == "PRIMARY"]
    secondary = [c for c in courses if c["level"] == "SECONDARY"]

    return render_template("academic/index.html",
        user=user, primary=primary, secondary=secondary,
        unassigned=unassigned, config=config, lapsos=lapsos, sy=sy)


# ─────────────────────────────── ASIGNACIÓN (v1.3, sin cambios) ──────────────

@bp.route("/asignar-seccion", methods=["GET", "POST"])
@login_required
@permission_required("academic", "edit")
def assign_section():
    user = current_user()
    with db() as conn:
        sy = conn.execute("SELECT id FROM school_years WHERE active=1").fetchone()
        sy_id = sy["id"] if sy else None

        courses = _get_all_courses(conn, sy_id)

        search_q = request.args.get("q", "")
        students_found = []
        if search_q and len(search_q) >= 2:
            students_found = conn.execute("""
                SELECT s.id, s.first_name, s.last_name, s.status, s.section_id,
                       c.name as course_name
                FROM students s
                LEFT JOIN sections sec ON sec.id=s.section_id
                LEFT JOIN courses c ON c.id=sec.course_id
                WHERE (s.first_name||' '||s.last_name LIKE ?
                    OR s.first_name LIKE ? OR s.last_name LIKE ?)
                  AND s.status NOT IN ('RETIRADO','EGRESADO')
                ORDER BY s.last_name LIMIT 10
            """, (f"%{search_q}%",)*3).fetchall()

        if request.method == "POST":
            student_id = request.form.get("student_id")
            course_id  = request.form.get("course_id")
            remove     = request.form.get("remove")

            if not student_id:
                flash("No se seleccionó ningún estudiante", "error")
                return redirect(url_for("academic.assign_section", q=search_q))

            if remove:
                old = conn.execute("SELECT section_id FROM students WHERE id=?", (student_id,)).fetchone()
                conn.execute("UPDATE students SET section_id=NULL WHERE id=?", (student_id,))
                audit(conn, "UPDATE", "academic", "students", int(student_id),
                      {"section_id": old["section_id"] if old else None}, {"section_id": None})
                flash("Estudiante removido del grado", "success")
                return redirect(url_for("academic.assign_section", q=search_q))

            if not course_id:
                flash("Selecciona un grado o año", "error")
                return redirect(url_for("academic.assign_section", q=search_q))

            if not sy:
                flash("No hay año escolar activo. Configúralo en Administración.", "error")
                return redirect(url_for("academic.assign_section", q=search_q))

            # Auto-crear sección si no existe para este curso y año
            section = conn.execute("""
                SELECT id FROM sections
                WHERE course_id=? AND school_year_id=?
                ORDER BY name LIMIT 1
            """, (course_id, sy_id)).fetchone()

            if not section:
                conn.execute("""
                    INSERT INTO sections(course_id, school_year_id, name, max_capacity)
                    VALUES(?, ?, 'Única', 60)
                """, (course_id, sy_id))
                section_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            else:
                section_id = section["id"]

            old = conn.execute("SELECT section_id FROM students WHERE id=?", (student_id,)).fetchone()
            conn.execute("UPDATE students SET section_id=? WHERE id=?", (section_id, student_id))
            audit(conn, "UPDATE", "academic", "students", int(student_id),
                  {"section_id": old["section_id"] if old else None},
                  {"section_id": section_id, "course_id": course_id})

            course_name = conn.execute("SELECT name FROM courses WHERE id=?", (course_id,)).fetchone()
            flash(f"Estudiante asignado a {course_name['name']}", "success")
            return redirect(url_for("academic.assign_section", q=search_q))

    primary   = [c for c in courses if c["level"] == "PRIMARY"]
    secondary = [c for c in courses if c["level"] == "SECONDARY"]

    return render_template("academic/assign_section.html",
        user=user, primary=primary, secondary=secondary,
        students_found=students_found, search_q=search_q, sy=sy)


# ─────────────────────────────── NOTAS (rediseñado v1.4) ─────────────────────

@bp.route("/notas", methods=["GET", "POST"])
@login_required
@permission_required("academic", "view")
def grades():
    """
    Flujo simplificado:
      1. Seleccionar grado/año  (course_id)
      2. Seleccionar lapso      (lapso_id)
      → Se muestra una tabla: filas = estudiantes, columnas = materias.
         Cada celda tiene un input de nota. Un solo botón "Guardar todo".

    Las materias se obtienen de subjects WHERE course_id = curso seleccionado.
    Si no hay materias configuradas para ese curso, se muestra aviso.
    No hay selector de sección ni de materia individual.
    """
    user = current_user()
    with db() as conn:
        sy = conn.execute("SELECT id FROM school_years WHERE active=1").fetchone()
        sy_id = sy["id"] if sy else None

        all_courses = _get_all_courses(conn, sy_id)

        lapsos = conn.execute("""
            SELECT l.* FROM lapsos l
            JOIN school_years sy ON sy.id=l.school_year_id
            WHERE sy.active=1 ORDER BY l.name
        """).fetchall() if sy else []

        course_id = request.args.get("course_id", "")
        lapso_id  = request.args.get("lapso_id", "")

        # Si solo hay un lapso, preseleccionarlo
        if not lapso_id and len(lapsos) == 1:
            lapso_id = str(lapsos[0]["id"])

        subjects = []
        students = []
        grade_map  = {}   # (student_id, subject_id) -> score
        notes_map  = {}   # student_id -> observación

        if course_id:
            subjects = conn.execute(
                "SELECT * FROM subjects WHERE course_id=? ORDER BY name",
                (course_id,)
            ).fetchall()

        if course_id and lapso_id:
            students = _students_of_course(conn, course_id, sy_id)

            if students and subjects:
                sid_list = ",".join(str(s["id"]) for s in students)
                sub_list = ",".join(str(s["id"]) for s in subjects)

                # Carga notas existentes para estos estudiantes + materias + lapso
                # Una nota por (student, subject, lapso) — promedio de actividades
                # Se usa el campo notes del primer activity_type que tenga nota
                existing = conn.execute(f"""
                    SELECT g.student_id, g.subject_id,
                           AVG(g.score) as avg_score,
                           MAX(g.notes) as notes
                    FROM grades g
                    WHERE g.lapso_id=?
                      AND g.student_id IN ({sid_list})
                      AND g.subject_id IN ({sub_list})
                    GROUP BY g.student_id, g.subject_id
                """, (lapso_id,)).fetchall()

                for g in existing:
                    grade_map[(g["student_id"], g["subject_id"])] = g["avg_score"]
                    if g["notes"]:
                        notes_map[g["student_id"]] = g["notes"]

        # ── POST: guardar notas ───────────────────────────────────────────────
        if request.method == "POST":
            c_id = request.form.get("course_id", course_id)
            l_id = request.form.get("lapso_id", lapso_id)

            if not (c_id and l_id):
                flash("Selecciona grado y lapso antes de guardar", "error")
                return redirect(url_for("academic.grades"))

            config = conn.execute("""
                SELECT ec.* FROM evaluation_config ec
                JOIN school_years sy ON sy.id=ec.school_year_id WHERE sy.active=1
            """).fetchone()
            max_g = config["max_grade"] if config else 20.0

            sub_list_post = conn.execute(
                "SELECT id FROM subjects WHERE course_id=?", (c_id,)
            ).fetchall()
            stu_list_post = _students_of_course(conn, c_id, sy_id)

            # Para guardar en la tabla grades necesitamos un activity_type.
            # Usamos el primero disponible para lapso+materia, o creamos
            # uno genérico "Nota Directa" si no hay ninguno configurado.
            saved = 0
            for stu in stu_list_post:
                note_val = request.form.get(f"note_{stu['id']}", "").strip() or None

                for sub in sub_list_post:
                    key = f"grade_{stu['id']}_{sub['id']}"
                    val = request.form.get(key, "").strip()
                    if val == "":
                        continue
                    try:
                        score = max(0.0, min(float(val), max_g))
                    except ValueError:
                        continue

                    # Buscar o crear activity_type genérico para esta materia+lapso
                    at = conn.execute("""
                        SELECT id FROM activity_types
                        WHERE subject_id=? AND lapso_id=?
                        ORDER BY id LIMIT 1
                    """, (sub["id"], l_id)).fetchone()

                    if not at:
                        conn.execute("""
                            INSERT INTO activity_types(name, weight, lapso_id, subject_id)
                            VALUES('Nota', 100.0, ?, ?)
                        """, (l_id, sub["id"]))
                        at_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    else:
                        at_id = at["id"]

                    conn.execute("""
                        INSERT INTO grades
                            (student_id, subject_id, lapso_id, activity_type_id,
                             score, notes, entered_by)
                        VALUES (?,?,?,?,?,?,?)
                        ON CONFLICT(student_id, subject_id, lapso_id, activity_type_id)
                        DO UPDATE SET score=excluded.score,
                                      notes=excluded.notes,
                                      entered_by=excluded.entered_by
                    """, (stu["id"], sub["id"], l_id, at_id,
                          score, note_val, user["id"]))
                    saved += 1

            flash(f"{saved} nota(s) guardadas correctamente", "success")
            return redirect(url_for("academic.grades",
                                    course_id=c_id, lapso_id=l_id))

        config = conn.execute("""
            SELECT ec.* FROM evaluation_config ec
            JOIN school_years sy ON sy.id=ec.school_year_id WHERE sy.active=1
        """).fetchone()

    primary   = [c for c in all_courses if c["level"] == "PRIMARY"]
    secondary = [c for c in all_courses if c["level"] == "SECONDARY"]

    return render_template("academic/grades.html",
        user=user,
        primary=primary, secondary=secondary,
        lapsos=lapsos,
        subjects=subjects,
        course_id=course_id, lapso_id=lapso_id,
        students=students,
        grade_map=grade_map, notes_map=notes_map,
        config=config)


# ─────────────────────────────── ASISTENCIA ──────────────────────────────────

@bp.route("/asistencia", methods=["GET", "POST"])
@login_required
@permission_required("academic", "view")
def attendance():
    user = current_user()
    with db() as conn:
        sy = conn.execute("SELECT id FROM school_years WHERE active=1").fetchone()
        sy_id = sy["id"] if sy else None

        all_courses = _get_all_courses(conn, sy_id)

        course_id = request.args.get("course_id", "")
        att_date  = request.args.get("date", datetime.date.today().isoformat())
        students  = []
        att_map   = {}

        if course_id:
            students = _students_of_course(conn, course_id, sy_id)
            if students:
                rows = conn.execute("""
                    SELECT student_id, present, justified, note FROM attendance
                    WHERE date=? AND student_id IN ({})
                """.format(",".join(str(s["id"]) for s in students)),
                    (att_date,)).fetchall()
                att_map = {r["student_id"]: r for r in rows}

        if request.method == "POST":
            c_id   = request.form.get("course_id", course_id)
            date_p = request.form.get("date", att_date)
            stu_ids = _students_of_course(conn, c_id, sy_id)

            for s in stu_ids:
                present   = 1 if request.form.get(f"present_{s['id']}") else 0
                justified = 1 if request.form.get(f"justified_{s['id']}") else 0
                note      = request.form.get(f"note_{s['id']}", "").strip() or None
                conn.execute("""
                    INSERT INTO attendance
                        (student_id, date, present, justified, note, recorded_by)
                    VALUES (?,?,?,?,?,?)
                    ON CONFLICT(student_id, date, subject_id)
                    DO UPDATE SET present=excluded.present,
                                  justified=excluded.justified,
                                  note=excluded.note
                """, (s["id"], date_p, present, justified, note, user["id"]))

            flash("Asistencia guardada", "success")
            return redirect(url_for("academic.attendance",
                                    course_id=c_id, date=date_p))

    primary   = [c for c in all_courses if c["level"] == "PRIMARY"]
    secondary = [c for c in all_courses if c["level"] == "SECONDARY"]

    return render_template("academic/attendance.html",
        user=user,
        primary=primary, secondary=secondary,
        course_id=course_id, att_date=att_date,
        students=students, att_map=att_map)


# ─────────────────────────────── CONFIGURACION ───────────────────────────────

@bp.route("/configuracion", methods=["GET", "POST"])
@login_required
@permission_required("academic", "edit")
def config():
    user = current_user()
    with db() as conn:
        sy  = conn.execute("SELECT * FROM school_years WHERE active=1").fetchone()
        cfg = conn.execute("""
            SELECT ec.* FROM evaluation_config ec
            JOIN school_years sy ON sy.id=ec.school_year_id WHERE sy.active=1
        """).fetchone() if sy else None
        lapsos = conn.execute("""
            SELECT l.* FROM lapsos l
            JOIN school_years sy ON sy.id=l.school_year_id
            WHERE sy.active=1 ORDER BY l.name
        """).fetchall() if sy else []
        subjects = conn.execute("""
            SELECT sub.*, c.name as course_name, c.level, c.grade
            FROM subjects sub JOIN courses c ON c.id=sub.course_id
            ORDER BY c.level DESC, c.grade, sub.name
        """).fetchall()
        activity_types = conn.execute("""
            SELECT at.*, sub.name as subject_name, l.name as lapso_name
            FROM activity_types at
            JOIN subjects sub ON sub.id=at.subject_id
            JOIN lapsos l ON l.id=at.lapso_id
            ORDER BY l.name, sub.name, at.name
        """).fetchall()

        if request.method == "POST":
            action = request.form.get("action")
            if action == "save_config" and sy:
                conn.execute("""
                    INSERT INTO evaluation_config
                        (school_year_id, min_passing_grade, max_grade,
                         use_decimals, rounding_rule)
                    VALUES (?,?,?,?,?)
                    ON CONFLICT(school_year_id) DO UPDATE
                    SET min_passing_grade=excluded.min_passing_grade,
                        max_grade=excluded.max_grade,
                        use_decimals=excluded.use_decimals,
                        rounding_rule=excluded.rounding_rule
                """, (sy["id"],
                      float(request.form.get("min_passing_grade", 10)),
                      float(request.form.get("max_grade", 20)),
                      1 if request.form.get("use_decimals") else 0,
                      request.form.get("rounding_rule", "ROUND_HALF_UP")))
                flash("Configuración guardada", "success")

            elif action == "add_activity":
                conn.execute("""
                    INSERT INTO activity_types(name, weight, lapso_id, subject_id)
                    VALUES (?,?,?,?)
                """, (request.form["act_name"],
                      float(request.form["act_weight"]),
                      request.form["act_lapso_id"],
                      request.form["act_subject_id"]))
                flash("Actividad agregada", "success")

            return redirect(url_for("academic.config"))

    return render_template("academic/config.html",
        user=user, sy=sy, cfg=cfg, lapsos=lapsos,
        subjects=subjects, activity_types=activity_types)
