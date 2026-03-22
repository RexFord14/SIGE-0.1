from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import date

from database import get_db
from models import (Student, StudentStatus, Representative, StudentRepresentative,
                    Enrollment, Section, SchoolYear, InvoiceStatus)
from utils.rbac import get_user_session, has_permission
from utils.audit_helper import log_event, get_client_ip
from utils.crypto import hash_value
from config import BASE_DIR

router = APIRouter(prefix="/students", tags=["students"])
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

VALID_TRANSITIONS = {
    StudentStatus.ACTIVO:   [StudentStatus.MOROSO, StudentStatus.RETIRADO, StudentStatus.EGRESADO],
    StudentStatus.MOROSO:   [StudentStatus.ACTIVO, StudentStatus.RETIRADO, StudentStatus.EGRESADO],
    StudentStatus.RETIRADO: [],
    StudentStatus.EGRESADO: [],
}


def _check_auth(request, module="students", action="view"):
    try:
        user = get_user_session(request)
    except Exception:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    if not has_permission(user["role"], module, action):
        raise HTTPException(status_code=403, detail="Sin permisos")
    return user


@router.get("/", response_class=HTMLResponse)
async def list_students(
    request: Request,
    q: str = "",
    status: str = "",
    page: int = 1,
    db: Session = Depends(get_db)
):
    user = _check_auth(request, "students", "view")
    query = db.query(Student)
    if q:
        query = query.filter(
            (Student.nombres.ilike(f"%{q}%")) |
            (Student.apellidos.ilike(f"%{q}%")) |
            (Student.codigo.ilike(f"%{q}%"))
        )
    if status:
        try:
            query = query.filter(Student.status == StudentStatus(status))
        except ValueError:
            pass

    total = query.count()
    per_page = 20
    students = query.order_by(Student.apellidos, Student.nombres)\
                    .offset((page - 1) * per_page).limit(per_page).all()

    is_htmx = request.headers.get("HX-Request")
    template = "students/list_partial.html" if is_htmx else "students/list.html"
    return templates.TemplateResponse(template, {
        "request": request, "user": user,
        "students": students, "q": q, "status_filter": status,
        "page": page, "total": total, "per_page": per_page,
        "statuses": [s.value for s in StudentStatus],
        "can_create": has_permission(user["role"], "students", "create"),
        "can_edit": has_permission(user["role"], "students", "edit"),
    })


@router.get("/new", response_class=HTMLResponse)
async def new_student_form(request: Request, db: Session = Depends(get_db)):
    user = _check_auth(request, "students", "create")
    sections = db.query(Section).filter(Section.is_active == True).all()
    active_year = db.query(SchoolYear).filter(SchoolYear.is_active == True).first()
    return templates.TemplateResponse("students/form.html", {
        "request": request, "user": user,
        "student": None, "sections": sections, "active_year": active_year,
        "mode": "create"
    })


@router.post("/new")
async def create_student(
    request: Request,
    nombres: str = Form(...),
    apellidos: str = Form(...),
    cedula: str = Form(""),
    fecha_nac: str = Form(""),
    sexo: str = Form(""),
    nacionalidad: str = Form("V"),
    section_id: int = Form(...),
    db: Session = Depends(get_db),
):
    user = _check_auth(request, "students", "create")

    # Generar código único
    last = db.query(Student).order_by(Student.id.desc()).first()
    new_id = (last.id + 1) if last else 1
    codigo = f"EST{new_id:05d}"

    student = Student(
        nombres=nombres.strip(),
        apellidos=apellidos.strip(),
        cedula=cedula.strip() if cedula.strip() else None,
        cedula_hash=hash_value(cedula) if cedula.strip() else None,
        fecha_nac=fecha_nac if fecha_nac else None,
        sexo=sexo if sexo else None,
        nacionalidad=nacionalidad,
        codigo=codigo,
        status=StudentStatus.ACTIVO,
    )
    db.add(student)
    db.flush()

    # Matrícula en sección activa
    active_year = db.query(SchoolYear).filter(SchoolYear.is_active == True).first()
    section = db.query(Section).get(section_id)

    if section and active_year:
        if section.cupo_disponible <= 0:
            db.rollback()
            return templates.TemplateResponse("students/form.html", {
                "request": request, "user": user,
                "error": "La sección seleccionada no tiene cupos disponibles",
                "student": None,
                "sections": db.query(Section).filter(Section.is_active == True).all(),
                "active_year": active_year, "mode": "create"
            })
        enrollment = Enrollment(
            student_id=student.id,
            school_year_id=active_year.id,
            section_id=section_id,
            fecha_ingreso=date.today(),
        )
        db.add(enrollment)

    log_event(db, "students", "INSERT", registro_id=student.id,
              valor_nuevo={"codigo": codigo, "nombres": nombres, "apellidos": apellidos},
              user_id=user["id"], ip_address=get_client_ip(request))
    db.commit()
    return RedirectResponse(f"/students/{student.id}", status_code=302)


