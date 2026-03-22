from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Float, Text,
    ForeignKey, Enum, JSON, Date, UniqueConstraint, CheckConstraint
)
from sqlalchemy.orm import relationship
from sqlalchemy.types import TypeDecorator
from datetime import datetime, date
from database import Base
import enum


# ─── ENCRYPTED STRING TYPE ───────────────────────────────────────────────────
class EncryptedString(TypeDecorator):
    """Campo de texto encriptado con AES-256 transparente."""
    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            from utils.crypto import encrypt_value
            return encrypt_value(str(value))
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            from utils.crypto import decrypt_value
            return decrypt_value(value)
        return value


# ─── ENUMS ───────────────────────────────────────────────────────────────────
class StudentStatus(str, enum.Enum):
    ACTIVO    = "Activo"
    MOROSO    = "Moroso"
    RETIRADO  = "Retirado"
    EGRESADO  = "Egresado"

class PaymentMethod(str, enum.Enum):
    EFECTIVO      = "Efectivo"
    TRANSFERENCIA = "Transferencia"
    PAGO_MOVIL    = "Pago Móvil"
    CHEQUE        = "Cheque"
    ZELLE         = "Zelle"
    OTRO          = "Otro"

class AccountType(str, enum.Enum):
    ACTIVO     = "Activo"
    PASIVO     = "Pasivo"
    PATRIMONIO = "Patrimonio"
    INGRESO    = "Ingreso"
    GASTO      = "Gasto"

class InvoiceStatus(str, enum.Enum):
    PENDIENTE  = "Pendiente"
    PAGADO     = "Pagado"
    VENCIDO    = "Vencido"
    ANULADO    = "Anulado"

class AttendanceStatus(str, enum.Enum):
    PRESENTE    = "Presente"
    AUSENTE     = "Ausente"
    JUSTIFICADO = "Justificado"

class DocumentJobStatus(str, enum.Enum):
    PENDIENTE  = "Pendiente"
    PROCESANDO = "Procesando"
    COMPLETADO = "Completado"
    ERROR      = "Error"

class CashRegisterStatus(str, enum.Enum):
    ABIERTA  = "Abierta"
    CERRADA  = "Cerrada"

class UserRole(str, enum.Enum):
    ADMIN      = "Admin"
    SECRETARIA = "Secretaria"
    DOCENTE    = "Docente"
    TESORERO   = "Tesorero"


# ─── USUARIOS & RBAC ─────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"
    id               = Column(Integer, primary_key=True, index=True)
    username         = Column(String(50), unique=True, nullable=False)
    full_name        = Column(String(200), nullable=False)
    email            = Column(String(200), unique=True, nullable=True)
    password_hash    = Column(String(200), nullable=False)
    role             = Column(Enum(UserRole), default=UserRole.SECRETARIA)
    is_active        = Column(Boolean, default=True)
    must_change_pwd  = Column(Boolean, default=True)
    last_login       = Column(DateTime, nullable=True)
    created_at       = Column(DateTime, default=datetime.utcnow)

    audit_logs       = relationship("AuditLog", back_populates="user")
    payments         = relationship("Payment", back_populates="user")
    journal_entries  = relationship("JournalEntry", back_populates="user")
    document_jobs    = relationship("DocumentJob", back_populates="user")
    cash_registers   = relationship("CashRegister", back_populates="user")


# ─── CONFIGURACIÓN GLOBAL ─────────────────────────────────────────────────────
class SchoolSetting(Base):
    __tablename__ = "school_settings"
    id             = Column(Integer, primary_key=True)
    key            = Column(String(100), unique=True, nullable=False)
    value          = Column(Text, nullable=True)
    description    = Column(String(500), nullable=True)
    updated_at     = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ─── AÑO ESCOLAR & LAPSOS ────────────────────────────────────────────────────
class SchoolYear(Base):
    __tablename__ = "school_years"
    id           = Column(Integer, primary_key=True)
    nombre       = Column(String(20), nullable=False, unique=True)  # "2024-2025"
    fecha_inicio = Column(Date, nullable=False)
    fecha_fin    = Column(Date, nullable=False)
    is_active    = Column(Boolean, default=False)
    created_at   = Column(DateTime, default=datetime.utcnow)

    lapsos       = relationship("SchoolLapso", back_populates="school_year", cascade="all, delete-orphan")
    enrollments  = relationship("Enrollment", back_populates="school_year")


