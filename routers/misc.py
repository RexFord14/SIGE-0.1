from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime

from database import get_db
from models import AuditLog, User, UserRole, SchoolSetting, SchoolYear, SchoolLapso
from utils.rbac import get_user_session, has_permission
from utils.audit_helper import log_event, get_client_ip
from passlib.context import CryptContext
from config import BASE_DIR
from datetime import date

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ─── AUDITORÍA ───────────────────────────────────────────────────────────────
@router.get("/audit", response_class=HTMLResponse)
async def audit_logs(
    request: Request,
    tabla: str = "", accion: str = "", page: int = 1,
    db: Session = Depends(get_db),
):
    try:
        user = get_user_session(request)
    except Exception:
        return RedirectResponse("/login", status_code=302)
    if not has_permission(user["role"], "audit", "view"):
        raise HTTPException(status_code=403)

    query = db.query(AuditLog)
    if tabla:
        query = query.filter(AuditLog.tabla == tabla)
    if accion:
        query = query.filter(AuditLog.accion == accion)

    total = query.count()
    per_page = 30
    logs = query.order_by(AuditLog.timestamp.desc())\
                .offset((page-1)*per_page).limit(per_page).all()

    tablas = [r[0] for r in db.query(AuditLog.tabla).distinct().all()]
    acciones = [r[0] for r in db.query(AuditLog.accion).distinct().all()]

    return templates.TemplateResponse("audit/logs.html", {
        "request": request, "user": user,
        "logs": logs, "page": page, "total": total, "per_page": per_page,
        "tabla_filter": tabla, "accion_filter": accion,
        "tablas": tablas, "acciones": acciones,
    })


# ─── USUARIOS ────────────────────────────────────────────────────────────────
@router.get("/users", response_class=HTMLResponse)
async def list_users(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_user_session(request)
    except Exception:
        return RedirectResponse("/login", status_code=302)
    if not has_permission(user["role"], "users", "view"):
        raise HTTPException(status_code=403)
    users = db.query(User).order_by(User.full_name).all()
    return templates.TemplateResponse("settings/users.html", {
        "request": request, "user": user, "users": users,
        "roles": [r.value for r in UserRole],
        "can_create": has_permission(user["role"], "users", "create"),
        "can_edit": has_permission(user["role"], "users", "edit"),
    })


@router.post("/users/new")
async def create_user(
    request: Request,
    username: str = Form(...),
    full_name: str = Form(...),
    email: str = Form(""),
    role: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        user = get_user_session(request)
    except Exception:
        return RedirectResponse("/login", status_code=302)
    if not has_permission(user["role"], "users", "create"):
        raise HTTPException(status_code=403)

    new_user = User(
        username=username.strip(),
        full_name=full_name.strip(),
        email=email.strip() or None,
        role=UserRole(role),
        password_hash=pwd_context.hash(password),
        must_change_pwd=True,
    )
    db.add(new_user)
    db.flush()
    log_event(db, "users", "INSERT", registro_id=new_user.id,
              valor_nuevo={"username": username, "role": role},
              user_id=user["id"], ip_address=get_client_ip(request))
    db.commit()
    return RedirectResponse("/users", status_code=302)


@router.post("/users/{uid}/toggle")
async def toggle_user(request: Request, uid: int, db: Session = Depends(get_db)):
    try:
        user = get_user_session(request)
    except Exception:
        return RedirectResponse("/login", status_code=302)
    if not has_permission(user["role"], "users", "edit"):
        raise HTTPException(status_code=403)
    if uid == user["id"]:
        raise HTTPException(status_code=400, detail="No puede desactivarse a sí mismo")
    target = db.query(User).get(uid)
    if not target:
        raise HTTPException(status_code=404)
    target.is_active = not target.is_active
    db.commit()
    return RedirectResponse("/users", status_code=302)


# ─── CONFIGURACIÓN ──────────────────────────────────────────────────────────
@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_user_session(request)
    except Exception:
        return RedirectResponse("/login", status_code=302)
    if not has_permission(user["role"], "settings", "view"):
        raise HTTPException(status_code=403)

    settings = {s.key: s.value for s in db.query(SchoolSetting).all()}
    school_years = db.query(SchoolYear).order_by(SchoolYear.nombre.desc()).all()

    return templates.TemplateResponse("settings/main.html", {
        "request": request, "user": user,
        "settings": settings, "school_years": school_years,
        "can_edit": has_permission(user["role"], "settings", "edit"),
    })


@router.post("/settings/save")
async def save_settings(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_user_session(request)
    except Exception:
        return RedirectResponse("/login", status_code=302)
    if not has_permission(user["role"], "settings", "edit"):
        raise HTTPException(status_code=403)

    form = await request.form()
    for key, value in form.items():
        setting = db.query(SchoolSetting).filter(SchoolSetting.key == key).first()
        if setting:
            setting.value = str(value)
            setting.updated_at = datetime.utcnow()
        else:
            db.add(SchoolSetting(key=key, value=str(value)))

    log_event(db, "school_settings", "UPDATE",
              descripcion="Configuración del colegio actualizada",
              user_id=user["id"], ip_address=get_client_ip(request))
    db.commit()
    return RedirectResponse("/settings", status_code=302)


@router.post("/settings/years/new")
async def new_school_year(
    request: Request,
    nombre: str = Form(...),
    fecha_inicio: str = Form(...),
    fecha_fin: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        user = get_user_session(request)
    except Exception:
        return RedirectResponse("/login", status_code=302)
    if not has_permission(user["role"], "settings", "edit"):
        raise HTTPException(status_code=403)

    year = SchoolYear(
        nombre=nombre.strip(),
        fecha_inicio=date.fromisoformat(fecha_inicio),
        fecha_fin=date.fromisoformat(fecha_fin),
        is_active=False,
    )
    db.add(year)
    db.flush()
    # Crear 3 lapsos por defecto
    from datetime import timedelta
    total_days = (year.fecha_fin - year.fecha_inicio).days
    lapso_days = total_days // 3
    for i in range(1, 4):
        inicio = year.fecha_inicio + timedelta(days=lapso_days*(i-1))
        fin = inicio + timedelta(days=lapso_days - 1) if i < 3 else year.fecha_fin
        lapso = SchoolLapso(
            school_year_id=year.id,
            numero=i,
            nombre=f"{'Primer' if i==1 else 'Segundo' if i==2 else 'Tercer'} Lapso",
            fecha_inicio=inicio,
            fecha_fin=fin,
        )
        db.add(lapso)

    log_event(db, "school_years", "INSERT", registro_id=year.id,
              valor_nuevo={"nombre": nombre},
              user_id=user["id"], ip_address=get_client_ip(request))
    db.commit()
    return RedirectResponse("/settings", status_code=302)


@router.post("/settings/years/{year_id}/activate")
async def activate_year(request: Request, year_id: int, db: Session = Depends(get_db)):
    try:
        user = get_user_session(request)
    except Exception:
        return RedirectResponse("/login", status_code=302)
    if not has_permission(user["role"], "settings", "edit"):
        raise HTTPException(status_code=403)
    # Desactivar todos
    db.query(SchoolYear).update({SchoolYear.is_active: False})
    year = db.query(SchoolYear).get(year_id)
    if year:
        year.is_active = True
    db.commit()
    return RedirectResponse("/settings", status_code=302)
