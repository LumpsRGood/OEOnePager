# app.py
import os
import re
import pandas as pd
import streamlit as st
from fpdf import FPDF
from datetime import datetime

st.set_page_config(page_title="IHOP OE One Pager", layout="wide")

LOGO_PATH = "ihop_logo.png"
EXCEL_FILE = "OE_Opportunities_Classification.xlsx"


# --- Utility Functions ---

@st.cache_data
def load_classifications(path: str) -> pd.DataFrame:
    """Load or create the classification database."""
    if os.path.exists(path):
        df = pd.read_excel(path)
    else:
        df = pd.DataFrame(columns=["Opportunity", "Classification"])
    df["Opportunity"] = df["Opportunity"].astype(str).str.strip()
    df["Classification"] = df["Classification"].astype(str).str.strip()
    return df


def save_classifications(df: pd.DataFrame, path: str):
    """Persist updated classification database."""
    df.to_excel(path, index=False)
    st.toast("✅ Updated classifications saved.")


def extract_opportunities(raw_text: str):
    """Extract clean, meaningful opportunities."""
    lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
    opportunities = []
    for l in lines:
        if len(l.split()) < 3 or l.endswith(":") or re.match(r"^[A-Z\s]+:$", l):
            continue
        opportunities.append(l)
    return opportunities


def generate_pdf(store_num: str, oe_cycle: str, df: pd.DataFrame):
    """Generate a one-pager PDF report."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)

    if os.path.exists(LOGO_PATH):
        pdf.image(LOGO_PATH, x=10, y=8, w=30)

    pdf.cell(200, 10, "IHOP OE One Pager", ln=True, align="C")
    pdf.set_font("Arial", "", 12)
    pdf.cell(200, 10, f"Store #{store_num} | OE Cycle: {oe_cycle}", ln=True, align="C")
    pdf.ln(10)

    pdf.set_font("Arial", "B", 12)
    pdf.cell(140, 8, "Opportunity", border=1)
    pdf.cell(40, 8, "Classification", border=1, ln=True)

    pdf.set_font("Arial", "", 11)
    for _, row in df.iterrows():
        pdf.cell(140, 8, row["Opportunity"][:80], border=1)
        pdf.cell(40, 8, row["Classification"], border=1, ln=True)

    filename = f"IHOP_OE_{store_num}_{oe_cycle}_{datetime.now():%Y%m%d}.pdf"
    pdf.output(filename)
    return filename


def sync_new_opportunities(existing_df, new_ops):
    """Add missing opportunities to classification DB."""
    existing = set(existing_df["Opportunity"].str.lower())
    missing = [o for o in new_ops if o.lower() not in existing]
    if missing:
        st.info(f"🆕 Found {len(missing)} new opportunities to classify.")
        new_df = pd.DataFrame({"Opportunity": missing, "Classification": [""] * len(missing)})
        updated_df = pd.concat([existing_df, new_df], ignore_index=True)
    else:
        updated_df = existing_df
    return updated_df


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

        # Display classification check UI
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
                index=["FOH", "BOH", "BOTH"].index(preselect) if preselect in ["FOH", "BOH", "BOTH"] else 0,
                key=opp,
            )
            updated_rows.append((opp, selected))

        st.warning("⚠️ Please review all classifications before generating the PDF.")
        st.divider()

        if st.button("💾 Save & Generate PDF One Pager"):
            # Update database
            for opp, selected in updated_rows:
                mask = classification_db["Opportunity"].str.lower() == opp.lower()
                if mask.any():
                    classification_db.loc[mask, "Classification"] = selected
                else:
                    classification_db.loc[len(classification_db)] = [opp, selected]

            save_classifications(classification_db, EXCEL_FILE)

            # Generate PDF for current session only
            session_df = pd.DataFrame(updated_rows, columns=["Opportunity", "Classification"])
            pdf_path = generate_pdf(store_num, oe_cycle, session_df)
            with open(pdf_path, "rb") as f:
                st.download_button(
                    label="⬇️ Download PDF One Pager",
                    data=f,
                    file_name=os.path.basename(pdf_path),
                    mime="application/pdf"
                )
else:
    st.info("Enter store info and paste OE notes to start.")

