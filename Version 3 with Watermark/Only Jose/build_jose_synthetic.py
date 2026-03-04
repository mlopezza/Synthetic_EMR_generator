"""
Generates ONLY the EMR for José Encarnación (Patient 05) with:
  1. Fictional institution name replacing "Sunnybrook Health Sciences Centre"
  2. Single centered diagonal watermark on every page
  3. Formal disclaimer at the bottom of the first page
"""

import io
import math
import os
import sys

# ── ReportLab ──────────────────────────────────────────────────────────────────
from reportlab.lib.pagesizes import letter
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.colors import Color
from reportlab.pdfbase.pdfmetrics import stringWidth

from pypdf import PdfReader, PdfWriter

# ── Paths ──────────────────────────────────────────────────────────────────────
OUTPUT_DIR   = "/mnt/user-data/outputs"
TEMP_PDF     = "/home/claude/05_jose_temp.pdf"
FINAL_PDF    = os.path.join(OUTPUT_DIR, "05_Jose_Encarnacion_EMR_SYNTHETIC.pdf")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── Page geometry ──────────────────────────────────────────────────────────────
PAGE_W, PAGE_H = letter
LEFT_MARGIN  = 0.75 * inch
RIGHT_MARGIN = 0.75 * inch
TOP_MARGIN   = 0.60 * inch
BOT_MARGIN   = 0.60 * inch
CONTENT_W    = PAGE_W - LEFT_MARGIN - RIGHT_MARGIN   # 7.0 inches

# ── FICTIONAL institution (replaces Sunnybrook) ────────────────────────────────
CLINIC = "Sample Metropolitan General Hospital – Cardiology & Anticoagulation Clinic"
ADDR   = "1275 University Medical Drive, Room H1-52 | Sample City, ON M4N 3M5"
PHONE  = "Tel: (555) 480-4928 | Fax: (555) 480-5878 | Anticoag Hotline ext. 2891"

DR     = "Dr. Felipe Andrade Restrepo, MD FRCPC"
LIC    = "MED-ON-65321"
SPEC   = "Internal Medicine / Cardiology – Sample Metropolitan General Hospital"
DATE   = "February 23, 2026"

# ── Watermark & Disclaimer ─────────────────────────────────────────────────────
WATERMARK_TEXT   = "SYNTHETIC SAMPLE – NOT A REAL PATIENT"
DISCLAIMER_TITLE = "DISCLAIMER"
DISCLAIMER_BODY  = (
    "This document is a fully synthetic medical record AI generated for software testing and "
    "demonstration purposes only. All patient data contained herein is fictional. Any resemblance "
    "to real persons, living or dead, is purely coincidental. Institutional names used in this "
    "document are fictional and do not represent real clinical documentation. This document must "
    "not be used for clinical, legal, or medical decision-making purposes."
)


# ══════════════════════════════════════════════════════════════════════════════
#  STYLES  (same as original generator)
# ══════════════════════════════════════════════════════════════════════════════

def make_styles():
    _ = getSampleStyleSheet()
    return {
        'title':    ParagraphStyle('title',    fontSize=13, fontName='Helvetica-Bold',  alignment=TA_CENTER, spaceAfter=4),
        'subtitle': ParagraphStyle('subtitle', fontSize=10, fontName='Helvetica-Bold',  alignment=TA_CENTER, spaceAfter=4),
        'clinic':   ParagraphStyle('clinic',   fontSize=8,  fontName='Helvetica',       alignment=TA_CENTER, spaceAfter=2, textColor=colors.HexColor('#555555')),
        'h1':       ParagraphStyle('h1',       fontSize=10, fontName='Helvetica-Bold',  spaceBefore=10, spaceAfter=4, textColor=colors.HexColor('#003366')),
        'h2':       ParagraphStyle('h2',       fontSize=9,  fontName='Helvetica-Bold',  spaceBefore=6, spaceAfter=3, textColor=colors.HexColor('#005599')),
        'body':     ParagraphStyle('body',     fontSize=8.5,fontName='Helvetica',       leading=12, spaceAfter=3, alignment=TA_JUSTIFY),
        'label':    ParagraphStyle('label',    fontSize=8.5,fontName='Helvetica-Bold',  spaceAfter=1),
        'small':    ParagraphStyle('small',    fontSize=7.5,fontName='Helvetica',       textColor=colors.HexColor('#666666')),
        'center':   ParagraphStyle('center',   fontSize=8.5,fontName='Helvetica',       alignment=TA_CENTER),
        'right':    ParagraphStyle('right',    fontSize=8.5,fontName='Helvetica',       alignment=TA_RIGHT),
        'warning':  ParagraphStyle('warning',  fontSize=8.5,fontName='Helvetica-Bold',  textColor=colors.red, spaceAfter=2),
        'sign':     ParagraphStyle('sign',     fontSize=8.5,fontName='Helvetica',       alignment=TA_CENTER, spaceAfter=2),
        'cell':     ParagraphStyle('cell',     fontSize=8,  fontName='Helvetica',       leading=10, spaceAfter=0),
        'cell_bold':ParagraphStyle('cell_bold',fontSize=8,  fontName='Helvetica-Bold',  leading=10, spaceAfter=0),
        'cell_hdr': ParagraphStyle('cell_hdr', fontSize=8,  fontName='Helvetica-Bold',  leading=10, spaceAfter=0, textColor=colors.white),
    }

