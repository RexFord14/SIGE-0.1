"""
SIGE – PDF Generation Service  (ReportLab)
Produces: recibos, boletines, constancias
"""
import os, datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                Paragraph, Spacer, HRFlowable, KeepTogether)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.pdfgen import canvas as rl_canvas

REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "generated")
os.makedirs(REPORTS_DIR, exist_ok=True)

# ── Palette ───────────────────────────────────────────────────────────────────
NAVY      = colors.HexColor("#0F1B2D")
NAVY_MID  = colors.HexColor("#1E3A5F")
GOLD      = colors.HexColor("#C9A84C")
GOLD_LIGHT= colors.HexColor("#E8C96D")
SLATE     = colors.HexColor("#94A3B8")
LIGHT_BG  = colors.HexColor("#F8F9FA")
MID_GRAY  = colors.HexColor("#DEE2E6")
RED_SOFT  = colors.HexColor("#FFEBEB")
GREEN_SOFT= colors.HexColor("#EBFFF4")
WHITE     = colors.white
BLACK     = colors.HexColor("#1A1A2E")

SCHOOL_NAME = "UNIDAD EDUCATIVA SIGE"
SCHOOL_RIF  = "J-XXXXXXXXXX-X"
SCHOOL_ADDR = "Dirección Institucional, Ciudad, Venezuela"
SCHOOL_PHONE= "0212-XXX.XXXX"

# ── Shared header ─────────────────────────────────────────────────────────────
def _header(elements):
    """Full letterhead header: logo box + school info + gold rule"""
    # Logo placeholder + school name side by side
    header_data = [[
        Table([[Paragraph('<b>UE</b>', ParagraphStyle('L', fontName='Helvetica-Bold',
                fontSize=18, textColor=WHITE, alignment=TA_CENTER))]],
              colWidths=[1.4*cm], rowHeights=[1.4*cm],
              style=[('BACKGROUND',(0,0),(-1,-1),GOLD),
                     ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
                     ('ALIGN',(0,0),(-1,-1),'CENTER')]),
        Table([
            [Paragraph(SCHOOL_NAME,
                ParagraphStyle('SN', fontName='Helvetica-Bold', fontSize=13,
                               textColor=NAVY, spaceAfter=2))],
            [Paragraph(f"RIF: {SCHOOL_RIF}  |  {SCHOOL_ADDR}",
                ParagraphStyle('SI', fontName='Helvetica', fontSize=8,
                               textColor=SLATE, spaceAfter=1))],
            [Paragraph(f"Tel.: {SCHOOL_PHONE}  |  Sistema Integral de Gestión Escolar",
                ParagraphStyle('SI2', fontName='Helvetica', fontSize=8,
                               textColor=SLATE))],
        ], colWidths=[14*cm])
    ]]
    ht = Table(header_data, colWidths=[1.8*cm, 14.7*cm])
    ht.setStyle(TableStyle([
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('LEFTPADDING',(1,0),(1,0),10),
    ]))
    elements.append(ht)
    elements.append(Spacer(1, 4*mm))
    elements.append(HRFlowable(width='100%', thickness=2.5, color=GOLD, spaceAfter=8*mm))

def _section_title(text):
    return Paragraph(text, ParagraphStyle('SecTitle',
        fontName='Helvetica-Bold', fontSize=9,
        textColor=GOLD, spaceBefore=6, spaceAfter=4,
        borderPad=0, leftIndent=0))

