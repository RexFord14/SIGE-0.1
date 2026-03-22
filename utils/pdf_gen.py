"""Generación de PDFs con WeasyPrint desde plantillas HTML."""
import os
from pathlib import Path
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
from config import BASE_DIR, EXPORTS_DIR

try:
    from weasyprint import HTML, CSS
    WEASYPRINT_OK = True
except ImportError:
    WEASYPRINT_OK = False

_jinja_env = Environment(
    loader=FileSystemLoader(str(BASE_DIR / "templates" / "pdf_templates"))
)


def _render_html(template_name: str, context: dict) -> str:
    template = _jinja_env.get_template(template_name)
    return template.render(**context)


def generate_boletin(student, lapso, grades_data: list, school_settings: dict) -> str:
    """Genera boletín de calificaciones en PDF."""
    html_content = _render_html("boletin.html", {
        "student": student,
        "lapso": lapso,
        "grades": grades_data,
        "settings": school_settings,
        "fecha": datetime.now().strftime("%d/%m/%Y"),
    })
    filename = f"boletin_{student.codigo}_lapso{lapso.numero}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
    output_path = EXPORTS_DIR / filename
    if WEASYPRINT_OK:
        HTML(string=html_content, base_url=str(BASE_DIR)).write_pdf(str(output_path))
    else:
        _fallback_html(output_path.with_suffix('.html'), html_content)
        output_path = output_path.with_suffix('.html')
    return str(output_path)


def generate_recibo(payment, invoice, student, school_settings: dict) -> str:
    """Genera recibo de pago en PDF."""
    html_content = _render_html("recibo.html", {
        "payment": payment,
        "invoice": invoice,
        "student": student,
        "settings": school_settings,
        "fecha": datetime.now().strftime("%d/%m/%Y %H:%M"),
    })
    filename = f"recibo_{payment.numero}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
    output_path = EXPORTS_DIR / filename
    if WEASYPRINT_OK:
        HTML(string=html_content, base_url=str(BASE_DIR)).write_pdf(str(output_path))
    else:
        _fallback_html(output_path.with_suffix('.html'), html_content)
        output_path = output_path.with_suffix('.html')
    return str(output_path)


def generate_constancia(student, enrollment, school_settings: dict) -> str:
    """Genera constancia de estudio en PDF."""
    html_content = _render_html("constancia.html", {
        "student": student,
        "enrollment": enrollment,
        "settings": school_settings,
        "fecha": datetime.now().strftime("%d/%m/%Y"),
    })
    filename = f"constancia_{student.codigo}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
    output_path = EXPORTS_DIR / filename
    if WEASYPRINT_OK:
        HTML(string=html_content, base_url=str(BASE_DIR)).write_pdf(str(output_path))
    else:
        _fallback_html(output_path.with_suffix('.html'), html_content)
        output_path = output_path.with_suffix('.html')
    return str(output_path)


def _fallback_html(path: Path, content: str):
    """Guarda como HTML si WeasyPrint no está disponible."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
