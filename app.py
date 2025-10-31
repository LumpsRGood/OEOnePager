import os
import re
import time
import unicodedata
from io import BytesIO
from datetime import datetime
import pandas as pd
import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from fpdf import FPDF
from fpdf.enums import XPos, YPos

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
st.set_page_config(page_title="IHOP OE One Pager", layout="wide")

LOGO_PATH = "ihop_logo.png"
CLASS_CHOICES = ["FOH", "BOH", "BOTH"]

try:
    SPREADSHEET_ID = st.secrets["gsheets"]["spreadsheet_id"]
    WORKSHEET_TITLE = st.secrets["gsheets"].get("worksheet_title", "Sheet1")
except Exception:
    st.error("❌ Missing [gsheets] in secrets.toml (spreadsheet_id, worksheet_title)")
    st.stop()

# ---------------------------------------------------------------------------
# GOOGLE SHEETS CONNECTION
# ---------------------------------------------------------------------------
def get_gsheet_client():
    creds_info = st.secrets["gcp_service_account"]
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
    return gspread.authorize(creds)

def open_ws():
    client = get_gsheet_client()
    ss = client.open_by_key(SPREADSHEET_ID)
    try:
        return ss.worksheet(WORKSHEET_TITLE)
    except gspread.exceptions.WorksheetNotFound:
        ws = ss.add_worksheet(title=WORKSHEET_TITLE, rows=1000, cols=2)
        ws.update([["Opportunity", "Classification"]], range_name="A1", value_input_option="RAW")
        return ws

def df_from_ws(ws):
    vals = ws.get_all_values()
    if not vals:
        return pd.DataFrame(columns=["Opportunity", "Classification"])
    df = pd.DataFrame(vals[1:], columns=vals[0])
    df = df.reindex(columns=["Opportunity", "Classification"], fill_value="")
    df = df.fillna("").astype(str)
    return df[df["Opportunity"].str.strip() != ""].reset_index(drop=True)

# ---------------------------------------------------------------------------
# NORMALIZATION
# ---------------------------------------------------------------------------
def normalize_text(s: str) -> str:
    """Normalize invisible characters, dashes, and spaces."""
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"[\u200B-\u200D\uFEFF]", "", s)  # zero-width
    s = s.replace("\u2013", "-").replace("\u2014", "-")  # en/em dash
    s = s.replace("\u00A0", " ")  # NBSP
    s = re.sub(r"[^\x20-\x7E]", "", s)  # strip non-ASCII
    return s.strip()

# ---------------------------------------------------------------------------
# SAVE CLASSIFICATIONS (FULL REPLACE METHOD)
# ---------------------------------------------------------------------------
def save_classifications_replace_all(updates_df):
    """Completely replaces the sheet body on each save — safest method."""
    try:
        ws = open_ws()

        updates_df["Opportunity"] = updates_df["Opportunity"].apply(normalize_text)
        updates_df["Classification"] = updates_df["Classification"].astype(str).str.strip()

        existing_df = df_from_ws(ws)
        existing_df["Opportunity"] = existing_df["Opportunity"].apply(normalize_text)
        existing_df["Classification"] = existing_df["Classification"].astype(str).str.strip()

        merged = (
            pd.concat([existing_df, updates_df], ignore_index=True)
            .drop_duplicates(subset=["Opportunity"], keep="last")
            .reset_index(drop=True)
        )

        all_rows = [["Opportunity", "Classification"]] + merged.values.tolist()
        ws.batch_clear(["A1:B1000"])
        time.sleep(0.5)
        ws.update(all_rows, range_name="A1", value_input_option="RAW")

        st.success(f"✅ Rewrote {len(merged)} rows to Google Sheet (full replace).")

        bdp_rows = merged[merged["Opportunity"].str.contains("BDP", case=False)]
        if not bdp_rows.empty:
            st.write("🧩 Debug – BDP entries written:")
            st.dataframe(bdp_rows)

        return merged

    except Exception as e:
        st.error(f"💥 Sheet replace failed: {e}")
        return None

# ---------------------------------------------------------------------------
# EXTRACT OPPORTUNITIES
# ---------------------------------------------------------------------------
def extract_opportunities(raw_text):
    lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
    opps = []
    for line in lines:
        line = normalize_text(line)
        line = line.replace("•", "").replace("●", "").replace("–", "-").replace("—", "-")
        if line.endswith(":") or len(line.split()) < 3:
            continue
        if re.match(r"^[A-Z\s]+:$", line):
            continue
        if re.match(r"^(FOH|BOH|BOTH|NOTES|SUMMARY)\b[:\-]?", line, re.I):
            continue
        opps.append(line)
    return opps

