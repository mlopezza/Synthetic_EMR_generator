"""
═══════════════════════════════════════════════════════════════════════════════
  EMR SYNTHETIC DATA GENERATOR  –  Version 4.0  (Compliance Edition)
═══════════════════════════════════════════════════════════════════════════════

  COMPLIANCE CHANGES vs v3
  ─────────────────────────
  1. INSTITUTIONS – All real hospital / clinic names replaced with five
     distinct fictional alternatives, defined centrally in INSTITUTION_MAP.
     The name propagates automatically to headers, signature blocks, and
     any embedded textual references via the `inst()` helper.

  2. WATERMARK – A single centered diagonal watermark
     "SYNTHETIC SAMPLE – NOT A REAL PATIENT" is applied to every page of
     every generated PDF via the post_process_pdf() pipeline function.
     Logic is fully centralised; no duplication across patient builders.

  3. DISCLAIMER – A formal disclaimer block is injected at the bottom of
     page 1 of every document. Rendering is handled by the reusable
     make_disclaimer_overlay() function called inside post_process_pdf().

  ARCHITECTURE GUIDE
  ──────────────────
  ┌─ INSTITUTION_MAP ──────────────────────────────────────────────────────┐
  │  Single dict keyed by patient ID (1-5). Each entry contains name,     │
  │  address, phone, and specialty string. Used by inst() helper.         │
  └────────────────────────────────────────────────────────────────────────┘
  ┌─ post_process_pdf(src, dst) ───────────────────────────────────────────┐
  │  Pipeline applied to every generated PDF:                             │
  │    1. make_watermark_overlay()  → applied to ALL pages                │
  │    2. make_disclaimer_overlay() → applied to page 1 only             │
  └────────────────────────────────────────────────────────────────────────┘
  ┌─ Patient builders (build_jacinta … build_jose) ────────────────────────┐
  │  Each receives its institution data via inst(patient_id). They write  │
  │  to a TEMP file; post_process_pdf() then produces the FINAL file.    │
  └────────────────────────────────────────────────────────────────────────┘

  REQUIREMENTS
  ────────────
  pip install reportlab pypdf --break-system-packages

═══════════════════════════════════════════════════════════════════════════════
"""

# ── Standard library ──────────────────────────────────────────────────────────
import io
import math
import os

# ── ReportLab ─────────────────────────────────────────────────────────────────
from reportlab.lib.pagesizes import letter
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_RIGHT
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.colors import Color
from reportlab.pdfbase.pdfmetrics import stringWidth

# ── pypdf ─────────────────────────────────────────────────────────────────────
from pypdf import PdfReader, PdfWriter


# ═══════════════════════════════════════════════════════════════════════════════
#  ① INSTITUTION MAP  ←── centralised fictional institution configuration
# ═══════════════════════════════════════════════════════════════════════════════

INSTITUTION_MAP = {
    # Each entry: name, address, phone, specialty line used in sig blocks
    1: {
        "name":      "Sample Maplewood Community Health Centre",
        "dept":      "Family Medicine & Primary Care",
        "address":   "123 Maplewood Crescent, Suite 200 | Riverdale, ON M5V 1A1",
        "phone":     "Tel: (555) 210-0100 | Fax: (555) 210-0101",
        "specialty": "Family Medicine – Sample Maplewood Community Health Centre",
    },
    2: {
        "name":      "Sample Lakeview General Hospital",
        "dept":      "Emergency Department & Intermediate Care Unit",
        "address":   "200 Lakeview Boulevard | Harbour District, ON M5G 2C4",
        "phone":     "Tel: (555) 340-4800 | Fax: (555) 340-3485",
        "specialty": "Internal Medicine – Sample Lakeview General Hospital",
    },
    3: {
        "name":      "Sample Northgate Family Health Team",
        "dept":      "Respiratory & Oncology Fast Track",
        "address":   "4001 Northgate Avenue, Suite 110 | Westpark, ON M2K 1E1",
        "phone":     "Tel: (555) 530-0530 | Fax: (555) 530-0531",
        "specialty": "Family Medicine + Respirology Liaison – Sample Northgate FHT",
    },
    4: {
        "name":      "Sample Maplewood Community Health Centre",
        "dept":      "Family Medicine & Primary Care",
        "address":   "123 Maplewood Crescent, Suite 200 | Riverdale, ON M5V 1A1",
        "phone":     "Tel: (555) 210-0100 | Fax: (555) 210-0101",
        "specialty": "Family Medicine – Sample Maplewood Community Health Centre",
    },
    5: {
        "name":      "Sample Bayview Heart & Vascular Institute",
        "dept":      "Cardiology & Anticoagulation Clinic",
        "address":   "2075 Bayview Medical Drive, Room H1-52 | Eastview, ON M4N 3M5",
        "phone":     "Tel: (555) 480-4928 | Fax: (555) 480-5878 | Anticoag Hotline ext. 2891",
        "specialty": "Internal Medicine / Cardiology – Sample Bayview Heart & Vascular Institute",
    },
}


def inst(patient_id: int) -> dict:
    """
    Return institution data dict for a given patient ID (1–5).
    Combines name + dept into the full clinic_name string used by header_block().
    """
    d = INSTITUTION_MAP[patient_id]
    return {
        "clinic_name": f"{d['name']} – {d['dept']}",
        "name":        d["name"],
        "dept":        d["dept"],
        "address":     d["address"],
        "phone":       d["phone"],
        "specialty":   d["specialty"],
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  ② WATERMARK & DISCLAIMER  ←── centralised compliance overlay functions
# ═══════════════════════════════════════════════════════════════════════════════

WATERMARK_TEXT   = "SYNTHETIC SAMPLE – NOT A REAL PATIENT"
DISCLAIMER_TITLE = "DISCLAIMER"
DISCLAIMER_BODY  = (
    "This document is a fully synthetic medical record generated for software testing and "
    "demonstration purposes only. All patient data contained herein is fictional. Any resemblance "
    "to real persons, living or dead, is purely coincidental. Institutional names used in this "
    "document are fictional and do not represent real clinical documentation. This document must "
    "not be used for clinical, legal, or medical decision-making purposes."
)


def make_watermark_overlay(page_width: float, page_height: float) -> object:
    """
    ② WATERMARK LOGIC
    Build a single centered diagonal watermark overlay page (in-memory PDF page).
    Applied to every page of every document via post_process_pdf().
    """
    packet = io.BytesIO()
    c = rl_canvas.Canvas(packet, pagesize=(page_width, page_height))
    c.setFillColor(Color(0.80, 0.10, 0.10, alpha=0.18))
    c.saveState()
    c.translate(page_width / 2, page_height / 2)
    # Natural diagonal angle proportional to page dimensions
    angle = math.degrees(math.atan2(page_height, page_width))
    c.rotate(angle)
    c.setFont("Helvetica-Bold", 42)
    c.drawCentredString(0, 0, WATERMARK_TEXT)
    c.restoreState()
    c.save()
    packet.seek(0)
    return PdfReader(packet).pages[0]


def make_disclaimer_overlay(page_width: float, page_height: float) -> object:
    """
    ② DISCLAIMER LOGIC
    Build a disclaimer block overlay for the bottom of page 1 (in-memory PDF page).
    Applied only to page index 0 via post_process_pdf().
    """
    packet  = io.BytesIO()
    c       = rl_canvas.Canvas(packet, pagesize=(page_width, page_height))
    margin  = 0.75 * 72               # 0.75 inch expressed in points
    max_w   = page_width - 2 * margin
    fn_body = "Helvetica"
    fs_body = 7.5
    line_h  = 11
    y_base  = 108                      # distance from page bottom to top of block

    # Separator rule
    c.setStrokeColor(Color(0.2, 0.2, 0.2, alpha=0.65))
    c.setLineWidth(0.7)
    c.line(margin, y_base + 56, page_width - margin, y_base + 56)

    # Bold title
    c.setFillColor(Color(0, 0, 0, alpha=1))
    c.setFont("Helvetica-Bold", 9)
    c.drawString(margin, y_base + 42, DISCLAIMER_TITLE)

    # Body text – pixel-accurate word wrap
    words, lines, cur = DISCLAIMER_BODY.split(), [], []
    for w in words:
        probe = " ".join(cur + [w])
        if stringWidth(probe, fn_body, fs_body) <= max_w:
            cur.append(w)
        else:
            if cur:
                lines.append(" ".join(cur))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))

    c.setFont(fn_body, fs_body)
    y = y_base + 28
    for ln in lines:
        c.drawString(margin, y, ln)
        y -= line_h

    c.save()
    packet.seek(0)
    return PdfReader(packet).pages[0]


def post_process_pdf(src_path: str, dst_path: str) -> None:
    """
    ② POST-PROCESSING PIPELINE
    Reads a freshly-built PDF, applies:
      - Disclaimer overlay  →  page 1 only
      - Watermark overlay   →  every page
    Writes the result to dst_path and removes the temp src_path.
    """
    reader = PdfReader(src_path)
    writer = PdfWriter()

    for i, page in enumerate(reader.pages):
        pw = float(page.mediabox.width)
        ph = float(page.mediabox.height)

        if i == 0:
            page.merge_page(make_disclaimer_overlay(pw, ph))

        page.merge_page(make_watermark_overlay(pw, ph))
        writer.add_page(page)

    with open(dst_path, "wb") as fh:
        writer.write(fh)

    if os.path.exists(src_path):
        os.remove(src_path)


# ═══════════════════════════════════════════════════════════════════════════════
#  GLOBAL CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

OUTPUT_DIR   = "/mnt/user-data/outputs"
os.makedirs(OUTPUT_DIR, exist_ok=True)

PAGE_W, PAGE_H = letter
LEFT_MARGIN    = 0.75 * inch
RIGHT_MARGIN   = 0.75 * inch
TOP_MARGIN     = 0.60 * inch
BOT_MARGIN     = 0.60 * inch
CONTENT_W      = PAGE_W - LEFT_MARGIN - RIGHT_MARGIN   # 7.0 inches


# ═══════════════════════════════════════════════════════════════════════════════
#  CORRECTION HELPERS (unchanged from v3)
# ═══════════════════════════════════════════════════════════════════════════════

def fix_hemoglobin_unit(value_gL: float) -> str:
    return f"{value_gL / 10:.1f}"

def fix_hematocrit_unit(value_LL: float) -> str:
    return f"{value_LL * 100:.1f}"

def validate_lab_row(row: list) -> None:
    if len(row) < 2:
        return
    test  = str(row[0]).lower()
    value = str(row[1]).replace(",", ".")
    if "hemoglobin" in test or "haemoglobin" in test:
        try:
            v = float(value.split()[0])
            if v > 25 or v < 3:
                raise ValueError(f"Impossible hemoglobin value: {v}. Use g/dL.")
        except (ValueError, IndexError):
            pass
    if "hematocrit" in test or "haematocrit" in test:
        try:
            v = float(value.split()[0])
            if v < 1.0:
                raise ValueError(f"Hematocrit appears to be in L/L fraction ({v}). Convert to %.")
        except (ValueError, IndexError):
            pass


# ═══════════════════════════════════════════════════════════════════════════════
#  STYLE FACTORY
# ═══════════════════════════════════════════════════════════════════════════════

def make_styles() -> dict:
    _ = getSampleStyleSheet()
    return {
        'title':     ParagraphStyle('title',     fontSize=13, fontName='Helvetica-Bold',  alignment=TA_CENTER, spaceAfter=4),
        'subtitle':  ParagraphStyle('subtitle',  fontSize=10, fontName='Helvetica-Bold',  alignment=TA_CENTER, spaceAfter=4),
        'clinic':    ParagraphStyle('clinic',    fontSize=8,  fontName='Helvetica',       alignment=TA_CENTER, spaceAfter=2, textColor=colors.HexColor('#555555')),
        'h1':        ParagraphStyle('h1',        fontSize=10, fontName='Helvetica-Bold',  spaceBefore=10, spaceAfter=4, textColor=colors.HexColor('#003366')),
        'h2':        ParagraphStyle('h2',        fontSize=9,  fontName='Helvetica-Bold',  spaceBefore=6,  spaceAfter=3, textColor=colors.HexColor('#005599')),
        'body':      ParagraphStyle('body',      fontSize=8.5,fontName='Helvetica',       leading=12, spaceAfter=3, alignment=TA_JUSTIFY),
        'label':     ParagraphStyle('label',     fontSize=8.5,fontName='Helvetica-Bold',  spaceAfter=1),
        'small':     ParagraphStyle('small',     fontSize=7.5,fontName='Helvetica',       textColor=colors.HexColor('#666666')),
        'center':    ParagraphStyle('center',    fontSize=8.5,fontName='Helvetica',       alignment=TA_CENTER),
        'right':     ParagraphStyle('right',     fontSize=8.5,fontName='Helvetica',       alignment=TA_RIGHT),
        'warning':   ParagraphStyle('warning',   fontSize=8.5,fontName='Helvetica-Bold',  textColor=colors.red, spaceAfter=2),
        'sign':      ParagraphStyle('sign',      fontSize=8.5,fontName='Helvetica',       alignment=TA_CENTER, spaceAfter=2),
        'cell':      ParagraphStyle('cell',      fontSize=8,  fontName='Helvetica',       leading=10, spaceAfter=0),
        'cell_bold': ParagraphStyle('cell_bold', fontSize=8,  fontName='Helvetica-Bold',  leading=10, spaceAfter=0),
        'cell_hdr':  ParagraphStyle('cell_hdr',  fontSize=8,  fontName='Helvetica-Bold',  leading=10, spaceAfter=0, textColor=colors.white),
    }

