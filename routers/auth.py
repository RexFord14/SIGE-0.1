from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from datetime import datetime

from database import get_db
from models import User
from utils.audit_helper import log_event, get_client_ip
from config import BASE_DIR

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == username, User.is_active == True).first()
    error = None

    if not user or not pwd_context.verify(password, user.password_hash):
        error = "Usuario o contraseña incorrectos"
        log_event(db, "users", "LOGIN_FAILED", descripcion=f"Intento fallido: {username}",
                  ip_address=get_client_ip(request))
        db.commit()
        return templates.TemplateResponse("login.html", {"request": request, "error": error})

    user.last_login = datetime.utcnow()
    log_event(db, "users", "LOGIN", registro_id=user.id,
              descripcion=f"Login exitoso: {user.username}", user_id=user.id,
              ip_address=get_client_ip(request))
    db.commit()

    request.session["user_id"] = user.id
    request.session["username"] = user.username
    request.session["full_name"] = user.full_name
    request.session["role"] = user.role.value
    request.session["must_change_pwd"] = user.must_change_pwd

    if user.must_change_pwd:
        return RedirectResponse("/change-password", status_code=302)
    return RedirectResponse("/", status_code=302)


@router.get("/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
    uid = request.session.get("user_id")
    if uid:
        log_event(db, "users", "LOGOUT", registro_id=uid,
                  descripcion=f"Logout: {request.session.get('username')}",
                  user_id=uid, ip_address=get_client_ip(request))
        db.commit()
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


@router.get("/change-password", response_class=HTMLResponse)
async def change_password_page(request: Request):
    if not request.session.get("user_id"):
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse("change_password.html", {"request": request})


@router.post("/change-password")
async def change_password_post(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    uid = request.session.get("user_id")
    if not uid:
        return RedirectResponse("/login", status_code=302)

    user = db.query(User).get(uid)
    errors = []

    if not pwd_context.verify(current_password, user.password_hash):
        errors.append("Contraseña actual incorrecta")
    if new_password != confirm_password:
        errors.append("Las contraseñas no coinciden")
    if len(new_password) < 8:
        errors.append("La contraseña debe tener al menos 8 caracteres")

    if errors:
        return templates.TemplateResponse("change_password.html", {
            "request": request, "errors": errors
        })

    user.password_hash = pwd_context.hash(new_password)
    user.must_change_pwd = False
    request.session["must_change_pwd"] = False
    log_event(db, "users", "PASSWORD_CHANGED", registro_id=user.id,
              user_id=user.id, ip_address=get_client_ip(request))
    db.commit()
    return RedirectResponse("/", status_code=302)
