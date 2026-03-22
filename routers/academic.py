from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import date

from database import get_db
from models import (Student, CourseSubject, Grade, Attendance, AttendanceStatus,
                    EvalActivity, SchoolYear, SchoolLapso, Section, Enrollment)
from utils.rbac import get_user_session, has_permission
from utils.audit_helper import log_event, get_client_ip
from config import BASE_DIR

router = APIRouter(prefix="/academic", tags=["academic"])
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _check_auth(request, action="view"):
    try:
        user = get_user_session(request)
    except Exception:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    if not has_permission(user["role"], "academic", action):
        raise HTTPException(status_code=403)
    return user


# ─── CONFIGURACIÓN EVALUATIVA ────────────────────────────────────────────────
@router.get("/eval-matrix", response_class=HTMLResponse)
async def eval_matrix(request: Request, db: Session = Depends(get_db)):
    user = _check_auth(request)
    course_subjects = db.query(CourseSubject).all()
    active_year = db.query(SchoolYear).filter(SchoolYear.is_active == True).first()
    return templates.TemplateResponse("academic/eval_matrix.html", {
        "request": request, "user": user,
        "course_subjects": course_subjects,
        "active_year": active_year,
        "can_edit": has_permission(user["role"], "academic", "edit"),
    })


@router.post("/eval-matrix/activity/new")
async def new_eval_activity(
    request: Request,
    course_subject_id: int = Form(...),
    lapso_numero: int = Form(...),
    nombre: str = Form(...),
    porcentaje: float = Form(...),
    db: Session = Depends(get_db),
):
    user = _check_auth(request, "edit")

    # Verificar que la suma de porcentajes no supere 100%
    existing = db.query(EvalActivity).filter(
        EvalActivity.course_subject_id == course_subject_id,
        EvalActivity.lapso_numero == lapso_numero,
    ).all()
    total_pct = sum(a.porcentaje for a in existing)
    if total_pct + porcentaje > 100:
        raise HTTPException(status_code=400, detail=f"Suma de porcentajes superaría 100% (actual: {total_pct}%)")

    activity = EvalActivity(
        course_subject_id=course_subject_id,
        lapso_numero=lapso_numero,
        nombre=nombre.strip(),
        porcentaje=porcentaje,
    )
    db.add(activity)
    log_event(db, "eval_activities", "INSERT",
              valor_nuevo={"nombre": nombre, "porcentaje": porcentaje, "lapso": lapso_numero},
              user_id=user["id"], ip_address=get_client_ip(request))
    db.commit()
    return RedirectResponse("/academic/eval-matrix", status_code=302)


# ─── NOTAS ───────────────────────────────────────────────────────────────────
@router.get("/grades", response_class=HTMLResponse)
async def grades_view(
    request: Request,
    course_subject_id: int = None,
    lapso_id: int = None,
    db: Session = Depends(get_db),
):
    user = _check_auth(request)
    active_year = db.query(SchoolYear).filter(SchoolYear.is_active == True).first()
    course_subjects = db.query(CourseSubject).all()

    students = []
    activities = []
    grades_map = {}
    selected_cs = None
    selected_lapso = None

    if course_subject_id and lapso_id:
        selected_cs = db.query(CourseSubject).get(course_subject_id)
        selected_lapso = db.query(SchoolLapso).get(lapso_id)

        if selected_cs:
            activities = db.query(EvalActivity).filter(
                EvalActivity.course_subject_id == course_subject_id,
                EvalActivity.lapso_numero == (selected_lapso.numero if selected_lapso else 1),
            ).all()

            # Estudiantes de la sección asociada al curso
            enrollments = db.query(Enrollment).filter(
                Enrollment.section_id.in_(
                    [s.id for s in selected_cs.course.sections]
                ),
                Enrollment.is_active == True,
            ).all()
            students = [e.student for e in enrollments]

            # Mapa de notas
            for student in students:
                grades_map[student.id] = {}
                for act in activities:
                    grade = db.query(Grade).filter(
                        Grade.student_id == student.id,
                        Grade.course_subject_id == course_subject_id,
                        Grade.lapso_id == lapso_id,
                        Grade.activity_id == act.id,
                    ).first()
                    grades_map[student.id][act.id] = grade.valor if grade else None

    lapsos = active_year.lapsos if active_year else []

    return templates.TemplateResponse("academic/grades.html", {
        "request": request, "user": user,
        "active_year": active_year, "lapsos": lapsos,
        "course_subjects": course_subjects,
        "selected_cs": selected_cs, "selected_lapso": selected_lapso,
        "students": students, "activities": activities,
        "grades_map": grades_map,
        "can_edit": has_permission(user["role"], "academic", "edit"),
    })


