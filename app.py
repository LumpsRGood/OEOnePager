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
CLASS_CHOICES = ["FOH", "BOH", "BOTH"]

# ---- Load secrets safely ----
try:
    SPREADSHEET_ID = st.secrets["gsheets"]["spreadsheet_id"]
    WORKSHEET_TITLE = st.secrets["gsheets"].get("worksheet_title", "Sheet1")
except Exception:
    st.error("❌ Missing [gsheets] in secrets.toml (spreadsheet_id, worksheet_title)")
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
    client = get_gsheet_client()
    ss = client.open_by_key(SPREADSHEET_ID)
    try:
        ws = ss.worksheet(WORKSHEET_TITLE)
    except gspread.exceptions.WorksheetNotFound:
        ws = ss.add_worksheet(title=WORKSHEET_TITLE, rows=1000, cols=2)
        ws.update("A1:B1", [["Opportunity", "Classification"]])
    return ws


def df_from_ws(ws):
    """Read entire worksheet as a clean DataFrame."""
    vals = ws.get_all_values()
    if not vals:
        return pd.DataFrame(columns=["Opportunity", "Classification"])
    df = pd.DataFrame(vals[1:], columns=vals[0])
    for col in ["Opportunity", "Classification"]:
        if col not in df.columns:
            df[col] = ""
    df = df[["Opportunity", "Classification"]].fillna("")
    df = df[df["Opportunity"].astype(str).str.strip() != ""]
    return df.astype(str).reset_index(drop=True)


def save_classifications_merge(updates_df):
    """Merge updates with existing sheet data."""
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
        ws.update("A1", rows, value_input_option="RAW")

        st.success(f"✅ Saved {len(merged)} total rows to Google Sheet.")
        return merged

    except Exception as e:
        st.error(f"💥 Error saving to Google Sheets: {e}")
        return None


# -----------------------------------------------------------------------------
# UTILITIES
# -----------------------------------------------------------------------------
def extract_opportunities(raw_text):
    """Extract valid opportunity lines."""
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
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = re.sub(r"[\u200B-\u200D\uFEFF]", "", s)
    s = s.replace("\u00A0", " ")
    s = re.sub(r"[^\x20-\x7E]", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s


# -----------------------------------------------------------------------------
# PDF GENERATION
# -----------------------------------------------------------------------------
def generate_pdf(store_num, oe_cycle, df):
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

    def bullet_line(t):
        text = clean_for_pdf(t)
        if not text:
            text = "[Empty]"
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(bullet_w, 6, "- ", ln=0)
        try:
            pdf.multi_cell(text_w, 6, text)
        except Exception:
            pdf.multi_cell(text_w, 6, re.sub(r"[^A-Za-z0-9 .,!?-]", "", text)[:100])

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

    buf = BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return buf


# -----------------------------------------------------------------------------
# STREAMLIT UI
# -----------------------------------------------------------------------------
st.image(LOGO_PATH, width=120) if os.path.exists(LOGO_PATH) else None
st.title("🥞 IHOP OE One Pager")

try:
    ws_test = open_ws()
    st.success(f"✅ Connected to Google Sheet: {WORKSHEET_TITLE}")
except Exception as e:
    st.error(f"❌ Could not connect to Google Sheets: {e}")
    st.stop()

store_num = st.text_input("Store Number")
oe_cycle = st.text_input("OE Cycle")
user_input = st.text_area("Paste OE Notes or Opportunities Below:", height=250)

classification_db = df_from_ws(ws_test)

if user_input.strip():
    opportunities = extract_opportunities(user_input)
    st.write(f"✅ Found **{len(opportunities)}** valid opportunities.")

    if opportunities:
        st.divider()
        st.markdown("### 🏷️ Review & Confirm Classifications")

        updated_rows = []
        for opp in opportunities:
            # check if already classified
            match = classification_db.loc[
                classification_db["Opportunity"].str.lower() == opp.lower(), "Classification"
            ]
            preselect = match.iloc[0] if len(match) > 0 and match.iloc[0] in CLASS_CHOICES else "FOH"

            selected = st.radio(
                f"**{opp}**",
                CLASS_CHOICES,
                horizontal=True,
                key=opp,
                index=CLASS_CHOICES.index(preselect),
            )
            updated_rows.append((opp, selected))

        st.warning("⚠️ Review classifications before generating PDF.")
        st.divider()

        if st.button("💾 Save & Generate PDF One Pager"):
            updates_df = pd.DataFrame(updated_rows, columns=["Opportunity", "Classification"])
            merged = save_classifications_merge(updates_df)
            if merged is not None:
                pdf_data = generate_pdf(store_num, oe_cycle, updates_df)
                st.download_button(
                    label="⬇️ Download PDF One Pager",
                    data=pdf_data,
                    file_name=f"IHOP_OE_{store_num}_{oe_cycle}_{datetime.now():%Y%m%d}.pdf",
                    mime="application/pdf",
                )
else:
    st.info("Enter store info and paste OE notes to begin.")
