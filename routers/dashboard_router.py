from flask import Blueprint, render_template
from database import db
from auth import login_required, current_user

bp = Blueprint("dashboard", __name__)

@bp.route("/")
@login_required
def index():
    stats = {}
    with db() as conn:
        stats["total_students"] = conn.execute("SELECT COUNT(*) FROM students WHERE status NOT IN ('RETIRADO','EGRESADO')").fetchone()[0]
        stats["activos"] = conn.execute("SELECT COUNT(*) FROM students WHERE status='ACTIVO'").fetchone()[0]
        stats["morosos"] = conn.execute("SELECT COUNT(*) FROM students WHERE status='MOROSO'").fetchone()[0]
        stats["pending_invoices"] = conn.execute("SELECT COUNT(*) FROM invoices WHERE status IN ('PENDIENTE','PARCIAL')").fetchone()[0]
        row = conn.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE voided=0 AND strftime('%Y-%m',payment_date)=strftime('%Y-%m','now')").fetchone()
        stats["monthly_income"] = row[0] if row else 0
        row2 = conn.execute("SELECT COALESCE(SUM(net_amount-paid_amount),0) FROM invoices WHERE status IN ('PENDIENTE','PARCIAL')").fetchone()
        stats["total_debt"] = row2[0] if row2 else 0
        stats["recent_payments"] = conn.execute("""
            SELECT p.payment_number, p.amount, p.payment_date, p.payment_method,
                   s.first_name||' '||s.last_name as student_name
            FROM payments p JOIN invoices i ON i.id=p.invoice_id
            JOIN students s ON s.id=i.student_id
            WHERE p.voided=0 ORDER BY p.created_at DESC LIMIT 8
        """).fetchall()
        stats["morosos_list"] = conn.execute("""
            SELECT s.first_name||' '||s.last_name as name,
                   COALESCE(SUM(i.net_amount-i.paid_amount),0) as debt
            FROM students s JOIN invoices i ON i.student_id=s.id
            WHERE s.status='MOROSO' AND i.status IN ('PENDIENTE','PARCIAL')
            GROUP BY s.id ORDER BY debt DESC LIMIT 6
        """).fetchall()
    return render_template("dashboard.html", stats=stats, user=current_user())
