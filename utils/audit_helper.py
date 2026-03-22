"""Registro de auditoría inmutable."""
from datetime import datetime
from sqlalchemy.orm import Session
from models import AuditLog


def log_event(
    db: Session,
    tabla: str,
    accion: str,
    registro_id: int | None = None,
    valor_anterior: dict | None = None,
    valor_nuevo: dict | None = None,
    descripcion: str | None = None,
    user_id: int | None = None,
    ip_address: str | None = None,
):
    """Registra un evento en la tabla de auditoría (inmutable)."""
    entry = AuditLog(
        tabla=tabla,
        registro_id=registro_id,
        accion=accion,
        valor_anterior=valor_anterior,
        valor_nuevo=valor_nuevo,
        descripcion=descripcion,
        user_id=user_id,
        ip_address=ip_address,
        timestamp=datetime.utcnow(),
    )
    db.add(entry)
    db.flush()  # No commit para que sea parte de la transacción principal


def get_client_ip(request) -> str:
    """Obtiene la IP del cliente."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
