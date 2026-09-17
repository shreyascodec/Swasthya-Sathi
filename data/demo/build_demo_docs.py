"""Render fictional Indian lab reports + prescriptions for Swasthya Sathi demos.

Produces A4 PDFs and PNGs under data/demo/out/. All patients, labs, and
registration numbers are invented. Values are chosen so LabQAR flags and the
intake question bank fire on a live pipeline run.
"""
from __future__ import annotations

from pathlib import Path

import fitz

OUT = Path(__file__).resolve().parent / "out"
A4 = fitz.paper_rect("a4")
W, H = A4.width, A4.height
L, R, TOP = 36, W - 36, 28

NAVY = (0.043, 0.239, 0.361)
TEAL = (0.02, 0.42, 0.48)
BURGUNDY = (0.42, 0.12, 0.12)
INK = (0.12, 0.12, 0.14)
MUTED = (0.38, 0.40, 0.43)
LINE = (0.78, 0.80, 0.82)
BOX = (0.94, 0.96, 0.97)
WHITE = (1, 1, 1)
RED = (0.72, 0.12, 0.12)
BLUE = (0.10, 0.28, 0.62)
AMBER = (0.55, 0.35, 0.05)
GREEN = (0.12, 0.42, 0.28)


def rgb(c: tuple[float, float, float]) -> tuple[float, float, float]:
    return c


def put(page: fitz.Page, x: float, y: float, text: str, *, size: float = 9,
        bold: bool = False, color=INK, font: str | None = None) -> None:
    name = font or ("hebo" if bold else "helv")
    page.insert_text((x, y), text, fontsize=size, fontname=name, color=color)


def wrap(page: fitz.Page, rect: fitz.Rect, text: str, *, size: float = 8,
         bold: bool = False, color=INK, align: int = 0) -> None:
    page.insert_textbox(
        rect, text, fontsize=size, fontname="hebo" if bold else "helv",
        color=color, align=align,
    )


def hline(page: fitz.Page, y: float, *, left: float = L, right: float = R,
          color=LINE, width: float = 0.6) -> None:
    page.draw_line(fitz.Point(left, y), fitz.Point(right, y), color=color, width=width)


def banner(page: fitz.Page, color, height: float = 64) -> None:
    page.draw_rect(fitz.Rect(0, 0, W, height), color=color, fill=color)
    page.draw_rect(fitz.Rect(0, height, W, height + 4), color=TEAL, fill=TEAL)


def demo_strip(page: fitz.Page) -> None:
    page.draw_rect(fitz.Rect(0, H - 18, W, H), color=(0.95, 0.90, 0.72), fill=(0.95, 0.90, 0.72))
    put(page, L, H - 6, "FOR DEMONSTRATION ONLY  ·  Fictional patient data  ·  Not a real clinical record",
        size=7, color=AMBER)


def barcode(page: fitz.Page, x: float, y: float, seed: str) -> None:
    """Simple barcode-look stripes (not a real barcode)."""
    page.draw_rect(fitz.Rect(x, y, x + 86, y + 22), color=WHITE, fill=WHITE)
    cursor = x + 2
    for i, ch in enumerate(seed.encode("ascii")):
        w = 0.8 + (ch % 3) * 0.55
        if i % 2 == 0:
            page.draw_rect(fitz.Rect(cursor, y + 1.5, cursor + w, y + 16),
                           color=INK, fill=INK)
        cursor += w + 0.7
        if cursor > x + 84:
            break


def kv_grid(page: fitz.Page, y: float, pairs: list[tuple[str, str]], cols: int = 3) -> float:
    col_w = (R - L) / cols
    row_h = 22
    for i, (k, v) in enumerate(pairs):
        c, r = i % cols, i // cols
        x = L + c * col_w
        yy = y + r * row_h
        put(page, x, yy, k.upper(), size=6.5, color=MUTED)
        put(page, x, yy + 11, v, size=9, bold=True)
    rows = (len(pairs) + cols - 1) // cols
    return y + rows * row_h + 8


