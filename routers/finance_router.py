"""
SIGE – Finance Router  /finanzas/  v1.2
Cambios v1.2:
  - Tasa del día (USD/VES): registro y consulta
  - Panel simplificado: solo totales del día en Bs y $
  - Removidos: botones rápidos innecesarios (caja, conciliación, conceptos)
  - Mantenido: flujo de pago individual por estudiante (intacto)
"""
import os, datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, jsonify
from werkzeug.security import check_password_hash
from database import db
from auth import login_required, permission_required, current_user, audit
from crypto import encrypt, decrypt
from services.image_service import save_payment_image, delete_payment_images, get_orig_path, get_thumb_path

bp = Blueprint("finance", __name__, url_prefix="/finanzas")


def _next_number(conn, prefix, table, col):
    last = conn.execute(
        f"SELECT {col} FROM {table} WHERE {col} LIKE ? ORDER BY id DESC LIMIT 1",
        (f"{prefix}-%",)
    ).fetchone()
    n = int(last[0].split("-")[1]) + 1 if last else 1
    return f"{prefix}-{n:06d}"


def _update_student_status(conn, student_id: int):
    """
    BECADO: la deuda existe pero el estado NO cambia a MOROSO.
    El becado siempre permanece en BECADO independientemente de su deuda.
    Solo cambia entre ACTIVO/MOROSO para estudiantes regulares.
    """
    student = conn.execute("SELECT status FROM students WHERE id=?", (student_id,)).fetchone()
    if not student or student["status"] in ("RETIRADO", "EGRESADO", "BECADO"):
        return  # BECADO: intocable por deuda

    debt = conn.execute("""
        SELECT COALESCE(SUM(net_amount - paid_amount), 0) as total
        FROM invoices
        WHERE student_id=? AND status IN ('PENDIENTE','PARCIAL')
    """, (student_id,)).fetchone()["total"]

    new_status = "MOROSO" if debt > 0 else "ACTIVO"
    conn.execute("UPDATE students SET status=? WHERE id=?", (new_status, student_id))


def _get_today_rate(conn):
    """Retorna la tasa del día o None si no fue registrada."""
    today = datetime.date.today().isoformat()
    row = conn.execute(
        "SELECT rate_bs FROM exchange_rates WHERE date=?", (today,)
    ).fetchone()
    return row["rate_bs"] if row else None


# ─────────────────────────────── TASA DEL DÍA ────────────────────────────────

@bp.route("/tasa", methods=["POST"])
@login_required
@permission_required("finance", "edit")
def set_rate():
    """Registra la tasa BsD del día. Si ya existe la actualiza."""
    rate = request.form.get("rate_bs", "")
    user = current_user()
    try:
        rate = float(rate)
        if rate <= 0:
            raise ValueError
    except (ValueError, TypeError):
        flash("Tasa inválida", "error")
        return redirect(url_for("finance.index"))

    today = datetime.date.today().isoformat()
    with db() as conn:
        conn.execute("""
            INSERT INTO exchange_rates(date, rate_bs, entered_by)
            VALUES(?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET rate_bs=excluded.rate_bs
        """, (today, rate, user["id"]))
    flash(f"Tasa actualizada: 1 USD = Bs.{rate:,.2f}", "success")
    return redirect(url_for("finance.index"))


# ─────────────────────────────── DASHBOARD ───────────────────────────────────