S = make_styles()


# ═══════════════════════════════════════════════════════════════════════════════
#  LAYOUT PRIMITIVES
# ═══════════════════════════════════════════════════════════════════════════════

def hr() -> HRFlowable:
    return HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#003366'), spaceAfter=4, spaceBefore=4)


def _default_doc(filename: str) -> SimpleDocTemplate:
    return SimpleDocTemplate(filename, pagesize=letter,
                             topMargin=TOP_MARGIN, bottomMargin=BOT_MARGIN,
                             leftMargin=LEFT_MARGIN, rightMargin=RIGHT_MARGIN)


def header_block(clinic_name: str, address: str, phone: str, date: str, doc_type: str) -> Table:
    col_l = CONTENT_W * 0.58
    col_r = CONTENT_W * 0.42
    data = [
        [Paragraph(clinic_name, S['title']),  Paragraph(doc_type,       S['subtitle'])],
        [Paragraph(address,     S['clinic']), Paragraph(f"Date: {date}", S['clinic'])],
        [Paragraph(phone,       S['clinic']), Paragraph("",              S['clinic'])],
    ]
    t = Table(data, colWidths=[col_l, col_r])
    t.setStyle(TableStyle([
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW',     (0, 2), (-1,  2), 0.5, colors.HexColor('#003366')),
        ('BOTTOMPADDING', (0, 2), (-1,  2), 6),
        ('TOPPADDING',    (0, 0), (-1, -1), 2),
    ]))
    return t


