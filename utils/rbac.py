"""Control de Acceso Basado en Roles (RBAC)."""
from fastapi import Request, HTTPException, status
from models import UserRole

# Matriz de permisos por módulo y rol
PERMISSIONS: dict[str, dict[str, list[str]]] = {
    UserRole.ADMIN: {
        "students":   ["view", "create", "edit", "delete", "status"],
        "courses":    ["view", "create", "edit", "delete"],
        "financial":  ["view", "create", "edit", "void"],
        "academic":   ["view", "create", "edit"],
        "documents":  ["view", "create"],
        "audit":      ["view"],
        "settings":   ["view", "edit"],
        "users":      ["view", "create", "edit", "delete"],
    },
    UserRole.SECRETARIA: {
        "students":   ["view", "create", "edit", "status"],
        "courses":    ["view"],
        "financial":  ["view", "create"],
        "academic":   ["view"],
        "documents":  ["view", "create"],
        "audit":      [],
        "settings":   ["view"],
        "users":      [],
    },
    UserRole.DOCENTE: {
        "students":   ["view"],
        "courses":    ["view"],
        "financial":  [],
        "academic":   ["view", "create", "edit"],
        "documents":  ["view", "create"],
        "audit":      [],
        "settings":   [],
        "users":      [],
    },
    UserRole.TESORERO: {
        "students":   ["view"],
        "courses":    ["view"],
        "financial":  ["view", "create", "edit", "void"],
        "academic":   [],
        "documents":  ["view", "create"],
        "audit":      ["view"],
        "settings":   ["view"],
        "users":      [],
    },
}


def has_permission(role: str, module: str, action: str) -> bool:
    """Verifica si un rol tiene permiso para una acción en un módulo."""
    try:
        role_enum = UserRole(role)
        return action in PERMISSIONS.get(role_enum, {}).get(module, [])
    except (ValueError, KeyError):
        return False


def get_user_session(request: Request) -> dict:
    """Obtiene los datos del usuario desde la sesión."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"}
        )
    return {
        "id": user_id,
        "username": request.session.get("username"),
        "full_name": request.session.get("full_name"),
        "role": request.session.get("role"),
        "must_change_pwd": request.session.get("must_change_pwd", False),
    }


def require_permission(module: str, action: str):
    """Decorador para verificar permisos en rutas."""
    def checker(request: Request):
        user = get_user_session(request)
        if not has_permission(user["role"], module, action):
            raise HTTPException(status_code=403, detail="Sin permisos suficientes")
        return user
    return checker