@bp.route("/")
@login_required
@permission_required("finance", "view")
def index():
    user = current_user()
    with db() as conn:
        today = datetime.date.today().isoformat()
        rate  = _get_today_rate(conn)

        stats = conn.execute("""
            SELECT
                (SELECT COALESCE(SUM(net_amount),0) FROM invoices
                 WHERE status IN ('PENDIENTE','PARCIAL')) as total_pendiente,
                (SELECT COALESCE(SUM(amount),0) FROM payments
                 WHERE payment_date=? AND voided=0) as cobrado_hoy,
                (SELECT COUNT(*) FROM invoices WHERE status='PENDIENTE') as facturas_pendientes,
                (SELECT COUNT(*) FROM students WHERE status='MOROSO') as morosos
        """, (today,)).fetchone()

        # Totales por método hoy
        totales_hoy = conn.execute("""
            SELECT payment_method,
                   COALESCE(SUM(amount),0) as total,
                   COUNT(*) as n
            FROM payments
            WHERE payment_date=? AND voided=0
            GROUP BY payment_method
        """, (today,)).fetchall()

        invoices = conn.execute("""
            SELECT i.*, s.id as student_id,
                   s.first_name||' '||s.last_name as student_name,
                   fc.name as concept_name,
                   (i.net_amount - i.paid_amount) as balance
            FROM invoices i
            JOIN students s ON s.id=i.student_id
            JOIN fee_concepts fc ON fc.id=i.concept_id
            WHERE i.status IN ('PENDIENTE','PARCIAL')
            ORDER BY i.due_date ASC LIMIT 20
        """).fetchall()

        recent_payments = conn.execute("""
            SELECT p.*, s.first_name||' '||s.last_name as student_name,
                   fc.name as concept_name,
                   (SELECT COUNT(*) FROM payment_images WHERE payment_id=p.id) as has_image
            FROM payments p
            JOIN invoices i ON i.id=p.invoice_id
            JOIN students s ON s.id=i.student_id
            JOIN fee_concepts fc ON fc.id=i.concept_id
            WHERE p.voided=0
            ORDER BY p.created_at DESC LIMIT 12
        """).fetchall()

        students_with_debt = conn.execute("""
            SELECT s.id, s.first_name||' '||s.last_name as name,
                   s.status,
                   SUM(i.net_amount - i.paid_amount) as debt
            FROM students s JOIN invoices i ON i.student_id=s.id
            WHERE i.status IN ('PENDIENTE','PARCIAL')
            GROUP BY s.id ORDER BY debt DESC LIMIT 10
        """).fetchall()

        concepts_list = conn.execute(
            "SELECT * FROM fee_concepts WHERE active=1 ORDER BY name"
        ).fetchall()

    return render_template("finance/index.html",
        user=user, stats=stats, invoices=invoices,
        recent_payments=recent_payments,
        students_with_debt=students_with_debt,
        concepts_list=concepts_list,
        totales_hoy=totales_hoy,
        rate=rate, today=today)


# ─────────────────────────────── NUEVO PAGO ──────────────────────────────────

@bp.route("/nuevo-pago", methods=["GET"])
@login_required
@permission_required("finance", "edit")
def nuevo_pago():
    user = current_user()
    with db() as conn:
        student_id = request.args.get("student_id", "")
        invoice_id = request.args.get("invoice_id", "")
        student = None
        invoice = None
        pending_invoices = []
        bank_accounts = conn.execute(
            "SELECT * FROM bank_accounts WHERE active=1 ORDER BY bank"
        ).fetchall()
        rate = _get_today_rate(conn)

        if student_id:
            student = conn.execute("""
                SELECT s.*, sec.name||' - '||c.name as section_label,
                       r.full_name as rep_name
                FROM students s
                LEFT JOIN sections sec ON sec.id=s.section_id
                LEFT JOIN courses c ON c.id=sec.course_id
                LEFT JOIN representatives r ON r.id=s.representative_id
                WHERE s.id=?
            """, (student_id,)).fetchone()
            pending_invoices = conn.execute("""
                SELECT i.*, fc.name as concept_name,
                       (i.net_amount - i.paid_amount) as balance
                FROM invoices i JOIN fee_concepts fc ON fc.id=i.concept_id
                WHERE i.student_id=? AND i.status IN ('PENDIENTE','PARCIAL')
                ORDER BY i.due_date ASC
            """, (student_id,)).fetchall()

        if invoice_id:
            invoice = conn.execute("""
                SELECT i.*, fc.name as concept_name,
                       (i.net_amount - i.paid_amount) as balance,
                       s.first_name||' '||s.last_name as student_name,
                       s.id as student_id
                FROM invoices i JOIN fee_concepts fc ON fc.id=i.concept_id
                JOIN students s ON s.id=i.student_id
                WHERE i.id=? AND i.status IN ('PENDIENTE','PARCIAL')
            """, (invoice_id,)).fetchone()

        search_q = request.args.get("q", "")
        search_results = []
        if search_q and len(search_q) >= 2:
            search_results = conn.execute("""
                SELECT s.id, s.first_name||' '||s.last_name as name,
                       c.name||' - '||sec.name as section, s.status
                FROM students s
                LEFT JOIN sections sec ON sec.id=s.section_id
                LEFT JOIN courses c ON c.id=sec.course_id
                WHERE (s.first_name||' '||s.last_name) LIKE ?
                   OR s.first_name LIKE ? OR s.last_name LIKE ?
                ORDER BY s.last_name LIMIT 8
            """, (f"%{search_q}%",)*3).fetchall()

    return render_template("finance/nuevo_pago.html",
        user=user, student=student, invoice=invoice,
        pending_invoices=pending_invoices,
        bank_accounts=bank_accounts,
        search_results=search_results,
        search_q=search_q, rate=rate,
        today=datetime.date.today().isoformat())


