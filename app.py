import os
import re
import unicodedata
from io import BytesIO
from datetime import datetime
import pandas as pd
import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from fpdf import FPDF

# -----------------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------------
st.set_page_config(page_title="IHOP OE One Pager", layout="wide")
LOGO_PATH = "ihop_logo.png"
CLASS_CHOICES = ("FOH", "BOH", "BOTH")

# Google Sheets details from secrets.toml
try:
    SPREADSHEET_ID = st.secrets["gsheets"]["spreadsheet_id"]
    WORKSHEET_TITLE = st.secrets["gsheets"].get("worksheet_title", "Sheet1")
except Exception:
    st.error("❌ Missing `[gsheets]` section in secrets.toml — add spreadsheet_id and worksheet_title.")
    st.stop()

# -----------------------------------------------------------------------------
# GOOGLE SHEETS CONNECTION
# -----------------------------------------------------------------------------
def get_gsheet_client():
    creds_info = st.secrets["gcp_service_account"]
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
    return gspread.authorize(creds)

def open_ws():
    """Open target worksheet, create if missing."""
    client = get_gsheet_client()
    ss = client.open_by_key(SPREADSHEET_ID)
    try:
        ws = ss.worksheet(WORKSHEET_TITLE)
    except gspread.exceptions.WorksheetNotFound:
        ws = ss.add_worksheet(title=WORKSHEET_TITLE, rows=1000, cols=2)
        ws.update("A1:B1", [["Opportunity", "Classification"]])
    return ws

def df_from_ws(ws):
    """Read entire worksheet into a DataFrame."""
    vals = ws.get_all_values()
    if not vals:
        return pd.DataFrame(columns=["Opportunity", "Classification"])
    df = pd.DataFrame(vals[1:], columns=vals[0])
    for col in ["Opportunity", "Classification"]:
        if col not in df.columns:
            df[col] = ""
    df = df[["Opportunity", "Classification"]].fillna("")
    df = df[(df["Opportunity"].astype(str).str.strip() != "")]
    return df.reset_index(drop=True).astype(str)

def save_classifications_merge(updates_df: pd.DataFrame):
    """Reliable merge + write with live verification."""
    try:
        ws = open_ws()
        existing_df = df_from_ws(ws)

        for df in (existing_df, updates_df):
            df["Opportunity"] = df["Opportunity"].astype(str).str.strip()
            df["Classification"] = df["Classification"].astype(str).str.strip()

        existing_df["__key"] = existing_df["Opportunity"].str.lower()
        updates_df["__key"] = updates_df["Opportunity"].str.lower()

        merged = pd.concat([existing_df, updates_df], ignore_index=True)
        merged = (
            merged.sort_values("__key")
            .drop_duplicates("__key", keep="last")
            .drop(columns="__key")[["Opportunity", "Classification"]]
            .fillna("")
            .astype(str)
        )

        rows = [list(merged.columns)] + merged.values.tolist()
        ws.clear()
        ws.resize(rows=len(rows), cols=len(rows[0]))
        ws.update(f"A1:B{len(rows)}", rows, value_input_option="RAW")

        new_vals = ws.get_all_values()
        st.success(f"✅ {len(merged)} rows now stored in Google Sheet ({len(new_vals) - 1} data rows).")
    except Exception as e:
        st.error(f"💥 Error saving to Google Sheets: {e}")

# -----------------------------------------------------------------------------
# UTILITIES
# -----------------------------------------------------------------------------
def extract_opportunities(raw_text: str):
    """Extract valid opportunity lines from user text."""
    lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
    opps = []
    for line in lines:
        line = line.replace("•", "").replace("●", "").replace("–", "-").replace("—", "-")
        if line.endswith(":") or len(line.split()) < 3:
            continue
        if re.match(r"^[A-Z\s]+:$", line):
            continue
        if re.match(r"^(FOH|BOH|BOTH|NOTES|SUMMARY)\b[:\-]?", line, re.I):
            continue
        opps.append(line)
    return opps