class SchoolLapso(Base):
    __tablename__ = "school_lapsos"
    id             = Column(Integer, primary_key=True)
    school_year_id = Column(Integer, ForeignKey("school_years.id"), nullable=False)
    numero         = Column(Integer, nullable=False)  # 1, 2, 3
    nombre         = Column(String(50), nullable=False)  # "Primer Lapso"
    fecha_inicio   = Column(Date, nullable=False)
    fecha_fin      = Column(Date, nullable=False)

    school_year    = relationship("SchoolYear", back_populates="lapsos")
    grades         = relationship("Grade", back_populates="lapso")

    __table_args__ = (UniqueConstraint("school_year_id", "numero"),)


# ─── CURSOS & SECCIONES ──────────────────────────────────────────────────────
class Course(Base):
    __tablename__ = "courses"
    id          = Column(Integer, primary_key=True)
    nombre      = Column(String(100), nullable=False)
    nivel       = Column(String(50), nullable=False)  # "Primaria", "Secundaria"
    grado       = Column(Integer, nullable=False)
    is_active   = Column(Boolean, default=True)

    sections    = relationship("Section", back_populates="course", cascade="all, delete-orphan")
    subjects    = relationship("CourseSubject", back_populates="course", cascade="all, delete-orphan")


class Section(Base):
    __tablename__ = "sections"
    id           = Column(Integer, primary_key=True)
    course_id    = Column(Integer, ForeignKey("courses.id"), nullable=False)
    nombre       = Column(String(10), nullable=False)  # "A", "B", "C"
    cupo_maximo  = Column(Integer, default=35)
    is_active    = Column(Boolean, default=True)

    course       = relationship("Course", back_populates="sections")
    enrollments  = relationship("Enrollment", back_populates="section")

    @property
    def cupo_ocupado(self):
        return sum(1 for e in self.enrollments if e.is_active)

    @property
    def cupo_disponible(self):
        return self.cupo_maximo - self.cupo_ocupado


# ─── MATERIAS ────────────────────────────────────────────────────────────────
class Subject(Base):
    __tablename__ = "subjects"
    id        = Column(Integer, primary_key=True)
    codigo    = Column(String(20), unique=True, nullable=False)
    nombre    = Column(String(200), nullable=False)
    is_active = Column(Boolean, default=True)

    course_subjects = relationship("CourseSubject", back_populates="subject")


class CourseSubject(Base):
    __tablename__ = "course_subjects"
    id          = Column(Integer, primary_key=True)
    course_id   = Column(Integer, ForeignKey("courses.id"), nullable=False)
    subject_id  = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    horas_sem   = Column(Integer, default=4)
    docente_id  = Column(Integer, ForeignKey("users.id"), nullable=True)

    course      = relationship("Course", back_populates="subjects")
    subject     = relationship("Subject", back_populates="course_subjects")
    docente     = relationship("User")
    eval_activities = relationship("EvalActivity", back_populates="course_subject", cascade="all, delete-orphan")
    grades      = relationship("Grade", back_populates="course_subject")
    attendance  = relationship("Attendance", back_populates="course_subject")

    __table_args__ = (UniqueConstraint("course_id", "subject_id"),)


class EvalActivity(Base):
    """Matriz de evaluación parametrizable por materia."""
    __tablename__ = "eval_activities"
    id                = Column(Integer, primary_key=True)
    course_subject_id = Column(Integer, ForeignKey("course_subjects.id"), nullable=False)
    lapso_numero      = Column(Integer, nullable=False)  # 1, 2, 3
    nombre            = Column(String(100), nullable=False)  # "Prueba", "Trabajo Práctico"
    porcentaje        = Column(Float, nullable=False)  # 30.0 = 30%
    es_porcentual     = Column(Boolean, default=True)

    course_subject    = relationship("CourseSubject", back_populates="eval_activities")
    grades            = relationship("Grade", back_populates="activity")


# ─── REPRESENTANTES ──────────────────────────────────────────────────────────
class Representative(Base):
    __tablename__ = "representatives"
    id           = Column(Integer, primary_key=True)
    cedula       = Column(EncryptedString(500), nullable=False)
    cedula_hash  = Column(String(64), unique=True, nullable=False)  # SHA-256 para búsqueda
    nombres      = Column(String(200), nullable=False)
    apellidos    = Column(String(200), nullable=False)
    telefono     = Column(EncryptedString(500), nullable=True)
    email        = Column(EncryptedString(500), nullable=True)
    direccion    = Column(EncryptedString(2000), nullable=True)
    profesion    = Column(String(200), nullable=True)
    created_at   = Column(DateTime, default=datetime.utcnow)
    is_active    = Column(Boolean, default=True)

    student_links = relationship("StudentRepresentative", back_populates="representative")


