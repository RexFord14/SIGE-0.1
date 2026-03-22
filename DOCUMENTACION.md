# SIGE — Documentación Técnica Completa
**Sistema Integral de Gestión Escolar v1.0**  
*Arquitectura, decisiones de diseño, y guía de mantenimiento*

---

## 1. VISIÓN GENERAL DEL PROYECTO

### 1.1 ¿Qué es SIGE?
SIGE es un ERP educativo de **servidor local** diseñado para colegios de pequeña/mediana matrícula. Gestiona el ciclo completo: inscripción → evaluación → cobro → documentos. Opera 100% en intranet sin dependencias de nube.

### 1.2 ¿Por qué estas tecnologías?

| Decisión | Tecnología elegida | Por qué esta y no otra |
|---|---|---|
| Backend web | **Flask** | Disponible en el entorno, liviano, sin magia oculta. FastAPI requeriría asyncio en toda la app, innecesario para carga local. Django sería sobredimensionado. |
| Base de datos | **SQLite (WAL mode)** | Sin servidor separado, archivo único, fácil backup (cp sige.db). WAL permite lecturas concurrentes sin bloquear escrituras. PostgreSQL sería exceso para <500 usuarios simultáneos. |
| ORM/Queries | **SQL crudo + sqlite3** | Control total del SQL generado, sin overhead de ORM. Importante para las transacciones financieras donde el comportamiento debe ser predecible. |
| Frontend | **Tailwind CDN + Jinja2** | Sin proceso de build. Tailwind CDN es suficiente para intranet donde latencia no importa. HTMX sería ideal en v2. |
| PDFs | **ReportLab** | Generación 100% Python sin dependencias del sistema (weasyprint requiere librerías C del OS). Funciona en Windows/Linux/Mac sin setup. |
| Criptografía | **AES-256-GCM** (lib cryptography) | Cifrado autenticado. GCM detecta tampering de datos. Mejor que AES-CBC porque incluye MAC integrado. |
| Imágenes | **Pillow** | Estándar Python para imagen, disponible preinstalado, permite thumbnails sin deps externas. |
| Sesiones | **Flask sessions (itsdangerous)** | Firmadas con HMAC, seguras por defecto. No requiere Redis. |

---

## 2. ESTRUCTURA DE ARCHIVOS

```
sige/
├── app.py                    ← Punto de entrada y registro de blueprints
├── database.py               ← Conexión SQLite, init_db(), migrations
├── auth.py                   ← Decoradores RBAC, sesión, función audit()
├── crypto.py                 ← AES-256-GCM para campos sensibles
├── seed_demo.py              ← Datos de prueba (ejecutar una vez)
├── instalar.sh               ← Instalador automático multiplataforma
├── arrancar.sh               ← Generado por instalar.sh
│
├── routers/                  ← Blueprints Flask (un archivo = un módulo)
│   ├── auth_router.py        ← /login, /logout
│   ├── dashboard_router.py   ← / (KPIs, resumen)
│   ├── students_router.py    ← /estudiantes/
│   ├── finance_router.py     ← /finanzas/ (facturas, pagos, caja)
│   ├── academic_router.py    ← /academico/ (notas, asistencia)
│   ├── admin_router.py       ← /administracion/ (usuarios, años, RBAC)
│   ├── reports_router.py     ← /reportes/ (PDFs async)
│   ├── settings_router.py    ← /configuracion/ (cuentas bancarias, PIN)
│   └── profile_router.py     ← /perfil/ (cambio de clave)
│
├── services/
│   ├── pdf_service.py        ← Generación ReportLab (recibo, boletín, constancia)
│   └── image_service.py      ← Compresión, thumbnails, limpieza de imágenes
│
├── templates/                ← Jinja2, extienden base.html
│   ├── base.html             ← Layout maestro: sidebar + nav + flash messages
│   ├── login.html            ← Página standalone (no extiende base)
│   ├── dashboard.html
│   ├── change_password.html
│   ├── students/
│   │   ├── index.html        ← Lista con filtros
│   │   ├── detail.html       ← Perfil completo + pagos + notas
│   │   └── form.html         ← Crear/editar (mismo template, flag edit=True/False)
│   ├── finance/
│   │   ├── index.html        ← Panel principal finanzas
│   │   ├── nuevo_pago.html   ← Flujo dedicado registro de pago
│   │   ├── cash_register.html
│   │   ├── reconciliation.html
│   │   └── concepts.html
│   ├── academic/
│   │   ├── index.html
│   │   ├── grades.html
│   │   ├── attendance.html
│   │   └── config.html
│   ├── reports/index.html
│   ├── admin/
│   │   ├── index.html        ← Tabbed: usuarios, años, cursos, secciones, materias
│   │   └── audit.html
│   ├── settings/index.html   ← Cuentas bancarias, PIN de seguridad
│   └── errors/
│       ├── 403.html
│       └── 404.html
│
├── uploads/                  ← Imágenes de comprobantes (NUNCA en git)
│   ├── originals/            ← Imagen original comprimida (max 800px, 80% JPEG)
│   └── thumbnails/           ← Miniatura (150x150px, crop centrado)
│
├── generated/                ← PDFs generados (NUNCA en git)
├── sige.db                   ← Base de datos SQLite (NUNCA en git)
├── .sige_key                 ← Clave AES-256 (NUNCA en git, permisos 600)
└── DOCUMENTACION.md          ← Este archivo
```