# ---------------------------------------------------------------------------
# PDF GENERATION (ARIAL, POLISHED)
# ---------------------------------------------------------------------------
def generate_pdf(store_num, oe_cycle, df):
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    margin_left = 15
    margin_right = 15
    content_width = 210 - margin_left - margin_right
    line_spacing = 6

    # --- Header ---
    if os.path.exists(LOGO_PATH):
        pdf.image(LOGO_PATH, x=10, y=8, w=30)
    pdf.set_font("Arial", "B", 18)
    pdf.cell(0, 10, "IHOP OE One Pager", align="C", ln=True)
    pdf.set_font("Arial", "", 12)
    pdf.cell(0, 8, f"Store #{store_num}  |  OE Cycle: {oe_cycle}", align="C", ln=True)
    pdf.ln(6)
    pdf.set_draw_color(0, 102, 204)
    pdf.set_line_width(0.8)
    pdf.line(margin_left, pdf.get_y(), 210 - margin_right, pdf.get_y())
    pdf.ln(8)

    # --- Text sanitizer ---
    def safe_text(text):
        """Force ASCII-compatible text for FPDF core fonts."""
        text = normalize_text(text)
        # Replace “smart quotes”, dashes, and bullets with ASCII equivalents
        replacements = {
            "“": '"', "”": '"', "‘": "'", "’": "'",
            "–": "-", "—": "-", "•": "-", "●": "-",
            "°": " deg", "…": "...", "→": "->",
        }
        for bad, good in replacements.items():
            text = text.replace(bad, good)
        text = re.sub(r"[^\x20-\x7E]", "", text)  # remove any leftover non-ASCII
        return text.strip()

    # --- Section helpers ---
    def section_header(title, color=(0, 102, 204)):
        pdf.set_font("Arial", "B", 13)
        pdf.set_text_color(*color)
        pdf.cell(0, 8, title, ln=True)
        pdf.set_draw_color(200, 200, 200)
        pdf.set_line_width(0.3)
        pdf.line(margin_left, pdf.get_y(), 210 - margin_right, pdf.get_y())
        pdf.ln(4)

    def bullet_item(text):
        pdf.set_font("Arial", "", 11)
        pdf.set_text_color(0, 0, 0)
        text = safe_text(text)
        pdf.multi_cell(content_width, line_spacing, f"• {text}")
        pdf.ln(1)

    def section(title, subset):
        section_header(title)
        if subset.empty:
            pdf.set_font("Arial", "I", 11)
            pdf.set_text_color(120, 120, 120)
            pdf.cell(0, line_spacing, "- None -", ln=True)
            pdf.ln(2)
        else:
            for _, row in subset.iterrows():
                bullet_item(row["Opportunity"])
            pdf.ln(4)

    # --- Split Data ---
    foh = df[df["Classification"].isin(["FOH", "BOTH"])]
    boh = df[df["Classification"].isin(["BOH", "BOTH"])]

    # --- Summary ---
    total_foh = len(foh)
    total_boh = len(boh)
    pdf.set_font("Arial", "B", 11)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 8, f"Summary: {total_foh} FOH items | {total_boh} BOH items", ln=True)
    pdf.ln(4)

    # --- Sections ---
    section("FRONT OF HOUSE (FOH)", foh)
    section("BACK OF HOUSE (BOH)", boh)

    # --- Footer ---
    pdf.set_y(-20)
    pdf.set_font("Arial", "I", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 8, f"Generated {datetime.now():%Y-%m-%d %H:%M} | IHOP Confidential", align="C")

    out = BytesIO()
    pdf.output(out)
    out.seek(0)
    return out

# ---------------------------------------------------------------------------
# STREAMLIT UI
# ---------------------------------------------------------------------------
if os.path.exists(LOGO_PATH):
    st.image(LOGO_PATH, width=120)

st.title("🥞 IHOP OE One Pager")

try:
    ws_test = open_ws()
    st.success(f"✅ Connected to Google Sheet: {WORKSHEET_TITLE}")
except Exception as e:
    st.error(f"❌ Google Sheets connection failed: {e}")
    st.stop()

store_num = st.text_input("Store Number")
oe_cycle = st.text_input("OE Cycle")
user_input = st.text_area("Paste OE Notes or Opportunities Below:", height=250)

classification_db = df_from_ws(ws_test)

if user_input.strip():
    opportunities = extract_opportunities(user_input)
    st.write(f"✅ Found **{len(opportunities)}** opportunities.")

    if opportunities:
        st.divider()
        st.markdown("### 🏷️ Review & Confirm Classifications")

        normalized_existing = classification_db["Opportunity"].apply(normalize_text).str.lower().tolist()
        updated_rows = []
        new_items = []

        new_count = sum(1 for opp in opportunities if normalize_text(opp).lower() not in normalized_existing)
        if new_count:
            st.info(f"🆕 {new_count} new opportunities detected — please review carefully.")

        for opp in opportunities:
            norm_opp = normalize_text(opp).lower()
            is_new = norm_opp not in normalized_existing

            existing_match = classification_db.loc[
                classification_db["Opportunity"].apply(normalize_text).str.lower() == norm_opp,
                "Classification",
            ]
            preselect = (
                existing_match.iloc[0]
                if len(existing_match) and existing_match.iloc[0] in CLASS_CHOICES
                else "FOH"
            )

            display_label = f"**{opp}**"
            if is_new:
                display_label = f"🆕 **{opp}**"

            selected = st.radio(
                display_label,
                CLASS_CHOICES,
                horizontal=True,
                key=opp,
                index=CLASS_CHOICES.index(preselect),
            )

            updated_rows.append((opp, selected))
            if is_new:
                new_items.append(opp)

        if new_items:
            st.warning("⚠️ New opportunities marked with 🆕 — confirm classifications before saving.")

        st.divider()

        if st.button("💾 Save & Generate PDF One Pager"):
            updates_df = pd.DataFrame(updated_rows, columns=["Opportunity", "Classification"])
            merged = save_classifications_replace_all(updates_df)
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
