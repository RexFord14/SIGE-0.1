"""
SIGE – Students Router  /estudiantes/

Gestiona el ciclo de vida completo del estudiante:
  Inscripción → Activo → (Moroso) → Egresado/Retirado

REGLAS DE NEGOCIO:
- No se puede cambiar a RETIRADO/EGRESADO si tiene deuda pendiente
- Eliminación física requiere PIN (datos sensibles, acción irreversible)
- Cédula almacenada encriptada (AES-256-GCM)
- Al eliminar: se verifican dependencias (no eliminar si tiene facturas/notas)
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from werkzeug.security import check_password_hash
from database import db
from auth import login_required, permission_required, current_user, audit
from crypto import encrypt, decrypt

bp = Blueprint("students", __name__, url_prefix="/estudiantes")


def _decrypt_safe(val):
    """Descifra campo AES. Si falla retorna '—' para no romper la UI."""
    try:
        return decrypt(val) if val else "—"
    except Exception:
        return "—"


# ─────────────────────────────── LISTA ───────────────────────────────────────

@bp.route("/")
@login_required
@permission_required("students", "view")
def index():
    user    = current_user()
    status  = request.args.get("status", "")
    section = request.args.get("section_id", "")
    search  = request.args.get("q", "")

    with db() as conn:
        query = """
            SELECT s.id, s.first_name, s.last_name, s.status,
                   c.name||' - '||sec.name as section_label
            FROM students s
            LEFT JOIN sections sec ON sec.id=s.section_id
            LEFT JOIN courses c ON c.id=sec.course_id
            WHERE 1=1
        """
        params = []
        if status:
            query += " AND s.status=?"; params.append(status)
        if section:
            query += " AND s.section_id=?"; params.append(section)
        if search:
            query += " AND (s.first_name||' '||s.last_name LIKE ? OR s.first_name LIKE ? OR s.last_name LIKE ?)"
            params += [f"%{search}%", f"%{search}%", f"%{search}%"]
        query += " ORDER BY s.last_name, s.first_name LIMIT 100"

        students  = conn.execute(query, params).fetchall()
        sections  = conn.execute("""
            SELECT sec.id, c.name||' - '||sec.name as label
            FROM sections sec JOIN courses c ON c.id=sec.course_id
            ORDER BY c.grade, sec.name
        """).fetchall()
        counts    = conn.execute("""
            SELECT status, COUNT(*) as n FROM students GROUP BY status
        """).fetchall()
        totals    = {r["status"]: r["n"] for r in counts}

    return render_template("students/index.html",
        user=user, students=students, sections=sections,
        status=status, section=section, search=search, totals=totals)


# ─────────────────────────────── DETALLE ─────────────────────────────────────

@bp.route("/<int:sid>")
@login_required
@permission_required("students", "view")
def detail(sid: int):
    user = current_user()
    with db() as conn:
        student = conn.execute("""
            SELECT s.*, sec.name||' - '||c.name as section_label,
                   r.full_name as rep_name, r.relationship as rep_rel,
                   r.phone_enc, r.email_enc
            FROM students s
            LEFT JOIN sections sec ON sec.id=s.section_id
            LEFT JOIN courses c ON c.id=sec.course_id
            LEFT JOIN representatives r ON r.id=s.representative_id
            WHERE s.id=?
        """, (sid,)).fetchone()

        if not student:
            flash("Estudiante no encontrado", "error")
            return redirect(url_for("students.index"))

        invoices = conn.execute("""
            SELECT i.*, fc.name as concept_name,
                   (i.net_amount - i.paid_amount) as balance
            FROM invoices i JOIN fee_concepts fc ON fc.id=i.concept_id
            WHERE i.student_id=? ORDER BY i.created_at DESC
        """, (sid,)).fetchall()

        # Pagos con imagen si existe
        payments = conn.execute("""
            SELECT p.*, u.full_name as cashier,
                   pi.thumb_filename
            FROM payments p
            JOIN invoices i ON i.id=p.invoice_id
            LEFT JOIN users u ON u.id=p.created_by
            LEFT JOIN payment_images pi ON pi.payment_id=p.id
            WHERE i.student_id=? AND p.voided=0
            ORDER BY p.created_at DESC
        """, (sid,)).fetchall()

        grades = conn.execute("""
            SELECT g.score, s.name as subject, l.name as lapso,
                   at.name as activity
            FROM grades g
            JOIN subjects s ON s.id=g.subject_id
            JOIN lapsos l ON l.id=g.lapso_id
            JOIN activity_types at ON at.id=g.activity_type_id
            WHERE g.student_id=? ORDER BY l.name, s.name
        """, (sid,)).fetchall()

        concepts = conn.execute(
            "SELECT * FROM fee_concepts WHERE active=1 ORDER BY name"
        ).fetchall()

    # Descifrar campos sensibles
    ced  = _decrypt_safe(student["cedula_enc"])
    phone = _decrypt_safe(student["phone_enc"] if "phone_enc" in student.keys() else None)
    email = _decrypt_safe(student["email_enc"] if "email_enc" in student.keys() else None)

    return render_template("students/detail.html",
        user=user, student=student, invoices=invoices,
        payments=payments, grades=grades, concepts=concepts,
        cedula=ced, phone=phone, email=email)


# ─────────────────────────────── CREAR / EDITAR ──────────────────────────────

@bp.route("/nuevo")
@login_required
@permission_required("students", "edit")
def new_form():
    user = current_user()
    with db() as conn:
        sections = conn.execute("""
            SELECT sec.id, c.name||' - '||sec.name as label
            FROM sections sec JOIN courses c ON c.id=sec.course_id
            ORDER BY c.grade, sec.name
        """).fetchall()
    return render_template("students/form.html",
        user=user, sections=sections, student=None, edit=False)


@bp.route("/<int:sid>/editar")
@login_required
@permission_required("students", "edit")
def edit_form(sid: int):
    user = current_user()
    with db() as conn:
        student = conn.execute("""
            SELECT s.*, r.full_name as rep_name, r.relationship,
                   r.phone_enc, r.email_enc, r.address
            FROM students s
            JOIN representatives r ON r.id=s.representative_id
            WHERE s.id=?
        """, (sid,)).fetchone()
        sections = conn.execute("""
            SELECT sec.id, c.name||' - '||sec.name as label
            FROM sections sec JOIN courses c ON c.id=sec.course_id
        """).fetchall()

    ced   = _decrypt_safe(student["cedula_enc"])
    phone = _decrypt_safe(student["phone_enc"])
    email = _decrypt_safe(student["email_enc"])
    return render_template("students/form.html",
        user=user, student=student, sections=sections,
        edit=True, cedula=ced, phone=phone, email=email)


@bp.route("/guardar", methods=["POST"])
@login_required
@permission_required("students", "edit")
def save():
    user = current_user()
    sid  = request.form.get("student_id")

    # Datos del representante
    rep_name = request.form.get("rep_name", "")
    rep_ced  = request.form.get("rep_cedula", "")
    rel      = request.form.get("relationship", "Madre")
    phone    = request.form.get("rep_phone", "")
    email    = request.form.get("rep_email", "")
    address  = request.form.get("rep_address", "")

    # Datos del estudiante
    first    = request.form.get("first_name", "")
    last     = request.form.get("last_name", "")
    ced      = request.form.get("cedula", "")
    bd       = request.form.get("birth_date", "")
    gender   = request.form.get("gender", "M")
    sec_id   = request.form.get("section_id") or None

    if not first or not last or not bd or not rep_name:
        flash("Nombre, apellido, fecha de nacimiento y representante son obligatorios", "error")
        return redirect(url_for("students.new_form"))

    with db() as conn:
        rep_enc_val = encrypt(rep_ced) if rep_ced else ""

        if sid:
            # Editar existente
            student = conn.execute(
                "SELECT representative_id FROM students WHERE id=?", (sid,)
            ).fetchone()
            conn.execute("""
                UPDATE representatives SET full_name=?, phone_enc=?,
                    email_enc=?, address=?, relationship=?
                WHERE id=?
            """, (rep_name,
                  encrypt(phone) if phone else None,
                  encrypt(email) if email else None,
                  address, rel, student["representative_id"]))

            conn.execute("""
                UPDATE students SET first_name=?, last_name=?,
                    cedula_enc=?, birth_date=?, gender=?, section_id=?
                WHERE id=?
            """, (first, last, encrypt(ced) if ced else None,
                  bd, gender, sec_id, sid))
            audit(conn, "UPDATE", "students", "students", int(sid),
                  None, {"first": first, "last": last})
            flash(f"{first} {last} actualizado", "success")

        else:
            # Crear representante (o reutilizar por cédula)
            existing_rep = conn.execute(
                "SELECT id FROM representatives WHERE cedula_enc=?", (rep_enc_val,)
            ).fetchone() if rep_ced else None

            if existing_rep:
                rep_id = existing_rep["id"]
            else:
                conn.execute("""
                    INSERT INTO representatives
                        (cedula_enc, full_name, phone_enc, email_enc, address, relationship)
                    VALUES (?,?,?,?,?,?)
                """, (rep_enc_val, rep_name,
                      encrypt(phone) if phone else None,
                      encrypt(email) if email else None,
                      address, rel))
                rep_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            conn.execute("""
                INSERT INTO students
                    (cedula_enc, first_name, last_name, birth_date,
                     gender, section_id, representative_id, status)
                VALUES (?,?,?,?,?,?,?,'ACTIVO')
            """, (encrypt(ced) if ced else None,
                  first, last, bd, gender, sec_id, rep_id))
            new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            audit(conn, "INSERT", "students", "students", new_id,
                  None, {"first": first, "last": last})
            flash(f"Estudiante {first} {last} inscrito", "success")

    return redirect(url_for("students.index"))


# ─────────────────────────────── CAMBIO DE ESTADO ────────────────────────────

@bp.route("/<int:sid>/estado", methods=["POST"])
@login_required
@permission_required("students", "edit")
def change_status(sid: int):
    new_status = request.form.get("new_status", "")
    user       = current_user()

    if new_status not in ("ACTIVO", "MOROSO", "RETIRADO", "EGRESADO", "BECADO"):
        flash("Estado inválido", "error")
        return redirect(url_for("students.detail", sid=sid))

    with db() as conn:
        student = conn.execute(
            "SELECT status FROM students WHERE id=?", (sid,)
        ).fetchone()

        # Verificar deuda si se intenta retirar/egresar (BECADO puede tener deuda suspendida)
        if new_status in ("RETIRADO", "EGRESADO"):
            debt = conn.execute("""
                SELECT COALESCE(SUM(net_amount - paid_amount), 0) as d
                FROM invoices WHERE student_id=? AND status IN ('PENDIENTE','PARCIAL')
            """, (sid,)).fetchone()["d"]
            if debt > 0:
                flash(
                    f"No se puede cambiar a {new_status}. "
                    f"El estudiante tiene deuda pendiente de Bs.{debt:,.2f}",
                    "error"
                )
                return redirect(url_for("students.detail", sid=sid))

        old_status = student["status"]
        conn.execute("UPDATE students SET status=? WHERE id=?", (new_status, sid))
        audit(conn, "UPDATE", "students", "students", sid,
              {"status": old_status}, {"status": new_status})

    flash(f"Estado actualizado a {new_status}", "success")
    return redirect(url_for("students.detail", sid=sid))


# ─────────────────────────────── ELIMINAR (con PIN) ──────────────────────────

@bp.route("/<int:sid>/eliminar", methods=["POST"])
@login_required
@permission_required("students", "delete")
def delete_student(sid: int):
    """
    Eliminación con verificación de PIN y dependencias.
    
    POLÍTICA:
    - Requiere PIN de 4 dígitos (mismo PIN del sistema)
    - Bloquea si tiene facturas emitidas (registros contables)
    - Bloquea si tiene notas registradas
    - Si tiene asistencias sin facturas/notas → permite eliminar (CASCADE)
    
    ¿Por qué no DELETE siempre?
    Un estudiante con factura es un registro contable. Su eliminación
    crearía facturas huérfanas que romperían la contabilidad.
    """
    pin  = request.form.get("delete_pin", "")
    user = current_user()

    with db() as conn:
        # Verificar PIN
        setting = conn.execute(
            "SELECT value FROM system_settings WHERE key='security_pin_hash'"
        ).fetchone()
        if not setting or not check_password_hash(setting["value"], pin):
            flash("PIN incorrecto", "error")
            return redirect(url_for("students.detail", sid=sid))

        student = conn.execute(
            "SELECT first_name, last_name FROM students WHERE id=?", (sid,)
        ).fetchone()
        if not student:
            flash("Estudiante no encontrado", "error")
            return redirect(url_for("students.index"))

        # Verificar dependencias contables
        inv_count = conn.execute(
            "SELECT COUNT(*) as n FROM invoices WHERE student_id=?", (sid,)
        ).fetchone()["n"]
        if inv_count > 0:
            flash(
                f"No se puede eliminar: {student['first_name']} tiene "
                f"{inv_count} factura(s) registrada(s). Use estado RETIRADO.",
                "error"
            )
            return redirect(url_for("students.detail", sid=sid))

        grades_count = conn.execute(
            "SELECT COUNT(*) as n FROM grades WHERE student_id=?", (sid,)
        ).fetchone()["n"]
        if grades_count > 0:
            flash(
                f"No se puede eliminar: {student['first_name']} tiene "
                f"{grades_count} nota(s) registrada(s). Use estado RETIRADO.",
                "error"
            )
            return redirect(url_for("students.detail", sid=sid))

        name = f"{student['first_name']} {student['last_name']}"

        # Limpiar dependencias sin impacto contable
        conn.execute("DELETE FROM attendance WHERE student_id=?", (sid,))
        conn.execute("DELETE FROM students WHERE id=?", (sid,))

        audit(conn, "DELETE", "students", "students", sid,
              {"name": name}, None)

    flash(f"Estudiante {name} eliminado permanentemente", "success")
    return redirect(url_for("students.index"))