---

## 3. BASE DE DATOS — ESQUEMA COMPLETO

### 3.1 Decisiones de diseño de datos

**¿Por qué SQLite y no PostgreSQL?**
Para un colegio local con <50 usuarios concurrentes, SQLite WAL supera en rendimiento a PostgreSQL por ausencia de overhead de red. Un archivo = fácil backup. PostgreSQL se justifica cuando superas 100 conexiones concurrentes escribiendo.

**`PRAGMA foreign_keys=ON`** — Se activa en cada conexión. SQLite por defecto NO enforza FKs para compatibilidad histórica. Esta línea es crítica para integridad referencial.

**`PRAGMA journal_mode=WAL`** — Write-Ahead Logging permite lecturas concurrentes mientras se escribe. Sin esto, cualquier escritura bloquea toda lectura. Esencial para intranet multiusuario.

### 3.2 Tablas y sus relaciones

```
roles ──< role_permissions >── permissions
  │
  └──< users

school_years ──< lapsos
school_years ──< sections
school_years ──< invoices
school_years ──< evaluation_config

courses ──< sections
courses ──< subjects

sections ──< students
sections ──< teacher_subjects

students ──< invoices ──< payments ──< payment_images
students ──< grades
students ──< attendance

representatives ──< students

fee_concepts ──< invoices

lapsos ──< activity_types
subjects ──< activity_types
activity_types ──< grades

payments ──< bank_reconciliation
bank_accounts (cuentas receptoras registradas)

system_settings (clave PIN hasheada)

background_tasks (cola de PDFs async)
audit_log (registro inmutable de eventos)
```

### 3.3 Tabla por tabla

#### `students` — Máquina de estados
```
ACTIVO → MOROSO (automático al tener factura pendiente)
MOROSO → ACTIVO (automático al saldar deuda)
ACTIVO/MOROSO → RETIRADO (manual, BLOQUEADO si hay deuda)
ACTIVO/MOROSO → EGRESADO (manual, BLOQUEADO si hay deuda)
```
**Campos encriptados AES-256:** `cedula_enc`  
**¿Por qué no guardar la cédula en claro?** Datos personales venezolanos son sensibles. Si alguien roba el .db no obtiene cédulas directamente.

#### `payments` — Columnas extendidas v1.1
```
payment_subtype  TEXT   -- PAGO_MOVIL|TRANSFERENCIA|EFECTIVO|ZELLE|OTRO
phone_number     TEXT   -- Para pago móvil (encriptado)
cedula_payer     TEXT   -- Para pago móvil (encriptado)
last4_ref        TEXT   -- Últimos 4 dígitos referencia
account_id       INT    -- FK bank_accounts (cuenta receptora)
zelle_email      TEXT   -- Para Zelle
zelle_name       TEXT   -- Nombre en Zelle
other_desc       TEXT   -- Descripción libre para "Otro"
```

