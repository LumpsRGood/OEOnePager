import os
import re
import unicodedata
import pandas as pd
import streamlit as st
from datetime import datetime
from io import BytesIO
from fpdf import FPDF
import gspread
from gspread_dataframe import get_as_dataframe
from oauth2client.service_account import ServiceAccountCredentials


# -----------------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------------
st.set_page_config(page_title="IHOP OE One Pager", layout="wide")
LOGO_PATH = "ihop_logo.png"
SHEET_NAME = "OE_Opportunities_Classification"


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


def load_classifications():
    """Load classifications from Google Sheet safely."""
    try:
        client = get_gsheet_client()
        sheet = client.open(SHEET_NAME).sheet1
        data = get_as_dataframe(sheet, evaluate_formulas=True, dtype=str)
        if data.empty or "Opportunity" not in data.columns:
            data = pd.DataFrame(columns=["Opportunity", "Classification"])
        data = data.fillna("")
        return data
    except Exception as e:
        st.error(f"❌ Error loading data: {e}")
        return pd.DataFrame(columns=["Opportunity", "Classification"])


def save_classifications(updated_df: pd.DataFrame):
    """Safely merge and update classifications without overwriting."""
    try:
        client = get_gsheet_client()
        sheet = client.open(SHEET_NAME).sheet1
        existing_df = get_as_dataframe(sheet, evaluate_formulas=True, dtype=str).fillna("")

        if existing_df.empty or "Opportunity" not in existing_df.columns:
            existing_df = pd.DataFrame(columns=["Opportunity", "Classification"])

        # Merge logic — preserve all, update duplicates
        updated_df["Opportunity_lower"] = updated_df["Opportunity"].str.lower()
        existing_df["Opportunity_lower"] = existing_df["Opportunity"].str.lower()
        merged_df = pd.concat([existing_df, updated_df], ignore_index=True)
        merged_df = (
            merged_df.sort_values(by="Opportunity_lower")
            .drop_duplicates(subset="Opportunity_lower", keep="last")
            .drop(columns=["Opportunity_lower"])
        )

        merged_df = merged_df.fillna("").astype(str)
        rows = [merged_df.columns.values.tolist()] + merged_df.values.tolist()

        # Update explicitly
        sheet.clear()
        sheet.update(rows)
        st.success("✅ Classifications merged & updated successfully!")
    except Exception as e:
        st.error(f"💥 Error updating Google Sheet: {e}")


# -----------------------------------------------------------------------------
# UTILITIES
# -----------------------------------------------------------------------------
def extract_opportunities(raw_text: str):
    """Extract valid opportunity lines."""
    lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
    opportunities = []
    for line in lines:
        line = line.replace("–", "-").replace("—", "-").replace("•", "").replace("●", "")
        if line.endswith(":") or len(line.split()) < 3:
            continue
        if re.match(r"^[A-Z\s]+:$", line) or re.match(r"^(FOH|BOH|BOTH|NOTES|SUMMARY)\b", line, re.I):
            continue
        opportunities.append(line)
    return opportunities


def sync_new_opportunities(existing_df: pd.DataFrame, new_ops: list) -> pd.DataFrame:
    """Add missing opportunities."""
    existing = set(existing_df["Opportunity"].str.lower())
    missing = [o for o in new_ops if o.lower() not in existing]
    if missing:
        st.info(f"🆕 Added {len(missing)} new opportunities to database.")
        new_df = pd.DataFrame({"Opportunity": missing, "Classification": [""] * len(missing)})
        existing_df = pd.concat([existing_df, new_df], ignore_index=True)
    return existing_df


def clean_for_pdf(s: str) -> str:
    """Normalize text to be FPDF-safe."""
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = re.sub(r"[\u200B-\u200D\uFEFF]", "", s)
    s = s.replace("\u00A0", " ")
    s = re.sub(r"[^\x20-\x7E]", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s


# -----------------------------------------------------------------------------
# PDF GENERATION (Stable)
# -----------------------------------------------------------------------------
def generate_pdf(store_num: str, oe_cycle: str, df: pd.DataFrame) -> BytesIO:
    """Generate a PDF safely with fixed column widths."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Header
    if os.path.exists(LOGO_PATH):
        pdf.image(LOGO_PATH, x=10, y=8, w=30)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "IHOP OE One Pager", new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 10, f"Store #{store_num} | OE Cycle: {oe_cycle}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(10)

    foh_items = df[df["Classification"].isin(["FOH", "BOTH"])]
    boh_items = df[df["Classification"].isin(["BOH", "BOTH"])]

    def section(title, items):
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        if items.empty:
            pdf.multi_cell(180, 6, "— None —")
        else:
            for _, row in items.iterrows():
                text = clean_for_pdf(row["Opportunity"])
                if not text:
                    text = "[Empty line]"
                if len(text) > 220:
                    text = text[:220] + "..."
                try:
                    pdf.multi_cell(180, 6, f"- {text}")
                except Exception:
                    safe_text = re.sub(r"[^A-Za-z0-9 .,!?-]", "", text)
                    pdf.multi_cell(180, 6, f"- {safe_text[:100]} [sanitized]")
        pdf.ln(4)

    section("FRONT OF HOUSE (FOH)", foh_items)
    section("BACK OF HOUSE (BOH)", boh_items)

    pdf.set_font("Helvetica", "I", 9)
    pdf.cell(0, 10, f"Generated {datetime.now():%Y-%m-%d %H:%M}", align="R")

    buffer = BytesIO()
    pdf.output(buffer)
    buffer.seek(0)
    return buffer


# -----------------------------------------------------------------------------
# STREAMLIT UI
# -----------------------------------------------------------------------------
if os.path.exists(LOGO_PATH):
    st.image(LOGO_PATH, width=120)
st.title("🥞 IHOP OE One Pager")

store_num = st.text_input("Store Number")
oe_cycle = st.text_input("OE Cycle")
user_input = st.text_area("Paste OE Notes or Opportunities Below:", height=250)

classification_db = load_classifications()

if user_input.strip():
    opportunities = extract_opportunities(user_input)
    st.write(f"✅ Found **{len(opportunities)}** opportunities.")

    if opportunities:
        classification_db = sync_new_opportunities(classification_db, opportunities)
        st.divider()
        st.markdown("### 🏷️ Review & Confirm Classifications")

        updated_rows = []
        for opp in opportunities:
            current_value = classification_db.loc[
                classification_db["Opportunity"].str.lower() == opp.lower(),
                "Classification",
            ].values
            preselect = current_value[0] if len(current_value) > 0 and current_value[0] else "FOH"

            selected = st.radio(
                f"**{opp}**",
                ["FOH", "BOH", "BOTH"],
                horizontal=True,
                index=["FOH", "BOH", "BOTH"].index(preselect),
                key=opp,
            )
            updated_rows.append((opp, selected))

        st.warning("⚠️ Review classifications before generating the PDF.")
        st.divider()

        if st.button("💾 Save & Generate PDF One Pager"):
            session_df = pd.DataFrame(updated_rows, columns=["Opportunity", "Classification"])
            save_classifications(session_df)
            pdf_data = generate_pdf(store_num, oe_cycle, session_df)
            st.download_button(
                label="⬇️ Download PDF One Pager",
                data=pdf_data,
                file_name=f"IHOP_OE_{store_num}_{oe_cycle}_{datetime.now():%Y%m%d}.pdf",
                mime="application/pdf",
            )
else:
    st.info("Enter store info and paste OE notes to begin.")
