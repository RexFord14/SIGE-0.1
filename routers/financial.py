from fastapi import APIRouter, Request, Depends, Form, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import date, datetime
from typing import Optional

from database import get_db
from models import (Student, StudentStatus, Invoice, InvoiceStatus, Payment, PaymentMethod,
                    CashRegister, CashRegisterStatus, BankConciliation, JournalEntry,
                    JournalLine, Account, SchoolYear, AccountType)
from utils.rbac import get_user_session, has_permission
from utils.audit_helper import log_event, get_client_ip
from config import BASE_DIR

router = APIRouter(prefix="/financial", tags=["financial"])
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _check_auth(request, action="view"):
    try:
        user = get_user_session(request)
    except Exception:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    if not has_permission(user["role"], "financial", action):
        raise HTTPException(status_code=403)
    return user


def _next_number(db, model, field, prefix):
    from sqlalchemy import func
    last = db.query(func.max(getattr(model, field))).scalar()
    if last:
        try:
            n = int(last.replace(prefix, "")) + 1
        except Exception:
            n = 1
    else:
        n = 1
    return f"{prefix}{n:06d}"


# ─── FACTURAS ────────────────────────────────────────────────────────────────
@router.get("/invoices", response_class=HTMLResponse)
async def list_invoices(
    request: Request, q: str = "", status: str = "", page: int = 1,
    db: Session = Depends(get_db)
):
    user = _check_auth(request)
    query = db.query(Invoice).join(Student)
    if q:
        query = query.filter(
            Student.nombres.ilike(f"%{q}%") |
            Student.apellidos.ilike(f"%{q}%") |
            Student.codigo.ilike(f"%{q}%") |
            Invoice.numero.ilike(f"%{q}%")
        )
    if status:
        try:
            query = query.filter(Invoice.status == InvoiceStatus(status))
        except ValueError:
            pass
    total = query.count()
    per_page = 20
    invoices = query.order_by(Invoice.fecha_vencimiento.desc())\
                    .offset((page-1)*per_page).limit(per_page).all()

    active_year = db.query(SchoolYear).filter(SchoolYear.is_active == True).first()

    return templates.TemplateResponse("financial/invoices.html", {
        "request": request, "user": user,
        "invoices": invoices, "q": q, "status_filter": status,
        "page": page, "total": total, "per_page": per_page,
        "statuses": [s.value for s in InvoiceStatus],
        "active_year": active_year,
        "can_create": has_permission(user["role"], "financial", "create"),
        "can_void": has_permission(user["role"], "financial", "void"),
    })


@router.post("/invoices/new")
async def create_invoice(
    request: Request,
    student_id: int = Form(...),
    concepto: str = Form(...),
    monto_total: float = Form(...),
    descuento: float = Form(0.0),
    fecha_vencimiento: str = Form(...),
    lapso: int = Form(None),
    notas: str = Form(""),
    db: Session = Depends(get_db),
):
    user = _check_auth(request, "create")
    active_year = db.query(SchoolYear).filter(SchoolYear.is_active == True).first()

    numero = _next_number(db, Invoice, "numero", "FAC")
    invoice = Invoice(
        numero=numero,
        student_id=student_id,
        concepto=concepto.strip(),
        monto_total=monto_total,
        descuento=descuento,
        fecha_vencimiento=date.fromisoformat(fecha_vencimiento),
        school_year_id=active_year.id if active_year else None,
        lapso=lapso,
        notas=notas.strip() or None,
    )
    db.add(invoice)
    db.flush()

    # Asiento contable: Dr. Cuentas por Cobrar / Cr. Ingresos
    _create_journal_entry(db, user["id"],
        descripcion=f"Factura {numero} - {concepto}",
        referencia=numero,
        debits={"1-1-01": invoice.monto_neto},  # Cuentas por cobrar
        credits={"4-1-01": invoice.monto_neto},  # Ingresos por matrícula
    )

    # Actualizar estado del estudiante si tiene deuda
    student = db.query(Student).get(student_id)
    if student and student.status == StudentStatus.ACTIVO:
        student.status = StudentStatus.MOROSO

    log_event(db, "invoices", "INSERT", registro_id=invoice.id,
              valor_nuevo={"numero": numero, "monto": monto_total, "student_id": student_id},
              user_id=user["id"], ip_address=get_client_ip(request))
    db.commit()
    return RedirectResponse("/financial/invoices", status_code=302)