# ─── ESTUDIANTES ─────────────────────────────────────────────────────────────
class Student(Base):
    __tablename__ = "students"
    id           = Column(Integer, primary_key=True)
    cedula       = Column(EncryptedString(500), nullable=True)
    cedula_hash  = Column(String(64), unique=True, nullable=True)
    nombres      = Column(String(200), nullable=False)
    apellidos    = Column(String(200), nullable=False)
    fecha_nac    = Column(EncryptedString(500), nullable=True)
    sexo         = Column(String(1), nullable=True)  # M / F
    nacionalidad = Column(String(1), default="V")   # V / E
    status       = Column(Enum(StudentStatus), default=StudentStatus.ACTIVO)
    codigo       = Column(String(30), unique=True, nullable=False)  # Código interno
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    representatives = relationship("StudentRepresentative", back_populates="student", cascade="all, delete-orphan")
    enrollments     = relationship("Enrollment", back_populates="student")
    invoices        = relationship("Invoice", back_populates="student")
    grades          = relationship("Grade", back_populates="student")
    attendance      = relationship("Attendance", back_populates="student")

    @property
    def tiene_deuda(self):
        return any(
            i.status in (InvoiceStatus.PENDIENTE, InvoiceStatus.VENCIDO)
            and i.saldo_pendiente > 0
            for i in self.invoices
        )

    @property
    def deuda_total(self):
        return sum(i.saldo_pendiente for i in self.invoices
                   if i.status in (InvoiceStatus.PENDIENTE, InvoiceStatus.VENCIDO))

    @property
    def current_enrollment(self):
        active = [e for e in self.enrollments if e.is_active]
        return active[0] if active else None


class StudentRepresentative(Base):
    __tablename__ = "student_representatives"
    id                = Column(Integer, primary_key=True)
    student_id        = Column(Integer, ForeignKey("students.id"), nullable=False)
    representative_id = Column(Integer, ForeignKey("representatives.id"), nullable=False)
    parentesco        = Column(String(50), nullable=False)  # "Padre", "Madre", "Tutor"
    es_responsable    = Column(Boolean, default=False)  # Responsable financiero principal
    is_active         = Column(Boolean, default=True)

    student         = relationship("Student", back_populates="representatives")
    representative  = relationship("Representative", back_populates="student_links")


class Enrollment(Base):
    """Matrícula del estudiante en un año escolar y sección."""
    __tablename__ = "enrollments"
    id             = Column(Integer, primary_key=True)
    student_id     = Column(Integer, ForeignKey("students.id"), nullable=False)
    school_year_id = Column(Integer, ForeignKey("school_years.id"), nullable=False)
    section_id     = Column(Integer, ForeignKey("sections.id"), nullable=False)
    fecha_ingreso  = Column(Date, default=date.today)
    fecha_retiro   = Column(Date, nullable=True)
    is_active      = Column(Boolean, default=True)
    observaciones  = Column(Text, nullable=True)

    student     = relationship("Student", back_populates="enrollments")
    school_year = relationship("SchoolYear", back_populates="enrollments")
    section     = relationship("Section", back_populates="enrollments")


# ─── MÓDULO FINANCIERO ───────────────────────────────────────────────────────
class Account(Base):
    """Plan de cuentas contables - sistema de doble partida."""
    __tablename__ = "accounts"
    id          = Column(Integer, primary_key=True)
    codigo      = Column(String(20), unique=True, nullable=False)
    nombre      = Column(String(200), nullable=False)
    tipo        = Column(Enum(AccountType), nullable=False)
    descripcion = Column(Text, nullable=True)
    parent_id   = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    is_active   = Column(Boolean, default=True)
    nivel       = Column(Integer, default=1)

    parent      = relationship("Account", remote_side=[id], backref="children")
    debit_lines  = relationship("JournalLine", foreign_keys="JournalLine.account_id", back_populates="account")