S = make_styles()


# ══════════════════════════════════════════════════════════════════════════════
#  LAYOUT PRIMITIVES  (identical to original)
# ══════════════════════════════════════════════════════════════════════════════

def hr():
    return HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#003366'), spaceAfter=4, spaceBefore=4)

def _default_doc(filename):
    return SimpleDocTemplate(filename, pagesize=letter,
                             topMargin=TOP_MARGIN, bottomMargin=BOT_MARGIN,
                             leftMargin=LEFT_MARGIN, rightMargin=RIGHT_MARGIN)

def header_block(clinic_name, address, phone, date, doc_type):
    col_l = CONTENT_W * 0.58
    col_r = CONTENT_W * 0.42
    data = [
        [Paragraph(clinic_name, S['title']),  Paragraph(doc_type,       S['subtitle'])],
        [Paragraph(address,     S['clinic']), Paragraph(f"Date: {date}", S['clinic'])],
        [Paragraph(phone,       S['clinic']), Paragraph("",              S['clinic'])],
    ]
    t = Table(data, colWidths=[col_l, col_r])
    t.setStyle(TableStyle([
        ('VALIGN',        (0,0), (-1,-1), 'TOP'),
        ('LINEBELOW',     (0,2), (-1,2),  0.5, colors.HexColor('#003366')),
        ('BOTTOMPADDING', (0,2), (-1,2),  6),
        ('TOPPADDING',    (0,0), (-1,-1), 2),
    ]))
    return t