@router.post("/invoices/{invoice_id}/void")
async def void_invoice(
    request: Request, invoice_id: int,
    razon: str = Form(...),
    db: Session = Depends(get_db),
):
    user = _check_auth(request, "void")
    invoice = db.query(Invoice).get(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404)
    if invoice.status == InvoiceStatus.ANULADO:
        raise HTTPException(status_code=400, detail="Ya está anulada")

    old_status = invoice.status.value
    invoice.status = InvoiceStatus.ANULADO
    log_event(db, "invoices", "VOID", registro_id=invoice_id,
              valor_anterior={"status": old_status},
              valor_nuevo={"status": "Anulado", "razon": razon},
              user_id=user["id"], ip_address=get_client_ip(request))
    db.commit()
    return RedirectResponse("/financial/invoices", status_code=302)


# ─── PAGOS ───────────────────────────────────────────────────────────────────
@router.get("/invoices/{invoice_id}/pay", response_class=HTMLResponse)
async def pay_invoice_form(request: Request, invoice_id: int, db: Session = Depends(get_db)):
    user = _check_auth(request, "create")
    invoice = db.query(Invoice).get(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404)
    caja = db.query(CashRegister).filter(
        CashRegister.fecha == date.today(),
        CashRegister.status == CashRegisterStatus.ABIERTA,
    ).first()
    return templates.TemplateResponse("financial/pay_form.html", {
        "request": request, "user": user,
        "invoice": invoice, "caja": caja,
        "metodos": [m.value for m in PaymentMethod],
    })


@router.post("/invoices/{invoice_id}/pay")
async def register_payment(
    request: Request,
    invoice_id: int,
    monto: float = Form(...),
    metodo: str = Form(...),
    referencia: str = Form(""),
    banco: str = Form(""),
    descripcion: str = Form(""),
    db: Session = Depends(get_db),
):
    user = _check_auth(request, "create")
    invoice = db.query(Invoice).get(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404)
    if invoice.status == InvoiceStatus.ANULADO:
        raise HTTPException(status_code=400, detail="Factura anulada")

    if monto <= 0 or monto > invoice.saldo_pendiente:
        raise HTTPException(status_code=400, detail="Monto inválido")

    caja = db.query(CashRegister).filter(
        CashRegister.fecha == date.today(),
        CashRegister.status == CashRegisterStatus.ABIERTA,
    ).first()

    numero = _next_number(db, Payment, "numero", "REC")
    payment = Payment(
        numero=numero,
        invoice_id=invoice_id,
        monto=monto,
        fecha=date.today(),
        metodo=PaymentMethod(metodo),
        referencia=referencia.strip() or None,
        banco=banco.strip() or None,
        descripcion=descripcion.strip() or None,
        user_id=user["id"],
        cash_register_id=caja.id if caja else None,
    )
    db.add(payment)
    db.flush()

    # Actualizar estado de la factura
    total_pagado = sum(p.monto for p in invoice.payments if not p.is_void) + monto
    if total_pagado >= invoice.monto_neto:
        invoice.status = InvoiceStatus.PAGADO

    # Verificar si el estudiante saldó todo
    student = invoice.student
    if not student.tiene_deuda:
        if student.status == StudentStatus.MOROSO:
            student.status = StudentStatus.ACTIVO

    # Asiento contable: Dr. Caja o Banco / Cr. Cuentas por cobrar
    cuenta_db = "1-1-02" if metodo == PaymentMethod.EFECTIVO.value else "1-1-03"
    _create_journal_entry(db, user["id"],
        descripcion=f"Pago {numero} - Factura {invoice.numero}",
        referencia=numero,
        debits={cuenta_db: monto},
        credits={"1-1-01": monto},
    )

    log_event(db, "payments", "INSERT", registro_id=payment.id,
              valor_nuevo={"numero": numero, "monto": monto, "metodo": metodo},
              user_id=user["id"], ip_address=get_client_ip(request))
    db.commit()
    return RedirectResponse(f"/financial/payments/{payment.id}/receipt", status_code=302)


