from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date

from database import get_db
from models import Student, StudentStatus, Invoice, InvoiceStatus, CashRegister, CashRegisterStatus, Enrollment, SchoolYear
from utils.rbac import get_user_session
from config import BASE_DIR

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_user_session(request)
    except Exception:
        return RedirectResponse("/login", status_code=302)

    if user.get("must_change_pwd"):
        return RedirectResponse("/change-password", status_code=302)

    # Año escolar activo
    active_year = db.query(SchoolYear).filter(SchoolYear.is_active == True).first()

    # Stats de estudiantes
    total_students = db.query(Student).count()
    activos = db.query(Student).filter(Student.status == StudentStatus.ACTIVO).count()
    morosos = db.query(Student).filter(Student.status == StudentStatus.MOROSO).count()

    # Stats financieras
    facturas_pendientes = db.query(Invoice).filter(
        Invoice.status.in_([InvoiceStatus.PENDIENTE, InvoiceStatus.VENCIDO])
    ).count()

    # Caja del día
    caja_hoy = db.query(CashRegister).filter(CashRegister.fecha == date.today()).first()
    total_cobrado_hoy = 0.0
    if caja_hoy:
        total_cobrado_hoy = caja_hoy.total_ingresos

    # Deuda total del sistema
    invoices_pending = db.query(Invoice).filter(
        Invoice.status.in_([InvoiceStatus.PENDIENTE, InvoiceStatus.VENCIDO])
    ).all()
    deuda_total = sum(i.saldo_pendiente for i in invoices_pending)

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "active_year": active_year,
        "stats": {
            "total_students": total_students,
            "activos": activos,
            "morosos": morosos,
            "facturas_pendientes": facturas_pendientes,
            "total_cobrado_hoy": total_cobrado_hoy,
            "deuda_total": deuda_total,
            "caja_abierta": caja_hoy and caja_hoy.status == CashRegisterStatus.ABIERTA,
        }
    })