def lab_table(page: fitz.Page, y: float, rows: list[dict], title: str) -> float:
    put(page, L, y, title, size=10, bold=True, color=NAVY)
    y += 8
    page.draw_rect(fitz.Rect(L, y, R, y + 16), color=NAVY, fill=NAVY)
    xs = {"name": L + 6, "value": L + 228, "unit": L + 292, "ref": L + 360, "flag": R - 38}
    for label, x in [("Investigation", xs["name"]), ("Result", xs["value"]),
                     ("Unit", xs["unit"]), ("Biological Ref. Interval", xs["ref"]),
                     ("Flag", xs["flag"])]:
        put(page, x, y + 11, label, size=7.5, bold=True, color=WHITE)
    y += 16
    for i, row in enumerate(rows):
        h = 15.5
        bg = BOX if i % 2 == 0 else WHITE
        page.draw_rect(fitz.Rect(L, y, R, y + h), color=bg, fill=bg)
        flag = row.get("flag") or ""
        flag_color = RED if flag == "H" else BLUE if flag == "L" else INK
        # Same baseline, column-spaced — OCR concatenates to:
        #   Analyte  value  unit  low-high
        put(page, xs["name"], y + 11, row["name"], size=8.5)
        put(page, xs["value"], y + 11, str(row["value"]), size=8.5, bold=True)
        put(page, xs["unit"], y + 11, row.get("unit") or "", size=8.5)
        put(page, xs["ref"], y + 11, row["ref"], size=8.5)
        if flag:
            put(page, xs["flag"], y + 11, flag, size=8.5, bold=True, color=flag_color)
        y += h
    hline(page, y, color=NAVY, width=1.0)
    return y + 10


def footer_lab(page: fitz.Page, pathologist: str, qual: str, lab_no: str) -> None:
    y = H - 96
    hline(page, y, color=NAVY, width=1.0)
    y += 14
    put(page, L, y, "Interpreted & electronically authenticated by", size=7, color=MUTED)
    put(page, L, y + 12, pathologist, size=9, bold=True)
    put(page, L, y + 24, qual, size=7.5, color=MUTED)
    put(page, R - 200, y, "Lab No. " + lab_no, size=8, color=MUTED)
    put(page, R - 200, y + 12, "End of Report", size=8, bold=True, color=NAVY)
    wrap(page, fitz.Rect(L, y + 36, R, H - 22),
         "This is a computer-generated report. Please correlate with clinical findings. "
         "Reference intervals are method- and laboratory-specific. Not for medico-legal use without the original signed copy.",
         size=6.5, color=MUTED)


def new_page() -> tuple[fitz.Document, fitz.Page]:
    doc = fitz.open()
    page = doc.new_page(width=W, height=H)
    return doc, page