def patient_box(data_dict):
    items = list(data_dict.items())
    rows  = []
    col_w = CONTENT_W / 2
    for i in range(0, len(items), 2):
        k1, v1 = items[i]
        cell_l = Paragraph(f"<b>{k1}:</b> {v1}", S['cell'])
        cell_r = Paragraph(f"<b>{items[i+1][0]}:</b> {items[i+1][1]}", S['cell']) if i+1 < len(items) else Paragraph("", S['cell'])
        rows.append([cell_l, cell_r])
    t = Table(rows, colWidths=[col_w, col_w])
    t.setStyle(TableStyle([
        ('BOX',           (0,0), (-1,-1), 0.5,  colors.HexColor('#003366')),
        ('BACKGROUND',    (0,0), (-1,-1), colors.HexColor('#EEF4FB')),
        ('INNERGRID',     (0,0), (-1,-1), 0.25, colors.lightgrey),
        ('TOPPADDING',    (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING',   (0,0), (-1,-1), 6),
        ('RIGHTPADDING',  (0,0), (-1,-1), 6),
        ('VALIGN',        (0,0), (-1,-1), 'TOP'),
    ]))
    return t

def _build_lab_table_flowable(title, rows_data, headers=None):
    if headers is None:
        headers = ["Test", "Result", "Reference Range", "Units", "Flag"]
    col_widths = [2.55*inch, 1.25*inch, 1.60*inch, 0.90*inch, 0.70*inch]
    def wrap(text, style=S['cell']): return Paragraph(str(text), style)
    hdr_cells  = [Paragraph(h, S['cell_hdr']) for h in headers]
    table_data = [hdr_cells] + [[wrap(c) for c in row] for row in rows_data]
    t = Table(table_data, colWidths=col_widths)
    style_cmds = [
        ('BACKGROUND',    (0,0), (-1,0),  colors.HexColor('#003366')),
        ('FONTSIZE',      (0,0), (-1,-1), 8),
        ('GRID',          (0,0), (-1,-1), 0.3, colors.grey),
        ('ROWBACKGROUNDS',(0,1), (-1,-1), [colors.white, colors.HexColor('#F5F8FC')]),
        ('TOPPADDING',    (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING',   (0,0), (-1,-1), 5),
        ('RIGHTPADDING',  (0,0), (-1,-1), 5),
        ('VALIGN',        (0,0), (-1,-1), 'TOP'),
    ]
    for i, row in enumerate(rows_data, 1):
        if len(row) >= 5 and str(row[4]).strip() in ('H','L','CRIT','ABN'):
            style_cmds += [
                ('TEXTCOLOR', (1,i), (1,i), colors.red), ('FONTNAME', (1,i), (1,i), 'Helvetica-Bold'),
                ('TEXTCOLOR', (4,i), (4,i), colors.red), ('FONTNAME', (4,i), (4,i), 'Helvetica-Bold'),
            ]
    t.setStyle(TableStyle(style_cmds))
    return t

def lab_table(title, rows_data, headers=None):
    t = _build_lab_table_flowable(title, rows_data, headers)
    block = KeepTogether([Paragraph(title, S['h2']), t])
    return [block, Spacer(1, 6)]

def _build_rx_table_flowable(title, meds):
    headers    = ["Generic Name", "Presentation", "Dose / Route / Frequency", "Qty", "Duration"]
    col_widths = [1.40*inch, 1.15*inch, 2.25*inch, 0.70*inch, 1.50*inch]
    def wrap(text, style=S['cell']): return Paragraph(str(text), style)
    hdr_cells  = [Paragraph(h, S['cell_hdr']) for h in headers]
    table_data = [hdr_cells] + [[wrap(c) for c in row] for row in meds]
    t = Table(table_data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,0),  colors.HexColor('#005599')),
        ('FONTSIZE',      (0,0), (-1,-1), 8),
        ('GRID',          (0,0), (-1,-1), 0.3, colors.grey),
        ('ROWBACKGROUNDS',(0,1), (-1,-1), [colors.white, colors.HexColor('#F0F8F0')]),
        ('TOPPADDING',    (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING',   (0,0), (-1,-1), 5),
        ('RIGHTPADDING',  (0,0), (-1,-1), 5),
        ('VALIGN',        (0,0), (-1,-1), 'TOP'),
    ]))
    return t

def rx_table(title, meds):
    t = _build_rx_table_flowable(title, meds)
    block = KeepTogether([Paragraph(title, S['h2']) if title else Spacer(1,1), t])
    return [block, Spacer(1, 6)]

def generic_order_table(title, headers, rows, col_widths, header_color=None):
    if header_color is None:
        header_color = colors.HexColor('#003366')
    col_pts = [w*inch if w < 20 else w for w in col_widths]
    def wrap(text, style=S['cell']): return Paragraph(str(text), style)
    hdr_cells  = [Paragraph(h, S['cell_hdr']) for h in headers]
    table_data = [hdr_cells] + [[wrap(c) for c in row] for row in rows]
    t = Table(table_data, colWidths=col_pts)
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,0),  header_color),
        ('FONTSIZE',      (0,0), (-1,-1), 8),
        ('GRID',          (0,0), (-1,-1), 0.3, colors.grey),
        ('ROWBACKGROUNDS',(0,1), (-1,-1), [colors.white, colors.HexColor('#F5F8FC')]),
        ('TOPPADDING',    (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING',   (0,0), (-1,-1), 5),
        ('RIGHTPADDING',  (0,0), (-1,-1), 5),
        ('VALIGN',        (0,0), (-1,-1), 'TOP'),
    ]))
    block = KeepTogether([Paragraph(title, S['h2']) if title else Spacer(1,1), t])
    return [block, Spacer(1, 8)]

def sig_block(doctor, reg, specialty, date):
    rows = [
        [Paragraph("_" * 44, S['sign'])],
        [Paragraph(f"<b>{doctor}</b>", S['sign'])],
        [Paragraph(f"License No.: {reg}", S['sign'])],
        [Paragraph(specialty, S['sign'])],
        [Paragraph(f"Date: {date}", S['sign'])],
    ]
    t = Table(rows, colWidths=[CONTENT_W])
    t.setStyle(TableStyle([('TOPPADDING',(0,0),(-1,-1),2),('BOTTOMPADDING',(0,0),(-1,-1),2)]))
    return t