@bp.route("/nuevo-pago", methods=["POST"])
@login_required
@permission_required("finance", "edit")
def registrar_pago():
    user       = current_user()
    invoice_id = request.form.get("invoice_id", "")
    amount_str = request.form.get("amount", "0")
    method     = request.form.get("payment_method", "")
    subtype    = request.form.get("payment_subtype", method)
    pay_date   = request.form.get("payment_date", datetime.date.today().isoformat())
    notes      = request.form.get("notes", "")
    image_file = request.files.get("comprobante")

    try:
        amount = float(amount_str)
        if amount <= 0:
            raise ValueError
    except ValueError:
        flash("Monto inválido", "error")
        return redirect(url_for("finance.nuevo_pago", invoice_id=invoice_id))

    if not method:
        flash("Debes seleccionar el método de pago", "error")
        return redirect(url_for("finance.nuevo_pago", invoice_id=invoice_id))

    with db() as conn:
        inv = conn.execute("""
            SELECT i.*, (i.net_amount - i.paid_amount) as balance, i.student_id
            FROM invoices i WHERE i.id=? AND i.status IN ('PENDIENTE','PARCIAL')
        """, (invoice_id,)).fetchone()

        if not inv:
            flash("Factura no encontrada o ya pagada", "error")
            return redirect(url_for("finance.index"))

        if amount > round(inv["balance"], 2):
            flash(f"El monto excede el saldo pendiente (Bs.{inv['balance']:,.2f})", "error")
            return redirect(url_for("finance.nuevo_pago",
                student_id=inv["student_id"], invoice_id=invoice_id))

        ref_num    = request.form.get("reference_num", "")
        bank       = request.form.get("bank_name", "")
        account_id = request.form.get("account_id") or None
        phone_enc  = None
        cedula_enc = None
        last4      = request.form.get("last4_ref", "")
        zelle_email= request.form.get("zelle_email", "")
        zelle_name = request.form.get("zelle_name", "")
        other_desc = request.form.get("other_desc", "")

        if subtype == "PAGO_MOVIL":
            phone_raw = request.form.get("phone_number", "")
            ced_raw   = request.form.get("cedula_payer", "")
            if not phone_raw or not ced_raw or not last4:
                flash("Pago Móvil requiere teléfono, cédula y últimos 4 dígitos", "error")
                return redirect(url_for("finance.nuevo_pago",
                    student_id=inv["student_id"], invoice_id=invoice_id))
            phone_enc  = encrypt(phone_raw)
            cedula_enc = encrypt(ced_raw)

        elif subtype == "TRANSFERENCIA":
            if not ref_num or not account_id:
                flash("Transferencia requiere referencia y cuenta receptora", "error")
                return redirect(url_for("finance.nuevo_pago",
                    student_id=inv["student_id"], invoice_id=invoice_id))

        elif subtype == "ZELLE":
            if not zelle_email or not zelle_name:
                flash("Zelle requiere email y nombre del remitente", "error")
                return redirect(url_for("finance.nuevo_pago",
                    student_id=inv["student_id"], invoice_id=invoice_id))

        elif subtype == "OTRO" and not other_desc:
            flash("Especifica el tipo de pago", "error")
            return redirect(url_for("finance.nuevo_pago",
                student_id=inv["student_id"], invoice_id=invoice_id))

        pay_num = _next_number(conn, "PAG", "payments", "payment_number")
        conn.execute("""
            INSERT INTO payments (
                payment_number, invoice_id, amount, payment_method,
                payment_subtype, reference_num, bank, payment_date, notes,
                phone_number, cedula_payer, last4_ref, account_id,
                zelle_email, zelle_name, other_desc, created_by
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (pay_num, invoice_id, amount, method, subtype,
              ref_num, bank, pay_date, notes,
              phone_enc, cedula_enc, last4, account_id,
              zelle_email, zelle_name, other_desc, user["id"]))
        pay_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        new_paid   = inv["paid_amount"] + amount
        new_status = "PAGADO" if new_paid >= inv["net_amount"] else "PARCIAL"
        conn.execute("UPDATE invoices SET paid_amount=?, status=? WHERE id=?",
                     (new_paid, new_status, invoice_id))

        _update_student_status(conn, inv["student_id"])

        if image_file and image_file.filename:
            img_data = save_payment_image(image_file, pay_id)
            if img_data:
                conn.execute("""
                    INSERT INTO payment_images
                        (payment_id, original_filename, stored_filename,
                         thumb_filename, file_size_kb)
                    VALUES (?,?,?,?,?)
                """, (pay_id, img_data["original_filename"],
                      img_data["stored_filename"], img_data["thumb_filename"],
                      img_data["file_size_kb"]))
            else:
                flash("El comprobante no pudo guardarse (formato no compatible)", "warning")

        audit(conn, "INSERT", "finance", "payments", pay_id, None,
              {"number": pay_num, "amount": amount, "method": subtype})

    flash(f"Pago {pay_num} registrado (Bs.{amount:,.2f})", "success")
    return redirect(url_for("finance.index"))


# ─────────────────────────────── ANULAR PAGO (PIN) ───────────────────────────

@bp.route("/anular-pago/<int:pid>", methods=["POST"])
@login_required
@permission_required("finance", "void")
def void_payment(pid: int):
    pin  = request.form.get("void_pin", "")
    user = current_user()
    with db() as conn:
        setting = conn.execute(
            "SELECT value FROM system_settings WHERE key='security_pin_hash'"
        ).fetchone()
        if not setting or not check_password_hash(setting["value"], pin):
            flash("PIN incorrecto. No se anuló el pago.", "error")
            return redirect(request.referrer or url_for("finance.index"))

        pay = conn.execute(
            "SELECT * FROM payments WHERE id=? AND voided=0", (pid,)
        ).fetchone()
        if not pay:
            flash("Pago no encontrado o ya anulado", "error")
            return redirect(url_for("finance.index"))

        inv = conn.execute("SELECT * FROM invoices WHERE id=?", (pay["invoice_id"],)).fetchone()
        new_paid   = max(0, inv["paid_amount"] - pay["amount"])
        new_status = "PENDIENTE" if new_paid == 0 else "PARCIAL"

        conn.execute("""
            UPDATE payments SET voided=1, voided_by=?, voided_at=datetime('now') WHERE id=?
        """, (user["id"], pid))
        conn.execute("UPDATE invoices SET paid_amount=?, status=? WHERE id=?",
                     (new_paid, new_status, inv["id"]))
        delete_payment_images(pid, conn)
        _update_student_status(conn, inv["student_id"])
        audit(conn, "VOID", "finance", "payments", pid,
              {"amount": pay["amount"]}, {"voided_by": user["username"]})

    flash("Pago anulado correctamente", "success")
    return redirect(request.referrer or url_for("finance.index"))


# ─────────────────────────────── FACTURAS ────────────────────────────────────

@bp.route("/nueva-factura", methods=["POST"])
@login_required
@permission_required("finance", "edit")
def new_invoice():
    student_id = request.form.get("student_id")
    concept_id = request.form.get("concept_id")
    discount   = float(request.form.get("discount", 0))
    due_date   = request.form.get("due_date", "")
    user       = current_user()
    try:
        amount = float(request.form.get("amount", 0))
    except ValueError:
        flash("Monto inválido", "error")
        return redirect(url_for("finance.index"))

    net = amount - discount
    if net <= 0:
        flash("Monto neto debe ser mayor a 0", "error")
        return redirect(url_for("finance.index"))

    with db() as conn:
        sy = conn.execute("SELECT id FROM school_years WHERE active=1").fetchone()
        if not sy:
            flash("No hay año escolar activo", "error")
            return redirect(url_for("finance.index"))
        inv_num = _next_number(conn, "FAC", "invoices", "invoice_number")
        conn.execute("""
            INSERT INTO invoices
                (invoice_number,student_id,concept_id,amount,discount,
                 net_amount,due_date,school_year_id,created_by)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (inv_num, student_id, concept_id, amount, discount,
              net, due_date, sy["id"], user["id"]))
        inv_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        _update_student_status(conn, int(student_id))
        audit(conn, "INSERT", "finance", "invoices", inv_id, None,
              {"number": inv_num, "amount": net})

    flash(f"Factura {inv_num} emitida (Bs.{net:,.2f})", "success")
    return redirect(url_for("finance.index"))


