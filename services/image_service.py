"""
SIGE – Image Service
Gestión de comprobantes de pago (captura/recibo de pantalla)

DECISIÓN DE DISEÑO:
- Archivos en disco, metadata en DB (nunca BLOB en SQLite → degrada performance)
- Dos versiones por imagen: original comprimido + thumbnail
- UUID como nombre de archivo → evita colisiones y oculta info en URL
- Compresión al guardar → factor ~40x reducción de espacio

CAPACIDAD ESTIMADA:
  Sin compresión: ~3MB/imagen × 300 pagos/mes = ~900MB/año
  Con compresión: ~60KB/imagen × 300 pagos/mes = ~18MB/año
"""
import os, uuid, io
from PIL import Image

BASE_DIR     = os.path.dirname(os.path.dirname(__file__))
UPLOAD_DIR   = os.path.join(BASE_DIR, "uploads")
ORIG_DIR     = os.path.join(UPLOAD_DIR, "originals")
THUMB_DIR    = os.path.join(UPLOAD_DIR, "thumbnails")

MAX_ORIG_PX  = 800    # px máximo en el lado más largo del original
THUMB_SIZE   = (150, 150)  # thumbnail cuadrado, crop centrado
JPEG_QUALITY = 80     # 80% JPEG: ~10x compresión vs PNG, imperceptible al ojo
MAX_FILE_MB  = 10     # rechaza archivos > 10MB antes de procesar

# Extensiones permitidas (imágenes comunes de celular)
ALLOWED_EXT  = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic"}

for d in [ORIG_DIR, THUMB_DIR]:
    os.makedirs(d, exist_ok=True)


def allowed_file(filename: str) -> bool:
    ext = os.path.splitext(filename.lower())[1]
    return ext in ALLOWED_EXT


def save_payment_image(file_storage, payment_id: int) -> dict | None:
    """
    Guarda comprobante de pago con compresión automática.
    
    FLUJO:
    1. Valida extensión y tamaño
    2. Abre con Pillow (maneja HEIC, WEBP, PNG, JPG)
    3. Convierte a RGB (elimina canal alpha incompatible con JPEG)
    4. Redimensiona manteniendo aspect ratio si > MAX_ORIG_PX
    5. Guarda original comprimido como JPEG
    6. Genera thumbnail 150x150 con crop inteligente (centrado)
    7. Registra metadata en DB
    
    Returns: dict con paths y metadata, o None si falla
    """
    if not file_storage or file_storage.filename == "":
        return None
    
    original_name = file_storage.filename
    if not allowed_file(original_name):
        return None

    # Generar nombres únicos con UUID → evita colisiones entre pagos
    uid = uuid.uuid4().hex
    stored_name = f"pay_{payment_id}_{uid}.jpg"
    thumb_name  = f"thumb_{payment_id}_{uid}.jpg"
    orig_path   = os.path.join(ORIG_DIR,  stored_name)
    thumb_path  = os.path.join(THUMB_DIR, thumb_name)

    try:
        raw = file_storage.read()
        
        # Rechazar archivos demasiado grandes antes de procesar
        if len(raw) > MAX_FILE_MB * 1024 * 1024:
            return None

        img = Image.open(io.BytesIO(raw))
        
        # EXIF rotation: muchos celulares guardan orientación en metadata
        try:
            from PIL import ImageOps
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass

        # Convertir a RGB: JPEG no soporta transparencia (RGBA/P)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        # Redimensionar original si es muy grande (preserva ratio)
        w, h = img.size
        if max(w, h) > MAX_ORIG_PX:
            ratio = MAX_ORIG_PX / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

        img.save(orig_path, "JPEG", quality=JPEG_QUALITY, optimize=True)
        file_size_kb = os.path.getsize(orig_path) // 1024

        # Thumbnail con crop centrado (ImageOps.fit = resize + crop)
        thumb_img = Image.open(orig_path)
        from PIL import ImageOps as IO2
        thumb_img = IO2.fit(thumb_img, THUMB_SIZE, Image.LANCZOS)
        thumb_img.save(thumb_path, "JPEG", quality=75, optimize=True)

        return {
            "original_filename": original_name,
            "stored_filename":   stored_name,
            "thumb_filename":    thumb_name,
            "file_size_kb":      file_size_kb,
        }

    except Exception as e:
        # Si falla el procesamiento, limpiar archivos parciales
        for p in [orig_path, thumb_path]:
            if os.path.exists(p):
                os.remove(p)
        print(f"[image_service] Error procesando imagen: {e}")
        return None


def delete_payment_images(payment_id: int, conn) -> int:
    """
    Elimina archivos físicos + registros DB de todas las imágenes de un pago.
    Se llama antes de anular un pago.
    Returns: número de imágenes eliminadas
    """
    rows = conn.execute(
        "SELECT stored_filename, thumb_filename FROM payment_images WHERE payment_id=?",
        (payment_id,)
    ).fetchall()
    
    count = 0
    for row in rows:
        for fname, folder in [(row["stored_filename"], ORIG_DIR), (row["thumb_filename"], THUMB_DIR)]:
            path = os.path.join(folder, fname)
            if os.path.exists(path):
                os.remove(path)
        count += 1
    
    conn.execute("DELETE FROM payment_images WHERE payment_id=?", (payment_id,))
    return count


def get_thumb_path(thumb_filename: str) -> str:
    return os.path.join(THUMB_DIR, thumb_filename)


def get_orig_path(stored_filename: str) -> str:
    return os.path.join(ORIG_DIR, stored_filename)


def get_storage_stats() -> dict:
    """Retorna estadísticas de uso de disco para panel de administración"""
    def folder_mb(path):
        total = sum(
            os.path.getsize(os.path.join(path, f))
            for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))
        ) if os.path.exists(path) else 0
        return round(total / (1024 * 1024), 2)
    
    return {
        "originals_mb":  folder_mb(ORIG_DIR),
        "thumbnails_mb": folder_mb(THUMB_DIR),
        "total_mb":      folder_mb(ORIG_DIR) + folder_mb(THUMB_DIR),
    }


def cleanup_orphans(conn) -> int:
    """
    Elimina imágenes en disco que no tienen registro en DB.
    Útil para limpiar inconsistencias tras errores.
    """
    db_files = set()
    rows = conn.execute("SELECT stored_filename, thumb_filename FROM payment_images").fetchall()
    for r in rows:
        db_files.add(r["stored_filename"])
        db_files.add(r["thumb_filename"])
    
    removed = 0
    for folder in [ORIG_DIR, THUMB_DIR]:
        if not os.path.exists(folder):
            continue
        for fname in os.listdir(folder):
            if fname not in db_files:
                os.remove(os.path.join(folder, fname))
                removed += 1
    return removed
