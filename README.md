# SIGE — Sistema Integral de Gestión Escolar v1.0

## Credenciales por defecto
- **Usuario:** `admin`
- **Contraseña:** `Admin2024!`

## Instalación y arranque

```bash
# 1. Instalar dependencias
pip install flask werkzeug reportlab cryptography itsdangerous

# 2. Arrancar (primera vez con datos demo)
python3 seed_demo.py   # carga datos de prueba
python3 app.py         # levanta en http://0.0.0.0:5000
```

## Módulos implementados

| Módulo | Ruta | Descripción |
|--------|------|-------------|
| Dashboard | `/` | KPIs, morosos top, pagos recientes |
| Estudiantes | `/estudiantes/` | Matrícula, estados, representantes |
| Finanzas | `/finanzas/` | Facturas, pagos fraccionados, doble partida |
| Caja Diaria | `/finanzas/caja` | Arqueo, apertura/cierre |
| Conciliación | `/finanzas/conciliacion` | Registro bancario inmutable |
| Académico | `/academico/` | Notas, asistencia, configuración |
| Reportes | `/reportes/` | Boletines, constancias PDF asíncronos |
| Administración | `/administracion/` | Usuarios, RBAC, años, secciones, materias |
| Auditoría | `/administracion/auditoria` | Log inmutable de todos los eventos |

## Seguridad
- AES-256 en cédulas, teléfonos y emails
- RBAC (5 roles: ADMIN, SECRETARIA, CAJA, DOCENTE, DIRECCION)
- Tabla audit_log inmutable con timestamp y usuario
- Regla de bloqueo: no se puede cambiar a RETIRADO/EGRESADO con deuda

## Stack técnico
- Backend: **Flask + SQLite** (WAL mode, FK enforced)
- Frontend: **Tailwind CDN + Jinja2**
- PDFs: **ReportLab**
- Criptografía: **AES-256-GCM** (cryptography lib)
