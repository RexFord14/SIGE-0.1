import threading
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, abort
from database import db
from auth import login_required, permission_required, current_user

bp = Blueprint("reports", __name__, url_prefix="/reportes")

def _run_in_background(task_id, func, *args):
    import traceback
    try:
        with db() as conn:
            conn.execute("UPDATE background_tasks SET status='RUNNING',updated_at=datetime('now') WHERE id=?", (task_id,))
        result_path = func(*args)
        with db() as conn:
            conn.execute("UPDATE background_tasks SET status='DONE',progress=100,result_path=?,updated_at=datetime('now') WHERE id=?", (result_path, task_id))
    except Exception as e:
        with db() as conn:
            conn.execute("UPDATE background_tasks SET status='ERROR',error_msg=?,updated_at=datetime('now') WHERE id=?", (str(e), task_id))

@bp.route("/")
@login_required
@permission_required("reports","view")
def index():
    with db() as conn:
        tasks = conn.execute("SELECT * FROM background_tasks ORDER BY created_at DESC LIMIT 20").fetchall()
        students = conn.execute("SELECT id,first_name||' '||last_name as name FROM students WHERE status IN ('ACTIVO','MOROSO') ORDER BY last_name").fetchall()
        lapsos = conn.execute("SELECT l.*,sy.name as year_name FROM lapsos l JOIN school_years sy ON sy.id=l.school_year_id ORDER BY sy.name,l.name").fetchall()
        sections = conn.execute("SELECT sec.id,c.name||' - Sección '||sec.name as label FROM sections sec JOIN courses c ON c.id=sec.course_id ORDER BY c.grade,sec.name").fetchall()
    return render_template("reports/index.html", tasks=tasks, students=students,
                           lapsos=lapsos, sections=sections, user=current_user())

@bp.route("/constancia/<int:sid>")
@login_required
@permission_required("reports","view")
def constancia(sid):
    from services.pdf_service import generate_constancia
    with db() as conn:
        s = conn.execute("""SELECT s.*,sec.name as section_name,c.name as grade_name,sy.name as school_year
            FROM students s LEFT JOIN sections sec ON sec.id=s.section_id LEFT JOIN courses c ON c.id=sec.course_id
            LEFT JOIN school_years sy ON sy.id=sec.school_year_id WHERE s.id=?""", (sid,)).fetchone()
        if not s: abort(404)
        from crypto import decrypt
        student_data = dict(s)
        student_data["cedula"] = decrypt(s["cedula_enc"]) if s["cedula_enc"] else ""
        student_data["section"] = s["section_name"] or ""
        uid = current_user()["id"]
        conn.execute("INSERT INTO background_tasks(task_type,status,progress,created_by) VALUES('CONSTANCIA','RUNNING',0,?)", (uid,))
        task_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    t = threading.Thread(target=_run_in_background, args=(task_id, generate_constancia, student_data))
    t.daemon = True
    t.start()
    flash(f"Generando constancia (Tarea #{task_id})...", "info")
    return redirect(url_for("reports.index"))

@bp.route("/boletin/<int:sid>/<int:lapso_id>")
@login_required
@permission_required("reports","view")
def boletin(sid, lapso_id):
    from services.pdf_service import generate_boletin
    with db() as conn:
        s = conn.execute("""SELECT s.*,sec.name as section_name,c.name as grade_name,sy.name as school_year,l.name as lapso_name
            FROM students s LEFT JOIN sections sec ON sec.id=s.section_id LEFT JOIN courses c ON c.id=sec.course_id
            LEFT JOIN school_years sy ON sy.id=sec.school_year_id LEFT JOIN lapsos l ON l.id=?
            WHERE s.id=?""", (lapso_id, sid)).fetchone()
        if not s: abort(404)
        subjects = conn.execute("SELECT * FROM subjects WHERE course_id=(SELECT course_id FROM sections WHERE id=?)", (s["section_id"],)).fetchall()
        grades_data = []
        config = conn.execute("SELECT * FROM evaluation_config WHERE school_year_id=(SELECT id FROM school_years WHERE active=1)").fetchone()
        cfg = dict(config) if config else {"min_passing_grade":10.0,"max_grade":20.0}
        for sub in subjects:
            gs = conn.execute("SELECT at.name,g.score,at.weight FROM grades g JOIN activity_types at ON at.id=g.activity_type_id WHERE g.student_id=? AND g.subject_id=? AND g.lapso_id=?", (sid, sub["id"], lapso_id)).fetchall()
            scores = {g["name"]: g["score"] for g in gs}
            total_weight = sum(g["weight"] for g in gs)
            avg = sum(g["score"]*g["weight"] for g in gs)/total_weight if total_weight > 0 else 0
            grades_data.append({"subject": sub["name"], "eval_score": scores.get("Evaluación","—"), "task_score": scores.get("Tarea","—"), "proj_score": scores.get("Proyecto","—"), "average": avg})
        student_data = dict(s)
        student_data["section"] = s["section_name"] or ""
        student_data["lapso"] = s["lapso_name"] or ""
        uid = current_user()["id"]
        conn.execute("INSERT INTO background_tasks(task_type,status,progress,created_by) VALUES('BOLETIN','RUNNING',0,?)", (uid,))
        task_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    t = threading.Thread(target=_run_in_background, args=(task_id, generate_boletin, student_data, grades_data, cfg))
    t.daemon = True
    t.start()
    flash(f"Generando boletín (Tarea #{task_id})...", "info")
    return redirect(url_for("reports.index"))

@bp.route("/tarea/<int:task_id>/estado")
@login_required
def task_status(task_id):
    from flask import jsonify
    with db() as conn:
        task = conn.execute("SELECT * FROM background_tasks WHERE id=?", (task_id,)).fetchone()
        if not task: abort(404)
    return jsonify({"status": task["status"], "progress": task["progress"], "result_path": task["result_path"], "error_msg": task["error_msg"]})

@bp.route("/tarea/<int:task_id>/descargar")
@login_required
def download_task(task_id):
    with db() as conn:
        task = conn.execute("SELECT * FROM background_tasks WHERE id=? AND status='DONE'", (task_id,)).fetchone()
        if not task or not task["result_path"]: abort(404)
    import os
    return send_file(task["result_path"], as_attachment=True, download_name=os.path.basename(task["result_path"]))