def save(doc: fitz.Document, stem: str) -> tuple[Path, Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    pdf_path = OUT / f"{stem}.pdf"
    png_path = OUT / f"{stem}.png"
    doc.save(pdf_path)
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    pix.save(png_path)
    doc.close()
    return pdf_path, png_path


def draw_lab(
    *,
    stem: str,
    lab_name: str,
    lab_tag: str,
    address: str,
    phone: str,
    nabl: str,
    patient: str,
    age_sex: str,
    pid: str,
    referred: str,
    collected: str,
    received: str,
    reported: str,
    sample: str,
    lab_no: str,
    sections: list[tuple[str, list[dict]]],
    pathologist: str,
    path_qual: str,
) -> tuple[Path, Path]:
    doc, page = new_page()
    banner(page, NAVY, 70)
    put(page, L, 22, lab_name, size=15, bold=True, color=WHITE)
    put(page, L, 36, lab_tag, size=8, color=(0.75, 0.88, 0.92))
    put(page, L, 50, address, size=7.5, color=WHITE)
    put(page, L, 62, phone, size=7.5, color=WHITE)

    page.draw_rect(fitz.Rect(R - 128, 8, R - 8, 42), color=WHITE, fill=None, width=0.8)
    put(page, R - 120, 20, "NABL ACCREDITED", size=7, bold=True, color=WHITE)
    put(page, R - 120, 32, nabl + "  ·  ISO 15189:2022", size=6.5, color=(0.80, 0.90, 0.94))
    barcode(page, R - 128, 44, lab_no)

    y = 82
    page.draw_rect(fitz.Rect(0, y, W, y + 22), color=TEAL, fill=TEAL)
    put(page, L, y + 15, "LABORATORY INVESTIGATION REPORT", size=11, bold=True, color=WHITE)
    put(page, R - 78, y + 15, "Final Report", size=8, bold=True, color=WHITE)
    y += 22

    page.draw_rect(fitz.Rect(L, y + 10, R, y + 10 + 90), color=BOX, fill=BOX)
    y = kv_grid(page, y + 22, [
        ("Patient name", patient),
        ("Age / Sex", age_sex),
        ("Patient ID", pid),
        ("Referred by", referred),
        ("Sample type", sample),
        ("Lab no.", lab_no),
        ("Collected", collected),
        ("Received", received),
        ("Reported", reported),
    ])
    y += 4
    for title, rows in sections:
        y = lab_table(page, y, rows, title)
        y += 4
    footer_lab(page, pathologist, path_qual, lab_no)
    demo_strip(page)
    return save(doc, stem)


def draw_rx(
    *,
    stem: str,
    clinic: str,
    clinic_sub: str,
    address: str,
    doctor: str,
    qual: str,
    regno: str,
    patient: str,
    age_sex: str,
    date: str,
    pid: str,
    diagnosis: str,
    meds: list[dict],
    advice: list[str],
    next_visit: str,
) -> tuple[Path, Path]:
    doc, page = new_page()
    banner(page, BURGUNDY, 66)
    put(page, L, 22, clinic, size=15, bold=True, color=WHITE, font="tibo")
    put(page, L, 38, clinic_sub, size=8, color=(0.95, 0.85, 0.85))
    put(page, L, 52, address, size=7.5, color=WHITE)
    put(page, R - 170, 24, doctor, size=10, bold=True, color=WHITE)
    put(page, R - 170, 38, qual, size=7.5, color=(0.95, 0.85, 0.85))
    put(page, R - 170, 52, regno, size=7.5, color=(0.95, 0.85, 0.85))

    y = 88
    put(page, L, y, "OUTPATIENT PRESCRIPTION", size=12, bold=True, color=BURGUNDY)
    put(page, R - 110, y, date, size=9, bold=True)
    y += 8
    hline(page, y, color=BURGUNDY, width=1.2)

    page.draw_rect(fitz.Rect(L, y + 10, R, y + 108), color=BOX, fill=BOX)
    y = kv_grid(page, y + 22, [
        ("Patient name", patient),
        ("Age / Sex", age_sex),
        ("OPD no.", pid),
        ("Date", date),
        ("Follow-up", next_visit),
    ])
    put(page, L, y, "PROVISIONAL DIAGNOSIS", size=6.5, color=MUTED)
    put(page, L, y + 12, diagnosis, size=9, bold=True)
    y += 28

    put(page, L, y + 6, "Rx", size=22, bold=True, color=BURGUNDY, font="tibo")
    y += 28

    page.draw_rect(fitz.Rect(L, y - 8, R, y - 8 + 12 + len(meds) * 36), color=BOX, fill=BOX)
    y += 6
    for i, m in enumerate(meds, 1):
        # OCR drug pattern: Tab|Cap|Syr|Inj|Tablet|Capsule|Rx + rest of line
        put(page, L + 10, y, f"{i}.  {m['line']}", size=10, bold=True)
        put(page, L + 28, y + 13, m["sig"], size=8, color=MUTED)
        y += 34

    y += 10
    put(page, L, y, "Advice", size=10, bold=True, color=BURGUNDY)
    y += 14
    for a in advice:
        put(page, L + 8, y, f"•  {a}", size=8.5)
        y += 13

    y = max(y + 20, H - 160)
    hline(page, y, color=BURGUNDY, width=0.8)
    put(page, R - 180, y + 36, doctor, size=9, bold=True)
    put(page, R - 180, y + 48, qual, size=7.5, color=MUTED)
    put(page, R - 180, y + 60, "Signature (demo)", size=7, color=MUTED)
    page.draw_rect(fitz.Rect(R - 180, y + 8, R - 40, y + 30), color=BURGUNDY, fill=None, width=0.6)
    put(page, L, y + 20, "Dispense branded or quality generic.", size=7.5, color=MUTED)
    put(page, L, y + 34, "Review sooner if symptoms worsen.", size=7.5, color=MUTED)
    demo_strip(page)
    return save(doc, stem)


# ---------------------------------------------------------------------------
# Four demo cases. Values sit clearly Low / High vs data/labqar/reference_ranges.yaml
# so Stage 5 flags and Stage 6 questions fire.
# ---------------------------------------------------------------------------

def build_maternal() -> list[tuple[str, Path, Path]]:
    """One antenatal (ANC) case for Swasthya Sakhi MCH mode: a pregnant woman with
    anaemia + gestational diabetes — the most common real ANC finding pair. Values
    sit against data/mch/maternal_thresholds.yaml so the maternal risk tier lands
    'moderate' and the grounded anaemia + high-sugar follow-up questions fire, on
    top of the always-asked antenatal danger-sign screen. Fictional patient."""
    written: list[tuple[str, Path, Path]] = []
    p, g = draw_lab(
        stem="05_lakshmi_anc_lab",
        lab_name="Matrika Diagnostics & Women's Lab",
        lab_tag="Antenatal Profile  ·  Haematology  ·  Biochemistry",
        address="7, Station Road, Varanasi 221002  ·  Uttar Pradesh",
        phone="Phone: 0542-2201 640  ·  matrika-labs.example",
        nabl="NABL-MC-38115",
        patient="Lakshmi Yadav",
        age_sex="26 Y / F  ·  28 wk POG",
        pid="SS-DEMO-005",
        referred="Dr. Sunita Menon, OBG",
        collected="16/09/2026  08:20",
        received="16/09/2026  08:45",
        reported="16/09/2026  14:30",
        sample="EDTA Blood + Serum",
        lab_no="MAT-260916-0518",
        sections=[
            ("HAEMATOLOGY — COMPLETE BLOOD COUNT", [
                {"name": "Hemoglobin", "value": "9.2", "unit": "g/dL", "ref": "11.0-14.0", "flag": "L"},
                {"name": "WBC", "value": "9800", "unit": "/cumm", "ref": "4000-11000", "flag": ""},
                {"name": "Platelets", "value": "2.1", "unit": "lakhs/cumm", "ref": "1.5-4.1", "flag": ""},
                {"name": "MCV", "value": "74", "unit": "fL", "ref": "80-100", "flag": "L"},
            ]),
            # Analyte names carry NO embedded numbers (e.g. not "OGTT 2-hour (75g)"):
            # the narrative repeats the label, and the faithfulness gate flags any
            # number in it that is not an extracted lab value ('75', '2' → ungrounded).
            ("GLUCOSE — ORAL GLUCOSE TOLERANCE TEST", [
                {"name": "Fasting Blood Sugar", "value": "104", "unit": "mg/dL", "ref": "70-92", "flag": "H"},
                {"name": "Post-prandial Blood Sugar", "value": "158", "unit": "mg/dL", "ref": "less than 140", "flag": "H"},
            ]),
            ("ANTENATAL SCREEN", [
                {"name": "Blood Group & Rh", "value": "B Positive", "unit": "", "ref": "", "flag": ""},
                {"name": "TSH", "value": "3.1", "unit": "mIU/L", "ref": "0.4-4.0", "flag": ""},
                {"name": "HIV I & II", "value": "Non-reactive", "unit": "", "ref": "Non-reactive", "flag": ""},
                {"name": "HBsAg", "value": "Non-reactive", "unit": "", "ref": "Non-reactive", "flag": ""},
                {"name": "VDRL", "value": "Non-reactive", "unit": "", "ref": "Non-reactive", "flag": ""},
                {"name": "Urine Albumin", "value": "Nil", "unit": "", "ref": "Nil", "flag": ""},
            ]),
        ],
        pathologist="Dr. Anita Deshpande",
        path_qual="MD (Pathology)  ·  Consultant Pathologist",
    )
    written += [("lab", p, g)]
    return written


def build() -> list[tuple[str, Path, Path]]:
    written: list[tuple[str, Path, Path]] = []

    # 1. Type 2 diabetes + mixed dyslipidaemia
    p, g = draw_lab(
        stem="01_ramesh_kumar_lab",
        lab_name="Aarogya Diagnostic Laboratory",
        lab_tag="Clinical Pathology  ·  Biochemistry  ·  Immunoassay",
        address="14, MI Road, Jaipur 302001  ·  Rajasthan",
        phone="Phone: 0141-4001 220  ·  aarogya-labs.example",
        nabl="NABL-MC-44021",
        patient="Ramesh Kumar",
        age_sex="52 Years / Male",
        pid="SS-DEMO-001",
        referred="Dr. Vikram Mehta",
        collected="18/08/2026  07:40",
        received="18/08/2026  08:10",
        reported="18/08/2026  16:20",
        sample="Fluoride Plasma + Serum",
        lab_no="ADL-260818-1044",
        sections=[
            ("BIOCHEMISTRY — GLUCOSE", [
                {"name": "Glucose Fasting", "value": "156", "unit": "mg/dL", "ref": "70-100", "flag": "H"},
                {"name": "HbA1c", "value": "8.2", "unit": "%", "ref": "4.0-5.6", "flag": "H"},
            ]),
            ("LIPID PROFILE (12-hour fasting)", [
                {"name": "Total Cholesterol", "value": "248", "unit": "mg/dL", "ref": "125-200", "flag": "H"},
                {"name": "Triglycerides", "value": "210", "unit": "mg/dL", "ref": "0-150", "flag": "H"},
                {"name": "HDL Cholesterol", "value": "32", "unit": "mg/dL", "ref": "40-60", "flag": "L"},
                {"name": "LDL Cholesterol", "value": "164", "unit": "mg/dL", "ref": "0-100", "flag": "H"},
                {"name": "VLDL Cholesterol", "value": "42", "unit": "mg/dL", "ref": "2-30", "flag": "H"},
            ]),
        ],
        pathologist="Dr. Neha Bansal",
        path_qual="MD (Pathology)  ·  Consultant Pathologist",
    )
    written += [("lab", p, g)]
    p, g = draw_rx(
        stem="01_ramesh_kumar_rx",
        clinic="Mehta Diabetes & Heart Clinic",
        clinic_sub="Consultant Physician  ·  Diabetology",
        address="C-22, Ashok Marg, C-Scheme, Jaipur 302001",
        doctor="Dr. Vikram Mehta",
        qual="MD (Medicine), Fellowship (Diabetes)",
        regno="RMC 2014/18220",
        patient="Ramesh Kumar",
        age_sex="52 Years / Male",
        date="18/08/2026",
        pid="OPD-88421",
        diagnosis="Type 2 Diabetes Mellitus  ·  Dyslipidaemia",
        meds=[
            {"line": "Tab Metformin 500mg", "sig": "1-0-1  after food  x 30 days"},
            {"line": "Tab Glimepiride 1mg", "sig": "1-0-0  before breakfast  x 30 days"},
            {"line": "Tab Atorvastatin 10mg", "sig": "0-0-1  at bedtime  x 30 days"},
        ],
        advice=[
            "Walk 30 minutes daily. Reduce fried food and sweets.",
            "Home fasting sugar record twice a week.",
            "Repeat HbA1c and lipid profile after 3 months.",
        ],
        next_visit="18/09/2026",
    )
    written += [("rx", p, g)]

    # 2. Iron-deficiency anaemia + low B12
    p, g = draw_lab(
        stem="02_sunita_devi_lab",
        lab_name="Sunrise Pathology Labs",
        lab_tag="Haematology  ·  Clinical Biochemistry",
        address="3/21, Hazratganj, Lucknow 226001  ·  Uttar Pradesh",
        phone="Phone: 0522-4100 118  ·  sunrise-path.example",
        nabl="NABL-MC-31807",
        patient="Sunita Devi",
        age_sex="34 Years / Female",
        pid="SS-DEMO-002",
        referred="Dr. Priya Nair",
        collected="22/08/2026  09:15",
        received="22/08/2026  09:40",
        reported="22/08/2026  15:05",
        sample="EDTA Whole Blood + Serum",
        lab_no="SPL-260822-0771",
        sections=[
            ("HAEMATOLOGY — COMPLETE BLOOD COUNT", [
                {"name": "Hemoglobin", "value": "8.4", "unit": "g/dL", "ref": "12.0-15.0", "flag": "L"},
                {"name": "WBC", "value": "7200", "unit": "/cumm", "ref": "4000-11000", "flag": ""},
                {"name": "Platelets", "value": "2.8", "unit": "lakhs/cumm", "ref": "1.5-4.1", "flag": ""},
                {"name": "MCV", "value": "68", "unit": "fL", "ref": "80-100", "flag": "L"},
                {"name": "RDW", "value": "17.8", "unit": "%", "ref": "11.5-14.5", "flag": "H"},
            ]),
            ("IRON STUDIES / VITAMINS", [
                {"name": "Ferritin", "value": "12", "unit": "ng/mL", "ref": "30-400", "flag": "L"},
                {"name": "Vitamin B12", "value": "168", "unit": "pg/mL", "ref": "200-900", "flag": "L"},
            ]),
        ],
        pathologist="Dr. Rakesh Srivastava",
        path_qual="MD (Pathology)  ·  Head of Haematology",
    )
    written += [("lab", p, g)]
    p, g = draw_rx(
        stem="02_sunita_devi_rx",
        clinic="Nair Women's Clinic",
        clinic_sub="Obstetrics  ·  Gynaecology  ·  General OPD",
        address="B-6, Jopling Road, Lucknow 226001",
        doctor="Dr. Priya Nair",
        qual="MS (OBG), DNB",
        regno="MCI 2009/09411",
        patient="Sunita Devi",
        age_sex="34 Years / Female",
        date="22/08/2026",
        pid="OPD-12038",
        diagnosis="Iron deficiency anaemia  ·  Vitamin B12 deficiency",
        meds=[
            {"line": "Tab Ferrous Sulphate 200mg", "sig": "1-0-1  after food  x 30 days"},
            {"line": "Tab Folic Acid 5mg", "sig": "0-1-0  after lunch  x 30 days"},
            {"line": "Cap Vitamin B12 1500mcg", "sig": "0-0-1  after dinner  x 30 days"},
        ],
        advice=[
            "Take iron tablet with lemon water. Avoid tea for 1 hour after iron.",
            "Include green leafy vegetables, dal, and jaggery.",
            "Repeat hemoglobin after 4 weeks.",
        ],
        next_visit="22/09/2026",
    )
    written += [("rx", p, g)]

    # 3. Hypothyroidism + vitamin D deficiency
    p, g = draw_lab(
        stem="03_meena_joshi_lab",
        lab_name="Greenfield Medical Centre",
        lab_tag="Department of Laboratory Medicine",
        address="88, Baner Road, Pune 411045  ·  Maharashtra",
        phone="Phone: 020-6712 4400  ·  greenfield-mc.example",
        nabl="NABL-MC-27654",
        patient="Meena Joshi",
        age_sex="41 Years / Female",
        pid="SS-DEMO-003",
        referred="Dr. Anjali Rao",
        collected="12/08/2026  08:50",
        received="12/08/2026  09:20",
        reported="12/08/2026  14:40",
        sample="Serum",
        lab_no="GMC-260812-3310",
        sections=[
            ("IMMUNOASSAY — THYROID", [
                {"name": "TSH", "value": "12.6", "unit": "mIU/L", "ref": "0.4-4.0", "flag": "H"},
            ]),
            ("VITAMIN ASSAY", [
                {"name": "Vitamin D", "value": "14.2", "unit": "ng/mL", "ref": "30-100", "flag": "L"},
            ]),
        ],
        pathologist="Dr. Sameer Kulkarni",
        path_qual="MD (Biochemistry)  ·  Consultant",
    )
    written += [("lab", p, g)]
    p, g = draw_rx(
        stem="03_meena_joshi_rx",
        clinic="Rao Endocrinology Clinic",
        clinic_sub="Thyroid  ·  Hormone  ·  Metabolic Bone",
        address="Shop 4, Gera Emerald, Baner, Pune 411045",
        doctor="Dr. Anjali Rao",
        qual="DM (Endocrinology), MD (Medicine)",
        regno="MMC 2011/33408",
        patient="Meena Joshi",
        age_sex="41 Years / Female",
        date="12/08/2026",
        pid="OPD-55102",
        diagnosis="Primary hypothyroidism  ·  Vitamin D deficiency",
        meds=[
            {"line": "Tab Thyroxine 50mcg", "sig": "1-0-0  empty stomach, 30 min before tea  x 30 days"},
            {"line": "Cap Vitamin D3 60000 IU", "sig": "once a week after food  x 8 weeks"},
        ],
        advice=[
            "Do not skip Thyroxine. Take it with water only.",
            "Morning sunlight 15 minutes, arms and face uncovered.",
            "Repeat TSH after 6 weeks. Do not change dose on your own.",
        ],
        next_visit="23/09/2026",
    )
    written += [("rx", p, g)]

    # 4. Raised creatinine + mild hepatitis pattern
    p, g = draw_lab(
        stem="04_abdul_rahman_lab",
        lab_name="City Care Hospital",
        lab_tag="Central Clinical Laboratory",
        address="27, Sitabuldi Main Road, Nagpur 440012  ·  Maharashtra",
        phone="Phone: 0712-2550 090  ·  citycare-hosp.example",
        nabl="NABL-MC-19883",
        patient="Abdul Rahman",
        age_sex="61 Years / Male",
        pid="SS-DEMO-004",
        referred="Dr. Suresh Kulkarni",
        collected="25/08/2026  07:55",
        received="25/08/2026  08:25",
        reported="25/08/2026  13:50",
        sample="Serum",
        lab_no="CCH-260825-2198",
        sections=[
            ("RENAL FUNCTION TEST", [
                {"name": "Creatinine", "value": "2.1", "unit": "mg/dL", "ref": "0.7-1.3", "flag": "H"},
                {"name": "Urea", "value": "58", "unit": "mg/dL", "ref": "15-40", "flag": "H"},
            ]),
            ("LIVER FUNCTION TEST", [
                {"name": "Bilirubin Total", "value": "1.8", "unit": "mg/dL", "ref": "0.3-1.2", "flag": "H"},
                {"name": "Direct Bilirubin", "value": "0.6", "unit": "mg/dL", "ref": "0-0.3", "flag": "H"},
                {"name": "SGPT", "value": "78", "unit": "U/L", "ref": "0-45", "flag": "H"},
                {"name": "Total Protein", "value": "6.8", "unit": "g/dL", "ref": "6.0-8.3", "flag": ""},
                {"name": "Globulin", "value": "2.9", "unit": "g/dL", "ref": "2.0-3.5", "flag": ""},
                {"name": "A/G Ratio", "value": "1.34", "unit": "", "ref": "1.0-2.5", "flag": ""},
            ]),
        ],
        pathologist="Dr. Farah Qureshi",
        path_qual="MD (Pathology)  ·  Laboratory Director",
    )
    written += [("lab", p, g)]
    p, g = draw_rx(
        stem="04_abdul_rahman_rx",
        clinic="Kulkarni Medical Clinic",
        clinic_sub="Internal Medicine  ·  Nephrology liaison",
        address="12, Dharampeth Extension, Nagpur 440010",
        doctor="Dr. Suresh Kulkarni",
        qual="MD (Medicine)",
        regno="MMC 1998/11765",
        patient="Abdul Rahman",
        age_sex="61 Years / Male",
        date="25/08/2026",
        pid="OPD-77301",
        diagnosis="Hypertension  ·  Raised creatinine  ·  Deranged LFT",
        meds=[
            {"line": "Tab Telmisartan 40mg", "sig": "1-0-0  in the morning  x 30 days"},
            {"line": "Tab Ursodeoxycholic Acid 300mg", "sig": "1-0-1  after food  x 15 days"},
        ],
        advice=[
            "Avoid painkillers (NSAIDs) and over-the-counter powders.",
            "Limit salt. Drink water as advised — do not force extra fluids.",
            "Ultrasound KUB if not done. Repeat KFT and LFT in 2 weeks.",
        ],
        next_visit="08/09/2026",
    )
    written += [("rx", p, g)]
    return written


def write_packs(files: list[tuple[str, Path, Path]]) -> list[Path]:
    """One two-page PDF per patient (lab + prescription) for a single upload."""
    packs: list[Path] = []
    stems = [
        "01_ramesh_kumar",
        "02_sunita_devi",
        "03_meena_joshi",
        "04_abdul_rahman",
    ]
    for stem in stems:
        lab = OUT / f"{stem}_lab.pdf"
        rx = OUT / f"{stem}_rx.pdf"
        pack_path = OUT / f"{stem}_pack.pdf"
        pack = fitz.open()
        pack.insert_pdf(fitz.open(lab))
        pack.insert_pdf(fitz.open(rx))
        pack.save(pack_path)
        pack.close()
        packs.append(pack_path)
    return packs


if __name__ == "__main__":
    files = build()
    packs = write_packs(files)
    print(f"Wrote {len(files)} documents + {len(packs)} packs to {OUT}")
    for kind, pdf, png in files:
        print(f"  [{kind}] {pdf.name}  |  {png.name}  ({png.stat().st_size // 1024} KB)")
    for p in packs:
        print(f"  [pack] {p.name}")