#### `payment_images` — Gestión de comprobantes
```
payment_id       -- FK al pago
stored_filename  -- Nombre en disco (UUID, evita colisiones)
thumb_filename   -- Miniatura 150x150
file_size_kb     -- Para alertas de uso de disco
```
**¿Por qué no guardar en base64 dentro de la DB?** Blobs en SQLite degradan el rendimiento. Los archivos en disco son más rápidos de servir y más fáciles de limpiar.

#### `bank_accounts` — Cuentas receptoras
Registra las cuentas bancarias del colegio a las que los representantes depositan. Cuando se registra un pago por transferencia, se selecciona la cuenta destino para trazabilidad.

#### `system_settings` — Configuración del sistema
Almacena el hash del PIN de seguridad. **Nunca en .txt**:
```sql
key: 'security_pin_hash'
value: werkzeug.generate_password_hash('1234')
```

---

## 4. MÓDULO DE AUTENTICACIÓN Y RBAC

### 4.1 `auth.py` — Funciones principales

**`login_required(f)`** — Decorador. Verifica `session['user_id']`. Si no existe redirige a `/login`. Se usa en TODAS las rutas que requieren autenticación.

**`permission_required(module, action)`** — Decorador anidado. Consulta `role_permissions` para el `role_id` del usuario en sesión. Lanza 403 si no tiene permiso. Los módulos/acciones son: `students/view|edit|delete`, `finance/view|edit|approve|void`, `academic/view|edit`, `reports/view`, `admin/view|edit`, `audit/view`.

**`audit(conn, action, module, entity, entity_id, old_val, new_val)`** — Inserta en `audit_log`. Se llama dentro de la misma transacción del cambio, garantizando que el log y el cambio son atómicos. `old_val` y `new_val` son dicts serializados a JSON.

**`get_user_permissions(role_id)`** — Retorna un `set` de tuplas `(module, action)`. Se reconsulta en cada request (no se cachea en sesión) para que los cambios de rol surtan efecto inmediatamente.

### 4.2 Roles predefinidos

| Rol | Puede hacer |
|---|---|
| ADMIN | Todo |
| SECRETARIA | Ver/editar estudiantes, ver académico, ver reportes |
| CAJA | Ver/editar finanzas, ver estudiantes, ver reportes |
| DOCENTE | Ver/editar académico, ver estudiantes |
| DIRECCION | Ver finanzas/estudiantes/académico/reportes/auditoría |

---

## 5. MÓDULO DE CRIPTOGRAFÍA

### 5.1 `crypto.py` — AES-256-GCM

**`encrypt(plaintext: str) → str`**  
1. Genera nonce aleatorio de 12 bytes (`os.urandom(12)`)
2. Cifra con AES-256-GCM usando la clave maestra
3. Retorna `base64(nonce + ciphertext)` como string

**`decrypt(token: str) → str`**  
1. Decodifica base64
2. Extrae nonce (primeros 12 bytes) y ciphertext
3. Descifra y verifica MAC automáticamente (GCM detecta tampering)

**¿Por qué GCM y no CBC?**  
GCM es cifrado autenticado: si alguien modifica el ciphertext en disco, la decriptación falla con excepción en lugar de retornar datos corruptos silenciosamente. CBC no detecta modificaciones.

**`.sige_key`** — Clave de 256 bits generada en primer uso. Permisos `chmod 600`. Si se pierde, los campos encriptados son irrecuperables → HACER BACKUP DE ESTE ARCHIVO junto con `sige.db`.

---

## 6. MÓDULO FINANCIERO

### 6.1 Flujo contable de doble partida

```
Emisión de factura:
  Cuentas por cobrar (Débito) ← net_amount
  Ingresos por servicios (Crédito) ← net_amount

Registro de pago:
  Efectivo/Banco (Débito) ← amount
  Cuentas por cobrar (Crédito) ← amount
  
  Si paid_amount == net_amount → status='PAGADO'
  Si 0 < paid_amount < net_amount → status='PARCIAL'
```

