"""
SIGE – Database Module
SQLite + WAL mode + strict FK enforcement

DECISIÓN: SQLite sobre PostgreSQL porque:
- Cero configuración de servidor
- Archivo único = backup trivial (cp sige.db)
- WAL mode maneja concurrencia de intranet (<50 usuarios)
- Migrar a PG en el futuro solo requiere cambiar el driver
"""
import sqlite3, os, json
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), "sige.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    # WAL: lecturas no bloquean escrituras en intranet multiusuario
    conn.execute("PRAGMA journal_mode=WAL")
    # CRÍTICO: SQLite desactiva FK por defecto por compatibilidad histórica
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


@contextmanager
def db():
    """Context manager: auto-commit en éxito, rollback en excepción"""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate(conn):
    """
    Migraciones seguras: añade columnas/tablas sin destruir datos existentes.
    Usa try/except porque SQLite no tiene IF NOT EXISTS para columnas.
    Se ejecuta cada vez que arranca el servidor (idempotente).
    """
    # ── Nuevas columnas en payments (v1.1) ────────────────────────────────────
    new_cols = [
        ("payment_subtype", "TEXT"),       # PAGO_MOVIL|TRANSFERENCIA|EFECTIVO|ZELLE|OTRO
        ("phone_number",    "TEXT"),        # Pago Móvil: teléfono emisor (encriptado)
        ("cedula_payer",    "TEXT"),        # Pago Móvil: cédula emisor (encriptado)
        ("last4_ref",       "TEXT"),        # Últimos 4 dígitos de referencia
        ("account_id",      "INTEGER"),     # FK bank_accounts (cuenta receptora)
        ("zelle_email",     "TEXT"),        # Zelle: email registrado
        ("zelle_name",      "TEXT"),        # Zelle: nombre en Zelle
        ("other_desc",      "TEXT"),        # Tipo "Otro": descripción libre
    ]
    for col_name, col_type in new_cols:
        try:
            conn.execute(f"ALTER TABLE payments ADD COLUMN {col_name} {col_type}")
        except Exception:
            pass  # Columna ya existe → OK

    # ── Nuevas tablas (v1.1) ──────────────────────────────────────────────────
    conn.executescript("""
    -- Cuentas bancarias receptoras del colegio
    -- Necesarias para registrar a qué cuenta llegó cada transferencia
    CREATE TABLE IF NOT EXISTS bank_accounts (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        bank         TEXT NOT NULL,
        account_number TEXT NOT NULL,
        account_holder TEXT NOT NULL,
        account_type TEXT NOT NULL DEFAULT 'CORRIENTE',
        rif          TEXT,
        active       INTEGER NOT NULL DEFAULT 1,
        created_at   TEXT NOT NULL DEFAULT (datetime('now'))
    );

    -- Imágenes de comprobantes de pago
    -- DISEÑO: archivos en disco, solo metadata en DB (más rápido que BLOB)
    CREATE TABLE IF NOT EXISTS payment_images (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        payment_id       INTEGER NOT NULL REFERENCES payments(id),
        original_filename TEXT NOT NULL,
        stored_filename  TEXT NOT NULL,
        thumb_filename   TEXT NOT NULL,
        file_size_kb     INTEGER NOT NULL DEFAULT 0,
        created_at       TEXT NOT NULL DEFAULT (datetime('now'))
    );

    -- Configuración del sistema (PIN de seguridad, etc.)
    -- PIN guardado como hash Werkzeug, NUNCA en texto plano ni en .txt
    CREATE TABLE IF NOT EXISTS system_settings (
        key        TEXT PRIMARY KEY,
        value      TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """)

    # Tabla tasas de cambio (nuevas en v1.2)
    try:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS exchange_rates (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            date       TEXT NOT NULL,
            rate_bs    REAL NOT NULL,
            entered_by INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(date)
        )""")
    except Exception:
        pass

    # PIN por defecto: 1234 (hash Werkzeug)
    existing = conn.execute(
        "SELECT key FROM system_settings WHERE key='security_pin_hash'"
    ).fetchone()
    if not existing:
        from werkzeug.security import generate_password_hash
        conn.execute(
            "INSERT INTO system_settings(key,value) VALUES('security_pin_hash',?)",
            (generate_password_hash("1234"),)
        )


def init_db():
    """Crea todas las tablas base y ejecuta migraciones. Idempotente."""
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL, label TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module TEXT NOT NULL, action TEXT NOT NULL, UNIQUE(module,action)
        );
        CREATE TABLE IF NOT EXISTS role_permissions (
            role_id INTEGER REFERENCES roles(id),
            permission_id INTEGER REFERENCES permissions(id),
            PRIMARY KEY(role_id,permission_id)
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL, role_id INTEGER NOT NULL REFERENCES roles(id),
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS school_years (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, start_date TEXT NOT NULL,
            end_date TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS lapsos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            school_year_id INTEGER NOT NULL REFERENCES school_years(id),
            name TEXT NOT NULL, start_date TEXT NOT NULL,
            end_date TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, level TEXT NOT NULL, grade INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL REFERENCES courses(id),
            school_year_id INTEGER NOT NULL REFERENCES school_years(id),
            name TEXT NOT NULL, max_capacity INTEGER NOT NULL DEFAULT 30,
            UNIQUE(course_id,school_year_id,name)
        );
        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, course_id INTEGER NOT NULL REFERENCES courses(id)
        );
        CREATE TABLE IF NOT EXISTS representatives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cedula_enc TEXT NOT NULL UNIQUE, full_name TEXT NOT NULL,
            phone_enc TEXT, email_enc TEXT, address TEXT,
            relationship TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cedula_enc TEXT UNIQUE, first_name TEXT NOT NULL,
            last_name TEXT NOT NULL, birth_date TEXT NOT NULL,
            gender TEXT NOT NULL, section_id INTEGER REFERENCES sections(id),
            representative_id INTEGER NOT NULL REFERENCES representatives(id),
            status TEXT NOT NULL DEFAULT 'ACTIVO',
            enrollment_date TEXT NOT NULL DEFAULT (date('now')),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            CHECK(status IN ('ACTIVO','MOROSO','RETIRADO','EGRESADO','BECADO'))
        );
        CREATE INDEX IF NOT EXISTS idx_students_section ON students(section_id);
        CREATE TABLE IF NOT EXISTS fee_concepts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, amount REAL NOT NULL,
            recurrent INTEGER NOT NULL DEFAULT 1, active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number TEXT NOT NULL UNIQUE,
            student_id INTEGER NOT NULL REFERENCES students(id),
            concept_id INTEGER NOT NULL REFERENCES fee_concepts(id),
            amount REAL NOT NULL, discount REAL NOT NULL DEFAULT 0,
            net_amount REAL NOT NULL, due_date TEXT NOT NULL,
            paid_amount REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'PENDIENTE',
            school_year_id INTEGER NOT NULL REFERENCES school_years(id),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            created_by INTEGER NOT NULL REFERENCES users(id),
            CHECK(status IN ('PENDIENTE','PARCIAL','PAGADO','ANULADO'))
        );
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payment_number TEXT NOT NULL UNIQUE,
            invoice_id INTEGER NOT NULL REFERENCES invoices(id),
            amount REAL NOT NULL, payment_method TEXT NOT NULL,
            reference_num TEXT, bank TEXT, payment_date TEXT NOT NULL,
            notes TEXT, created_by INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            voided INTEGER NOT NULL DEFAULT 0,
            voided_by INTEGER REFERENCES users(id), voided_at TEXT
        );
        CREATE TABLE IF NOT EXISTS cash_register (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE, opening_amount REAL NOT NULL DEFAULT 0,
            closing_amount REAL, total_cash_in REAL NOT NULL DEFAULT 0,
            total_transfers REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'ABIERTO',
            opened_by INTEGER NOT NULL REFERENCES users(id),
            closed_by INTEGER REFERENCES users(id), closed_at TEXT, notes TEXT
        );
        CREATE TABLE IF NOT EXISTS bank_reconciliation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL, reference_num TEXT NOT NULL,
            bank TEXT NOT NULL, amount REAL NOT NULL, concept TEXT NOT NULL,
            reconciled INTEGER NOT NULL DEFAULT 0,
            payment_id INTEGER REFERENCES payments(id),
            created_by INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS evaluation_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            school_year_id INTEGER NOT NULL REFERENCES school_years(id) UNIQUE,
            min_passing_grade REAL NOT NULL DEFAULT 10.0,
            max_grade REAL NOT NULL DEFAULT 20.0,
            use_decimals INTEGER NOT NULL DEFAULT 1,
            rounding_rule TEXT NOT NULL DEFAULT 'ROUND_HALF_UP'
        );
        CREATE TABLE IF NOT EXISTS activity_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, weight REAL NOT NULL,
            lapso_id INTEGER NOT NULL REFERENCES lapsos(id),
            subject_id INTEGER NOT NULL REFERENCES subjects(id)
        );
        CREATE TABLE IF NOT EXISTS grades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES students(id),
            subject_id INTEGER NOT NULL REFERENCES subjects(id),
            lapso_id INTEGER NOT NULL REFERENCES lapsos(id),
            activity_type_id INTEGER NOT NULL REFERENCES activity_types(id),
            score REAL NOT NULL, notes TEXT,
            entered_by INTEGER NOT NULL REFERENCES users(id),
            entered_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(student_id,subject_id,lapso_id,activity_type_id)
        );
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES students(id),
            date TEXT NOT NULL, subject_id INTEGER REFERENCES subjects(id),
            present INTEGER NOT NULL DEFAULT 1, justified INTEGER NOT NULL DEFAULT 0,
            note TEXT, recorded_by INTEGER NOT NULL REFERENCES users(id),
            UNIQUE(student_id,date,subject_id)
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id), username TEXT NOT NULL,
            action TEXT NOT NULL, module TEXT NOT NULL, entity TEXT NOT NULL,
            entity_id INTEGER, old_value TEXT, new_value TEXT,
            ip_address TEXT, timestamp TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS background_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING',
            progress INTEGER NOT NULL DEFAULT 0, result_path TEXT,
            error_msg TEXT, created_by INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """)

        # Seed roles y permisos
        conn.executescript("""
        INSERT OR IGNORE INTO roles(name,label) VALUES
            ('ADMIN','Administrador'),('SECRETARIA','Secretaría'),
            ('DOCENTE','Docente'),('CAJA','Cajero/a'),('DIRECCION','Dirección');
        INSERT OR IGNORE INTO permissions(module,action) VALUES
            ('students','view'),('students','edit'),('students','delete'),
            ('finance','view'),('finance','edit'),('finance','approve'),('finance','void'),
            ('academic','view'),('academic','edit'),
            ('reports','view'),('admin','view'),('admin','edit'),('audit','view');
        INSERT OR IGNORE INTO role_permissions(role_id,permission_id)
            SELECT r.id,p.id FROM roles r,permissions p WHERE r.name='ADMIN';
        INSERT OR IGNORE INTO role_permissions(role_id,permission_id)
            SELECT r.id,p.id FROM roles r,permissions p WHERE r.name='SECRETARIA'
            AND ((p.module='students' AND p.action IN ('view','edit'))
              OR (p.module='academic' AND p.action='view')
              OR (p.module='reports' AND p.action='view'));
        INSERT OR IGNORE INTO role_permissions(role_id,permission_id)
            SELECT r.id,p.id FROM roles r,permissions p WHERE r.name='CAJA'
            AND ((p.module='finance' AND p.action IN ('view','edit'))
              OR (p.module='students' AND p.action='view')
              OR (p.module='reports' AND p.action='view'));
        INSERT OR IGNORE INTO role_permissions(role_id,permission_id)
            SELECT r.id,p.id FROM roles r,permissions p WHERE r.name='DOCENTE'
            AND ((p.module='academic' AND p.action IN ('view','edit'))
              OR (p.module='students' AND p.action='view'));
        INSERT OR IGNORE INTO role_permissions(role_id,permission_id)
            SELECT r.id,p.id FROM roles r,permissions p WHERE r.name='DIRECCION'
            AND p.module IN ('students','finance','academic','reports','audit');
        """)

        from werkzeug.security import generate_password_hash
        conn.execute("""
            INSERT OR IGNORE INTO users(username,password_hash,full_name,role_id)
            SELECT 'admin',?,'Administrador del Sistema',id FROM roles WHERE name='ADMIN'
        """, (generate_password_hash("Admin2024!"),))

        # Ejecutar migraciones v1.1
        _migrate(conn)
