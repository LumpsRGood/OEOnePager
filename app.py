# app.py
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

# ---- Secrets (set in Streamlit Secrets) -------------------------------------
# [gcp_service_account] ... (the service account JSON you provided earlier)
# [gsheets]
# spreadsheet_id = "<YOUR_SHEET_ID>"        # <-- REQUIRED
# worksheet_title = "Sheet1"                 # <-- or your tab name
SPREADSHEET_ID = st.secrets["gsheets"]["spreadsheet_id"]
WORKSHEET_TITLE = st.secrets["gsheets"].get("worksheet_title", "Sheet1")

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
    client = get_gsheet_client()
    ss = client.open_by_key(SPREADSHEET_ID)
    try:
        ws = ss.worksheet(WORKSHEET_TITLE)
    except gspread.exceptions.WorksheetNotFound:
        ws = ss.add_worksheet(title=WORKSHEET_TITLE, rows=1000, cols=2)
        ws.update("A1:B1", [["Opportunity", "Classification"]])
    return ws

def df_from_ws(ws) -> pd.DataFrame:
    values = ws.get_all_values()
    if not values:
        return pd.DataFrame(columns=["Opportunity", "Classification"])
    df = pd.DataFrame(values[1:], columns=values[0])  # skip header row
    # keep only required columns, fill missing
    for col in ["Opportunity", "Classification"]:
        if col not in df.columns:
            df[col] = ""
    df = df[["Opportunity", "Classification"]].fillna("")
    # drop completely empty lines
    df = df[(df["Opportunity"].astype(str).str.strip() != "") | (df["Classification"].astype(str).str.strip() != "")]
    # force string dtype
    df = df.astype({"Opportunity": "string", "Classification": "string"})
    return df.reset_index(drop=True)

def ws_write_df(ws, df: pd.DataFrame):
    """Resize + write values. Then read back to verify."""
    out = df[["Opportunity", "Classification"]].copy()
    out = out.fillna("").astype(str)

    rows = [list(out.columns)] + out.values.tolist()
    nrows = len(rows)
    ncols = len(rows[0]) if rows else 2

    # Resize then write
    ws.resize(rows=nrows or 1, cols=ncols or 2)
    ws.update(f"A1:{chr(ord('A') + ncols - 1)}{nrows}", rows, value_input_option="RAW")

def load_classifications() -> pd.DataFrame:
    try:
        ws = open_ws()
        return df_from_ws(ws)
    except Exception as e:
        st.error(f"❌ Error loading data from Google Sheets: {e}")
        return pd.DataFrame(columns=["Opportunity", "Classification"])

def save_classifications_merge(updates_df: pd.DataFrame):
    """Merge updates into sheet without clearing other users' rows, then write."""
    try:
        ws = open_ws()
        existing_df = df_from_ws(ws)

        # normalize
        for df in (existing_df, updates_df):
            df["Opportunity"] = df["Opportunity"].astype(str).str.strip()
            df["Classification"] = df["Classification"].astype(str).str.strip()

        # add helper key for case-insensitive merge
        existing_df["__key"] = existing_df["Opportunity"].str.lower()
        updates_df["__key"] = updates_df["Opportunity"].str.lower()

        merged = pd.concat([existing_df, updates_df], ignore_index=True)
        merged = merged.sort_values("__key").drop_duplicates("__key", keep="last")
        merged = merged.drop(columns="__key")[["Opportunity", "Classification"]].fillna("")

        ws_write_df(ws, merged)

        # read-back verification
        after = df_from_ws(ws)
        st.success(f"✅ Saved {len(updates_df)} updates. Sheet now has {len(after)} rows.")
    except Exception as e:
        st.error(f"💥 Error saving to Google Sheets: {e}")

# -----------------------------------------------------------------------------
# TEXT PARSING & PDF-SAFE SANITIZATION
# -----------------------------------------------------------------------------
def extract_opportunities(raw_text: str) -> list[str]:
    lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
    opps: list[str] = []
    for line in lines:
        # normalize bullets/dashes early (keep ':' logic intact)
        line = line.replace("•", "").replace("●", "").replace("–", "-").replace("—", "-").strip()
        if line.endswith(":"):
            continue
        if re.match(r"^[A-Z\s]+:$", line):
            continue
        if len(line.split()) < 3:
            continue
        if re.match(r"^(FOH|BOH|BOTH|NOTES|SUMMARY)\b[:\-]?", line, re.I):
            continue
        opps.append(line)
    return opps