**Regla crítica en `finance_router.py → new_payment()`:**  
```python
remaining = inv["net_amount"] - inv["paid_amount"]
if amount > remaining:
    flash("El pago excede el saldo pendiente", "error")
    return  # NEVER permitir sobrepago
```
Esto previene errores contables donde un pago crea saldo a favor no controlado.

### 6.2 Actualización automática de estado del estudiante

Después de cada pago:
```python
total_debt = SUM(net_amount - paid_amount) WHERE status IN ('PENDIENTE','PARCIAL')
if total_debt <= 0:
    UPDATE students SET status='ACTIVO' WHERE status='MOROSO'
```
Después de cada factura:
```python
if student.status == 'ACTIVO':
    UPDATE students SET status='MOROSO'
```

### 6.3 PIN de seguridad para anulaciones

El PIN de 4 dígitos se almacena como hash Werkzeug en `system_settings`:
```python
# Verificación
row = conn.execute("SELECT value FROM system_settings WHERE key='security_pin_hash'").fetchone()
if not check_password_hash(row['value'], pin_ingresado):
    flash("PIN incorrecto", "error")
    return
```
**¿Por qué no en .txt?** Un archivo .txt en el directorio del proyecto puede ser leído por cualquier usuario del sistema o expuesto por error en un repositorio git. La DB ya está protegida con los permisos del sistema operativo.

### 6.4 Gestión de imágenes de comprobantes

**`services/image_service.py`:**
- `save_payment_image(file_storage, payment_id)` → comprime original a max 800px JPEG 80%, genera thumbnail 150×150 crop centrado, guarda ambos con UUID como nombre
- `delete_payment_images(payment_id)` → elimina archivos físicos + registros DB
- `get_storage_stats()` → retorna uso total en MB para panel admin

**¿Por qué comprimir?** Un capture de pantalla típico en Android = 2-4 MB. Con 300 pagos/mes = 600MB-1.2GB al año sin comprimir. Con compresión al 80% JPEG max 800px = ~50KB/imagen = ~15MB/mes. Factor 40x de reducción.

---

## 7. MÓDULO ACADÉMICO

### 7.1 Cálculo de promedios ponderados

```python
# En reports_router.py → boletin()
total_weight = sum(g["weight"] for g in grades)
avg = sum(g["score"] * g["weight"] for g in grades) / total_weight if total_weight > 0 else 0
```
**¿Por qué no un simple promedio?** Porque las ponderaciones (Evaluación 40%, Tarea 30%, Proyecto 30%) son configurables por materia/lapso. Un promedio simple trataría igual una tarea de 5% que un examen de 40%.

### 7.2 Regla de redondeo configurable

En `evaluation_config.rounding_rule`:
- `ROUND_HALF_UP`: 7.5 → 8 (estándar venezolano)
- `ROUND_DOWN`: 7.9 → 7
- `ROUND_UP`: 7.1 → 8

---

## 8. GENERACIÓN DE PDFs (ASÍNCRONA)

### 8.1 ¿Por qué asíncrono?

ReportLab puede tardar 0.5-3s por documento. Si se generan 50 boletines simultáneamente en un servidor de intranet, un modelo síncrono bloquearía el servidor Flask por minutos. Con `threading.Thread + background_tasks` el usuario ve progreso en tiempo real y el servidor sigue respondiendo.

### 8.2 Flujo async

```
1. Usuario solicita PDF → POST /reportes/constancia/1
2. router: INSERT INTO background_tasks (status='PENDING')
3. router: Thread(target=_run_in_background, args=(task_id, func)).start()
4. router: redirect → /reportes/ (instantáneo)
5. Background: UPDATE task SET status='RUNNING'
6. Background: genera PDF
7. Background: UPDATE task SET status='DONE', result_path=...
8. Frontend: cada 3s hace GET /reportes/tarea/{id}/estado → JSON
9. Cuando status='DONE': muestra botón "Descargar"
```