def _info_table(rows, col_widths=None):
    """Key-value info grid"""
    col_widths = col_widths or [3.5*cm, 6*cm, 3.5*cm, 4.5*cm]
    t = Table(rows, colWidths=col_widths)
    t.setStyle(TableStyle([
        ('FONTNAME',(0,0),(-1,-1),'Helvetica'),
        ('FONTNAME',(0,0),(0,-1),'Helvetica-Bold'),
        ('FONTNAME',(2,0),(2,-1),'Helvetica-Bold'),
        ('FONTSIZE',(0,0),(-1,-1),8.5),
        ('TEXTCOLOR',(0,0),(0,-1),SLATE),
        ('TEXTCOLOR',(2,0),(2,-1),SLATE),
        ('TEXTCOLOR',(1,0),(-1,-1),BLACK),
        ('GRID',(0,0),(-1,-1),0.4,MID_GRAY),
        ('BACKGROUND',(0,0),(0,-1),LIGHT_BG),
        ('BACKGROUND',(2,0),(2,-1),LIGHT_BG),
        ('PADDING',(0,0),(-1,-1),5),
        ('ROWBACKGROUNDS',(0,0),(-1,-1),[WHITE, LIGHT_BG]),
    ]))
    return t

# ── RECIBO DE PAGO ─────────────────────────────────────────────────────────────
def generate_receipt(payment_data: dict, student_data: dict, invoice_data: dict) -> str:
    ts   = datetime.date.today().isoformat()
    pnum = payment_data.get("payment_number","0")
    filepath = os.path.join(REPORTS_DIR, f"recibo_{pnum}_{ts}.pdf")

    doc = SimpleDocTemplate(filepath, pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
    e = []

    _header(e)

    # Document title + number box
    title_row = [[
        Paragraph("RECIBO DE PAGO",
            ParagraphStyle('T', fontName='Helvetica-Bold', fontSize=16,
                           textColor=NAVY, alignment=TA_LEFT)),
        Paragraph(f"N° <b>{pnum}</b>",
            ParagraphStyle('N', fontName='Helvetica', fontSize=10,
                           textColor=SLATE, alignment=TA_RIGHT)),
    ]]
    tt = Table(title_row, colWidths=[11*cm, 6.5*cm])
    tt.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE')]))
    e.append(tt)
    e.append(HRFlowable(width='100%', thickness=0.8, color=MID_GRAY, spaceAfter=5*mm))

    # Info grid
    e.append(_section_title("DATOS DEL ESTUDIANTE"))
    e.append(_info_table([
        ["Estudiante:", f"{student_data.get('first_name','')} {student_data.get('last_name','')}",
         "Sección:", student_data.get("section","—")],
        ["Representante:", student_data.get("representative","—"),
         "Cédula Rep.:", student_data.get("cedula_rep","—")],
    ]))
    e.append(Spacer(1,4*mm))

    # Invoice detail
    e.append(_section_title("DETALLE DE FACTURA"))
    det = [
        ["CONCEPTO","MONTO ORIGINAL","DESCUENTO","MONTO NETO"],
        [invoice_data.get("concept","—"),
         f"Bs. {invoice_data.get('amount',0):,.2f}",
         f"Bs. {invoice_data.get('discount',0):,.2f}",
         f"Bs. {invoice_data.get('net_amount',0):,.2f}"],
    ]
    dt = Table(det, colWidths=[7.5*cm, 3.5*cm, 3*cm, 3.5*cm])
    dt.setStyle(TableStyle([
        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
        ('FONTNAME',(0,1),(-1,-1),'Helvetica'),
        ('FONTSIZE',(0,0),(-1,-1),8.5),
        ('BACKGROUND',(0,0),(-1,0),NAVY),
        ('TEXTCOLOR',(0,0),(-1,0),WHITE),
        ('BACKGROUND',(0,1),(-1,1),LIGHT_BG),
        ('GRID',(0,0),(-1,-1),0.4,MID_GRAY),
        ('ALIGN',(1,0),(-1,-1),'RIGHT'),
        ('PADDING',(0,0),(-1,-1),6),
    ]))
    e.append(dt)
    e.append(Spacer(1,4*mm))

    # Payment detail
    e.append(_section_title("DATOS DEL PAGO"))
    pay = [
        ["MONTO PAGADO","MÉTODO","REFERENCIA","BANCO","FECHA"],
        [f"Bs. {payment_data.get('amount',0):,.2f}",
         payment_data.get("payment_method","—"),
         payment_data.get("reference_num","N/A"),
         payment_data.get("bank","N/A"),
         payment_data.get("payment_date","—")],
    ]
    pt = Table(pay, colWidths=[3.5*cm,3*cm,3.5*cm,3.5*cm,4*cm])
    pt.setStyle(TableStyle([
        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
        ('FONTNAME',(0,1),(-1,-1),'Helvetica'),
        ('FONTSIZE',(0,0),(-1,-1),8.5),
        ('BACKGROUND',(0,0),(-1,0),NAVY_MID),
        ('TEXTCOLOR',(0,0),(-1,0),WHITE),
        ('BACKGROUND',(0,1),(-1,1),colors.HexColor("#EBFFF4")),
        ('GRID',(0,0),(-1,-1),0.4,MID_GRAY),
        ('ALIGN',(0,1),(0,1),'RIGHT'),
        ('PADDING',(0,0),(-1,-1),6),
    ]))
    e.append(pt)
    e.append(Spacer(1, 18*mm))

    # Signatures
    sig = [["_________________________","","_________________________"],
           ["Cajero/a Responsable","","Representante / Receptor"]]
    st = Table(sig, colWidths=[6*cm,5.5*cm,6*cm])
    st.setStyle(TableStyle([
        ('ALIGN',(0,0),(-1,-1),'CENTER'),
        ('FONTNAME',(0,1),(-1,1),'Helvetica-Bold'),
        ('FONTSIZE',(0,0),(-1,-1),8),
        ('TEXTCOLOR',(0,1),(-1,1),SLATE),
    ]))
    e.append(st)

    # Footer watermark
    e.append(Spacer(1,10*mm))
    e.append(Paragraph(
        f"Documento generado el {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')} "
        f"— SIGE v1.0 — {SCHOOL_NAME}",
        ParagraphStyle('F', fontName='Helvetica', fontSize=7,
                       textColor=MID_GRAY, alignment=TA_CENTER)))

    doc.build(e)
    return filepath

# ── BOLETÍN DE CALIFICACIONES ─────────────────────────────────────────────────
def generate_boletin(student_data: dict, grades_data: list, config: dict) -> str:
    ts  = datetime.date.today().isoformat()
    sid = student_data.get("id","x")
    filepath = os.path.join(REPORTS_DIR, f"boletin_{sid}_{ts}.pdf")

    doc = SimpleDocTemplate(filepath, pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
    e = []
    _header(e)

    # Title
    e.append(Paragraph("BOLETÍN DE CALIFICACIONES",
        ParagraphStyle('BT', fontName='Helvetica-Bold', fontSize=15,
                       textColor=NAVY, alignment=TA_CENTER, spaceAfter=4*mm)))
    e.append(HRFlowable(width='100%', thickness=0.8, color=MID_GRAY, spaceAfter=4*mm))

    # Student info
    e.append(_section_title("DATOS DEL ESTUDIANTE"))
    e.append(_info_table([
        ["Estudiante:", f"{student_data.get('first_name','')} {student_data.get('last_name','')}",
         "Sección:", student_data.get("section","—")],
        ["Año Escolar:", student_data.get("school_year","—"),
         "Lapso:", student_data.get("lapso","—")],
    ]))
    e.append(Spacer(1,4*mm))

    # Grade table
    e.append(_section_title("CALIFICACIONES"))
    min_g = config.get("min_passing_grade", 10.0)

    rows = [["MATERIA","EVALUACIÓN\n(40%)","TAREA\n(30%)","PROYECTO\n(30%)","PROMEDIO","STATUS"]]
    row_styles = []
    for i, g in enumerate(grades_data, 1):
        avg = g.get("average", 0)
        passed = avg >= min_g
        status = "APROBADO" if passed else "REPROBADO"
        bg = GREEN_SOFT if passed else RED_SOFT
        rows.append([
            g.get("subject",""),
            str(g.get("eval_score","—")),
            str(g.get("task_score","—")),
            str(g.get("proj_score","—")),
            f"{avg:.2f}",
            status,
        ])
        row_styles.append(('BACKGROUND',(0,i),(-1,i), bg))
        row_styles.append(('TEXTCOLOR',(4,i),(4,i),
            colors.HexColor("#0D7A4E") if passed else colors.HexColor("#C0392B")))
        row_styles.append(('FONTNAME',(4,i),(5,i),'Helvetica-Bold'))

    gt = Table(rows, colWidths=[5*cm,2.6*cm,2.6*cm,2.6*cm,2.4*cm,2.3*cm])
    gt.setStyle(TableStyle([
        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
        ('FONTNAME',(0,1),(-1,-1),'Helvetica'),
        ('FONTSIZE',(0,0),(-1,-1),8.5),
        ('BACKGROUND',(0,0),(-1,0),NAVY),
        ('TEXTCOLOR',(0,0),(-1,0),WHITE),
        ('ALIGN',(1,0),(-1,-1),'CENTER'),
        ('ALIGN',(0,0),(0,-1),'LEFT'),
        ('GRID',(0,0),(-1,-1),0.4,MID_GRAY),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[WHITE, LIGHT_BG]),
        ('PADDING',(0,0),(-1,-1),6),
        *row_styles,
    ]))
    e.append(gt)

    # Summary stats
    e.append(Spacer(1,5*mm))
    if grades_data:
        approved = sum(1 for g in grades_data if g.get("average",0) >= min_g)
        total    = len(grades_data)
        overall  = sum(g.get("average",0) for g in grades_data) / total
        summary  = [["MATERIAS APROBADAS","MATERIAS REPROBADAS","PROMEDIO GENERAL"],
                    [f"{approved} / {total}", f"{total-approved} / {total}", f"{overall:.2f}"]]
        st = Table(summary, colWidths=[5.7*cm,5.7*cm,5.7*cm])
        st.setStyle(TableStyle([
            ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
            ('FONTSIZE',(0,0),(-1,-1),8.5),
            ('BACKGROUND',(0,0),(-1,0),NAVY_MID),
            ('TEXTCOLOR',(0,0),(-1,0),WHITE),
            ('BACKGROUND',(0,1),(0,1), GREEN_SOFT if approved==total else LIGHT_BG),
            ('BACKGROUND',(1,1),(1,1), RED_SOFT if (total-approved)>0 else LIGHT_BG),
            ('ALIGN',(0,0),(-1,-1),'CENTER'),
            ('GRID',(0,0),(-1,-1),0.4,MID_GRAY),
            ('FONTNAME',(0,1),(-1,1),'Helvetica-Bold'),
            ('FONTSIZE',(0,1),(-1,1),11),
            ('PADDING',(0,0),(-1,-1),7),
        ]))
        e.append(st)

    # Director signature
    e.append(Spacer(1, 14*mm))
    sig = [["","_______________________",""],
           ["","Director(a) / Sello Inst.",""],
           ["","",""],]
    st2 = Table(sig, colWidths=[5.5*cm,7*cm,5.5*cm])
    st2.setStyle(TableStyle([
        ('ALIGN',(0,0),(-1,-1),'CENTER'),
        ('FONTNAME',(1,1),(1,1),'Helvetica-Bold'),
        ('FONTSIZE',(0,0),(-1,-1),8),
        ('TEXTCOLOR',(1,1),(1,1),SLATE),
    ]))
    e.append(st2)
    e.append(Paragraph(
        f"Generado: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')} — SIGE v1.0",
        ParagraphStyle('F', fontName='Helvetica', fontSize=7,
                       textColor=MID_GRAY, alignment=TA_CENTER, spaceBefore=6)))
    doc.build(e)
    return filepath

# ── CONSTANCIA DE ESTUDIOS ────────────────────────────────────────────────────
def generate_constancia(student_data: dict) -> str:
    ts  = datetime.date.today().isoformat()
    sid = student_data.get("id","x")
    filepath = os.path.join(REPORTS_DIR, f"constancia_{sid}_{ts}.pdf")

    doc = SimpleDocTemplate(filepath, pagesize=A4,
        rightMargin=3*cm, leftMargin=3*cm, topMargin=2.5*cm, bottomMargin=2.5*cm)
    e = []
    _header(e)

    e.append(Paragraph("CONSTANCIA DE ESTUDIOS",
        ParagraphStyle('CT', fontName='Helvetica-Bold', fontSize=16,
                       textColor=NAVY, alignment=TA_CENTER,
                       spaceBefore=10*mm, spaceAfter=8*mm)))

    # Decorative line
    e.append(HRFlowable(width='60%', thickness=1.5, color=GOLD,
                         hAlign='CENTER', spaceAfter=8*mm))

    # Body
    today_str = datetime.date.today().strftime("%d de %B de %Y")
    fn   = student_data.get('first_name','')
    ln   = student_data.get('last_name','')
    ced  = student_data.get('cedula','')
    grad = student_data.get('grade_name','')
    sec  = student_data.get('section','')
    year = student_data.get('school_year','')

    body_style = ParagraphStyle('B', fontName='Helvetica', fontSize=11,
                                 leading=24, alignment=TA_LEFT,
                                 spaceBefore=4, spaceAfter=4)
    e.append(Paragraph(
        f"Quien suscribe, Director(a) de la institución educativa "
        f"<b>{SCHOOL_NAME}</b>, con RIF Nro. <b>{SCHOOL_RIF}</b>, hace constar "
        f"mediante la presente que el/la ciudadano/a:", body_style))
    e.append(Spacer(1, 4*mm))

    # Highlighted student data box
    box_data = [[
        Paragraph(
            f"<b>{fn} {ln}</b><br/>"
            f"<font size='9' color='#475569'>Cédula de Identidad: {ced or 'No registrada'}</font>",
            ParagraphStyle('BD', fontName='Helvetica', fontSize=12, leading=18, alignment=TA_CENTER))
    ]]
    bt = Table(box_data, colWidths=[12*cm])
    bt.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),LIGHT_BG),
        ('BOX',(0,0),(-1,-1),1.5,GOLD),
        ('PADDING',(0,0),(-1,-1),14),
        ('ALIGN',(0,0),(-1,-1),'CENTER'),
    ]))
    e.append(bt)
    e.append(Spacer(1,4*mm))

    e.append(Paragraph(
        f"se encuentra debidamente inscrito(a) en esta institución educativa, "
        f"cursando actualmente <b>{grad}</b>, Sección <b>{sec}</b>, "
        f"correspondiente al Año Escolar <b>{year}</b>. "
        f"El/la estudiante se encuentra al día con sus obligaciones académicas "
        f"según los registros institucionales.", body_style))
    e.append(Spacer(1,4*mm))
    e.append(Paragraph(
        f"La presente constancia se expide a solicitud de la parte interesada, "
        f"a los efectos legales que hubiere lugar, en la ciudad, a los "
        f"<b>{today_str}</b>.", body_style))

    # Signature block
    e.append(Spacer(1, 20*mm))
    sig_data = [
        ["","__________________________________",""],
        ["","Director(a)",""],
        ["","Sello Institucional",""],
    ]
    st = Table(sig_data, colWidths=[4*cm,9*cm,4*cm])
    st.setStyle(TableStyle([
        ('ALIGN',(0,0),(-1,-1),'CENTER'),
        ('FONTNAME',(1,1),(1,1),'Helvetica-Bold'),
        ('FONTNAME',(1,2),(1,2),'Helvetica'),
        ('FONTSIZE',(0,0),(-1,-1),9),
        ('TEXTCOLOR',(1,1),(1,2),SLATE),
    ]))
    e.append(st)
    e.append(Spacer(1,8*mm))
    e.append(HRFlowable(width='100%', thickness=0.5, color=MID_GRAY, spaceAfter=3))
    e.append(Paragraph(
        f"Documento generado el {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')} "
        f"— SIGE v1.0 — Este documento no requiere firma húmeda adicional.",
        ParagraphStyle('F', fontName='Helvetica', fontSize=7,
                       textColor=MID_GRAY, alignment=TA_CENTER)))
    doc.build(e)
    return filepath