def section(title, content_paragraphs):
    story = [hr(), Paragraph(title, S['h1'])]
    for p in content_paragraphs:
        story.append(Paragraph(p, S['body']))
    return story


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 1 – Build the base PDF with fictional institution name
# ══════════════════════════════════════════════════════════════════════════════

def build_jose_base():
    doc   = _default_doc(TEMP_PDF)
    story = []

    # ── CPP ───────────────────────────────────────────────────────────────
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
        "Family Physician":   "Dr. Felipe Andrade Restrepo",
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
        ["Warfarin Sodium",     "5 mg tablet",       "5 mg PO daily at 18:00 (dose per INR)",  "30 tabs", "Indefinite – AF"],
        ["Metoprolol Succinate","100 mg ER tablet",  "100 mg PO once daily",                   "30 tabs", "Ongoing"],
        ["Ramipril",            "10 mg capsule",     "10 mg PO once daily",                    "30 caps", "Ongoing"],
        ["Amlodipine",          "10 mg tablet",      "10 mg PO once daily",                    "30 tabs", "Ongoing"],
        ["Rosuvastatin",        "40 mg tablet",      "40 mg PO at bedtime",                    "30 tabs", "Ongoing"],
        ["Metformin",           "1000 mg tablet",    "1000 mg PO twice daily with meals",      "60 tabs", "Ongoing"],
        ["Pantoprazole",        "40 mg tablet",      "40 mg PO once daily (fasting)",          "30 tabs", "Ongoing"],
        ["Aspirin low-dose",    "81 mg tablet",      "81 mg PO once daily",                    "30 tabs", "Ongoing"],
        ["Cilostazol",          "100 mg tablet",     "100 mg PO twice daily (PAD)",            "60 tabs", "Ongoing"],
    ])
    story += section("1.5 – Immunization History", [
        "Influenza Oct 2025. Pneumococcal PCV15: 2023. COVID-19 boosters through 2024. Shingrix: 2023 (2-dose). Td: 2019.",
    ])
    story += section("1.6 – Family & Social History", [
        "<b>Family:</b> Father (†70, stroke + AF). Mother (†74, MI). Brother (65, AF + HTN).",
        "<b>Social:</b> Retired mechanical engineer. Married 40 yrs. Non-smoker (ex-smoker 30 pack-years, quit 2012). Rare social alcohol (1-2 drinks/week). Mediterranean diet – consistent green leafy vegetable intake (important for warfarin stability). Walking 30 min/day (limited by claudication). Cardiac rehab completed 2021.",
    ])

    # ── Encounter Note ────────────────────────────────────────────────────
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

    # ── Lab & Special Orders ──────────────────────────────────────────────
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
            ["INR",                         "URGENT – today",           "Warfarin monitoring. Target 2.0-3.0. CHF may alter levels.",              "Lab"],
            ["HbA1c",                        "ROUTINE",                  "Quarterly T2DM monitoring.",                                              "Lab"],
            ["CBC with differential",        "ROUTINE",                  "Anaemia screening; thrombocytopaenia monitoring (warfarin).",              "Lab"],
            ["BMP: Cr, BUN, Na, K, HCO3",   "ROUTINE",                  "Monitor for hypokalaemia + renal function with furosemide dose increase.", "Lab"],
            ["Transthoracic Echocardiogram (TTE)", "PRIORITY within 7 days", "Reassess EF, diastolic function, valvular disease. CHF decompensation workup.", "Imaging"],
            ["24-h Holter Monitor",          "ROUTINE within 2 weeks",   "AF burden; rate control adequacy (target HR <80 bpm at rest).",            "Special"],
        ],
        col_widths=[1.9, 1.1, 2.9, 1.1],
    )
    story.append(Spacer(1, 14))
    story.append(sig_block(DR, LIC, SPEC, DATE))

    # ── Lab Results ───────────────────────────────────────────────────────
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
        "Lab #":           "SHSC-2026-0223-7821",
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

    story.append(Paragraph("<b>ECHOCARDIOGRAM REPORT (Sample Metropolitan General Hospital Cardiac Imaging – ECHO-2026-0223-4411):</b>", S['label']))
    for para in [
        "<b>Indication:</b> CHF decompensation; reassessment of EF and haemodynamic status.",
        "<b>Findings:</b> LV mildly dilated with mildly reduced systolic function; EF 42% (down from 45% in 2024). Mild global hypokinesis. Grade II diastolic dysfunction (E/e' 14). Mild mitral regurgitation. No significant aortic stenosis. RV normal size and function. IVC dilated 2.4 cm; collapsibility <50% (elevated RAP). No pericardial effusion.",
        "<b>Impression:</b> Ischemic cardiomyopathy with mildly reduced EF (42%), grade II diastolic dysfunction, dilated IVC – findings consistent with decompensated HFmrEF. Optimise diuretic and neurohormonal therapy.",
    ]:
        story.append(Paragraph(para, S['body']))

    # ── Prescription ─────────────────────────────────────────────────────
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
    print(f"  Base PDF generated: {TEMP_PDF}")


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 2 – Post-process: add watermark + disclaimer overlay
# ══════════════════════════════════════════════════════════════════════════════

