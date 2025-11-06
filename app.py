# app.py
import streamlit as st
import pdfplumber
import re
import io
import pandas as pd
import matplotlib.pyplot as plt
from pdf2image import convert_from_bytes
import pytesseract
from rapidfuzz import fuzz

st.set_page_config(layout="wide", page_title="Paystub Analyzer (Local)")

st.title("Paystub Analyzer — Local (Prototype)")

uploaded = st.file_uploader("Upload a paystub PDF (local only)", type=["pdf"])
if not uploaded:
    st.info("Upload a PDF paystub to start. This runs locally in your browser session.")
    st.stop()

# Helper: extract text via pdfplumber, fallback to OCR
def extract_text_from_pdf_bytes(pdf_bytes):
    text = ""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for p in pdf.pages:
                page_text = p.extract_text()
                if page_text:
                    text += "\n" + page_text
    except Exception as e:
        st.warning(f"pdfplumber extraction failed: {e}")

    # if we got little text, fallback to OCR
    if len(text.strip()) < 50:
        st.info("Falling back to OCR (this requires Tesseract installed).")
        imgs = convert_from_bytes(pdf_bytes, dpi=300)
        ocr_text = ""
        for im in imgs:
            ocr_text += "\n" + pytesseract.image_to_string(im)
        if len(ocr_text) > len(text):
            text = ocr_text
    return text

bytes_data = uploaded.read()
raw_text = extract_text_from_pdf_bytes(bytes_data)

st.subheader("Raw extracted text (first 2000 chars)")
st.text_area("", raw_text[:2000], height=200)

# Utility regexes
money_re = r"\$?\s?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)"
int_re = r"([0-9]+(?:\.[0-9]+)?)"

# Patterns: try to find common labels
patterns = {
    "gross": [r"Gross Pay", r"Gross Earnings", r"Total Gross", r"Gross"],
    "net": [r"Net Pay", r"Net Amount", r"Net Pay to Employee", r"Pay After Deductions"],
    "federal": [r"Federal Withholding", r"Federal Tax", r"Fed Withheld", r"Federal Income Tax"],
    "state": [r"State Withholding", r"State Tax", r"State Income Tax"],
    "ss": [r"Social Security", r"FICA Social Security", r"Social Sec"],
    "medicare": [r"Medicare", r"FICA Medicare"],
    "regular_hours": [r"Regular Hours", r"Hours Regular", r"Reg Hrs"],
    "overtime_hours": [r"Overtime Hours", r"OT Hours", r"Overtime Hrs"],
    "regular_amount": [r"Regular Pay", r"Regular Earnings"],
    "overtime_amount": [r"Overtime Pay", r"OT Pay", r"Overtime Earnings"]
}

def find_best_pattern(text, label_patterns):
    best = {"match": None, "score": 0, "value": None}
    for pat in label_patterns:
        # fuzzy find the label occurrence
        for m in re.finditer(r".{0,40}" + re.escape(pat) + r".{0,40}", text, flags=re.IGNORECASE):
            substr = m.group(0)
            # get the first money-looking thing in nearby substring
            mval = re.search(money_re, substr)
            if not mval:
                # search after the label for numbers
                after = text[m.end(): m.end()+80]
                m2 = re.search(money_re, after)
                if m2:
                    val = m2.group(1)
                    score = fuzz.partial_ratio(pat.lower(), substr.lower())
                    if score > best["score"]:
                        best.update({"match": substr, "score": score, "value": val})
            else:
                val = mval.group(1)
                score = fuzz.partial_ratio(pat.lower(), substr.lower())
                if score > best["score"]:
                    best.update({"match": substr, "score": score, "value": val})
    return best

extracted = {}
for key, pats in patterns.items():
    res = find_best_pattern(raw_text, pats)
    if res["value"]:
        # cleanup numeric
        v = res["value"].replace(",", "").strip()
        try:
            extracted[key] = float(v)
        except:
            extracted[key] = v

# Show extracted with editing
st.subheader("Extracted fields (editable)")
cols = st.columns(2)
with cols[0]:
    gross = st.number_input("Gross pay (period)", value=float(extracted.get("gross", 0.0)))
    regular_pay = st.number_input("Regular pay (period)", value=float(extracted.get("regular_amount", 0.0)))
    overtime_pay = st.number_input("Overtime pay (period)", value=float(extracted.get("overtime_amount", 0.0)))
    net = st.number_input("Net pay (period)", value=float(extracted.get("net", 0.0)))