def patient_box(data_dict: dict) -> Table:
    items = list(data_dict.items())
    rows  = []
    col_w = CONTENT_W / 2
    for i in range(0, len(items), 2):
        k1, v1 = items[i]
        cell_l = Paragraph(f"<b>{k1}:</b> {v1}", S['cell'])
        if i + 1 < len(items):
            k2, v2 = items[i + 1]
            cell_r = Paragraph(f"<b>{k2}:</b> {v2}", S['cell'])
        else:
            cell_r = Paragraph("", S['cell'])
        rows.append([cell_l, cell_r])
    t = Table(rows, colWidths=[col_w, col_w])
    t.setStyle(TableStyle([
        ('BOX',           (0, 0), (-1, -1), 0.5,  colors.HexColor('#003366')),
        ('BACKGROUND',    (0, 0), (-1, -1), colors.HexColor('#EEF4FB')),
        ('INNERGRID',     (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING',   (0, 0), (-1, -1), 6),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
    ]))
    return t


def _build_lab_table_flowable(title: str, rows_data: list, headers: list = None) -> Table:
    if headers is None:
        headers = ["Test", "Result", "Reference Range", "Units", "Flag"]
    for row in rows_data:
        validate_lab_row(row)
    col_widths = [2.55*inch, 1.25*inch, 1.60*inch, 0.90*inch, 0.70*inch]

    def wrap(text, style=S['cell']):
        return Paragraph(str(text), style)

    hdr_cells  = [Paragraph(h, S['cell_hdr']) for h in headers]
    table_data = [hdr_cells] + [[wrap(c) for c in row] for row in rows_data]
    t = Table(table_data, colWidths=col_widths)
    style_cmds = [
        ('BACKGROUND',     (0, 0), (-1,  0), colors.HexColor('#003366')),
        ('FONTSIZE',       (0, 0), (-1, -1), 8),
        ('GRID',           (0, 0), (-1, -1), 0.3, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F5F8FC')]),
        ('TOPPADDING',     (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING',  (0, 0), (-1, -1), 4),
        ('LEFTPADDING',    (0, 0), (-1, -1), 5),
        ('RIGHTPADDING',   (0, 0), (-1, -1), 5),
        ('VALIGN',         (0, 0), (-1, -1), 'TOP'),
    ]
    for i, row in enumerate(rows_data, 1):
        if len(row) >= 5 and str(row[4]).strip() in ('H', 'L', 'CRIT', 'ABN'):
            style_cmds += [
                ('TEXTCOLOR', (1, i), (1, i), colors.red), ('FONTNAME', (1, i), (1, i), 'Helvetica-Bold'),
                ('TEXTCOLOR', (4, i), (4, i), colors.red), ('FONTNAME', (4, i), (4, i), 'Helvetica-Bold'),
            ]
    t.setStyle(TableStyle(style_cmds))
    return t


def lab_table(title: str, rows_data: list, headers: list = None) -> list:
    t     = _build_lab_table_flowable(title, rows_data, headers)
    block = KeepTogether([Paragraph(title, S['h2']), t])
    return [block, Spacer(1, 6)]


def _build_rx_table_flowable(title: str, meds: list) -> Table:
    headers    = ["Generic Name", "Presentation", "Dose / Route / Frequency", "Qty", "Duration"]
    col_widths = [1.40*inch, 1.15*inch, 2.25*inch, 0.70*inch, 1.50*inch]

    def wrap(text, style=S['cell']):
        return Paragraph(str(text), style)

    hdr_cells  = [Paragraph(h, S['cell_hdr']) for h in headers]
    table_data = [hdr_cells] + [[wrap(c) for c in row] for row in meds]
    t = Table(table_data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ('BACKGROUND',     (0, 0), (-1,  0), colors.HexColor('#005599')),
        ('FONTSIZE',       (0, 0), (-1, -1), 8),
        ('GRID',           (0, 0), (-1, -1), 0.3, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F0F8F0')]),
        ('TOPPADDING',     (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING',  (0, 0), (-1, -1), 5),
        ('LEFTPADDING',    (0, 0), (-1, -1), 5),
        ('RIGHTPADDING',   (0, 0), (-1, -1), 5),
        ('VALIGN',         (0, 0), (-1, -1), 'TOP'),
    ]))
    return t


def rx_table(title: str, meds: list) -> list:
    t     = _build_rx_table_flowable(title, meds)
    block = KeepTogether([Paragraph(title, S['h2']) if title else Spacer(1, 1), t])
    return [block, Spacer(1, 6)]


def generic_order_table(title: str, headers: list, rows: list,
                         col_widths: list, header_color=None) -> list:
    if header_color is None:
        header_color = colors.HexColor('#003366')
    col_pts = [w * inch if w < 20 else w for w in col_widths]

    def wrap(text, style=S['cell']):
        return Paragraph(str(text), style)

    hdr_cells  = [Paragraph(h, S['cell_hdr']) for h in headers]
    table_data = [hdr_cells] + [[wrap(c) for c in row] for row in rows]
    t = Table(table_data, colWidths=col_pts)
    t.setStyle(TableStyle([
        ('BACKGROUND',     (0, 0), (-1,  0), header_color),
        ('FONTSIZE',       (0, 0), (-1, -1), 8),
        ('GRID',           (0, 0), (-1, -1), 0.3, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F5F8FC')]),
        ('TOPPADDING',     (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING',  (0, 0), (-1, -1), 5),
        ('LEFTPADDING',    (0, 0), (-1, -1), 5),
        ('RIGHTPADDING',   (0, 0), (-1, -1), 5),
        ('VALIGN',         (0, 0), (-1, -1), 'TOP'),
    ]))
    block = KeepTogether([Paragraph(title, S['h2']) if title else Spacer(1, 1), t])
    return [block, Spacer(1, 8)]


def sig_block(doctor: str, reg: str, specialty: str, date: str) -> Table:
    rows = [
        [Paragraph("_" * 44, S['sign'])],
        [Paragraph(f"<b>{doctor}</b>", S['sign'])],
        [Paragraph(f"License No.: {reg}", S['sign'])],
        [Paragraph(specialty, S['sign'])],
        [Paragraph(f"Date: {date}", S['sign'])],
    ]
    t = Table(rows, colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ('TOPPADDING',    (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    return t


def section(title: str, content_paragraphs: list) -> list:
    story = [hr(), Paragraph(title, S['h1'])]
    for p in content_paragraphs:
        story.append(Paragraph(p, S['body']))
    return story


# ═══════════════════════════════════════════════════════════════════════════════
#  PATIENT 1 – JACINTA DEL SOCORRO
#  Institution: Sample Maplewood Community Health Centre
# ═══════════════════════════════════════════════════════════════════════════════

def build_jacinta():
    pid    = 1
    I      = inst(pid)
    FNAME  = os.path.join(OUTPUT_DIR, "_tmp_01_Jacinta.pdf")
    FINAL  = os.path.join(OUTPUT_DIR, "01_Jacinta_del_Socorro_EMR.pdf")
    CLINIC = I["clinic_name"]
    ADDR   = I["address"]
    PHONE  = I["phone"]
    SPEC   = I["specialty"]
    DR     = "Dr. Alejandro Martínez Roa, MD"
    LIC    = "MED-ON-88742"
    DATE   = "February 19, 2026"

    doc   = _default_doc(FNAME)
    story = []

    # ── Page 1: CPP ────────────────────────────────────────────────────────
    story.append(header_block(CLINIC, ADDR, PHONE, DATE, "COMPLETE MEDICAL RECORD"))
    story.append(Spacer(1, 10))
    story.append(Paragraph("SECTION 1 – CUMULATIVE PATIENT PROFILE (CPP)", S['h1']))
    story.append(patient_box({
        "Full Name":          "Jacinta del Socorro Fuentes Ríos",
        "Date of Birth":      "March 14, 1941  (Age: 84)",
        "Health Card (OHIP)": "3421-876-543 VU",
        "Sex / Gender":       "Female / Woman",
        "Address":            "45 Birchwood Ave., Toronto, ON M4E 2K3",
        "Phone":              "(416) 555-0094",
        "Emergency Contact":  "Rosa Fuentes (daughter) – (416) 555-0391",
        "Family Physician":   DR,
        "Pharmacy":           "Shoppers Drug Mart – 88 Queen St E",
        "Language":           "Spanish / English",
    }))
    story += section("1.1 – Active Medical Problems", [
        "1. Essential Hypertension (HTN) – I10 | Dx: 2005 | Controlled.",
        "2. Type 2 Diabetes Mellitus (T2DM) with peripheral neuropathy – E11.40 | Dx: 2008 | Insulin-dependent since 2019.",
        "3. Congestive Heart Failure – preserved EF (HFpEF) – I50.30 | Dx: 2018 | NYHA Class II-III.",
        "4. Chronic Kidney Disease Stage 3b – N18.32 | Dx: 2020 | eGFR 32 mL/min/1.73m2.",
        "5. Hypothyroidism – E03.9 | Dx: 2015 | Levothyroxine-dependent.",
        "6. Venous Leg Ulcer, right lower extremity, infected – L97.919 | CURRENT VISIT.",
        "7. Dyslipidemia – E78.5 | Dx: 2010.",
    ])
    story += section("1.2 – Past Medical & Surgical History", [
        "2003: Right inguinal hernia repair (open). Uneventful recovery.",
        "2010: Hospitalization for hypertensive urgency.",
        "2015: Hypothyroidism diagnosed on routine TSH screening.",
        "2017: Cataract extraction, right eye.",
        "2020: Hospitalization for acute decompensated CHF; diuretic therapy started.",
    ])
    story += section("1.3 – Allergies & Adverse Drug Reactions", [
        "<b>PENICILLIN</b> – Anaphylaxis (hives, angioedema, hypotension). 1985. HIGH-RISK.",
        "Ibuprofen / NSAIDs – peripheral edema, worsening renal function. Avoid.",
        "Iodinated contrast – urticaria. Pre-medication required.",
    ])
    story += section("1.4 – Current Medications", [])
    story += rx_table("Chronic Medication List", [
        ["Ramipril",          "5 mg tab",           "5 mg PO once daily",                    "30",     "Ongoing"],
        ["Furosemide",        "40 mg tab",           "40 mg PO once daily (AM)",              "30",     "Ongoing"],
        ["Bisoprolol",        "5 mg tab",            "5 mg PO once daily",                    "30",     "Ongoing"],
        ["Atorvastatin",      "40 mg tab",           "40 mg PO at bedtime",                   "30",     "Ongoing"],
        ["Metformin",         "500 mg tab",          "500 mg PO twice daily",                 "60",     "Ongoing"],
        ["Insulin Glargine",  "100 U/mL 10 mL vial", "20 units SC at bedtime",               "2 vials","Ongoing"],
        ["Insulin Lispro",    "100 U/mL 3 mL pen",   "4-6 units SC before meals",            "3 pens", "Ongoing"],
        ["Levothyroxine",     "75 mcg tab",          "75 mcg PO daily (fasting)",             "30",     "Ongoing"],
        ["Aspirin",           "81 mg tab",           "81 mg PO once daily",                   "30",     "Ongoing"],
        ["Spironolactone",    "25 mg tab",           "25 mg PO once daily",                   "30",     "Ongoing"],
        ["Calcium + Vit D3",  "500/400 tab",         "1 tab PO twice daily with meals",       "60",     "Ongoing"],
    ])
    story += section("1.5 – Immunization History", [
        "Influenza: October 2025 (annual). Pneumococcal PCV15: 2023. Td: 2018. COVID-19 boosters: Fall 2024. Shingrix: 2021.",
    ])
    story += section("1.6 – Family & Social History", [
        "<b>Family:</b> Father (†72, MI). Mother (†88, CVA). Sister with T2DM and HTN.",
        "<b>Social:</b> Widowed. Lives alone (elevator access). Retired seamstress. Daughter visits daily. Uses cane. Never smoked. Abstinent from alcohol since 2020. MMSE 27/30. No advance directive.",
    ])

    # ── Page 2: Encounter Note ─────────────────────────────────────────────
    story.append(PageBreak())
    story.append(header_block(CLINIC, ADDR, PHONE, DATE, "ENCOUNTER NOTE – SOAP"))
    story.append(Spacer(1, 8))
    story.append(Paragraph("SECTION 2 – ENCOUNTER NOTE", S['h1']))
    story.append(patient_box({
        "Patient":    "Jacinta del Socorro Fuentes Ríos",
        "DOB":        "March 14, 1941",
        "Visit Date": DATE,
        "Visit Type": "Office – Acute + Chronic Review",
        "Physician":  DR,
        "License":    LIC,
    }))
    story += section("S – SUBJECTIVE", [
        '<b>Chief Complaint:</b> "My right leg wound is getting worse and it smells bad."',
        "<b>HPI:</b> Mrs. Fuentes is an 84-year-old woman presenting with a right lower extremity chronic venous ulcer present for ~10 weeks. Over the last 2 weeks she notes increasing pain (7/10 VAS), foul-smelling purulent exudate, and perilesional erythema extending to mid-calf. No fever or chills at home. She has been changing dressings herself with plain gauze. Glycemic logs show fasting glucose 130–160 mg/dL. Reports mild exertional dyspnea (1 flight, consistent with baseline CHF). No weight gain or orthopnea.",
        "<b>ROS:</b> No fever. Mild fatigue. Bilateral ankle oedema (chronic). Bilateral foot paraesthesias (baseline neuropathy). Slight increase in nocturia (×2/night).",
    ])
    story += section("O – OBJECTIVE", [
        "<b>Vitals:</b> BP 148/88 mmHg | HR 74 bpm (regular) | RR 16/min | SpO2 96% RA | T 37.4 °C | Wt 68.2 kg | Ht 155 cm | BMI 28.4 kg/m<super>2</super>.",
        "<b>CVS:</b> S1 S2 regular, no murmurs. JVP ~3 cm above clavicle. Peripheral pulses 2+.",
        "<b>Respiratory:</b> Clear bilaterally.",
        "<b>Right Leg:</b> 2+ pitting oedema to knee. Medial malleolar ulcer 4×3.5 cm, sloughing base, moderate purulent exudate, moderate odour. Perilesional erythema 6 cm radius, induration, warmth, tenderness. No crepitus.",
        "<b>Neuro:</b> Diminished monofilament sensation bilateral feet (chronic neuropathy).",
    ])
    story += section("A – ASSESSMENT", [
        "1. <b>Infected chronic venous leg ulcer, right LE</b> – local infection (erythema, purulence, odour). No systemic sepsis. Culture ordered. Penicillin allergy: clindamycin selected.",
        "2. <b>T2DM – suboptimally controlled</b> – hyperglycemia impairs healing. HbA1c ordered.",
        "3. <b>CKD Stage 3b</b> – dose-adjustment required. Metformin continued at low dose. Cr/BUN ordered.",
        "4. <b>Hypothyroidism</b> – T4L ordered to assess levothyroxine adequacy.",
        "5. <b>CHF (HFpEF) – compensated</b>. No acute decompensation.",
        "6. <b>HTN</b> – slightly above target today; likely pain/anxiety. No medication change.",
    ])
    story += section("P – PLAN", [
        "1. Antibiotic: Clindamycin 300 mg PO q8h × 14 days (penicillin allergy).",
        "2. Wound care referral: Wound Care Clinic, dressing changes 3×/week.",
        "3. Labs: CBC, Creatinine, BUN, Free T4, HbA1c. Wound swab culture collected today.",
        "4. Medication reconciliation completed – no changes to chronic regimen today.",
        "5. Glycaemic counselling and foot care education.",
        "6. Follow-up in 2 weeks or sooner if fever >38.5 °C, expanding erythema, or systemic symptoms.",
        "7. Counsel to attend ED if rapid deterioration, confusion, or haemodynamic change.",
    ])
    story.append(Spacer(1, 14))
    story.append(sig_block(DR, LIC, SPEC, DATE))

    # ── Page 3: Prescription ──────────────────────────────────────────────
    story.append(PageBreak())
    story.append(header_block(CLINIC, ADDR, PHONE, DATE, "PRESCRIPTION (Rx)"))
    story.append(Spacer(1, 8))
    story.append(Paragraph("SECTION 3 – PRESCRIPTION", S['h1']))
    story.append(patient_box({
        "Patient": "Jacinta del Socorro Fuentes Ríos", "DOB": "March 14, 1941",
        "OHIP": "3421-876-543 VU", "Date": DATE, "Physician": DR, "License": LIC,
    }))
    story.append(Spacer(1, 8))
    story += rx_table("Complete Medication List – Chronic + New Antibiotic", [
        ["Clindamycin",      "300 mg capsule",      "300 mg PO every 8 h",              "42",     "14 days"],
        ["Ramipril",         "5 mg tab",            "5 mg PO once daily",               "30",     "Ongoing"],
        ["Furosemide",       "40 mg tab",           "40 mg PO once daily AM",           "30",     "Ongoing"],
        ["Bisoprolol",       "5 mg tab",            "5 mg PO once daily",               "30",     "Ongoing"],
        ["Atorvastatin",     "40 mg tab",           "40 mg PO at bedtime",              "30",     "Ongoing"],
        ["Metformin",        "500 mg tab",          "500 mg PO twice daily",            "60",     "Ongoing"],
        ["Insulin Glargine", "100 U/mL 10 mL vial", "20 units SC at bedtime",          "2 vials","90 days"],
        ["Insulin Lispro",   "100 U/mL 3 mL pen",   "4-6 units SC before meals",       "3 pens", "90 days"],
        ["Levothyroxine",    "75 mcg tab",          "75 mcg PO daily (fasting)",        "30",     "Ongoing"],
        ["Aspirin",          "81 mg tab",           "81 mg PO once daily",              "30",     "Ongoing"],
        ["Spironolactone",   "25 mg tab",           "25 mg PO once daily",              "30",     "Ongoing"],
        ["Calcium + Vit D3", "500/400 tab",         "1 tab PO twice daily",             "60",     "Ongoing"],
    ])
    story.append(Paragraph(
        "* Penicillin allergy documented. NSAIDs contraindicated (CKD). "
        "Metformin dose-adjusted for eGFR 32 mL/min.", S['warning']
    ))
    story.append(Spacer(1, 14))
    story.append(sig_block(DR, LIC, SPEC, DATE))

    # ── Page 4: Lab Orders ────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(header_block(CLINIC, ADDR, PHONE, DATE, "LABORATORY REQUISITION"))
    story.append(Spacer(1, 8))
    story.append(Paragraph("SECTION 4 – LABORATORY ORDERS", S['h1']))
    story.append(patient_box({
        "Patient":  "Jacinta del Socorro Fuentes Ríos", "DOB": "March 14, 1941",
        "OHIP":     "3421-876-543 VU", "Date": DATE,
        "Priority": "ROUTINE (within 48 h)", "Fasting": "Required (10-12 h)",
    }))
    story.append(Spacer(1, 8))
    story += generic_order_table(
        "Ordered Tests",
        ["Test", "Clinical Indication"],
        [
            ["Complete Blood Count (CBC)",           "Anaemia screening; infection monitoring"],
            ["Serum Creatinine (Cr)",                "CKD monitoring; medication dose adjustment"],
            ["BUN (Blood Urea Nitrogen)",            "Renal function – complement to creatinine"],
            ["Free T4 (FT4 / T4L)",                 "Hypothyroidism management; levothyroxine titration"],
            ["HbA1c",                                "Diabetic control; wound healing correlation"],
            ["Wound Swab Culture & Sensitivity",     "Guide targeted antibiotic therapy"],
        ],
        col_widths=[2.8, 4.2],
    )
    story.append(Paragraph(
        "Clinical Notes: CKD Stage 3b (eGFR 32). Avoid iodinated contrast "
        "(allergy). Results to be reviewed at 2-week follow-up.", S['body']
    ))
    story.append(Spacer(1, 14))
    story.append(sig_block(DR, LIC, SPEC, DATE))

    # ── Page 5: Wound Care Order ──────────────────────────────────────────
    story.append(PageBreak())
    story.append(header_block(CLINIC, ADDR, PHONE, DATE, "WOUND CARE CLINIC ORDER"))
    story.append(Spacer(1, 8))
    story.append(Paragraph("SECTION 5 – WOUND CARE REFERRAL", S['h1']))
    story.append(patient_box({
        "Patient":             "Jacinta del Socorro Fuentes Ríos",
        "DOB":                 "March 14, 1941",
        "OHIP":                "3421-876-543 VU",
        "Referring Physician": DR,
        "Date":                DATE,
        "Priority":            "URGENT – start within 48 h",
    }))
    story.append(Spacer(1, 8))
    story += generic_order_table(
        "Wound Details",
        ["Parameter", "Detail"],
        [
            ["Location",  "Right LE – medial malleolar region"],
            ["Dimensions","4.0 × 3.5 cm; depth ~0.3 cm"],
            ["Wound Bed", "Sloughing tissue; moderate purulent exudate; malodorous"],
            ["Periwound", "Erythema 6 cm radius; induration; warmth; tenderness"],
            ["Duration",  "~10 weeks; infected × 2 weeks"],
            ["Etiology",  "Chronic venous insufficiency + bacterial superinfection"],
            ["Frequency", "3×/week (Mon / Wed / Fri)"],
        ],
        col_widths=[1.8, 5.2],
    )
    story.append(Paragraph("<b>Dressing Protocol:</b>", S['label']))
    for line in [
        "1. Cleanse with sterile normal saline at each visit.",
        "2. Debridement: sharp/autolytic as indicated.",
        "3. Apply non-adherent contact layer (e.g., Mepitel One).",
        "4. Moisture-retentive secondary dressing (e.g., Allevyn foam).",
        "5. 2-layer compression bandage if vascular assessment permits.",
        "6. Document dimensions, exudate, and progress at each visit.",
        "7. Notify physician if worsening infection, cellulitis extension, or systemic illness.",
    ]:
        story.append(Paragraph(line, S['body']))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "<b>Co-morbidities:</b> HTN, T2DM (insulin), CKD 3b, CHF, Hypothyroidism. "
        "Penicillin allergy. Currently on Clindamycin 300 mg q8h.", S['body']
    ))
    story.append(Spacer(1, 14))
    story.append(sig_block(DR, LIC, SPEC, DATE))

    doc.build(story)
    post_process_pdf(FNAME, FINAL)
    print("✔ Patient 1 – Jacinta del Socorro – DONE")


# ═══════════════════════════════════════════════════════════════════════════════
#  PATIENT 2 – MARIA GUADALUPE
#  Institution: Sample Lakeview General Hospital
# ═══════════════════════════════════════════════════════════════════════════════

def build_maria():
    pid    = 2
    I      = inst(pid)
    FNAME  = os.path.join(OUTPUT_DIR, "_tmp_02_Maria.pdf")
    FINAL  = os.path.join(OUTPUT_DIR, "02_Maria_Guadalupe_EMR.pdf")
    CLINIC = I["clinic_name"]
    ADDR   = I["address"]
    PHONE  = I["phone"]
    SPEC   = I["specialty"]
    DR     = "Dr. Sandra Villalobos Peña, MD"
    LIC    = "MED-ON-77231"
    DATE   = "February 12, 2026"
    DISCH  = "February 19, 2026"

    doc   = _default_doc(FNAME)
    story = []

    # ── CPP ───────────────────────────────────────────────────────────────
    story.append(header_block(CLINIC, ADDR, PHONE, DATE, "COMPLETE MEDICAL RECORD"))
    story.append(Spacer(1, 10))
    story.append(Paragraph("SECTION 1 – CUMULATIVE PATIENT PROFILE (CPP)", S['h1']))
    story.append(patient_box({
        "Full Name":          "Maria Guadalupe Torres Méndez",
        "Date of Birth":      "June 22, 1991  (Age: 34)",
        "Health Card (OHIP)": "5812-234-901 KM",
        "Sex / Gender":       "Female / Woman",
        "Address":            "77 Parliament Street Apt 3B, Toronto, ON M5A 2Y8",
        "Phone":              "(416) 555-0763",
        "Emergency Contact":  "Carlos Torres (brother) – (416) 555-0812",
        "Family Physician":   "Dr. Alejandro Martínez Roa (community)",
        "Pharmacy":           "Rexall – 100 Queen St E",
        "Language":           "Spanish / English",
    }))
    story += section("1.1 – Active Medical Problems", [
        "1. Urosepsis secondary to complicated UTI (E. coli ESBL-producing) – A41.51 | CURRENT.",
        "2. Acute Kidney Injury (AKI) on previously normal renal function – N17.9 | CURRENT.",
        "3. Metabolic acidosis with elevated lactate – E87.2 | CURRENT.",
        "4. Recurrent urinary tract infections (3 episodes in 18 months) – N39.0 | CHRONIC.",
    ])
    story += section("1.2 – Past Medical & Surgical History", [
        "2× prior UTIs in 2024 (treated with nitrofurantoin and ciprofloxacin).",
        "Appendectomy 2012, uncomplicated.",
        "No chronic conditions. No prior hospitalizations except appendectomy.",
    ])
    story += section("1.3 – Allergies", ["No known drug or food allergies (NKDA/NKFA)."])
    story += section("1.4 – Medications at Admission", [
        "Nitrofurantoin 100 mg BID (self-prescribed × 5 days) – DISCONTINUED on admission.",
        "Ibuprofen 400 mg PRN (last dose 48 h before admission).",
        "OCP: Desogestrel / Ethinyl Estradiol 0.15/0.03 mg – continued.",
    ])
    story += section("1.5 – Immunization History", [
        "COVID-19 series completed through 2024. Influenza: Oct 2025. HPV Gardasil-9: 2014 (3-dose). Hepatitis B: childhood.",
    ])
    story += section("1.6 – Family & Social History", [
        "<b>Family:</b> Mother (55, T2DM). Father (57, healthy). No FH renal disease.",
        "<b>Social:</b> Single. Bilingual admin assistant. Non-smoker. Social alcohol (occasional). No drugs. G0P0. Pap 2024 normal.",
    ])

    # ── Admission SOAP ────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(header_block(CLINIC, ADDR, PHONE, DATE, "EMERGENCY ADMISSION NOTE – SOAP"))
    story.append(Spacer(1, 8))
    story.append(Paragraph("SECTION 2 – EMERGENCY ADMISSION ENCOUNTER", S['h1']))
    story.append(patient_box({
        "Patient":        "Maria Guadalupe Torres Méndez",
        "DOB":            "June 22, 1991",
        "Admission Date": DATE,
        "Admission Time": "09:42 AM",
        "Admitting Unit": "IMCU – Bed 14B",
        "Attending":      DR,
    }))
    story += section("S – SUBJECTIVE", [
        '<b>Chief Complaint:</b> "I\'ve had burning urination for 5 days and now I feel like I\'m going to pass out – I have fever and chills."',
        "<b>HPI:</b> Ms. Torres is a 34-year-old previously healthy woman with a 5-day history of dysuria, frequency, and suprapubic pain. She self-prescribed nitrofurantoin 100 mg BID (leftover) without improvement. 24 hours prior to arrival she developed fever (peak 39.0 °C), rigors, drenching sweats, diffuse malaise, and right costovertebral angle pain. Minimal oral intake for 24 h. No vaginal symptoms, recent instrumentation, or travel.",
        "<b>ROS:</b> Constitutional: fever, chills, diaphoresis. GU: dysuria, frequency, flank pain, dark urine. No respiratory, cardiac, or neurological symptoms.",
    ])
    story += section("O – OBJECTIVE", [
        "<b>Vitals on Arrival:</b> BP 90/60 mmHg | HR 118 bpm (sinus tachycardia) | RR 22/min | SpO2 97% RA | T 39.2 °C | Wt 62 kg.",
        "<b>qSOFA:</b> 2.  <b>SOFA:</b> 4 (cardiovascular 2, renal 2).",
        "<b>General:</b> Ill-appearing, diaphoretic, shivering. Alert and oriented ×3.",
        "<b>Abdomen:</b> Mild suprapubic tenderness. Right CVA tenderness 2+.",
        "<b>Skin:</b> Warm, diaphoretic. No rash, no petechiae.",
        "<b>Neuro:</b> GCS 15. No focal deficits.",
    ])
    story += section("A – ASSESSMENT", [
        "1. <b>Urosepsis</b> – qSOFA 2, hemodynamic compromise, urinary source confirmed.",
        "2. <b>ESBL-producing E. coli</b> – resistant to penicillins/cephalosporins; nitrofurantoin failure (upper tract). Meropenem required.",
        "3. <b>Acute Kidney Injury</b> – Creatinine 3.0 mg/dL vs. estimated baseline <0.9. Pre-renal component from dehydration.",
        "4. <b>Metabolic acidosis with hyperlactatemia</b> – lactate >2 mmol/L; consistent with sepsis-induced hypoperfusion.",
    ])
    story += section("P – PLAN", [
        "1. Admit to IMCU – haemodynamic monitoring, 2 large-bore peripheral IVs.",
        "2. IV fluid resuscitation: NS 30 mL/kg bolus, then reassess.",
        "3. <b>Meropenem 1 g IV q8h</b> – empiric; targeted once sensitivities confirmed.",
        "4. Blood cultures ×2 (peripheral) prior to antibiotics.",
        "5. Urinary catheter – strict I/O.",
        "6. Acetaminophen 1 g IV q6h PRN for T >38.5 °C.",
        "7. Enoxaparin 40 mg SC daily for DVT prophylaxis once AKI resolves.",
        "8. Serial renal function q24–48 h.",
        "9. Repeat urine culture at 48 h to confirm sterilisation.",
        "10. Total 7-day IV antibiotic course; discharge when afebrile ×48 h.",
        "11. Follow-up with family physician within 7 days of discharge.",
    ])
    story.append(Spacer(1, 14))
    story.append(sig_block(DR, LIC, SPEC, DATE))

    # ── Lab Results – Admission ───────────────────────────────────────────
    story.append(PageBreak())
    story.append(header_block(CLINIC, ADDR, PHONE, DATE, "LABORATORY REPORT – ADMISSION"))
    story.append(Spacer(1, 8))
    story.append(Paragraph("SECTION 3A – ADMISSION LABORATORY RESULTS", S['h1']))
    story.append(patient_box({
        "Patient":         "Maria Guadalupe Torres Méndez",
        "DOB":             "June 22, 1991",
        "OHIP":            "5812-234-901 KM",
        "Collection Date": DATE,
        "Collection Time": "09:55 AM",
        "Lab #":           "LVH-2026-0212-4421",
    }))
    story.append(Spacer(1, 6))
    story += lab_table("Complete Blood Count (CBC)", [
        ["WBC",         "17.0 x10<super>9</super>/L",     "4.0 – 11.0",  "x10<super>9</super>/L",  "H"],
        ["Neutrophils", "13.9 x10<super>9</super>/L (82%)","1.8 – 7.7",  "x10<super>9</super>/L",  "H"],
        ["Lymphocytes", "2.1 x10<super>9</super>/L",      "1.0 – 4.8",  "x10<super>9</super>/L",  "N"],
        ["Monocytes",   "0.8 x10<super>9</super>/L",      "0.2 – 1.0",  "x10<super>9</super>/L",  "N"],
        ["Eosinophils", "0.1 x10<super>9</super>/L",      "0.0 – 0.5",  "x10<super>9</super>/L",  "N"],
        ["RBC",         "4.3 x10<super>12</super>/L",     "3.9 – 5.0",  "x10<super>12</super>/L", "N"],
        ["Hemoglobin",  "12.8 g/dL",      "12.0 – 16.0", "g/dL",   "N"],
        ["Hematocrit",  "38.0 %",         "37.0 – 47.0", "%",       "N"],
        ["MCV",         "88.3 fL",        "80.0 – 100.0","fL",      "N"],
        ["Platelets",   "214 x10<super>9</super>/L",      "150 – 400",  "x10<super>9</super>/L",  "N"],
    ])
    story += lab_table("Renal Function & Metabolic Panel", [
        ["Creatinine",      "3.0 mg/dL",        "0.5 – 1.1",  "mg/dL",  "CRIT"],
        ["BUN",             "48 mg/dL",          "7 – 25",     "mg/dL",  "H"],
        ["eGFR (CKD-EPI)",  "18 mL/min/1.73m2", "≥ 60",       "mL/min", "CRIT"],
        ["Sodium (Na)",     "136 mmol/L",        "136 – 145",  "mmol/L", "N"],
        ["Potassium (K)",   "4.2 mmol/L",        "3.5 – 5.1",  "mmol/L", "N"],
        ["Chloride",        "104 mmol/L",        "98 – 107",   "mmol/L", "N"],
        ["Bicarbonate HCO3","14 mmol/L",         "22 – 29",    "mmol/L", "L"],
        ["Glucose",         "5.8 mmol/L",        "3.9 – 11.0", "mmol/L", "N"],
        ["ALT",             "32 U/L",            "7 – 40",     "U/L",    "N"],
        ["AST",             "28 U/L",            "10 – 40",    "U/L",    "N"],
    ])
    story += lab_table("Arterial Blood Gas (ABG)", [
        ["pH",               "7.28",          "7.35 – 7.45", "",       "L"],
        ["pCO2",             "28 mmHg",       "35 – 45",     "mmHg",   "L"],
        ["pO2",              "88 mmHg",       "80 – 100",    "mmHg",   "N"],
        ["HCO3 (calculated)","13.2 mmol/L",   "22 – 26",     "mmol/L", "L"],
        ["Base Excess",      "-12.4 mmol/L",  "-2 – +2",     "mmol/L", "L"],
        ["Lactate",          "2.8 mmol/L",    "0.5 – 2.0",   "mmol/L", "H"],
        ["SpO2 (arterial)",  "97.1 %",        "95 – 100",    "%",      "N"],
    ])
    story += lab_table("Urinalysis (UA)", [
        ["Color",            "Dark yellow",     "Pale yellow",   "–",       "ABN"],
        ["Clarity",          "Turbid",          "Clear",         "–",       "ABN"],
        ["pH",               "6.0",             "4.5 – 8.0",     "–",       "N"],
        ["Specific Gravity", "1.028",           "1.005 – 1.030", "–",       "N"],
        ["Leukocytes (WBC)", ">500 cells/µL",   "<10",           "cells/µL","CRIT"],
        ["Nitrites",         "POSITIVE",        "Negative",      "–",       "ABN"],
        ["Bacteria",         "++++ (many)",     "None",          "–",       "ABN"],
        ["Epithelial cells", "None seen",       "<5/hpf",        "–",       "N"],
        ["Erythrocytes RBC", "0 – 1/hpf",       "0 – 3",         "/hpf",    "N"],
        ["Protein",          "Trace",           "Negative",      "mg/dL",   "ABN"],
        ["Glucose",          "Negative",        "Negative",      "–",       "N"],
    ])
    story.append(Paragraph("Urine Culture & Sensitivity – FINAL (Feb 12, 2026)", S['h2']))
    story.append(Paragraph(
        "<b>Organism:</b> Escherichia coli – Colony count: &gt;100,000 CFU/mL. "
        "<b>ESBL-producer confirmed.</b>", S['body']
    ))
    story += generic_order_table(
        "Antibiotic Susceptibility",
        ["Antibiotic", "MIC", "Interpretation"],
        [
            ["Meropenem",               "0.03 µg/mL", "SUSCEPTIBLE"],
            ["Ertapenem",               "0.06 µg/mL", "SUSCEPTIBLE"],
            ["Imipenem",                "0.12 µg/mL", "SUSCEPTIBLE"],
            ["Fosfomycin",              "16 µg/mL",   "SUSCEPTIBLE"],
            ["Amoxicillin",             ">16 µg/mL",  "RESISTANT (ESBL)"],
            ["Ampicillin-Sulbactam",    ">16 µg/mL",  "RESISTANT (ESBL)"],
            ["Cefazolin",               ">32 µg/mL",  "RESISTANT (ESBL)"],
            ["Ceftriaxone",             ">16 µg/mL",  "RESISTANT (ESBL)"],
            ["Piperacillin-Tazobactam", "16 µg/mL",   "RESISTANT (ESBL)"],
            ["Nitrofurantoin",          "128 µg/mL",  "RESISTANT"],
            ["TMP-SMX",                 ">32 µg/mL",  "RESISTANT"],
            ["Ciprofloxacin",           "4 µg/mL",    "INTERMEDIATE"],
        ],
        col_widths=[3.0, 1.5, 2.5],
        header_color=colors.HexColor('#660000'),
    )

    # ── Control Labs ──────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(header_block(CLINIC, ADDR, PHONE, "February 14, 2026", "LABORATORY REPORT – CONTROL (48 h)"))
    story.append(Spacer(1, 8))
    story.append(Paragraph("SECTION 3B – CONTROL LABORATORY RESULTS (48 h POST-ADMISSION)", S['h1']))
    story.append(patient_box({
        "Patient":         "Maria Guadalupe Torres Méndez",
        "DOB":             "June 22, 1991",
        "OHIP":            "5812-234-901 KM",
        "Collection Date": "February 14, 2026",
        "Collection Time": "08:15 AM",
        "Lab #":           "LVH-2026-0214-4899",
    }))
    story.append(Spacer(1, 6))
    story += lab_table("CBC – Control (48 h)", [
        ["WBC",        "7.2 x10<super>9</super>/L",      "4.0 – 11.0",  "x10<super>9</super>/L", "N"],
        ["Neutrophils","4.9 x10<super>9</super>/L (68%)", "1.8 – 7.7",  "x10<super>9</super>/L", "N"],
        ["Lymphocytes","1.8 x10<super>9</super>/L",      "1.0 – 4.8",  "x10<super>9</super>/L", "N"],
        ["Hemoglobin", "12.5 g/dL",       "12.0 – 16.0", "g/dL",   "N"],
        ["Hematocrit", "37.5 %",          "37.0 – 47.0", "%",       "N"],
        ["Platelets",  "228 x10<super>9</super>/L",      "150 – 400",  "x10<super>9</super>/L", "N"],
    ])
    story += lab_table("Renal Function – Control (48 h)", [
        ["Creatinine",    "1.0 mg/dL",        "0.5 – 1.1",  "mg/dL",  "N"],
        ["BUN",           "18 mg/dL",         "7 – 25",     "mg/dL",  "N"],
        ["eGFR",          "72 mL/min/1.73m2", "≥ 60",       "mL/min", "N"],
        ["Sodium (Na)",   "138 mmol/L",       "136 – 145",  "mmol/L", "N"],
        ["Potassium (K)", "3.9 mmol/L",       "3.5 – 5.1",  "mmol/L", "N"],
        ["HCO3",          "24 mmol/L",        "22 – 29",    "mmol/L", "N"],
    ])
    story += lab_table("Arterial Blood Gas – Control (48 h)", [
        ["pH",          "7.41",        "7.35 – 7.45", "",       "N"],
        ["pCO2",        "39 mmHg",     "35 – 45",     "mmHg",   "N"],
        ["pO2",         "91 mmHg",     "80 – 100",    "mmHg",   "N"],
        ["HCO3",        "24.5 mmol/L", "22 – 26",     "mmol/L", "N"],
        ["Base Excess", "+0.8 mmol/L", "-2 – +2",     "mmol/L", "N"],
        ["Lactate",     "1.2 mmol/L",  "0.5 – 2.0",   "mmol/L", "N"],
    ])
    story.append(Paragraph("<b>Urine Culture (Feb 14):</b> NO GROWTH at 48 h – microbiological clearance confirmed.", S['body']))
    story.append(Paragraph("<b>Blood Cultures ×2 (Feb 12):</b> NO GROWTH at 5 days – bacteraemia ruled out.", S['body']))

    # ── Epicrisis ─────────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(header_block(CLINIC, ADDR, PHONE, DISCH, "DISCHARGE SUMMARY (EPICRISIS)"))
    story.append(Spacer(1, 8))
    story.append(Paragraph("SECTION 4 – HOSPITAL DISCHARGE SUMMARY (EPICRISIS)", S['h1']))
    story.append(patient_box({
        "Patient":             "Maria Guadalupe Torres Méndez",
        "DOB":                 "June 22, 1991",
        "OHIP":                "5812-234-901 KM",
        "Admission Date":      "February 12, 2026 – 09:42",
        "Discharge Date":      "February 19, 2026 – 11:30",
        "Length of Stay":      "7 days",
        "Admitting Unit":      "ED → IMCU Bed 14B",
        "Attending Physician": DR,
        "Discharge Diagnosis": "Resolved urosepsis (E. coli ESBL) with AKI and metabolic acidosis",
        "Discharge Condition": "Good – stable, afebrile, tolerating oral intake",
    }))
    story += section("Reason for Admission", [
        "Ms. Torres was admitted through the ED on February 12, 2026 with a 5-day history of lower urinary tract symptoms "
        "unresponsive to self-prescribed nitrofurantoin, followed by fever (39.2 °C), rigors, diaphoresis, right flank pain, "
        "and haemodynamic instability (BP 90/60 mmHg, HR 118 bpm). Assessment confirmed urosepsis (qSOFA 2, SOFA 4) with "
        "concurrent AKI (Cr 3.0 mg/dL), hyperlactatemia (2.8 mmol/L), and metabolic acidosis (pH 7.28).",
    ])
    story += section("Hospital Course", [
        "<b>Day 1 (Feb 12):</b> IMCU admission. IV fluid resuscitation (NS 30 mL/kg). Urine and blood cultures collected. Empiric Meropenem 1 g IV q8h started within 1 h of sepsis identification. Foley catheter placed. Haemodynamics improved within 6 h.",
        "<b>Day 2 (Feb 14):</b> ESBL E. coli confirmed – Meropenem appropriate. Cr trending down (1.0 mg/dL). Blood cultures: no growth. Lactate normalised. ABG normalised (pH 7.41). Afebrile ×12 h. Oral fluids started.",
        "<b>Days 3–5 (Feb 15–17):</b> Progressive improvement. Full oral diet resumed. IV-to-oral analgesics. Urine output normalised. Vitals stable (BP 118/74, HR 82). Foley removed Day 4.",
        "<b>Days 6–7 (Feb 18–19):</b> Clinically well. Afebrile ×48 h. Full oral diet. Ambulating independently. 7-day Meropenem course completed. Discharge planned.",
    ])
    story += section("Discharge Medications", [
        "No new discharge prescriptions required.",
        "Nitrofurantoin: DISCONTINUED (ESBL resistant; inadequate for upper tract).",
        "OCP (Desogestrel/EE): CONTINUED.",
        "Acetaminophen 500 mg q6h PRN × 3 days.",
        "AVOID NSAIDs until renal function confirmed normal at follow-up.",
    ])
    story += section("Discharge Instructions", [
        "1. Rest for 2 days following discharge.",
        "2. Maintain adequate hydration (≥ 2 L water/day).",
        "3. Return to ED immediately if: fever >38.5 °C, rigors, flank pain, decreased urine output, or confusion.",
        "4. Avoid self-medication with antibiotics.",
        "5. Follow up with family physician within 7 days.",
        "6. Urological assessment recommended if recurrent UTI occurs (3rd episode in 18 months).",
    ])
    story += section("Medical Leave Certificate", [
        "Patient is granted medical leave for 2 (two) calendar days: February 19–20, 2026. "
        "Patient may return to regular occupational activities on February 21, 2026.",
    ])
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "<b>Follow-Up Order:</b> Control appointment with Family Physician within 7 days "
        "(on or before February 26, 2026).", S['body']
    ))
    story.append(Spacer(1, 14))
    story.append(sig_block(DR, LIC, SPEC, DISCH))

    doc.build(story)
    post_process_pdf(FNAME, FINAL)
    print("✔ Patient 2 – Maria Guadalupe – DONE")


# ═══════════════════════════════════════════════════════════════════════════════
#  PATIENT 3 – SALVADOR ANTONIO
#  Institution: Sample Northgate Family Health Team
# ═══════════════════════════════════════════════════════════════════════════════

def build_salvador():
    pid    = 3
    I      = inst(pid)
    FNAME  = os.path.join(OUTPUT_DIR, "_tmp_03_Salvador.pdf")
    FINAL  = os.path.join(OUTPUT_DIR, "03_Salvador_Antonio_EMR.pdf")
    CLINIC = I["clinic_name"]
    ADDR   = I["address"]
    PHONE  = I["phone"]
    SPEC   = I["specialty"]
    DR     = "Dr. Patricia Suárez Montoya, MD"
    LIC    = "MED-ON-91045"
    DATE   = "February 20, 2026"
    DATE_R = "February 24, 2026"

    doc   = _default_doc(FNAME)
    story = []

    story.append(header_block(CLINIC, ADDR, PHONE, DATE, "COMPLETE MEDICAL RECORD"))
    story.append(Spacer(1, 10))
    story.append(Paragraph("SECTION 1 – CUMULATIVE PATIENT PROFILE (CPP)", S['h1']))
    story.append(patient_box({
        "Full Name":          "Salvador Antonio Bermúdez Orozco",
        "Date of Birth":      "November 5, 1965  (Age: 60)",
        "Health Card (OHIP)": "7234-512-088 VR",
        "Sex / Gender":       "Male / Man",
        "Address":            "29 Sheppard Ave W Apt 5A, Toronto, ON M2N 1M2",
        "Phone":              "(416) 555-0184",
        "Emergency Contact":  "Elena Bermúdez (wife) – (416) 555-0185",
        "Family Physician":   DR,
        "Pharmacy":           "Costco Pharmacy – 1 Price Club Blvd",
        "Language":           "Spanish / English",
    }))
    story += section("1.1 – Active Medical Problems", [
        "1. COPD – J44.1 | NEW DIAGNOSIS (spirometry-confirmed).",
        "2. Secondary polycythemia (hypoxia-induced) – D75.1 | Hematocrit 70% (CRITICAL).",
        "3. Suspicious pulmonary nodule – RUL 13 mm – R91.1 | UNDER INVESTIGATION.",
        "4. Alcohol Use Disorder (AUD) – F10.20 | Chronic heavy use.",
        "5. Tobacco Use Disorder – F17.210 | Active smoker (5 cig/day; 25+ pack-years).",
        "6. Involuntary weight loss 10 kg / 3 months – R63.4 | Aetiology under investigation.",
        "7. Chronic cough – R05 | Likely COPD-related; malignancy to be excluded.",
    ])
    story += section("1.2 – Past Medical & Surgical History", [
        "No hospitalizations. No surgeries. No prior chronic disease diagnoses.",
        "Chronic snoring – possible obstructive sleep apnoea (evaluation pending).",
        "Occupational diesel fume exposure: 25 years (municipal bus driver, retired).",
    ])
    story += section("1.3 – Allergies", ["No known drug or food allergies (NKDA/NKFA)."])
    story += section("1.4 – Medications", [
        "Salbutamol MDI 100 mcg – 2 puffs q4-6h PRN (new today).",
        "Bupropion SR 150 mg – 1 tab daily × 7 days then BID (new today).",
    ])
    story += section("1.5 – Immunization History", [
        "Influenza Oct 2025. COVID-19 primary series; booster not current. "
        "Pneumococcal PCV15: ordered today. Td: 2011 – booster indicated.",
    ])
    story += section("1.6 – Family & Social History", [
        "<b>Family:</b> Father (†68, lung cancer – smoker). Mother (82, HTN).",
        "<b>Social:</b> Retired bus driver. Married. 2 adult children. Daily alcohol to intoxication "
        "(~6-8 standard drinks/day). Currently 5 cig/day (was 20/day × 25 yrs). No drugs. "
        "Minimal exercise due to dyspnoea.",
    ])

    story.append(PageBreak())
    story.append(header_block(CLINIC, ADDR, PHONE, DATE, "ENCOUNTER NOTE – SOAP"))
    story.append(Spacer(1, 8))
    story.append(Paragraph("SECTION 2 – ENCOUNTER NOTE", S['h1']))
    story.append(patient_box({
        "Patient":    "Salvador Antonio Bermúdez Orozco",
        "DOB":        "November 5, 1965",
        "Visit Date": DATE,
        "Visit Type": "New Patient + Acute Concerns",
        "Physician":  DR,
        "License":    LIC,
    }))
    story += section("S – SUBJECTIVE", [
        '<b>Chief Complaint:</b> "I\'ve lost a lot of weight and my cough has gotten much worse."',
        "<b>HPI:</b> Mr. Bermúdez is a 60-year-old man accompanied by his wife. He reports 10 kg unintentional weight loss over 3 months, worsening of a longstanding chronic cough, new exertional dyspnoea (MRC grade 3), and significant fatigue. History of heavy daily alcohol consumption and 25+ pack-year smoking history. Wife reports decade-long snoring with apnoeic episodes.",
        "<b>ROS:</b> Constitutional: 10 kg weight loss, malaise, reduced appetite. Respiratory: dyspnoea on exertion, productive cough (clear-to-yellow). No haemoptysis. Cardiovascular: no chest pain. Neuro: morning headaches (possible hypoxia). GI: heartburn.",
    ])
    story += section("O – OBJECTIVE", [
        "<b>Vitals:</b> BP 132/84 mmHg | HR 88 bpm | RR 20/min | <b>SpO2 89% RA (CRITICAL)</b> | T 36.8 °C | Wt 62 kg | Ht 170 cm | BMI 21.5 kg/m<super>2</super>.",
        "<b>General:</b> Thin, chronically ill-appearing. Mild lip cyanosis. Barrel chest.",
        "<b>Respiratory:</b> Hyperresonant percussion bilateral. Prolonged expiratory phase. Diffuse expiratory wheeze. Reduced breath sounds bases.",
        "<b>Abdomen:</b> Mild hepatomegaly (~2 cm below costal margin).",
        "<b>Extremities:</b> Mild bilateral digital clubbing. No peripheral oedema.",
    ])
    story += section("A – ASSESSMENT", [
        "1. <b>COPD – GOLD Stage III-IV suspected</b> – SpO2 89%, barrel chest, wheeze. Spirometry ordered urgently. Secondary polycythemia (Hct 70%) from chronic hypoxia.",
        "2. <b>Suspicious pulmonary nodule / probable lung malignancy</b> – 13 mm RUL nodule, irregular spiculated borders, ground-glass component; consuntive syndrome; 25+ pack-years; paternal lung cancer. High pre-test probability for primary lung malignancy.",
        "3. <b>Alcohol Use Disorder</b> – daily intoxication. LFTs elevated (ALT, AST, GGT). Bupropion initiated. Psychiatry referral placed.",
        "4. <b>Hypoxia-induced secondary polycythemia</b> – Hct 70%; hyperviscosity risk; supplemental O2 evaluation pending.",
    ])
    story += section("P – PLAN", [
        "1. CT Thorax with contrast (PRIORITY HIGH) – nodule characterisation / staging.",
        "2. Spirometry pre + post bronchodilator (PRIORITY HIGH).",
        "3. CBC, Creatinine, ABG, LFTs (PRIORITY HIGH).",
        "4. Salbutamol MDI 2 puffs q4-6h PRN – symptom relief.",
        "5. Bupropion SR 150 mg daily × 7 days then BID × 12 weeks – cessation support.",
        "6. Smoking cessation counselling + NRT information provided.",
        "7. Alcohol reduction: strong medical recommendation. Psychiatry referral placed. "
        "Advise: do NOT stop alcohol abruptly – withdrawal risk.",
        "8. Pneumococcal PCV15 administered today.",
        "9. Control appointment with all results.",
    ])
    story.append(Spacer(1, 14))
    story.append(sig_block(DR, LIC, SPEC, DATE))

    story.append(PageBreak())
    story.append(header_block(CLINIC, ADDR, PHONE, DATE, "DIAGNOSTIC EXTENSION ORDERS"))
    story.append(Spacer(1, 8))
    story.append(Paragraph("SECTION 3 – DIAGNOSTIC ORDERS", S['h1']))
    story.append(patient_box({
        "Patient":          "Salvador Antonio Bermúdez Orozco",
        "DOB":              "November 5, 1965",
        "OHIP":             "7234-512-088 VR",
        "Date":             DATE,
        "Priority":         "HIGH – results within 5 business days",
        "Clinical Summary": "Consuntive syndrome, COPD, suspicious pulmonary nodule",
    }))
    story.append(Spacer(1, 8))
    story += generic_order_table(
        "Tests Ordered",
        ["Test", "Priority", "Clinical Indication"],
        [
            ["CT Thorax with contrast",              "HIGH",    "Characterise 13 mm RUL nodule. Staging / malignancy workup."],
            ["Spirometry Pre + Post Bronchodilator", "HIGH",    "COPD diagnosis and GOLD staging. Administer salbutamol 400 mcg, repeat at 15 min."],
            ["CBC with differential",                "HIGH",    "Polycythaemia quantification, leucocytosis, baseline."],
            ["Serum Creatinine (Cr)",                "HIGH",    "Renal function baseline – prior to IV contrast."],
            ["Arterial Blood Gas (ABG) at rest",     "HIGH",    "Quantify hypoxia; respiratory failure; guide O2 therapy."],
            ["LFTs (ALT, AST, GGT, ALP, Bili)",     "ROUTINE", "Hepatic assessment – heavy daily alcohol use."],
        ],
        col_widths=[2.5, 0.9, 3.6],
    )
    story.append(Spacer(1, 14))
    story.append(sig_block(DR, LIC, SPEC, DATE))

    story.append(PageBreak())
    story.append(header_block(CLINIC, ADDR, PHONE, DATE, "PRESCRIPTION (Rx)"))
    story.append(Spacer(1, 8))
    story.append(Paragraph("SECTION 4 – PRESCRIPTION", S['h1']))
    story.append(patient_box({
        "Patient":  "Salvador Antonio Bermúdez Orozco",
        "DOB":      "November 5, 1965",
        "OHIP":     "7234-512-088 VR",
        "Date":     DATE,
        "Physician":DR,
        "License":  LIC,
    }))
    story.append(Spacer(1, 8))
    story += rx_table("New Prescriptions", [
        ["Salbutamol (Albuterol)", "100 mcg/actuation MDI",
         "2 puffs inhaled q4-6h PRN dyspnoea / wheeze",
         "1 inhaler", "Ongoing – reassess after spirometry"],
        ["Bupropion HCl (SR)", "150 mg tablet",
         "150 mg PO once daily × 7 days, then 150 mg PO twice daily",
         "60 tabs", "12 weeks (tobacco and alcohol cessation)"],
    ])
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "<b>Prescriber Note:</b> Bupropion contraindicated with history of seizures or eating disorders. "
        "Counsel patient: do NOT stop alcohol abruptly – risk of withdrawal seizures.", S['body']
    ))
    story.append(Spacer(1, 14))
    story.append(sig_block(DR, LIC, SPEC, DATE))

    story.append(PageBreak())
    story.append(header_block(CLINIC, ADDR, PHONE, DATE, "SPECIALIST REFERRAL – PSYCHIATRY"))
    story.append(Spacer(1, 8))
    story.append(Paragraph("SECTION 5 – REFERRAL TO ADDICTION PSYCHIATRY", S['h1']))
    story.append(patient_box({
        "Referring Physician": DR,
        "License":             LIC,
        "Date":                DATE,
        "Patient":             "Salvador Antonio Bermúdez Orozco",
        "DOB":                 "November 5, 1965",
        "OHIP":                "7234-512-088 VR",
        "Referred to":         "Addiction Psychiatry / Tobacco Cessation Unit",
        "Priority":            "URGENT – within 2 weeks",
    }))
    story.append(Spacer(1, 8))
    for para in [
        "Dear Colleague,",
        "I am referring Mr. Salvador Antonio Bermúdez Orozco, a 60-year-old male with the following urgent addictive behaviours requiring specialised psychiatric assessment:",
        "<b>1. Alcohol Use Disorder (AUD) – Heavy Pattern:</b> Daily consumption to intoxication (estimated 6-8 standard drinks/day, collateral from wife). Long-standing history. No prior treatment. Risk of withdrawal-related complications if cessation attempted without supervision.",
        "<b>2. Tobacco Use Disorder:</b> Active smoker, 5 cig/day (previously 20/day; 25+ pack-years). Multiple failed quit attempts. Highly ambivalent.",
        "<b>Clinical Context:</b> Newly identified 13 mm suspicious pulmonary nodule on CT Thorax (pending full staging), COPD GOLD Stage III, consuntive syndrome. Cessation of both substances is medically urgent.",
        "<b>Current Pharmacotherapy:</b> Bupropion SR 150 mg (cessation support). Please reassess, adjust, and complement with evidence-based CBT and NRT protocol.",
        "<b>Goals of Referral:</b> (1) Comprehensive addiction assessment; (2) Structured behavioural therapy; (3) Coordination with oncology/respirology once pulmonary workup is complete.",
        "Thank you for your valued involvement in this patient's care.",
    ]:
        story.append(Paragraph(para, S['body']))
    story.append(Spacer(1, 14))
    story.append(sig_block(DR, LIC, SPEC, DATE))

    story.append(PageBreak())
    story.append(header_block(CLINIC, ADDR, PHONE, DATE_R, "DIAGNOSTIC RESULTS REPORT"))
    story.append(Spacer(1, 8))
    story.append(Paragraph("SECTION 6 – DIAGNOSTIC TEST RESULTS", S['h1']))
    story.append(patient_box({
        "Patient":       "Salvador Antonio Bermúdez Orozco",
        "DOB":           "November 5, 1965",
        "OHIP":          "7234-512-088 VR",
        "Results Date":  DATE_R,
        "Lab #":         "NGT-2026-0224-3301",
        "Requesting MD": DR,
    }))
    story.append(Spacer(1, 6))
    story += lab_table("CBC – Results", [
        ["WBC",        "9.2 x10<super>9</super>/L",   "4.0 – 11.0",   "x10<super>9</super>/L",  "N"],
        ["RBC",        "6.9 x10<super>12</super>/L",  "4.2 – 5.8",    "x10<super>12</super>/L", "H"],
        ["Hemoglobin", "21.8 g/dL",    "13.5 – 17.5",  "g/dL",    "CRIT"],
        ["Hematocrit", "70.0 %",       "39.0 – 51.0",  "%",        "CRIT"],
        ["MCV",        "88.0 fL",      "80.0 – 100.0", "fL",       "N"],
        ["Platelets",  "245 x10<super>9</super>/L",   "150 – 400",    "x10<super>9</super>/L",  "N"],
    ])
    story += lab_table("Chemistry & Liver Function", [
        ["Creatinine",      "0.92 mg/dL", "0.7 – 1.3", "mg/dL", "N"],
        ["BUN",             "16 mg/dL",   "7 – 25",    "mg/dL", "N"],
        ["ALT",             "88 U/L",     "7 – 40",    "U/L",   "H"],
        ["AST",             "104 U/L",    "10 – 40",   "U/L",   "H"],
        ["GGT",             "312 U/L",    "9 – 48",    "U/L",   "H"],
        ["ALP",             "112 U/L",    "44 – 147",  "U/L",   "N"],
        ["Total Bilirubin", "1.2 mg/dL",  "0.2 – 1.2", "mg/dL", "N"],
    ])
    story += lab_table("Arterial Blood Gas (ABG) at Rest", [
        ["pH",             "7.38",        "7.35 – 7.45", "",       "N"],
        ["pCO2",           "48 mmHg",     "35 – 45",     "mmHg",   "H"],
        ["pO2",            "30 mmHg",     "80 – 100",    "mmHg",   "CRIT"],
        ["HCO3",           "28 mmol/L",   "22 – 26",     "mmol/L", "H"],
        ["Base Excess",    "+4.1 mmol/L", "-2 – +2",     "mmol/L", "H"],
        ["Lactate",        "1.6 mmol/L",  "0.5 – 2.0",   "mmol/L", "N"],
        ["SpO2 (arterial)","74 %",        "95 – 100",    "%",      "CRIT"],
    ])
    story += generic_order_table(
        "Spirometry – Pre and Post Bronchodilator",
        ["Parameter", "Pre-BD", "Post-BD", "Predicted/Ref", "Interpretation"],
        [
            ["FVC",               "2.8 L", "2.9 L", "4.2 L (67%)", "Reduced"],
            ["FEV1",              "1.4 L", "1.5 L", "3.3 L (45%)", "Severely reduced"],
            ["FEV1/FVC Ratio",    "50%",   "60%",   ">70%",         "OBSTRUCTIVE"],
            ["FEV1 % Change (BD)","7.1%",  "–",     "<12%",         "Not reversible"],
            ["TLC (estimated)",   "Elevated","–",   "Normal",       "Air trapping"],
        ],
        col_widths=[1.8, 0.9, 0.9, 1.5, 1.9],
    )
    story.append(Paragraph(
        "<b>Spirometry Interpretation:</b> Moderate-to-severe obstructive ventilatory defect. "
        "FEV1/FVC 60% post-BD. FEV1 45% predicted – consistent with COPD GOLD Stage III. Non-reversible obstruction.", S['body']
    ))
    story.append(Spacer(1, 8))
    story += section("CT THORAX WITH CONTRAST – IMAGING REPORT", [
        f"<b>Facility:</b> {I['name']} Radiology | Report #: RAD-2026-0224-1188",
        "<b>Radiologist:</b> Dr. Kamila Nowak, MD FRCPC – Thoracic Radiology",
    ])
    for para in [
        "<b>TECHNIQUE:</b> Multidetector CT thorax with IV contrast. Helical acquisition 1.25 mm reconstructions. Lung, mediastinal and soft-tissue windows reviewed.",
        "<b>DOMINANT FINDING (Right Upper Lobe Nodule):</b> 13 × 11 mm subsolid pulmonary nodule in the posterior segment of the right upper lobe. Irregular, spiculated margins with a ground-glass attenuation component (part-solid pattern). No calcification. Fleischner Society Category C: follow-up CT at 3–6 months AND MDT review recommended; PET-CT and tissue biopsy to be considered.",
        "<b>BILATERAL LUNG FIELDS:</b> Hyperinflation. Flattening of hemidiaphragms bilaterally. Increased AP diameter. Diffuse air trapping. Mild bullous changes both upper lobes. No additional masses. No pneumothorax. No pleural effusion.",
        "<b>MEDIASTINUM:</b> No mediastinal or hilar lymphadenopathy. No mediastinal masses. Heart size upper limits of normal. No pericardial effusion.",
        "<b>UPPER ABDOMEN (included):</b> Mild hepatomegaly. Liver parenchyma homogeneous. No focal hepatic lesions. No adrenal abnormality.",
        "<b>IMPRESSION:</b><br/>1. 13 mm subsolid RUL nodule – HIGH SUSPICION for malignancy. Urgent PET-CT and thoracic oncology MDT referral recommended.<br/>2. Severe bilateral COPD pattern – hyperinflation, air trapping, bullous emphysema.<br/>3. Mild hepatomegaly – clinical correlation required.",
        f"<b>URGENT COMMUNICATION:</b> Report communicated to Dr. P. Suárez Montoya by telephone on February 24, 2026 at 14:30.",
    ]:
        story.append(Paragraph(para, S['body']))
    story.append(Spacer(1, 14))
    story.append(sig_block(DR, LIC, SPEC, DATE_R))

    doc.build(story)
    post_process_pdf(FNAME, FINAL)
    print("✔ Patient 3 – Salvador Antonio – DONE")


# ═══════════════════════════════════════════════════════════════════════════════
#  PATIENT 4 – ARMANDO CASAS
#  Institution: Sample Maplewood Community Health Centre (shared with P1)
# ═══════════════════════════════════════════════════════════════════════════════

def build_armando():
    pid    = 4
    I      = inst(pid)
    FNAME  = os.path.join(OUTPUT_DIR, "_tmp_04_Armando.pdf")
    FINAL  = os.path.join(OUTPUT_DIR, "04_Armando_Casas_EMR.pdf")
    CLINIC = I["clinic_name"]
    ADDR   = I["address"]
    PHONE  = I["phone"]
    SPEC   = I["specialty"]
    DR     = "Dr. Alejandro Martínez Roa, MD"
    LIC    = "MED-ON-88742"
    DATE   = "February 21, 2026"

    doc   = _default_doc(FNAME)
    story = []

    story.append(header_block(CLINIC, ADDR, PHONE, DATE, "COMPLETE MEDICAL RECORD"))
    story.append(Spacer(1, 10))
    story.append(Paragraph("SECTION 1 – CUMULATIVE PATIENT PROFILE (CPP)", S['h1']))
    story.append(patient_box({
        "Full Name":          "Armando Casas Velázquez",
        "Date of Birth":      "January 30, 2001  (Age: 25)",
        "Health Card (OHIP)": "9012-345-678 JK",
        "Sex / Gender":       "Male / Man",
        "Address":            "311 College St Apt 6, Toronto, ON M5T 1S2",
        "Phone":              "(416) 555-0641",
        "Emergency Contact":  "Jorge Casas (father) – (416) 555-0642",
        "Family Physician":   DR,
        "Pharmacy":           "Rexall – 302 College St",
        "Language":           "Spanish / English",
    }))
    story += section("1.1 – Active Medical Problems", [
        "1. Acute right ankle injury – probable fracture vs. Grade III lateral ligament sprain – S93.40 | CURRENT. Under evaluation.",
    ])
    story += section("1.2 – Past Medical & Surgical History", [
        "Left knee sprain 2019 – conservatively managed, full recovery. No chronic illnesses. No surgeries.",
    ])
    story += section("1.3 – Allergies", ["No known drug or food allergies (NKDA/NKFA)."])
    story += section("1.4 – Medications", [
        "Acetaminophen 500 mg OTC (2 tabs per dose ~q6h since injury) – inadequate pain control.",
    ])
    story += section("1.5 – Immunization History", [
        "Childhood vaccination series: complete. COVID-19 primary series 2021. Influenza: not received this season.",
    ])
    story += section("1.6 – Family & Social History", [
        "<b>Family:</b> Father (52, mild HTN). Mother (49, healthy). No relevant FH.",
        "<b>Social:</b> Single. University student (Engineering, Year 4). Amateur soccer player. Non-smoker. Social alcohol (weekends, moderate). No drugs. Active – gym 3×/week.",
    ])

    story.append(PageBreak())
    story.append(header_block(CLINIC, ADDR, PHONE, DATE, "ENCOUNTER NOTE – SOAP"))
    story.append(Spacer(1, 8))
    story.append(Paragraph("SECTION 2 – ENCOUNTER NOTE", S['h1']))
    story.append(patient_box({
        "Patient":    "Armando Casas Velázquez",
        "DOB":        "January 30, 2001",
        "Visit Date": DATE,
        "Visit Type": "Urgent/Acute – Musculoskeletal Injury",
        "Physician":  DR,
        "License":    LIC,
    }))
    story += section("S – SUBJECTIVE", [
        '<b>Chief Complaint:</b> "I twisted my ankle playing soccer yesterday and I can\'t walk on it."',
        "<b>HPI:</b> Mr. Casas is a 25-year-old man presenting with a right ankle injury sustained ~18 hours ago during recreational soccer. Inversion mechanism – stepped on another player's foot (forced plantar flexion + inversion). Immediate severe pain (8/10 VAS), inability to bear weight from moment of injury, rapid progressive oedema, significant periarticular bruising (lateral ankle), marked instability sensation. Acetaminophen 1000 mg q6h with minimal relief. Non-ambulatory.",
    ])
    story += section("O – OBJECTIVE", [
        "<b>Vitals:</b> BP 122/78 mmHg | HR 80 bpm | SpO2 99% RA | T 36.6 °C | Wt 78 kg | Ht 178 cm | BMI 24.6 kg/m<super>2</super>.",
        "<b>Right Ankle:</b> Marked diffuse oedema. Extensive perimalleolar ecchymosis (lateral > medial). Significant tenderness: ATFL, CFL, lateral malleolus tip, base of 5th metatarsal. Ottawa Rules POSITIVE (bony tenderness at lateral malleolus tip + inability to bear weight ×4 steps). Neurovascular: dorsalis pedis pulse 2+, capillary refill <2 s, sensation intact.",
        "<b>Knee / Hip:</b> No tenderness, no effusion. Full ROM.",
    ])
    story += section("A – ASSESSMENT", [
        "1. <b>Acute right ankle injury – Ottawa Rules positive</b> – must rule out fracture (lateral malleolus, talus, 5th metatarsal base).",
        "2. Inadequate analgesia with acetaminophen. NSAID therapy appropriate – no contraindications.",
    ])
    story += section("P – PLAN", [
        "1. X-ray right ankle (AP/Lateral/Mortise) + right foot (AP/Lateral/Oblique) – URGENT.",
        "2. Ibuprofen 400 mg PO q8h with food – maximum 7 days.",
        "3. Discontinue acetaminophen while on ibuprofen.",
        "4. RICE: Rest, Ice, Compression (elastic bandage), Elevation above heart.",
        "5. Non-weight bearing on right foot until X-ray results and reassessment.",
        "6. Follow-up with X-ray results – same or next business day.",
        "7. Attend ED if: increased pain despite analgesia, numbness/tingling, skin colour changes, rapidly worsening swelling.",
        "8. Crutches provided. Instructions given.",
    ])
    story.append(Spacer(1, 14))
    story.append(sig_block(DR, LIC, SPEC, DATE))

    story.append(PageBreak())
    story.append(header_block(CLINIC, ADDR, PHONE, DATE, "DIAGNOSTIC IMAGING ORDER"))
    story.append(Spacer(1, 8))
    story.append(Paragraph("SECTION 3 – IMAGING REQUISITION", S['h1']))
    story.append(patient_box({
        "Patient":             "Armando Casas Velázquez",
        "DOB":                 "January 30, 2001",
        "OHIP":                "9012-345-678 JK",
        "Date":                DATE,
        "Priority":            "URGENT – same day / within 24 h",
        "Referring Physician": DR,
    }))
    story.append(Spacer(1, 8))
    story += generic_order_table(
        "Imaging Orders",
        ["Study", "Priority", "Clinical Indication"],
        [
            ["X-ray Right Ankle (3 views: AP / Lateral / Mortise)", "URGENT",
             "Acute traumatic ankle injury – inversion mechanism. Ottawa Rules positive. Rule out lateral malleolus fracture, talus fracture, tibial plafond injury."],
            ["X-ray Right Foot (3 views: AP / Lateral / Oblique)", "URGENT",
             "Rule out fracture base of 5th metatarsal (Jones fracture / avulsion). Bony tenderness on exam."],
        ],
        col_widths=[2.0, 0.9, 4.1],
    )
    story.append(Spacer(1, 14))
    story.append(sig_block(DR, LIC, SPEC, DATE))

    story.append(PageBreak())
    story.append(header_block(CLINIC, ADDR, PHONE, DATE, "PRESCRIPTION (Rx)"))
    story.append(Spacer(1, 8))
    story.append(Paragraph("SECTION 4 – MEDICATION PRESCRIPTION", S['h1']))
    story.append(patient_box({
        "Patient":  "Armando Casas Velázquez", "DOB":      "January 30, 2001",
        "OHIP":     "9012-345-678 JK",         "Date":     DATE,
        "Physician":DR,                         "License":  LIC,
    }))
    story.append(Spacer(1, 8))
    story += rx_table("Prescription", [
        ["Ibuprofen", "400 mg tablet", "400 mg PO every 8 h with food or milk", "21 tabs", "7 days maximum"],
    ])
    story.append(Paragraph(
        "<b>Instructions:</b> Take with food. Do not exceed 1200 mg/day. "
        "Stop and call clinic if: stomach pain, black stools, or allergic reaction. "
        "Do not combine with other NSAIDs.", S['body']
    ))
    story.append(Spacer(1, 14))
    story.append(sig_block(DR, LIC, SPEC, DATE))

    story.append(PageBreak())
    story.append(header_block(CLINIC, ADDR, PHONE, DATE, "FOLLOW-UP APPOINTMENT ORDER"))
    story.append(Spacer(1, 8))
    story.append(Paragraph("SECTION 5 – FOLLOW-UP WITH X-RAY RESULTS", S['h1']))
    story.append(patient_box({
        "Patient":           "Armando Casas Velázquez",
        "DOB":               "January 30, 2001",
        "OHIP":              "9012-345-678 JK",
        "Ordering Physician":DR,
        "Appointment Type":  "Follow-up with X-ray results in hand",
        "Timeframe":         "Same day or next business day after imaging",
    }))
    story.append(Spacer(1, 8))
    story.append(Paragraph("<b>Instructions for Patient:</b>", S['label']))
    for line in [
        "1. Proceed to radiology with this imaging requisition TODAY.",
        "2. Request report sent electronically to Dr. Martínez Roa.",
        "3. Contact clinic as soon as you have the report to schedule follow-up.",
        "4. If fracture is confirmed, you will be referred to Orthopedic Trauma Clinic.",
        "5. Continue RICE and non-weight bearing until reassessment.",
        "<b>RED FLAGS – Attend Emergency Department IMMEDIATELY if:</b>",
        "– Oedema increases dramatically after first 24 h.",
        "– Numbness, tingling, or sensory loss in foot or toes.",
        "– Skin becomes cold, pale, or discoloured.",
        "– Inability to move toes.",
        "– Pain becomes uncontrollable despite medications.",
    ]:
        story.append(Paragraph(line, S['body']))
    story.append(Spacer(1, 14))
    story.append(sig_block(DR, LIC, SPEC, DATE))

    doc.build(story)
    post_process_pdf(FNAME, FINAL)
    print("✔ Patient 4 – Armando Casas – DONE")


# ═══════════════════════════════════════════════════════════════════════════════
#  PATIENT 5 – JOSÉ ENCARNACIÓN
#  Institution: Sample Bayview Heart & Vascular Institute
# ═══════════════════════════════════════════════════════════════════════════════

def build_jose():
    pid    = 5
    I      = inst(pid)
    FNAME  = os.path.join(OUTPUT_DIR, "_tmp_05_Jose.pdf")
    FINAL  = os.path.join(OUTPUT_DIR, "05_Jose_Encarnacion_EMR.pdf")
    CLINIC = I["clinic_name"]
    ADDR   = I["address"]
    PHONE  = I["phone"]
    SPEC   = I["specialty"]
    DR     = "Dr. Felipe Andrade Restrepo, MD FRCPC"
    LIC    = "MED-ON-65321"
    DATE   = "February 23, 2026"

    doc   = _default_doc(FNAME)
    story = []

    story.append(header_block(CLINIC, ADDR, PHONE, DATE, "COMPLETE MEDICAL RECORD"))
    story.append(Spacer(1, 10))
    story.append(Paragraph("SECTION 1 – CUMULATIVE PATIENT PROFILE (CPP)", S['h1']))
    story.append(patient_box({
        "Full Name":          "José Encarnación Ríos Delgado",
        "Date of Birth":      "August 18, 1958  (Age: 67)",
        "Health Card (OHIP)": "6183-029-441 PQ",
        "Sex / Gender":       "Male / Man",
        "Address":            "81 Bayview Ridge, Toronto, ON M2L 1A4",
        "Phone":              "(416) 555-0902",
        "Emergency Contact":  "Lucía Delgado (wife) – (416) 555-0903",
        "Family Physician":   DR,
        "Pharmacy":           "Shoppers Drug Mart – 2090 Bayview Ave",
        "Language":           "Spanish / English",
    }))
    story += section("1.1 – Active Medical Problems", [
        "1. Non-valvular Atrial Fibrillation – I48.91 | Dx 2021 | CHA2DS2-VASc 5 – HIGH RISK | Warfarin (INR target 2.0-3.0).",
        "2. Ischemic cardiomyopathy post-NSTEMI 2020, mildly reduced EF (42%) – I25.10.",
        "3. Essential Hypertension – I10 | Dx 2012 | Triple therapy.",
        "4. Prior TIA 2022 – fully resolved. No residual deficits. Precipitated warfarin initiation.",
        "5. Type 2 Diabetes Mellitus – E11.9 | Dx 2016 | Oral agents.",
        "6. Dyslipidaemia – E78.5 | Dx 2015.",
        "7. Peripheral Arterial Disease, right LE, claudication at 150 m – I70.212 | Dx 2023.",
    ])
    story += section("1.2 – Past Medical & Surgical History", [
        "2020: NSTEMI – PCI with DES to LAD. DAPT completed (12-month course).",
        "2022: TIA (right hemispheric, 15 min, fully resolved). MRI brain: no infarct. Warfarin started.",
        "2023: PAD diagnosis (ABI 0.72 right).",
        "2024: Colonoscopy – 2 small tubular adenomas removed; repeat colonoscopy due 2027.",
    ])
    story += section("1.3 – Allergies", [
        "Aspirin – GI intolerance at full dose; low-dose 81 mg tolerated with PPI.",
        "Sulfa drugs (TMP-SMX) – rash. Avoid.",
    ])
    story += section("1.4 – Current Medications", [])
    story += rx_table("Current Medication List", [
        ["Warfarin Sodium",     "5 mg tablet",      "5 mg PO daily at 18:00 (dose per INR)",  "30 tabs", "Indefinite – AF"],
        ["Metoprolol Succinate","100 mg ER tablet", "100 mg PO once daily",                   "30 tabs", "Ongoing"],
        ["Ramipril",            "10 mg capsule",    "10 mg PO once daily",                    "30 caps", "Ongoing"],
        ["Amlodipine",          "10 mg tablet",     "10 mg PO once daily",                    "30 tabs", "Ongoing"],
        ["Rosuvastatin",        "40 mg tablet",     "40 mg PO at bedtime",                    "30 tabs", "Ongoing"],
        ["Metformin",           "1000 mg tablet",   "1000 mg PO twice daily with meals",      "60 tabs", "Ongoing"],
        ["Pantoprazole",        "40 mg tablet",     "40 mg PO once daily (fasting)",          "30 tabs", "Ongoing"],
        ["Aspirin low-dose",    "81 mg tablet",     "81 mg PO once daily",                    "30 tabs", "Ongoing"],
        ["Cilostazol",          "100 mg tablet",    "100 mg PO twice daily (PAD)",            "60 tabs", "Ongoing"],
    ])
    story += section("1.5 – Immunization History", [
        "Influenza Oct 2025. Pneumococcal PCV15: 2023. COVID-19 boosters through 2024. Shingrix: 2023 (2-dose). Td: 2019.",
    ])
    story += section("1.6 – Family & Social History", [
        "<b>Family:</b> Father (†70, stroke + AF). Mother (†74, MI). Brother (65, AF + HTN).",
        "<b>Social:</b> Retired mechanical engineer. Married 40 yrs. Non-smoker (ex-smoker 30 pack-years, quit 2012). Rare social alcohol (1-2 drinks/week). Mediterranean diet – consistent green leafy vegetable intake (important for warfarin stability). Walking 30 min/day (limited by claudication). Cardiac rehab completed 2021.",
    ])

    story.append(PageBreak())
    story.append(header_block(CLINIC, ADDR, PHONE, DATE, "ENCOUNTER NOTE – SOAP"))
    story.append(Spacer(1, 8))
    story.append(Paragraph("SECTION 2 – ENCOUNTER NOTE (ANTICOAGULATION CLINIC)", S['h1']))
    story.append(patient_box({
        "Patient":    "José Encarnación Ríos Delgado",
        "DOB":        "August 18, 1958",
        "Visit Date": DATE,
        "Visit Type": "Scheduled – Anticoagulation + Cardiology Review",
        "Physician":  DR,
        "License":    LIC,
    }))
    story += section("S – SUBJECTIVE", [
        '<b>Chief Complaint:</b> "I\'ve been getting more short of breath climbing stairs and my legs feel heavy."',
        "<b>HPI:</b> Mr. Ríos Delgado is a 67-year-old with known non-valvular AF, ischemic cardiomyopathy (EF 42%), prior TIA, and multiple cardiovascular risk factors presenting for scheduled quarterly anticoagulation review. He reports progressive exertional dyspnoea over 4-6 weeks (perceived NYHA Class III – cannot climb 2 flights without stopping; previously Class II), bilateral lower extremity heaviness and evening ankle swelling, and 2.1 kg weight gain over 4 weeks. No chest pain, palpitations, presyncope, or bleeding.",
        "<b>ROS:</b> CVS: exertional dyspnoea (worsening), bilateral ankle oedema (new). Neuro: no new neurological symptoms. GI: no bleeding. MSK: right calf claudication ~150 m (was 200 m).",
    ])
    story += section("O – OBJECTIVE", [
        "<b>Vitals:</b> BP 138/86 mmHg | HR 78 bpm (irregular) | RR 16/min | SpO2 95% RA | T 36.7 °C | Wt 84.3 kg (+2.1 kg in 4 weeks) | BMI 28.5 kg/m<super>2</super>.",
        "<b>CVS:</b> Irregular rhythm (AF). S3 gallop audible at apex. JVP 6 cm above sternal angle. No murmurs.",
        "<b>Respiratory:</b> Bibasilar fine crackles. No wheeze.",
        "<b>Abdomen:</b> Mild hepatomegaly ~1.5 cm. No ascites.",
        "<b>Lower Extremities:</b> 2+ bilateral pitting oedema to mid-calf.",
        "<b>Neuro:</b> GCS 15. No focal deficits.",
    ])
    story += section("A – ASSESSMENT", [
        "1. <b>Decompensated CHF (HFmrEF, EF 42%)</b> – S3, elevated JVP, crackles, oedema, 2.1 kg weight gain. Likely AF tachycardia-related + ischaemic progression. Echocardiogram ordered.",
        "2. <b>AF – rate controlled, ongoing anticoagulation</b> – INR 2.6 (last check 4 weeks ago) – therapeutic. CHA2DS2-VASc 5 – indefinite anticoagulation. Warfarin continued.",
        "3. <b>HTN – slightly above target</b> – likely CHF-related. Monitor post-diuretic adjustment.",
        "4. <b>PAD – progressive</b> – claudication worsening (200 → 150 m). Vascular surgery referral to be placed.",
        "5. <b>T2DM – stable</b>. HbA1c ordered.",
    ])
    story += section("P – PLAN", [
        "1. Furosemide: increase 40 → 80 mg PO daily × 5 days, then reassess weight.",
        "2. Daily weight monitoring: call clinic if weight increases >2 kg in 2 days.",
        "3. INR today (see labs). Warfarin 5 mg maintained if INR 2.0-3.0.",
        "4. Echocardiogram – PRIORITY within 7 days.",
        "5. 24-hour Holter monitor – routine within 2 weeks.",
        "6. Labs: INR, HbA1c, CBC, BMP (Cr + electrolytes – diuretic dose increase).",
        "7. Warfarin counselling: INR schedule, dietary vitamin K consistency, drug interactions, bleeding signs.",
        "8. Sodium restriction: <2 g/day.",
        "9. Return in 1 week (or sooner if worsening).",
    ])
    story.append(Spacer(1, 14))
    story.append(sig_block(DR, LIC, SPEC, DATE))

    story.append(PageBreak())
    story.append(header_block(CLINIC, ADDR, PHONE, DATE, "LABORATORY & SPECIAL TEST ORDERS"))
    story.append(Spacer(1, 8))
    story.append(Paragraph("SECTION 3 – LABORATORY AND SPECIAL TEST ORDERS", S['h1']))
    story.append(patient_box({
        "Patient":   "José Encarnación Ríos Delgado",
        "DOB":       "August 18, 1958",
        "OHIP":      "6183-029-441 PQ",
        "Date":      DATE,
        "Priority":  "Labs today; imaging within 7 days",
        "Physician": DR,
    }))
    story.append(Spacer(1, 8))
    story += generic_order_table(
        "Tests Ordered",
        ["Test", "Priority", "Clinical Indication", "Type"],
        [
            ["INR",                              "URGENT – today",          "Warfarin monitoring. Target 2.0-3.0. CHF may alter levels.",              "Lab"],
            ["HbA1c",                            "ROUTINE",                  "Quarterly T2DM monitoring.",                                              "Lab"],
            ["CBC with differential",            "ROUTINE",                  "Anaemia screening; thrombocytopaenia monitoring (warfarin).",              "Lab"],
            ["BMP: Cr, BUN, Na, K, HCO3",        "ROUTINE",                  "Monitor for hypokalaemia + renal function with furosemide dose increase.", "Lab"],
            ["Transthoracic Echocardiogram (TTE)","PRIORITY within 7 days",  "Reassess EF, diastolic function, valvular disease. CHF workup.",          "Imaging"],
            ["24-h Holter Monitor",               "ROUTINE within 2 weeks",  "AF burden; rate control adequacy (target HR <80 bpm at rest).",            "Special"],
        ],
        col_widths=[1.9, 1.1, 2.9, 1.1],
    )
    story.append(Spacer(1, 14))
    story.append(sig_block(DR, LIC, SPEC, DATE))

    story.append(PageBreak())
    story.append(header_block(CLINIC, ADDR, PHONE, DATE, "LABORATORY RESULTS REPORT"))
    story.append(Spacer(1, 8))
    story.append(Paragraph("SECTION 4 – LABORATORY RESULTS", S['h1']))
    story.append(patient_box({
        "Patient":         "José Encarnación Ríos Delgado",
        "DOB":             "August 18, 1958",
        "OHIP":            "6183-029-441 PQ",
        "Collection Date": DATE,
        "Collection Time": "10:20 AM",
        "Lab #":           "BVI-2026-0223-7821",
    }))
    story.append(Spacer(1, 6))
    story += lab_table("Anticoagulation Panel", [
        ["INR",  "2.6",    "2.0 – 3.0 (AF target)", "–",   "N"],
        ["PT",   "29.4 s", "11.0 – 14.0",           "sec", "H"],
        ["aPTT", "34.2 s", "25.0 – 37.0",           "sec", "N"],
    ])
    story += lab_table("Complete Blood Count (CBC)", [
        ["WBC",        "8.1 x10<super>9</super>/L",   "4.0 – 11.0",  "x10<super>9</super>/L",  "N"],
        ["RBC",        "4.4 x10<super>12</super>/L",  "4.2 – 5.8",   "x10<super>12</super>/L", "N"],
        ["Hemoglobin", "13.2 g/dL",    "13.5 – 17.5", "g/dL",   "L"],
        ["Hematocrit", "40.0 %",       "39.0 – 51.0", "%",       "N"],
        ["MCV",        "88.2 fL",      "80.0 – 100.0","fL",      "N"],
        ["Platelets",  "198 x10<super>9</super>/L",   "150 – 400",   "x10<super>9</super>/L",  "N"],
        ["Neutrophils","5.9 x10<super>9</super>/L",   "1.8 – 7.7",   "x10<super>9</super>/L",  "N"],
    ])
    story += lab_table("Metabolic Panel & Renal Function", [
        ["Creatinine",     "1.18 mg/dL",      "0.7 – 1.3",  "mg/dL",  "N"],
        ["BUN",            "22 mg/dL",        "7 – 25",     "mg/dL",  "N"],
        ["eGFR (CKD-EPI)", "62 mL/min/1.73m2","≥ 60",       "mL/min", "N"],
        ["Sodium (Na)",    "140 mmol/L",      "136 – 145",  "mmol/L", "N"],
        ["Potassium (K)",  "4.0 mmol/L",      "3.5 – 5.1",  "mmol/L", "N"],
        ["Chloride",       "103 mmol/L",      "98 – 107",   "mmol/L", "N"],
        ["HCO3",           "24 mmol/L",       "22 – 29",    "mmol/L", "N"],
        ["Glucose (fast)", "7.2 mmol/L",      "3.9 – 6.1",  "mmol/L", "H"],
        ["HbA1c",          "7.2 %",           "<7.0% (DM)", "%",      "H"],
    ])
    story.append(Paragraph(
        f"<b>ECHOCARDIOGRAM REPORT ({I['name']} Cardiac Imaging – ECHO-2026-0223-4411):</b>", S['label']
    ))
    for para in [
        "<b>Indication:</b> CHF decompensation; reassessment of EF and haemodynamic status.",
        "<b>Findings:</b> LV mildly dilated with mildly reduced systolic function; EF 42% (down from 45% in 2024). Mild global hypokinesis. Grade II diastolic dysfunction (E/e' 14). Mild mitral regurgitation. No significant aortic stenosis. RV normal size and function. IVC dilated 2.4 cm; collapsibility <50% (elevated RAP). No pericardial effusion.",
        "<b>Impression:</b> Ischemic cardiomyopathy with mildly reduced EF (42%), grade II diastolic dysfunction, dilated IVC – findings consistent with decompensated HFmrEF. Optimise diuretic and neurohormonal therapy.",
    ]:
        story.append(Paragraph(para, S['body']))

    story.append(PageBreak())
    story.append(header_block(CLINIC, ADDR, PHONE, DATE, "OUTPATIENT PRESCRIPTION (Rx)"))
    story.append(Spacer(1, 8))
    story.append(Paragraph("SECTION 5 – OUTPATIENT MEDICATION PRESCRIPTION", S['h1']))
    story.append(patient_box({
        "Patient":  "José Encarnación Ríos Delgado",
        "DOB":      "August 18, 1958",
        "OHIP":     "6183-029-441 PQ",
        "Date":     DATE,
        "Physician":DR,
        "License":  LIC,
    }))
    story.append(Spacer(1, 8))
    story += rx_table("Complete Outpatient Medication Prescription", [
        ["Warfarin Sodium",     "5 mg tablet",      "5 mg PO at 18:00 daily. Dose adjusted per INR (current INR 2.6 – therapeutic). Target 2.0-3.0.", "30 tabs", "Indefinite – AF anticoagulation"],
        ["Furosemide",          "40 mg tablet",     "80 mg PO once daily (AM) × 5 days, then 40 mg PO once daily. Monitor weight.",                    "45 tabs", "Ongoing – adjust per volume status"],
        ["Metoprolol Succinate","100 mg ER tablet", "100 mg PO once daily (rate control – AF)",                                                        "30 tabs", "Ongoing"],
        ["Ramipril",            "10 mg capsule",    "10 mg PO once daily (CHF + HTN)",                                                                 "30 caps", "Ongoing"],
        ["Amlodipine",          "10 mg tablet",     "10 mg PO once daily (HTN)",                                                                       "30 tabs", "Ongoing"],
        ["Rosuvastatin",        "40 mg tablet",     "40 mg PO at bedtime",                                                                             "30 tabs", "Ongoing"],
        ["Metformin",           "1000 mg tablet",   "1000 mg PO twice daily with meals (T2DM)",                                                        "60 tabs", "Ongoing"],
        ["Pantoprazole",        "40 mg tablet",     "40 mg PO once daily fasting (GI prophylaxis)",                                                    "30 tabs", "Ongoing"],
        ["Aspirin low-dose",    "81 mg tablet",     "81 mg PO once daily (post-NSTEMI/PCI)",                                                           "30 tabs", "Ongoing"],
    ])
    story.append(Spacer(1, 8))
    story.append(Paragraph("<b>WARFARIN MONITORING INSTRUCTIONS:</b>", S['warning']))
    for line in [
        "Current INR: 2.6 – THERAPEUTIC. Maintain Warfarin 5 mg daily.",
        "Next INR: in 4 weeks, or sooner if new medications, illness, or significant dietary change.",
        "Keep dietary Vitamin K intake CONSISTENT (do not suddenly change green leafy vegetable intake).",
        "SIGNS OF OVER-ANTICOAGULATION (INR >3): unusual bruising, prolonged bleeding, blood in urine, black/tarry stools, coughing blood – attend ED immediately.",
        "SIGNS OF UNDER-ANTICOAGULATION (INR <2): stroke symptoms (sudden weakness, speech difficulty, face drooping, vision changes) – call 911 immediately.",
        "DRUG INTERACTIONS: notify clinic before starting ANY new medication including OTC drugs (NSAIDs, vitamin E, antibiotics significantly affect INR).",
    ]:
        story.append(Paragraph(f"• {line}", S['body']))
    story.append(Spacer(1, 14))
    story.append(sig_block(DR, LIC, SPEC, DATE))

    doc.build(story)
    post_process_pdf(FNAME, FINAL)
    print("✔ Patient 5 – José Encarnación – DONE")


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print(f"Output directory: {OUTPUT_DIR}\n")
    print("Institution mapping:")
    for pid, d in INSTITUTION_MAP.items():
        print(f"  EMR #{pid:02d} → {d['name']}")
    print()

    build_jacinta()
    build_maria()
    build_salvador()
    build_armando()
    build_jose()

    print("\n✅  All 5 EMR PDFs generated with compliance overlays.")
    print("   ✔ Fictional institution names applied (5 distinct)")
    print("   ✔ Watermark on every page of every document")
    print("   ✔ Disclaimer at bottom of page 1 of every document")


if __name__ == "__main__":
    main()