class JournalEntry(Base):
    """Asiento contable (libro diario)."""
    __tablename__ = "journal_entries"
    id          = Column(Integer, primary_key=True)
    numero      = Column(String(20), unique=True, nullable=False)
    fecha       = Column(Date, nullable=False, default=date.today)
    descripcion = Column(Text, nullable=False)
    referencia  = Column(String(100), nullable=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at  = Column(DateTime, default=datetime.utcnow)
    is_void     = Column(Boolean, default=False)
    void_reason = Column(Text, nullable=True)
    void_by_id  = Column(Integer, ForeignKey("users.id"), nullable=True)
    void_at     = Column(DateTime, nullable=True)

    user        = relationship("User", foreign_keys=[user_id], back_populates="journal_entries")
    void_by     = relationship("User", foreign_keys=[void_by_id])
    lines       = relationship("JournalLine", back_populates="entry", cascade="all, delete-orphan")


class JournalLine(Base):
    __tablename__ = "journal_lines"
    id         = Column(Integer, primary_key=True)
    entry_id   = Column(Integer, ForeignKey("journal_entries.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    debe       = Column(Float, default=0.0)
    haber      = Column(Float, default=0.0)
    descripcion = Column(String(500), nullable=True)

    entry   = relationship("JournalEntry", back_populates="lines")
    account = relationship("Account", back_populates="debit_lines")


class Invoice(Base):
    """Factura / Cuenta por cobrar al estudiante."""
    __tablename__ = "invoices"
    id             = Column(Integer, primary_key=True)
    numero         = Column(String(20), unique=True, nullable=False)
    student_id     = Column(Integer, ForeignKey("students.id"), nullable=False)
    concepto       = Column(String(500), nullable=False)
    monto_total    = Column(Float, nullable=False)
    descuento      = Column(Float, default=0.0)
    fecha_emision  = Column(Date, default=date.today)
    fecha_vencimiento = Column(Date, nullable=False)
    status         = Column(Enum(InvoiceStatus), default=InvoiceStatus.PENDIENTE)
    school_year_id = Column(Integer, ForeignKey("school_years.id"), nullable=True)
    lapso          = Column(Integer, nullable=True)
    notas          = Column(Text, nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow)

    student     = relationship("Student", back_populates="invoices")
    school_year = relationship("SchoolYear")
    payments    = relationship("Payment", back_populates="invoice")

    @property
    def monto_neto(self):
        return self.monto_total - self.descuento

    @property
    def monto_pagado(self):
        return sum(p.monto for p in self.payments if not p.is_void)

    @property
    def saldo_pendiente(self):
        return max(0, self.monto_neto - self.monto_pagado)


class Payment(Base):
    """Pago registrado (puede ser fraccionado)."""
    __tablename__ = "payments"
    id                 = Column(Integer, primary_key=True)
    numero             = Column(String(20), unique=True, nullable=False)
    invoice_id         = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    monto              = Column(Float, nullable=False)
    fecha              = Column(Date, default=date.today)
    metodo             = Column(Enum(PaymentMethod), nullable=False)
    referencia         = Column(EncryptedString(500), nullable=True)
    banco              = Column(String(100), nullable=True)
    descripcion        = Column(String(500), nullable=True)
    user_id            = Column(Integer, ForeignKey("users.id"), nullable=False)
    cash_register_id   = Column(Integer, ForeignKey("cash_registers.id"), nullable=True)
    is_void            = Column(Boolean, default=False)
    void_reason        = Column(Text, nullable=True)
    created_at         = Column(DateTime, default=datetime.utcnow)

    invoice        = relationship("Invoice", back_populates="payments")
    user           = relationship("User", back_populates="payments")
    cash_register  = relationship("CashRegister", back_populates="payments")
    conciliation   = relationship("BankConciliation", back_populates="payment", uselist=False)


class CashRegister(Base):
    """Arqueo de caja diario."""
    __tablename__ = "cash_registers"
    id               = Column(Integer, primary_key=True)
    fecha            = Column(Date, default=date.today, unique=True)
    saldo_apertura   = Column(Float, default=0.0)
    saldo_cierre     = Column(Float, nullable=True)
    status           = Column(Enum(CashRegisterStatus), default=CashRegisterStatus.ABIERTA)
    user_id          = Column(Integer, ForeignKey("users.id"), nullable=False)
    notas            = Column(Text, nullable=True)
    created_at       = Column(DateTime, default=datetime.utcnow)
    closed_at        = Column(DateTime, nullable=True)

    user     = relationship("User", back_populates="cash_registers")
    payments = relationship("Payment", back_populates="cash_register")

    @property
    def total_efectivo(self):
        return sum(p.monto for p in self.payments
                   if not p.is_void and p.metodo == PaymentMethod.EFECTIVO)

    @property
    def total_transferencias(self):
        return sum(p.monto for p in self.payments
                   if not p.is_void and p.metodo != PaymentMethod.EFECTIVO)

    @property
    def total_ingresos(self):
        return sum(p.monto for p in self.payments if not p.is_void)


class BankConciliation(Base):
    """Conciliación bancaria - inmutable una vez conciliada."""
    __tablename__ = "bank_conciliations"
    id              = Column(Integer, primary_key=True)
    payment_id      = Column(Integer, ForeignKey("payments.id"), nullable=True)
    referencia      = Column(String(200), nullable=False)
    fecha_banco     = Column(Date, nullable=False)
    monto           = Column(Float, nullable=False)
    banco           = Column(String(100), nullable=False)
    concepto        = Column(String(500), nullable=False)
    conciliado      = Column(Boolean, default=False)
    fecha_conciliacion = Column(DateTime, nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)

    payment = relationship("Payment", back_populates="conciliation")


# ─── MÓDULO ACADÉMICO ────────────────────────────────────────────────────────
class Grade(Base):
    """Nota de un estudiante en una actividad evaluativa."""
    __tablename__ = "grades"
    id                = Column(Integer, primary_key=True)
    student_id        = Column(Integer, ForeignKey("students.id"), nullable=False)
    course_subject_id = Column(Integer, ForeignKey("course_subjects.id"), nullable=False)
    lapso_id          = Column(Integer, ForeignKey("school_lapsos.id"), nullable=False)
    activity_id       = Column(Integer, ForeignKey("eval_activities.id"), nullable=True)
    valor             = Column(Float, nullable=False)
    fecha             = Column(Date, default=date.today)
    observacion       = Column(String(500), nullable=True)
    created_at        = Column(DateTime, default=datetime.utcnow)
    updated_at        = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    student        = relationship("Student", back_populates="grades")
    course_subject = relationship("CourseSubject", back_populates="grades")
    lapso          = relationship("SchoolLapso", back_populates="grades")
    activity       = relationship("EvalActivity", back_populates="grades")

    __table_args__ = (UniqueConstraint("student_id", "course_subject_id", "lapso_id", "activity_id"),)


class Attendance(Base):
    """Control de asistencia diaria."""
    __tablename__ = "attendance"
    id                = Column(Integer, primary_key=True)
    student_id        = Column(Integer, ForeignKey("students.id"), nullable=False)
    course_subject_id = Column(Integer, ForeignKey("course_subjects.id"), nullable=False)
    fecha             = Column(Date, nullable=False, default=date.today)
    status            = Column(Enum(AttendanceStatus), default=AttendanceStatus.PRESENTE)
    justificacion     = Column(String(500), nullable=True)

    student        = relationship("Student", back_populates="attendance")
    course_subject = relationship("CourseSubject", back_populates="attendance")

    __table_args__ = (UniqueConstraint("student_id", "course_subject_id", "fecha"),)


# ─── DOCUMENTOS & JOBS ───────────────────────────────────────────────────────
class DocumentJob(Base):
    """Trabajo asíncrono de generación de documentos."""
    __tablename__ = "document_jobs"
    id          = Column(Integer, primary_key=True)
    tipo        = Column(String(50), nullable=False)  # "boletin", "recibo", "constancia"
    descripcion = Column(String(500), nullable=False)
    status      = Column(Enum(DocumentJobStatus), default=DocumentJobStatus.PENDIENTE)
    progreso    = Column(Integer, default=0)  # 0-100
    total       = Column(Integer, default=1)
    file_path   = Column(String(500), nullable=True)
    error_msg   = Column(Text, nullable=True)
    parametros  = Column(JSON, nullable=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at  = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="document_jobs")


# ─── AUDITORÍA (EVENT SOURCING LITE) ─────────────────────────────────────────
class AuditLog(Base):
    """Registro inmutable de eventos críticos del sistema."""
    __tablename__ = "audit_logs"
    id          = Column(Integer, primary_key=True)
    tabla       = Column(String(100), nullable=False)
    registro_id = Column(Integer, nullable=True)
    accion      = Column(String(20), nullable=False)  # INSERT / UPDATE / DELETE / VOID / LOGIN
    valor_anterior = Column(JSON, nullable=True)
    valor_nuevo    = Column(JSON, nullable=True)
    descripcion = Column(Text, nullable=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=True)
    ip_address  = Column(String(45), nullable=True)
    timestamp   = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="audit_logs")