@router.get("/payments/{payment_id}/receipt", response_class=HTMLResponse)
async def payment_receipt(request: Request, payment_id: int, db: Session = Depends(get_db)):
    user = _check_auth(request)
    payment = db.query(Payment).get(payment_id)
    if not payment:
        raise HTTPException(status_code=404)
    from models import SchoolSetting
    settings = {s.key: s.value for s in db.query(SchoolSetting).all()}
    return templates.TemplateResponse("financial/receipt.html", {
        "request": request, "user": user,
        "payment": payment, "settings": settings,
    })


# ─── CAJA ────────────────────────────────────────────────────────────────────
@router.get("/cash", response_class=HTMLResponse)
async def cash_register(request: Request, db: Session = Depends(get_db)):
    user = _check_auth(request)
    today_caja = db.query(CashRegister).filter(CashRegister.fecha == date.today()).first()
    recent = db.query(CashRegister).order_by(CashRegister.fecha.desc()).limit(30).all()
    return templates.TemplateResponse("financial/cash.html", {
        "request": request, "user": user,
        "caja_hoy": today_caja, "recent": recent,
        "today": date.today(),
        "can_create": has_permission(user["role"], "financial", "create"),
        "can_void": has_permission(user["role"], "financial", "void"),
    })


@router.post("/cash/open")
async def open_cash(
    request: Request,
    saldo_apertura: float = Form(0.0),
    db: Session = Depends(get_db),
):
    user = _check_auth(request, "create")
    existing = db.query(CashRegister).filter(CashRegister.fecha == date.today()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Caja ya abierta hoy")
    caja = CashRegister(
        fecha=date.today(), saldo_apertura=saldo_apertura,
        status=CashRegisterStatus.ABIERTA, user_id=user["id"]
    )
    db.add(caja)
    log_event(db, "cash_registers", "INSERT", descripcion="Apertura de caja",
              valor_nuevo={"fecha": str(date.today()), "saldo_apertura": saldo_apertura},
              user_id=user["id"], ip_address=get_client_ip(request))
    db.commit()
    return RedirectResponse("/financial/cash", status_code=302)


@router.post("/cash/close")
async def close_cash(
    request: Request,
    saldo_cierre: float = Form(...),
    notas: str = Form(""),
    db: Session = Depends(get_db),
):
    user = _check_auth(request, "edit")
    caja = db.query(CashRegister).filter(
        CashRegister.fecha == date.today(),
        CashRegister.status == CashRegisterStatus.ABIERTA,
    ).first()
    if not caja:
        raise HTTPException(status_code=400, detail="No hay caja abierta")
    caja.saldo_cierre = saldo_cierre
    caja.status = CashRegisterStatus.CERRADA
    caja.notas = notas.strip() or None
    caja.closed_at = datetime.utcnow()
    log_event(db, "cash_registers", "UPDATE", registro_id=caja.id,
              descripcion="Cierre de caja",
              valor_nuevo={"saldo_cierre": saldo_cierre},
              user_id=user["id"], ip_address=get_client_ip(request))
    db.commit()
    return RedirectResponse("/financial/cash", status_code=302)


# ─── CONCILIACIÓN BANCARIA ───────────────────────────────────────────────────
@router.get("/conciliation", response_class=HTMLResponse)
async def conciliation(request: Request, db: Session = Depends(get_db)):
    user = _check_auth(request)
    entries = db.query(BankConciliation).order_by(BankConciliation.fecha_banco.desc()).limit(100).all()
    payments_unmatched = db.query(Payment).filter(
        Payment.metodo != PaymentMethod.EFECTIVO,
        Payment.is_void == False,
    ).outerjoin(BankConciliation).filter(BankConciliation.id == None).limit(50).all()
    return templates.TemplateResponse("financial/conciliation.html", {
        "request": request, "user": user,
        "entries": entries,
        "payments_unmatched": payments_unmatched,
        "can_create": has_permission(user["role"], "financial", "create"),
    })


@router.post("/conciliation/new")
async def new_conciliation(
    request: Request,
    referencia: str = Form(...),
    fecha_banco: str = Form(...),
    monto: float = Form(...),
    banco: str = Form(...),
    concepto: str = Form(...),
    payment_id: int = Form(None),
    db: Session = Depends(get_db),
):
    user = _check_auth(request, "create")
    entry = BankConciliation(
        referencia=referencia.strip(),
        fecha_banco=date.fromisoformat(fecha_banco),
        monto=monto,
        banco=banco.strip(),
        concepto=concepto.strip(),
        payment_id=payment_id if payment_id else None,
        conciliado=bool(payment_id),
        fecha_conciliacion=datetime.utcnow() if payment_id else None,
    )
    db.add(entry)
    log_event(db, "bank_conciliations", "INSERT",
              valor_nuevo={"referencia": referencia, "monto": monto, "banco": banco},
              user_id=user["id"], ip_address=get_client_ip(request))
    db.commit()
    return RedirectResponse("/financial/conciliation", status_code=302)


@router.post("/conciliation/{entry_id}/match")
async def match_conciliation(
    request: Request,
    entry_id: int,
    payment_id: int = Form(...),
    db: Session = Depends(get_db),
):
    user = _check_auth(request, "edit")
    entry = db.query(BankConciliation).get(entry_id)
    if not entry or entry.conciliado:
        raise HTTPException(status_code=400, detail="Ya conciliado o no existe")
    entry.payment_id = payment_id
    entry.conciliado = True
    entry.fecha_conciliacion = datetime.utcnow()
    log_event(db, "bank_conciliations", "UPDATE", registro_id=entry_id,
              descripcion=f"Conciliado con pago #{payment_id}",
              user_id=user["id"], ip_address=get_client_ip(request))
    db.commit()
    return RedirectResponse("/financial/conciliation", status_code=302)


# ─── LIBRO DIARIO ────────────────────────────────────────────────────────────
@router.get("/journal", response_class=HTMLResponse)
async def journal(request: Request, db: Session = Depends(get_db)):
    user = _check_auth(request)
    entries = db.query(JournalEntry).order_by(JournalEntry.fecha.desc()).limit(100).all()
    accounts = db.query(Account).filter(Account.is_active == True).order_by(Account.codigo).all()
    return templates.TemplateResponse("financial/journal.html", {
        "request": request, "user": user,
        "entries": entries, "accounts": accounts,
        "can_void": has_permission(user["role"], "financial", "void"),
    })


def _create_journal_entry(db, user_id, descripcion, referencia, debits: dict, credits: dict):
    """Helper para crear asientos contables automáticos."""
    numero = _next_number(db, JournalEntry, "numero", "AS")
    entry = JournalEntry(
        numero=numero, fecha=date.today(),
        descripcion=descripcion, referencia=referencia, user_id=user_id,
    )
    db.add(entry)
    db.flush()

    for codigo, monto in debits.items():
        account = db.query(Account).filter(Account.codigo == codigo).first()
        if account:
            line = JournalLine(entry_id=entry.id, account_id=account.id, debe=monto, haber=0)
            db.add(line)

    for codigo, monto in credits.items():
        account = db.query(Account).filter(Account.codigo == codigo).first()
        if account:
            line = JournalLine(entry_id=entry.id, account_id=account.id, debe=0, haber=monto)
            db.add(line)

    return entry