@router.post("/grades/save")
async def save_grades(request: Request, db: Session = Depends(get_db)):
    user = _check_auth(request, "edit")
    form = await request.form()

    saved = 0
    for key, value in form.items():
        # key format: grade_{student_id}_{course_subject_id}_{lapso_id}_{activity_id}
        if not key.startswith("grade_"):
            continue
        try:
            _, student_id, cs_id, lapso_id, act_id = key.split("_")
            student_id, cs_id, lapso_id, act_id = int(student_id), int(cs_id), int(lapso_id), int(act_id)
            valor = float(value) if value else None
        except (ValueError, TypeError):
            continue

        if valor is None:
            continue

        # Validar escala (0-20)
        valor = max(0, min(20, valor))

        existing = db.query(Grade).filter(
            Grade.student_id == student_id,
            Grade.course_subject_id == cs_id,
            Grade.lapso_id == lapso_id,
            Grade.activity_id == act_id,
        ).first()

        if existing:
            old_val = existing.valor
            existing.valor = valor
            log_event(db, "grades", "UPDATE", registro_id=existing.id,
                      valor_anterior={"valor": old_val},
                      valor_nuevo={"valor": valor},
                      user_id=user["id"])
        else:
            grade = Grade(
                student_id=student_id,
                course_subject_id=cs_id,
                lapso_id=lapso_id,
                activity_id=act_id,
                valor=valor,
            )
            db.add(grade)
            log_event(db, "grades", "INSERT",
                      valor_nuevo={"student_id": student_id, "valor": valor},
                      user_id=user["id"])
        saved += 1

    db.commit()

    # Redirigir de vuelta con los mismos parámetros
    cs_id = form.get("course_subject_id", "")
    lapso_id = form.get("lapso_id", "")
    return RedirectResponse(f"/academic/grades?course_subject_id={cs_id}&lapso_id={lapso_id}", status_code=302)


# ─── ASISTENCIA ──────────────────────────────────────────────────────────────
@router.get("/attendance", response_class=HTMLResponse)
async def attendance_view(
    request: Request,
    course_subject_id: int = None,
    fecha: str = None,
    db: Session = Depends(get_db),
):
    user = _check_auth(request)
    course_subjects = db.query(CourseSubject).all()
    selected_cs = None
    students = []
    attendance_map = {}
    fecha_obj = date.fromisoformat(fecha) if fecha else date.today()

    if course_subject_id:
        selected_cs = db.query(CourseSubject).get(course_subject_id)
        if selected_cs:
            enrollments = db.query(Enrollment).filter(
                Enrollment.section_id.in_(
                    [s.id for s in selected_cs.course.sections]
                ),
                Enrollment.is_active == True,
            ).all()
            students = [e.student for e in enrollments]

            for student in students:
                att = db.query(Attendance).filter(
                    Attendance.student_id == student.id,
                    Attendance.course_subject_id == course_subject_id,
                    Attendance.fecha == fecha_obj,
                ).first()
                attendance_map[student.id] = att.status.value if att else AttendanceStatus.PRESENTE.value

    return templates.TemplateResponse("academic/attendance.html", {
        "request": request, "user": user,
        "course_subjects": course_subjects,
        "selected_cs": selected_cs,
        "students": students,
        "attendance_map": attendance_map,
        "fecha": str(fecha_obj),
        "statuses": [s.value for s in AttendanceStatus],
        "can_edit": has_permission(user["role"], "academic", "edit"),
    })