def clean_for_pdf(s: str):
    """Sanitize text for PDF rendering."""
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = re.sub(r"[\u200B-\u200D\uFEFF]", "", s)
    s = s.replace("\u00A0", " ")
    s = re.sub(r"[^\x20-\x7E]", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s

# -----------------------------------------------------------------------------
# PDF GENERATION (safe & formatted)
# -----------------------------------------------------------------------------
def generate_pdf(store_num: str, oe_cycle: str, df: pd.DataFrame):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    content_width = pdf.w - pdf.l_margin - pdf.r_margin
    bullet_w = 4
    text_w = content_width - bullet_w

    # Header
    if os.path.exists(LOGO_PATH):
        pdf.image(LOGO_PATH, x=10, y=8, w=30)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "IHOP OE One Pager", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 10, f"Store #{store_num} | OE Cycle: {oe_cycle}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(6)

    def bullet_line(txt):
        t = clean_for_pdf(txt)
        if not t:
            t = "[Empty]"
        if len(t) > 500:
            t = t[:500] + "..."
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(bullet_w, 6, "- ", ln=0)
        try:
            pdf.multi_cell(text_w, 6, t)
        except Exception:
            safe = re.sub(r"[^A-Za-z0-9 .,!?-]", "", t)[:150]
            pdf.multi_cell(text_w, 6, safe + " [sanitized]")

    def section(title, subset):
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        if subset.empty:
            pdf.cell(bullet_w, 6, "- ", ln=0)
            pdf.multi_cell(text_w, 6, "None")
        else:
            for _, row in subset.iterrows():
                bullet_line(row["Opportunity"])
        pdf.ln(4)

    foh = df[df["Classification"].isin(["FOH", "BOTH"])]
    boh = df[df["Classification"].isin(["BOH", "BOTH"])]

    section("FRONT OF HOUSE (FOH)", foh)
    section("BACK OF HOUSE (BOH)", boh)

    pdf.set_font("Helvetica", "I", 9)
    pdf.cell(0, 8, f"Generated {datetime.now():%Y-%m-%d %H:%M}", align="R")

    buffer = BytesIO()
    pdf.output(buffer)
    buffer.seek(0)
    return buffer

# -----------------------------------------------------------------------------
# STREAMLIT UI
# -----------------------------------------------------------------------------
try:
    ws_test = open_ws()
    st.success(f"✅ Connected to Google Sheet: **{WORKSHEET_TITLE}** (ID: {SPREADSHEET_ID})")
except Exception as e:
    st.error(f"❌ Could not connect to Google Sheets: {e}")
    st.stop()

if os.path.exists(LOGO_PATH):
    st.image(LOGO_PATH, width=120)
st.title("🥞 IHOP OE One Pager")

store_num = st.text_input("Store Number")
oe_cycle = st.text_input("OE Cycle")
user_input = st.text_area("Paste OE Notes or Opportunities Below:", height=250)

if user_input.strip():
    opportunities = extract_opportunities(user_input)
    st.write(f"✅ Found **{len(opportunities)}** valid opportunities.")
    if opportunities:
        st.divider()
        st.markdown("### 🏷️ Review & Confirm Classifications")

        updated_rows = []
        for opp in opportunities:
            selected = st.radio(
                f"**{opp}**", CLASS_CHOICES,
                horizontal=True, key=opp, index=0
            )
            updated_rows.append((opp, selected))

        st.warning("⚠️ Review classifications before generating the PDF.")
        st.divider()

        if st.button("💾 Save & Generate PDF One Pager"):
            updates_df = pd.DataFrame(updated_rows, columns=["Opportunity", "Classification"])
            save_classifications_merge(updates_df)
            pdf_data = generate_pdf(store_num, oe_cycle, updates_df)
            st.download_button(
                label="⬇️ Download PDF One Pager",
                data=pdf_data,
                file_name=f"IHOP_OE_{store_num}_{oe_cycle}_{datetime.now():%Y%m%d}.pdf",
                mime="application/pdf",
            )
else:
    st.info("Enter store info and paste OE notes to begin.")