def make_watermark(page_width, page_height):
    """Single centered diagonal watermark."""
    packet = io.BytesIO()
    c = rl_canvas.Canvas(packet, pagesize=(page_width, page_height))
    c.setFillColor(Color(0.80, 0.10, 0.10, alpha=0.20))
    c.saveState()
    c.translate(page_width / 2, page_height / 2)
    angle = math.degrees(math.atan2(page_height, page_width))
    c.rotate(angle)
    c.setFont("Helvetica-Bold", 42)
    c.drawCentredString(0, 0, WATERMARK_TEXT)
    c.restoreState()
    c.save()
    packet.seek(0)
    return PdfReader(packet).pages[0]


def make_disclaimer(page_width, page_height):
    """Disclaimer block for the first page only — placed at bottom."""
    packet = io.BytesIO()
    c = rl_canvas.Canvas(packet, pagesize=(page_width, page_height))

    margin     = 0.75 * 72          # 0.75 inch in points
    max_width  = page_width - 2 * margin
    font_body  = "Helvetica"
    size_body  = 7.5
    line_h     = 11
    y_sep      = 108                 # top of disclaimer block from page bottom

    # Separator line
    c.setStrokeColor(Color(0.2, 0.2, 0.2, alpha=0.7))
    c.setLineWidth(0.7)
    c.line(margin, y_sep + 56, page_width - margin, y_sep + 56)

    # Title
    c.setFillColor(Color(0, 0, 0, alpha=1))
    c.setFont("Helvetica-Bold", 9)
    c.drawString(margin, y_sep + 42, DISCLAIMER_TITLE)

    # Body — word-wrap by measured pixel width
    words = DISCLAIMER_BODY.split()
    lines, cur = [], []
    for w in words:
        test = " ".join(cur + [w])
        if stringWidth(test, font_body, size_body) <= max_width:
            cur.append(w)
        else:
            if cur: lines.append(" ".join(cur))
            cur = [w]
    if cur: lines.append(" ".join(cur))

    c.setFont(font_body, size_body)
    y = y_sep + 28
    for ln in lines:
        c.drawString(margin, y, ln)
        y -= line_h

    c.save()
    packet.seek(0)
    return PdfReader(packet).pages[0]


def post_process():
    reader = PdfReader(TEMP_PDF)
    writer = PdfWriter()
    total  = len(reader.pages)
    print(f"  Post-processing {total} pages...")

    for i, page in enumerate(reader.pages):
        pw = float(page.mediabox.width)
        ph = float(page.mediabox.height)

        # Disclaimer only on first page
        if i == 0:
            page.merge_page(make_disclaimer(pw, ph))

        # Watermark on every page (on top so it's always visible)
        page.merge_page(make_watermark(pw, ph))

        writer.add_page(page)
        print(f"    Page {i+1}/{total} done.")

    with open(FINAL_PDF, "wb") as f:
        writer.write(f)
    print(f"  Final PDF saved: {FINAL_PDF}")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Step 1 – Building base PDF with fictional institution name...")
    build_jose_base()

    print("Step 2 – Adding watermark & disclaimer...")
    post_process()

    # Clean up temp file
    if os.path.exists(TEMP_PDF):
        os.remove(TEMP_PDF)

    print("\n✅  05_Jose_Encarnacion_EMR_SYNTHETIC.pdf complete.")