with cols[1]:
    fed = st.number_input("Federal tax withheld (period)", value=float(extracted.get("federal", 0.0)))
    state = st.number_input("State tax withheld (period)", value=float(extracted.get("state", 0.0)))
    ss = st.number_input("Social Security withheld (period)", value=float(extracted.get("ss", 0.0)))
    medicare = st.number_input("Medicare withheld (period)", value=float(extracted.get("medicare", 0.0)))

# Basic summary computations
total_taxes = fed + state + ss + medicare
pre_tax_contrib = st.number_input("Pre-tax contributions this period (e.g., 401k, HSA)", value=0.0)
post_tax_contrib = st.number_input("After-tax deductions this period", value=0.0)

st.subheader("Summary")
st.write(f"Gross: ${gross:,.2f}")
st.write(f"Total taxes (sum of entered fields): ${total_taxes:,.2f}")
st.write(f"Pre-tax contributions: ${pre_tax_contrib:,.2f}")
st.write(f"Net pay (entered): ${net:,.2f}")
estimated_take_home = gross - total_taxes - pre_tax_contrib - post_tax_contrib
st.write(f"Estimated take-home (computed): ${estimated_take_home:,.2f}")

# Very simple federal withholding check (placeholder estimation)
st.subheader("Simple 'Do you have enough federal withholding?' check (rough estimate)")
# Annualize
freq = st.selectbox("Pay frequency", ["Biweekly (26)", "Weekly (52)", "Semi-monthly (24)", "Monthly (12)"])
freq_map = {"Biweekly (26)":26, "Weekly (52)":52, "Semi-monthly (24)":24, "Monthly (12)":12}
periods = freq_map[freq]
annual_gross = gross * periods
annual_pre_tax = pre_tax_contrib * periods
taxable_est = annual_gross - annual_pre_tax
st.write(f"Projected annual taxable income (simple): ${taxable_est:,.0f}")

# placeholder progressive bracket example (simplified)
def estimate_federal_tax_simple(annual_taxable):
    # simplified single-filer 2024-ish bracket example — REPLACE with up-to-date table
    brackets = [
        (11000, 0.10),
        (44725-11000, 0.12),
        (95375-44725, 0.22),
        (182100-95375, 0.24),
        (231250-182100, 0.32),
        (578125-231250, 0.35),
        (10**12, 0.37)
    ]
    tax = 0.0
    rem = annual_taxable
    for amt, rate in brackets:
        take = min(rem, amt)
        tax += take * rate
        rem -= take
        if rem <= 0:
            break
    return tax

estimated_fed_annual = estimate_federal_tax_simple(taxable_est)
estimated_fed_period = estimated_fed_annual / periods
st.write(f"Estimated federal tax (annual): ${estimated_fed_annual:,.0f}")
st.write(f"Estimated federal tax per period: ${estimated_fed_period:,.2f}")
st.write(f"Actual federal withheld this period: ${fed:,.2f}")

diff = fed - estimated_fed_period
if diff > 50:
    st.success(f"You are over-withholding federal by about ${diff:,.2f} this period (rough). Consider adjusting W-4 if desired.")
elif diff < -50:
    st.warning(f"You may be under-withholding federal by about ${-diff:,.2f} this period (rough). Consider checking your W-4 or adding extra withholding.")
else:
    st.info("Your federal withholding roughly matches this simple estimate.")

# Simple donut chart
st.subheader("Pay breakdown (period)")
fig, ax = plt.subplots(figsize=(5,4))
labels = ["Taxes", "Pre-tax contrib", "Net/Other"]
sizes = [total_taxes, pre_tax_contrib, max(estimated_take_home, 0.0)]
ax.pie(sizes, labels=labels, autopct="%1.1f%%", startangle=90)
ax.axis('equal')
st.pyplot(fig)

st.success("Prototype complete — this is a starting point. To make it production-ready: add robust label mappings, state tax tables, exact IRS withholding logic, better OCR tuning, and UI polishing.")
