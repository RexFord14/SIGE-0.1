from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from models import Course, Section, Subject, CourseSubject, User, UserRole
from utils.rbac import get_user_session, has_permission
from utils.audit_helper import log_event, get_client_ip
from config import BASE_DIR

router = APIRouter(prefix="/courses", tags=["courses"])
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _check_auth(request, action="view"):
    try:
        user = get_user_session(request)
    except Exception:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    if not has_permission(user["role"], "courses", action):
        raise HTTPException(status_code=403)
    return user


@router.get("/", response_class=HTMLResponse)
async def list_courses(request: Request, db: Session = Depends(get_db)):
    user = _check_auth(request)
    courses = db.query(Course).filter(Course.is_active == True).order_by(Course.grado).all()
    return templates.TemplateResponse("courses/list.html", {
        "request": request, "user": user,
        "courses": courses,
        "can_create": has_permission(user["role"], "courses", "create"),
        "can_edit": has_permission(user["role"], "courses", "edit"),
    })


@router.post("/new")
async def create_course(
    request: Request,
    nombre: str = Form(...),
    nivel: str = Form(...),
    grado: int = Form(...),
    db: Session = Depends(get_db),
):
    user = _check_auth(request, "create")
    course = Course(nombre=nombre.strip(), nivel=nivel.strip(), grado=grado)
    db.add(course)
    db.flush()
    log_event(db, "courses", "INSERT", registro_id=course.id,
              valor_nuevo={"nombre": nombre, "grado": grado},
              user_id=user["id"], ip_address=get_client_ip(request))
    db.commit()
    return RedirectResponse("/courses", status_code=302)


@router.post("/{course_id}/sections/new")
async def create_section(
    request: Request,
    course_id: int,
    nombre: str = Form(...),
    cupo_maximo: int = Form(35),
    db: Session = Depends(get_db),
):
    user = _check_auth(request, "create")
    section = Section(course_id=course_id, nombre=nombre.strip(), cupo_maximo=cupo_maximo)
    db.add(section)
    db.flush()
    log_event(db, "sections", "INSERT", registro_id=section.id,
              valor_nuevo={"course_id": course_id, "nombre": nombre, "cupo_maximo": cupo_maximo},
              user_id=user["id"], ip_address=get_client_ip(request))
    db.commit()
    return RedirectResponse("/courses", status_code=302)


@router.get("/subjects", response_class=HTMLResponse)
async def list_subjects(request: Request, db: Session = Depends(get_db)):
    user = _check_auth(request)
    subjects = db.query(Subject).filter(Subject.is_active == True).all()
    courses = db.query(Course).filter(Course.is_active == True).all()
    docentes = db.query(User).filter(User.role == UserRole.DOCENTE, User.is_active == True).all()
    return templates.TemplateResponse("courses/subjects.html", {
        "request": request, "user": user,
        "subjects": subjects, "courses": courses, "docentes": docentes,
        "can_create": has_permission(user["role"], "courses", "create"),
    })


@router.post("/subjects/new")
async def create_subject(
    request: Request,
    codigo: str = Form(...),
    nombre: str = Form(...),
    db: Session = Depends(get_db),
):
    user = _check_auth(request, "create")
    subject = Subject(codigo=codigo.strip().upper(), nombre=nombre.strip())
    db.add(subject)
    db.flush()
    log_event(db, "subjects", "INSERT", registro_id=subject.id,
              valor_nuevo={"codigo": codigo, "nombre": nombre},
              user_id=user["id"], ip_address=get_client_ip(request))
    db.commit()
    return RedirectResponse("/courses/subjects", status_code=302)


@router.post("/subjects/assign")
async def assign_subject(
    request: Request,
    course_id: int = Form(...),
    subject_id: int = Form(...),
    docente_id: int = Form(None),
    horas_sem: int = Form(4),
    db: Session = Depends(get_db),
):
    user = _check_auth(request, "create")
    existing = db.query(CourseSubject).filter(
        CourseSubject.course_id == course_id,
        CourseSubject.subject_id == subject_id,
    ).first()
    if not existing:
        cs = CourseSubject(
            course_id=course_id, subject_id=subject_id,
            docente_id=docente_id if docente_id else None,
            horas_sem=horas_sem,
        )
        db.add(cs)
        db.commit()
    return RedirectResponse("/courses/subjects", status_code=302)