# ─────────────────────────────── RUTAS SIMPLES ───────────────────────────────

@bp.route("/caja")
@login_required
@permission_required("finance", "view")
def cash_register():
    user = current_user()
    with db() as conn:
        today = datetime.date.today().isoformat()
        rate  = _get_today_rate(conn)
        pagos = conn.execute("""
            SELECT p.*, s.first_name||' '||s.last_name as student_name,
                   fc.name as concept_name
            FROM payments p
            JOIN invoices i ON i.id=p.invoice_id
            JOIN students s ON s.id=i.student_id
            JOIN fee_concepts fc ON fc.id=i.concept_id
            WHERE p.payment_date=? AND p.voided=0 ORDER BY p.created_at DESC
        """, (today,)).fetchall()
        totales = conn.execute("""
            SELECT payment_method, COALESCE(SUM(amount),0) as total, COUNT(*) as n
            FROM payments WHERE payment_date=? AND voided=0 GROUP BY payment_method
        """, (today,)).fetchall()
        total_bs = sum(t["total"] for t in totales)
    return render_template("finance/cash_register.html",
        user=user, pagos=pagos, totales=totales, today=today,
        total_bs=total_bs, rate=rate)


@bp.route("/conciliacion")
@login_required
@permission_required("finance", "view")
def reconciliation():
    user = current_user()
    with db() as conn:
        records = conn.execute("""
            SELECT br.*, u.username FROM bank_reconciliation br
            JOIN users u ON u.id=br.created_by ORDER BY br.date DESC LIMIT 50
        """).fetchall()
    return render_template("finance/reconciliation.html", user=user, records=records)