---

## 9. FLUJO DE UN REQUEST TÍPICO

```
Browser → GET /estudiantes/1
  → Flask routing → students_router.py:detail(sid=1)
    → @login_required: verifica session['user_id']
    → @permission_required('students','view'): verifica role_permissions
    → db() context manager: conn = sqlite3.connect(DB_PATH)
    → SQL: SELECT estudiante + sección + representante
    → decrypt(cedula_enc) → cedula legible
    → SQL: SELECT facturas del estudiante
    → SQL: SELECT notas del estudiante
    → render_template('students/detail.html', ...)
    → conn.commit() (si hubo writes) o conn.close()
  → Jinja2 renderiza HTML con datos
← Browser recibe HTML completo
```

---

## 10. SEGURIDAD — DECISIONES CLAVE

### 10.1 Qué está protegido
- **Cédulas, teléfonos, emails** → AES-256-GCM en DB
- **Contraseñas** → bcrypt via Werkzeug (factor de trabajo adaptable)
- **PIN de seguridad** → Werkzeug hash en system_settings
- **Sesiones** → Firmadas con HMAC (itsdangerous), no pueden ser forjadas
- **RBAC** → Verificado server-side en cada request, no solo en UI

### 10.2 Qué NO está protegido (mejoras futuras)
- Comunicación HTTP (no HTTPS) → Aceptable en intranet, agregar nginx+SSL para WAN
- Rate limiting en login → Agregar flask-limiter en v2
- CSRF tokens → Flask no los incluye por defecto, agregar flask-wtf en v2
- Logs de acceso HTTP → Activar logging de Werkzeug a archivo en producción

---

## 11. GUÍA DE ESCALABILIDAD

### Qué hacer cuando el colegio crezca:

| Necesidad | Migración |
|---|---|
| +usuarios concurrentes (>50) | Migrar a PostgreSQL: cambiar `database.py`, mismas queries |
| HTTPS | Poner nginx como reverse proxy delante de Flask |
| Múltiples sedes | Agregar tabla `campuses`, FK en students/sections |
| App móvil | Agregar endpoints JSON en routers existentes (Flask ya maneja JSON) |
| Pagos en línea | Agregar módulo pagos.py con webhook del banco |

---

## 12. VARIABLES Y CONSTANTES CRÍTICAS

| Variable | Archivo | Valor por defecto | Cambiar antes de producción |
|---|---|---|---|
| `app.secret_key` | app.py | "SIGE_DEV_SECRET..." | ✅ OBLIGATORIO |
| `DB_PATH` | database.py | `./sige.db` | Opcional (mover a ruta absoluta) |
| `KEY_FILE` | crypto.py | `./.sige_key` | Mover a ruta fuera del proyecto |
| `REPORTS_DIR` | pdf_service.py | `./generated/` | OK para producción local |
| `UPLOAD_DIR` | image_service.py | `./uploads/` | OK para producción local |
| `SCHOOL_NAME` | pdf_service.py | "UNIDAD EDUCATIVA SIGE" | ✅ CAMBIAR |
| `SCHOOL_RIF` | pdf_service.py | "J-XXXXXXXXXX-X" | ✅ CAMBIAR |

---

## 13. COMANDOS DE MANTENIMIENTO

```bash
# Backup completo (ejecutar diariamente con cron)
cp sige.db backups/sige_$(date +%Y%m%d).db
cp .sige_key backups/.sige_key_$(date +%Y%m%d)

# Ver tamaño de uploads
du -sh uploads/

# Limpiar imágenes huérfanas (sin pago asociado)
python3 -c "from services.image_service import cleanup_orphans; cleanup_orphans()"

# Reiniciar servidor (Linux con systemd)
sudo systemctl restart sige

# Ver logs de auditoría (últimas 50 acciones)
sqlite3 sige.db "SELECT timestamp,username,action,module,entity FROM audit_log ORDER BY timestamp DESC LIMIT 50;"
```

---

*Documentación generada para SIGE v1.1 — Última actualización: 2026*
