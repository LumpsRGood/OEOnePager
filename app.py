# app.py
import os
import re
import pandas as pd
import streamlit as st
from datetime import datetime
from io import BytesIO
from fpdf import FPDF

st.set_page_config(page_title="IHOP OE One Pager", layout="wide")

LOGO_PATH = "ihop_logo.png"
EXCEL_FILE = "OE_Opportunities_Classification.xlsx"

# --- Utility Functions ---


@st.cache_data
def load_classifications(path: str) -> pd.DataFrame:
    """Load or create classification database."""
    if os.path.exists(path):
        df = pd.read_excel(path)
    else:
        df = pd.DataFrame(columns=["Opportunity", "Classification"])
    df["Opportunity"] = df["Opportunity"].astype(str).str.strip()
    df["Classification"] = df["Classification"].astype(str).str.strip()
    return df


def save_classifications(df: pd.DataFrame, path: str):
    """Save classification DB to Excel."""
    df.to_excel(path, index=False)
    st.toast("✅ Classification database updated.")


def extract_opportunities(raw_text: str):
    """Extract opportunity-like lines from pasted notes."""
    lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
    opportunities = []
    for l in lines:
        if len(l.split()) < 3 or l.endswith(":") or re.match(r"^[A-Z\s]+:$", l):
            continue
        opportunities.append(l)
    return opportunities


def sync_new_opportunities(existing_df: pd.DataFrame, new_ops: list) -> pd.DataFrame:
    """Add new opportunities to DB if not already present."""
    existing = set(existing_df["Opportunity"].str.lower())
    missing = [o for o in new_ops if o.lower() not in existing]
    if missing:
        st.info(f"🆕 Found {len(missing)} new opportunities to classify.")
        new_df = pd.DataFrame({"Opportunity": missing, "Classification": [""] * len(missing)})
        return pd.concat([existing_df, new_df], ignore_index=True)
    return existing_df


def generate_pdf(store_num: str, oe_cycle: str, df: pd.DataFrame) -> BytesIO:
    """Generate PDF with FOH and BOH sections using fpdf2."""
    pdf = FPDF()
    pdf.add_page()

    # Add Unicode font (DejaVu bundled in fpdf2)
    pdf.add_font("DejaVu", "", fname=None, uni=True)
    pdf.set_font("DejaVu", "", 14)

    # Logo
    if os.path.exists(LOGO_PATH):
        pdf.image(LOGO_PATH, x=10, y=8, w=30)

    # Header
    pdf.cell(200, 10, "IHOP OE One Pager", ln=True, align="C")
    pdf.set_font("DejaVu", "", 11)
    pdf.cell(200, 10, f"Store #{store_num} | OE Cycle: {oe_cycle}", ln=True, align="C")
    pdf.ln(10)

    # Split data
    foh_items = df[df["Classification"].isin(["FOH", "BOTH"])]
    boh_items = df[df["Classification"].isin(["BOH", "BOTH"])]

    # Helper to print section
    def section(title, items):
        pdf.set_font("DejaVu", "B", 12)
        pdf.cell(0, 8, title, ln=True)
        pdf.set_font("DejaVu", "", 10)
        for _, row in items.iterrows():
            pdf.multi_cell(0, 6, f"• {row['Opportunity']}", align="L")
        pdf.ln(4)

    # Sections
    if not foh_items.empty:
        section("FRONT OF HOUSE (FOH)", foh_items)
    if not boh_items.empty:
        section("BACK OF HOUSE (BOH)", boh_items)

    # Export to memory
    pdf_bytes = BytesIO()
    pdf.output(pdf_bytes)
    pdf_bytes.seek(0)
    return pdf_bytes


# --- UI Layout ---

if os.path.exists(LOGO_PATH):
    st.image(LOGO_PATH, width=120)
st.title("🥞 IHOP OE One Pager")

store_num = st.text_input("Store Number")
oe_cycle = st.text_input("OE Cycle")
user_input = st.text_area("Paste OE Notes or Opportunities Below:", height=250)

classification_db = load_classifications(EXCEL_FILE)

if user_input.strip():
    opportunities = extract_opportunities(user_input)
    st.write(f"✅ Found {len(opportunities)} opportunities.")

    if opportunities:
        # Sync with master DB
        classification_db = sync_new_opportunities(classification_db, opportunities)

        st.divider()
        st.markdown("### 🏷️ Review & Classify Opportunities")

        updated_rows = []
        for opp in opportunities:
            current_value = classification_db.loc[
                classification_db["Opportunity"].str.lower() == opp.lower(), "Classification"
            ].values
            preselect = current_value[0] if len(current_value) > 0 and current_value[0] else "FOH"

            selected = st.radio(
                f"**{opp}**",
                ["FOH", "BOH", "BOTH"],
                horizontal=True,
                index=["FOH", "BOH", "BOTH"].index(preselect)
                if preselect in ["FOH", "BOH", "BOTH"]
                else 0,
                key=opp,
            )
            updated_rows.append((opp, selected))

        st.warning("⚠️ Please review all classifications before generating the PDF.")
        st.divider()

        if st.button("💾 Save & Generate PDF One Pager"):
            # Update DB
            for opp, selected in updated_rows:
                mask = classification_db["Opportunity"].str.lower() == opp.lower()
                if mask.any():
                    classification_db.loc[mask, "Classification"] = selected
                else:
                    classification_db.loc[len(classification_db)] = [opp, selected]

            save_classifications(classification_db, EXCEL_FILE)

            # Generate PDF from current session data
            session_df = pd.DataFrame(updated_rows, columns=["Opportunity", "Classification"])
            pdf_data = generate_pdf(store_num, oe_cycle, session_df)

            st.download_button(
                label="⬇️ Download PDF One Pager",
                data=pdf_data,
                file_name=f"IHOP_OE_{store_num}_{oe_cycle}_{datetime.now():%Y%m%d}.pdf",
                mime="application/pdf",
            )
else:
    st.info("Enter store info and paste OE notes to start.")