@router.get("/{student_id}", response_class=HTMLResponse)
async def student_detail(request: Request, student_id: int, db: Session = Depends(get_db)):
    user = _check_auth(request, "students", "view")
    student = db.query(Student).get(student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")

    active_year = db.query(SchoolYear).filter(SchoolYear.is_active == True).first()

    return templates.TemplateResponse("students/detail.html", {
        "request": request, "user": user,
        "student": student,
        "active_year": active_year,
        "valid_transitions": [s.value for s in VALID_TRANSITIONS.get(student.status, [])],
        "can_edit": has_permission(user["role"], "students", "edit"),
        "can_status": has_permission(user["role"], "students", "status"),
        "StudentStatus": StudentStatus,
    })


@router.get("/{student_id}/edit", response_class=HTMLResponse)
async def edit_student_form(request: Request, student_id: int, db: Session = Depends(get_db)):
    user = _check_auth(request, "students", "edit")
    student = db.query(Student).get(student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    sections = db.query(Section).filter(Section.is_active == True).all()
    active_year = db.query(SchoolYear).filter(SchoolYear.is_active == True).first()
    return templates.TemplateResponse("students/form.html", {
        "request": request, "user": user,
        "student": student, "sections": sections,
        "active_year": active_year, "mode": "edit"
    })


@router.post("/{student_id}/edit")
async def update_student(
    request: Request,
    student_id: int,
    nombres: str = Form(...),
    apellidos: str = Form(...),
    cedula: str = Form(""),
    fecha_nac: str = Form(""),
    sexo: str = Form(""),
    nacionalidad: str = Form("V"),
    db: Session = Depends(get_db),
):
    user = _check_auth(request, "students", "edit")
    student = db.query(Student).get(student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")

    old = {"nombres": student.nombres, "apellidos": student.apellidos}
    student.nombres = nombres.strip()
    student.apellidos = apellidos.strip()
    if cedula.strip():
        student.cedula = cedula.strip()
        student.cedula_hash = hash_value(cedula)
    if fecha_nac:
        student.fecha_nac = fecha_nac
    student.sexo = sexo
    student.nacionalidad = nacionalidad

    log_event(db, "students", "UPDATE", registro_id=student_id,
              valor_anterior=old,
              valor_nuevo={"nombres": student.nombres, "apellidos": student.apellidos},
              user_id=user["id"], ip_address=get_client_ip(request))
    db.commit()
    return RedirectResponse(f"/students/{student_id}", status_code=302)


@router.post("/{student_id}/status")
async def change_status(
    request: Request,
    student_id: int,
    new_status: str = Form(...),
    razon: str = Form(""),
    db: Session = Depends(get_db),
):
    user = _check_auth(request, "students", "status")
    student = db.query(Student).get(student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")

    try:
        target = StudentStatus(new_status)
    except ValueError:
        raise HTTPException(status_code=400, detail="Estado inválido")

    # Máquina de estados
    allowed = VALID_TRANSITIONS.get(student.status, [])
    if target not in allowed:
        raise HTTPException(status_code=400, detail=f"Transición {student.status.value} → {target.value} no permitida")

    # REGLA DE BLOQUEO: No se puede retirar/egresar con deudas
    if target in (StudentStatus.RETIRADO, StudentStatus.EGRESADO):
        if student.tiene_deuda:
            return templates.TemplateResponse("students/detail.html", {
                "request": request, "user": user,
                "student": student,
                "error": f"No se puede cambiar a '{target.value}'. El estudiante tiene una deuda pendiente de Bs. {student.deuda_total:,.2f}",
                "valid_transitions": [s.value for s in allowed],
                "can_edit": has_permission(user["role"], "students", "edit"),
                "can_status": has_permission(user["role"], "students", "status"),
                "StudentStatus": StudentStatus,
            })

    old_status = student.status.value
    student.status = target

    # Desactivar matrícula si se retira/egresa
    if target in (StudentStatus.RETIRADO, StudentStatus.EGRESADO):
        for e in student.enrollments:
            if e.is_active:
                e.is_active = False
                e.fecha_retiro = date.today()

    log_event(db, "students", "STATUS_CHANGE", registro_id=student_id,
              valor_anterior={"status": old_status},
              valor_nuevo={"status": target.value, "razon": razon},
              user_id=user["id"], ip_address=get_client_ip(request))
    db.commit()
    return RedirectResponse(f"/students/{student_id}", status_code=302)


# ─── Representantes del estudiante ───────────────────────────────────────────
@router.post("/{student_id}/representatives/link")
async def link_representative(
    request: Request,
    student_id: int,
    cedula: str = Form(...),
    nombres: str = Form(...),
    apellidos: str = Form(...),
    parentesco: str = Form(...),
    telefono: str = Form(""),
    email: str = Form(""),
    direccion: str = Form(""),
    es_responsable: bool = Form(False),
    db: Session = Depends(get_db),
):
    user = _check_auth(request, "students", "edit")
    student = db.query(Student).get(student_id)
    if not student:
        raise HTTPException(status_code=404)

    cedula_hash = hash_value(cedula)
    rep = db.query(Representative).filter(Representative.cedula_hash == cedula_hash).first()

    if not rep:
        rep = Representative(
            cedula=cedula.strip(),
            cedula_hash=cedula_hash,
            nombres=nombres.strip(),
            apellidos=apellidos.strip(),
            telefono=telefono.strip() or None,
            email=email.strip() or None,
            direccion=direccion.strip() or None,
        )
        db.add(rep)
        db.flush()

    # Verificar que no esté ya vinculado
    existing = db.query(StudentRepresentative).filter(
        StudentRepresentative.student_id == student_id,
        StudentRepresentative.representative_id == rep.id,
        StudentRepresentative.is_active == True,
    ).first()

    if not existing:
        link = StudentRepresentative(
            student_id=student_id,
            representative_id=rep.id,
            parentesco=parentesco,
            es_responsable=es_responsable,
        )
        db.add(link)
        log_event(db, "student_representatives", "INSERT", registro_id=student_id,
                  valor_nuevo={"representante": f"{nombres} {apellidos}", "parentesco": parentesco},
                  user_id=user["id"], ip_address=get_client_ip(request))
        db.commit()

    return RedirectResponse(f"/students/{student_id}", status_code=302)