@bp.route("/conciliacion/nueva", methods=["POST"])
@login_required
@permission_required("finance", "edit")
def new_reconciliation():
    user = current_user()
    with db() as conn:
        conn.execute("""
            INSERT INTO bank_reconciliation(date,reference_num,bank,amount,concept,created_by)
            VALUES(?,?,?,?,?,?)
        """, (request.form.get("date"), request.form.get("reference_num"),
              request.form.get("bank"), float(request.form.get("amount",0)),
              request.form.get("concept"), user["id"]))
    flash("Movimiento registrado", "success")
    return redirect(url_for("finance.reconciliation"))


@bp.route("/conceptos")
@login_required
@permission_required("finance", "view")
def concepts():
    user = current_user()
    with db() as conn:
        items = conn.execute("SELECT * FROM fee_concepts ORDER BY name").fetchall()
    return render_template("finance/concepts.html", user=user, items=items)


@bp.route("/conceptos/nuevo", methods=["POST"])
@login_required
@permission_required("finance", "edit")
def new_concept():
    with db() as conn:
        conn.execute("INSERT INTO fee_concepts(name,amount,recurrent) VALUES(?,?,?)",
                     (request.form["name"], float(request.form["amount"]),
                      1 if request.form.get("recurrent") else 0))
    flash("Concepto creado", "success")
    return redirect(url_for("finance.concepts"))


@bp.route("/conceptos/<int:cid>/toggle", methods=["POST"])
@login_required
@permission_required("finance", "edit")
def toggle_concept(cid):
    with db() as conn:
        conn.execute("UPDATE fee_concepts SET active=1-active WHERE id=?", (cid,))
    return redirect(url_for("finance.concepts"))