@router.post("/attendance/save")
async def save_attendance(request: Request, db: Session = Depends(get_db)):
    user = _check_auth(request, "edit")
    form = await request.form()
    cs_id = int(form.get("course_subject_id", 0))
    fecha_str = form.get("fecha", str(date.today()))
    fecha_obj = date.fromisoformat(fecha_str)

    for key, value in form.items():
        if not key.startswith("att_"):
            continue
        try:
            student_id = int(key.replace("att_", ""))
        except ValueError:
            continue

        try:
            status_val = AttendanceStatus(value)
        except ValueError:
            status_val = AttendanceStatus.PRESENTE

        justificacion = form.get(f"just_{student_id}", "")

        existing = db.query(Attendance).filter(
            Attendance.student_id == student_id,
            Attendance.course_subject_id == cs_id,
            Attendance.fecha == fecha_obj,
        ).first()

        if existing:
            existing.status = status_val
            existing.justificacion = justificacion or None
        else:
            att = Attendance(
                student_id=student_id,
                course_subject_id=cs_id,
                fecha=fecha_obj,
                status=status_val,
                justificacion=justificacion or None,
            )
            db.add(att)

    log_event(db, "attendance", "BATCH_SAVE",
              descripcion=f"Asistencia guardada: CS {cs_id}, fecha {fecha_str}",
              user_id=user["id"], ip_address=get_client_ip(request))
    db.commit()
    return RedirectResponse(f"/academic/attendance?course_subject_id={cs_id}&fecha={fecha_str}", status_code=302)


# ─── REPORTE DE NOTAS ────────────────────────────────────────────────────────
@router.get("/report/student/{student_id}", response_class=HTMLResponse)
async def student_report(request: Request, student_id: int, db: Session = Depends(get_db)):
    user = _check_auth(request)
    student = db.query(Student).get(student_id)
    if not student:
        raise HTTPException(status_code=404)

    active_year = db.query(SchoolYear).filter(SchoolYear.is_active == True).first()
    lapsos = active_year.lapsos if active_year else []

    # Construir boletín
    boletin = {}
    for lapso in lapsos:
        boletin[lapso.id] = {}
        grades = db.query(Grade).filter(
            Grade.student_id == student_id,
            Grade.lapso_id == lapso.id,
        ).all()
        for grade in grades:
            cs_id = grade.course_subject_id
            if cs_id not in boletin[lapso.id]:
                boletin[lapso.id][cs_id] = {
                    "materia": grade.course_subject.subject.nombre,
                    "actividades": {},
                    "promedio": None
                }
            act_name = grade.activity.nombre if grade.activity else "Nota"
            boletin[lapso.id][cs_id]["actividades"][act_name] = grade.valor

        # Calcular promedios ponderados
        for cs_id, data in boletin[lapso.id].items():
            activities = db.query(EvalActivity).filter(
                EvalActivity.course_subject_id == cs_id,
                EvalActivity.lapso_numero == lapso.numero,
            ).all()
            if activities:
                total_pct = sum(a.porcentaje for a in activities)
                weighted = sum(
                    data["actividades"].get(a.nombre, 0) * (a.porcentaje / 100)
                    for a in activities
                )
                if total_pct > 0:
                    data["promedio"] = round(weighted * 20 / total_pct if total_pct != 100 else weighted, 2)

    # Asistencia
    attendance_stats = {}
    for lapso in lapsos:
        records = db.query(Attendance).filter(
            Attendance.student_id == student_id,
            Attendance.fecha >= lapso.fecha_inicio,
            Attendance.fecha <= lapso.fecha_fin,
        ).all()
        attendance_stats[lapso.id] = {
            "total": len(records),
            "presentes": sum(1 for r in records if r.status == AttendanceStatus.PRESENTE),
            "ausentes": sum(1 for r in records if r.status == AttendanceStatus.AUSENTE),
            "justificados": sum(1 for r in records if r.status == AttendanceStatus.JUSTIFICADO),
        }

    return templates.TemplateResponse("academic/student_report.html", {
        "request": request, "user": user,
        "student": student, "lapsos": lapsos,
        "boletin": boletin, "attendance_stats": attendance_stats,
        "active_year": active_year,
    })
