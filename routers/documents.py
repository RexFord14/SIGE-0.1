import threading
from fastapi import APIRouter, Request, Depends, Form, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, sessionmaker
from datetime import datetime
from pathlib import Path

from database import get_db, engine
from models import DocumentJob, DocumentJobStatus, Student, SchoolYear, Invoice, Payment, SchoolSetting
from utils.rbac import get_user_session, has_permission
from utils.audit_helper import log_event, get_client_ip
from utils.pdf_gen import generate_boletin, generate_recibo, generate_constancia
from config import BASE_DIR

router = APIRouter(prefix="/documents", tags=["documents"])
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _check_auth(request, action="view"):
    try:
        user = get_user_session(request)
    except Exception:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    if not has_permission(user["role"], "documents", action):
        raise HTTPException(status_code=403)
    return user


def _get_settings(db):
    return {s.key: s.value for s in db.query(SchoolSetting).all()}


def _run_job(job_id: int, job_type: str, params: dict):
    """Ejecuta el trabajo de generación de documentos en un hilo separado."""
    SessionThread = sessionmaker(bind=engine)
    db = SessionThread()
    try:
        job = db.query(DocumentJob).get(job_id)
        if not job:
            return
        job.status = DocumentJobStatus.PROCESANDO
        job.progreso = 10
        db.commit()

        settings = _get_settings(db)

        if job_type == "recibo":
            payment_id = params.get("payment_id")
            payment = db.query(Payment).get(payment_id)
            if payment:
                path = generate_recibo(payment, payment.invoice, payment.invoice.student, settings)
                job.file_path = path
                job.progreso = 100
                job.status = DocumentJobStatus.COMPLETADO
        elif job_type == "constancia":
            student_id = params.get("student_id")
            student = db.query(Student).get(student_id)
            if student and student.current_enrollment:
                path = generate_constancia(student, student.current_enrollment, settings)
                job.file_path = path
                job.progreso = 100
                job.status = DocumentJobStatus.COMPLETADO
        elif job_type == "boletin_masivo":
            student_ids = params.get("student_ids", [])
            lapso_id = params.get("lapso_id")
            total = len(student_ids)
            paths = []
            for i, sid in enumerate(student_ids):
                student = db.query(Student).get(sid)
                if student:
                    from models import SchoolLapso
                    lapso = db.query(SchoolLapso).get(lapso_id)
                    if lapso:
                        path = generate_boletin(student, lapso, [], settings)
                        paths.append(path)
                job.progreso = int(((i + 1) / total) * 90) + 5
                db.commit()
            job.file_path = paths[0] if len(paths) == 1 else str(BASE_DIR / "exports")
            job.progreso = 100
            job.status = DocumentJobStatus.COMPLETADO
        else:
            job.status = DocumentJobStatus.ERROR
            job.error_msg = f"Tipo de documento no reconocido: {job_type}"

        job.completed_at = datetime.utcnow()
        db.commit()
    except Exception as e:
        db = SessionThread()
        job = db.query(DocumentJob).get(job_id)
        if job:
            job.status = DocumentJobStatus.ERROR
            job.error_msg = str(e)
            db.commit()
    finally:
        db.close()


@router.get("/", response_class=HTMLResponse)
async def list_jobs(request: Request, db: Session = Depends(get_db)):
    user = _check_auth(request)
    jobs = db.query(DocumentJob).order_by(DocumentJob.created_at.desc()).limit(50).all()
    students = db.query(Student).order_by(Student.apellidos).all()
    active_year = db.query(SchoolYear).filter(SchoolYear.is_active == True).first()
    return templates.TemplateResponse("documents/list.html", {
        "request": request, "user": user,
        "jobs": jobs, "students": students,
        "active_year": active_year,
        "can_create": has_permission(user["role"], "documents", "create"),
    })


@router.post("/generate/constancia")
async def generate_constancia_job(
    request: Request,
    student_id: int = Form(...),
    db: Session = Depends(get_db),
):
    user = _check_auth(request, "create")
    student = db.query(Student).get(student_id)
    if not student:
        raise HTTPException(status_code=404)

    job = DocumentJob(
        tipo="constancia",
        descripcion=f"Constancia de Estudio: {student.nombres} {student.apellidos}",
        parametros={"student_id": student_id},
        user_id=user["id"],
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    thread = threading.Thread(target=_run_job, args=(job.id, "constancia", {"student_id": student_id}))
    thread.daemon = True
    thread.start()

    return RedirectResponse(f"/documents/jobs/{job.id}/status", status_code=302)


@router.post("/generate/recibo/{payment_id}")
async def generate_recibo_job(
    request: Request,
    payment_id: int,
    db: Session = Depends(get_db),
):
    user = _check_auth(request, "create")
    payment = db.query(Payment).get(payment_id)
    if not payment:
        raise HTTPException(status_code=404)

    job = DocumentJob(
        tipo="recibo",
        descripcion=f"Recibo de Pago {payment.numero}",
        parametros={"payment_id": payment_id},
        user_id=user["id"],
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    thread = threading.Thread(target=_run_job, args=(job.id, "recibo", {"payment_id": payment_id}))
    thread.daemon = True
    thread.start()

    return RedirectResponse(f"/documents/jobs/{job.id}/status", status_code=302)


@router.get("/jobs/{job_id}/status", response_class=HTMLResponse)
async def job_status_page(request: Request, job_id: int, db: Session = Depends(get_db)):
    user = _check_auth(request)
    job = db.query(DocumentJob).get(job_id)
    if not job:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse("documents/job_status.html", {
        "request": request, "user": user, "job": job,
    })


@router.get("/jobs/{job_id}/poll")
async def job_poll(request: Request, job_id: int, db: Session = Depends(get_db)):
    """Endpoint para polling HTMX del progreso."""
    user = _check_auth(request)
    job = db.query(DocumentJob).get(job_id)
    if not job:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse("documents/job_progress.html", {
        "request": request, "job": job,
    })


@router.get("/jobs/{job_id}/download")
async def download_job(request: Request, job_id: int, db: Session = Depends(get_db)):
    user = _check_auth(request)
    job = db.query(DocumentJob).get(job_id)
    if not job or job.status != DocumentJobStatus.COMPLETADO or not job.file_path:
        raise HTTPException(status_code=404)
    path = Path(job.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(
        path=str(path),
        filename=path.name,
        media_type="application/pdf" if path.suffix == ".pdf" else "text/html",
    )