@bp.route("/cuentas")
@login_required
@permission_required("finance", "view")
def bank_accounts():
    user = current_user()
    with db() as conn:
        accounts = conn.execute("SELECT * FROM bank_accounts ORDER BY bank").fetchall()
    return render_template("finance/bank_accounts.html", user=user, accounts=accounts)


@bp.route("/cuentas/nueva", methods=["POST"])
@login_required
@permission_required("finance", "edit")
def new_bank_account():
    with db() as conn:
        conn.execute("""
            INSERT INTO bank_accounts(bank,account_number,account_holder,account_type,rif)
            VALUES(?,?,?,?,?)
        """, (request.form["bank"], request.form["account_number"],
              request.form["account_holder"],
              request.form.get("account_type","CORRIENTE"),
              request.form.get("rif","")))
    flash("Cuenta registrada", "success")
    return redirect(url_for("finance.bank_accounts"))


@bp.route("/cuentas/<int:aid>/toggle", methods=["POST"])
@login_required
@permission_required("finance", "edit")
def toggle_bank_account(aid):
    with db() as conn:
        conn.execute("UPDATE bank_accounts SET active=1-active WHERE id=?", (aid,))
    return redirect(url_for("finance.bank_accounts"))


# ─────────────────────────────── PDF / IMÁGENES ──────────────────────────────

@bp.route("/recibo/<int:pid>/pdf")
@login_required
@permission_required("finance", "view")
def receipt_pdf(pid: int):
    from services.pdf_service import generate_receipt
    with db() as conn:
        pay = conn.execute("SELECT * FROM payments WHERE id=?", (pid,)).fetchone()
        if not pay:
            flash("Pago no encontrado", "error")
            return redirect(url_for("finance.index"))
        inv = conn.execute("""
            SELECT i.*, fc.name as concept FROM invoices i
            JOIN fee_concepts fc ON fc.id=i.concept_id WHERE i.id=?
        """, (pay["invoice_id"],)).fetchone()
        stu = conn.execute("""
            SELECT s.*, r.full_name as representative,
                   c.name||' '||sec.name as section
            FROM students s JOIN representatives r ON r.id=s.representative_id
            LEFT JOIN sections sec ON sec.id=s.section_id
            LEFT JOIN courses c ON c.id=sec.course_id WHERE s.id=?
        """, (inv["student_id"],)).fetchone()
    try:
        ced = decrypt(stu["cedula_enc"]) if stu.get("cedula_enc") else "—"
    except Exception:
        ced = "—"
    path = generate_receipt(
        {"payment_number": pay["payment_number"], "amount": pay["amount"],
         "payment_method": pay["payment_method"],
         "reference_num": pay["reference_num"] or "N/A",
         "bank": pay["bank"] or "N/A", "payment_date": pay["payment_date"]},
        {"first_name": stu["first_name"], "last_name": stu["last_name"],
         "section": stu["section"] or "—",
         "representative": stu["representative"], "cedula_rep": ced},
        {"concept": inv["concept"], "amount": inv["amount"],
         "discount": inv["discount"], "net_amount": inv["net_amount"]}
    )
    return send_file(path, as_attachment=True,
                     download_name=f"recibo_{pay['payment_number']}.pdf")


@bp.route("/comprobante/<int:pid>/thumb")
@login_required
def payment_thumb(pid: int):
    with db() as conn:
        img = conn.execute(
            "SELECT thumb_filename FROM payment_images WHERE payment_id=?", (pid,)
        ).fetchone()
    if not img:
        return "", 404
    path = get_thumb_path(img["thumb_filename"])
    if not os.path.exists(path):
        return "", 404
    return send_file(path, mimetype="image/jpeg")


@bp.route("/comprobante/<int:pid>/original")
@login_required
@permission_required("finance", "view")
def payment_original(pid: int):
    with db() as conn:
        img = conn.execute(
            "SELECT stored_filename FROM payment_images WHERE payment_id=?", (pid,)
        ).fetchone()
    if not img:
        return "", 404
    path = get_orig_path(img["stored_filename"])
    if not os.path.exists(path):
        return "", 404
    return send_file(path, mimetype="image/jpeg")