def clean_for_pdf(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = re.sub(r"[\u200B-\u200D\uFEFF]", "", s)   # zero-widths
    s = s.replace("\u00A0", " ")                  # NBSP
    s = s.replace("\t", " ").replace("\r", " ").replace("\n", " ")
    s = re.sub(r"[^\x20-\x7E]", "", s)            # non-ASCII
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s

# -----------------------------------------------------------------------------
# PDF GENERATION (hanging bullets, fixed widths, no crash)
# -----------------------------------------------------------------------------
def generate_pdf(store_num: str, oe_cycle: str, df: pd.DataFrame) -> BytesIO:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # margins & widths
    content_width = pdf.w - pdf.l_margin - pdf.r_margin
    bullet_w = 4  # width for "- "
    text_w = content_width - bullet_w

    # Header
    if os.path.exists(LOGO_PATH):
        pdf.image(LOGO_PATH, x=10, y=8, w=30)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "IHOP OE One Pager", new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 10, f"Store #{store_num} | OE Cycle: {oe_cycle}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(6)

    # Sections
    foh_items = df[df["Classification"].isin(["FOH", "BOTH"])]
    boh_items = df[df["Classification"].isin(["BOH", "BOTH"])]

    def bullet_line(text: str):
        """Hanging bullet: small cell for dash + multi_cell for wrapped text, fixed widths."""
        t = clean_for_pdf(text)
        if not t:
            t = "[Empty]"
        if len(t) > 500:
            t = t[:500] + "..."
        # draw bullet segment
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(bullet_w, 6, "- ", ln=0)
        # draw text in remaining width; ensure at least 1 char fits
        try:
            pdf.multi_cell(text_w, 6, t)
        except Exception:
            safe = re.sub(r"[^A-Za-z0-9 .,!?-]", "", t)[:150]
            pdf.multi_cell(text_w, 6, f"{safe} [sanitized]")

    def section(title: str, items: pd.DataFrame):
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        if items.empty:
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(bullet_w, 6, "- ", ln=0)
            pdf.multi_cell(text_w, 6, "None")
            pdf.ln(2)
            return
        for _, row in items.iterrows():
            bullet_line(str(row["Opportunity"]))
        pdf.ln(2)

    section("FRONT OF HOUSE (FOH)", foh_items)
    section("BACK OF HOUSE (BOH)", boh_items)

    pdf.set_font("Helvetica", "I", 9)
    pdf.cell(0, 8, f"Generated {datetime.now():%Y-%m-%d %H:%M}", align="R")

    out = BytesIO()
    pdf.output(out)
    out.seek(0)
    return out

# -----------------------------------------------------------------------------
# STREAMLIT UI
# -----------------------------------------------------------------------------
if os.path.exists(LOGO_PATH):
    st.image(LOGO_PATH, width=120)
st.title("🥞 IHOP OE One Pager")

store_num = st.text_input("Store Number")
oe_cycle = st.text_input("OE Cycle")
user_input = st.text_area("Paste OE Notes or Opportunities Below:", height=250)

# load current DB
classification_db = load_classifications()

if user_input.strip():
    opportunities = extract_opportunities(user_input)
    st.write(f"✅ Found **{len(opportunities)}** valid opportunities.")
    if opportunities:
        # ensure each pasted opp exists in DB
        existing_keys = set(classification_db["Opportunity"].str.lower())
        missing = [o for o in opportunities if o.lower() not in existing_keys]
        if missing:
            st.info(f"🆕 Adding {len(missing)} new opportunities to database preview (will be saved on submit).")
            classification_db = pd.concat([
                classification_db,
                pd.DataFrame({"Opportunity": missing, "Classification": [""] * len(missing)})
            ], ignore_index=True)

        st.divider()
        st.markdown("### 🏷️ Review & Confirm Classifications")

        updated_rows = []
        for opp in opportunities:
            row = classification_db.loc[classification_db["Opportunity"].str.lower() == opp.lower()]
            preselect = row["Classification"].iloc[0] if not row.empty and row["Classification"].iloc[0] in CLASS_CHOICES else "FOH"
            selected = st.radio(
                f"**{opp}**", CLASS_CHOICES, horizontal=True,
                index=CLASS_CHOICES.index(preselect), key=opp
            )
            updated_rows.append((opp, selected))

        st.warning("⚠️ Review classifications before generating the PDF.")
        st.divider()

        if st.button("💾 Save & Generate PDF One Pager"):
            # build updates df and MERGE into sheet
            updates_df = pd.DataFrame(updated_rows, columns=["Opportunity", "Classification"])
            save_classifications_merge(updates_df)

            # generate session PDF
            pdf_data = generate_pdf(store_num, oe_cycle, updates_df)
            st.download_button(
                label="⬇️ Download PDF One Pager",
                data=pdf_data,
                file_name=f"IHOP_OE_{store_num}_{oe_cycle}_{datetime.now():%Y%m%d}.pdf",
                mime="application/pdf",
            )
else:
    st.info("Enter store info and paste OE notes to begin.")
