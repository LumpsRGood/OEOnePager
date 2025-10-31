import os
import re
import pandas as pd
import streamlit as st
from datetime import datetime
from io import BytesIO
from fpdf import FPDF

# -----------------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------------
st.set_page_config(page_title="IHOP OE One Pager", layout="wide")

LOGO_PATH = "ihop_logo.png"
EXCEL_FILE = "OE_Opportunities_Classification.xlsx"


# -----------------------------------------------------------------------------
# UTILITIES
# -----------------------------------------------------------------------------
@st.cache_data
def load_classifications(file_path: str) -> pd.DataFrame:
    """Load or create the Excel classification DB."""
    if os.path.exists(file_path):
        df = pd.read_excel(file_path)
    else:
        df = pd.DataFrame(columns=["Opportunity", "Classification"])
    df["Opportunity"] = df["Opportunity"].astype(str).str.strip()
    df["Classification"] = df["Classification"].astype(str).str.strip()
    return df


def save_classifications(df: pd.DataFrame, file_path: str):
    """Save updates to the Excel classification DB."""
    df.to_excel(file_path, index=False)
    st.toast("✅ Classification database updated.")


def extract_opportunities(raw_text: str):
    """
    Extract opportunity lines, ignoring headers, short lines, and labels.
    Cleans up bullets and dashes.
    """
    lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
    opportunities = []

    for line in lines:
        # Clean up smart punctuation and bullets
        line = line.replace("–", "-").replace("—", "-").replace("•", "").replace("●", "").strip()

        # --- Exclusion rules ---
        if line.endswith(":"):
            continue
        if re.match(r"^[A-Z\s]+:$", line):
            continue
        if len(line.split()) < 3:
            continue
        if re.match(r"^(FOH|BOH|BOTH|NOTES|SUMMARY)\b[:\-]?", line, re.I):
            continue

        opportunities.append(line)
    return opportunities


def sync_new_opportunities(existing_df: pd.DataFrame, new_ops: list) -> pd.DataFrame:
    """Add new opportunities to DB if missing."""
    existing = set(existing_df["Opportunity"].str.lower())
    missing = [o for o in new_ops if o.lower() not in existing]
    if missing:
        st.info(f"🆕 Added {len(missing)} new opportunities to the database.")
        new_df = pd.DataFrame({"Opportunity": missing, "Classification": [""] * len(missing)})
        existing_df = pd.concat([existing_df, new_df], ignore_index=True)
    return existing_df


def sanitize_text(text: str) -> str:
    """Replace unsupported characters with safe ASCII equivalents."""
    if not isinstance(text, str):
        return ""
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("‘", "'").replace("’", "'")
    text = re.sub(r"[•·●▪]", "-", text)
    text = re.sub(r"[^\x00-\x7F]+", "", text)
    return text.strip()


def generate_pdf(store_num: str, oe_cycle: str, df: pd.DataFrame) -> BytesIO:
    """Generate PDF with FOH/BOH sections using built-in Helvetica font."""
    pdf = FPDF()
    pdf.add_page()

    # Header
    pdf.set_font("Helvetica", "B", 16)
    if os.path.exists(LOGO_PATH):
        pdf.image(LOGO_PATH, x=10, y=8, w=30)
    pdf.cell(200, 10, "IHOP OE One Pager", new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.set_font("Helvetica", "", 12)
    pdf.cell(200, 10, f"Store #{store_num} | OE Cycle: {oe_cycle}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(10)

    # Split sections
    foh_items = df[df["Classification"].isin(["FOH", "BOTH"])]
    boh_items = df[df["Classification"].isin(["BOH", "BOTH"])]

    def section(title, items):
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        if items.empty:
            pdf.multi_cell(0, 6, "— None —")
        else:
            for _, row in items.iterrows():
                opp = sanitize_text(row["Opportunity"])
                pdf.multi_cell(0, 6, f"- {opp}")
        pdf.ln(4)

    # Add sections
    section("FRONT OF HOUSE (FOH)", foh_items)
    section("BACK OF HOUSE (BOH)", boh_items)

    # Footer
    pdf.set_font("Helvetica", "I", 9)
    pdf.cell(0, 10, f"Generated on {datetime.now():%Y-%m-%d %H:%M}", align="R")

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

classification_db = load_classifications(EXCEL_FILE)

if user_input.strip():
    opportunities = extract_opportunities(user_input)
    st.write(f"✅ Found **{len(opportunities)}** valid opportunities.")

    if opportunities:
        # Sync with DB
        classification_db = sync_new_opportunities(classification_db, opportunities)

        st.divider()
        st.markdown("### 🏷️ Review & Confirm Classifications")

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
                index=["FOH", "BOH", "BOTH"].index(preselect),
                key=opp,
            )
            updated_rows.append((opp, selected))

        st.warning("⚠️ Please review all classifications before generating the PDF.")
        st.divider()

        if st.button("💾 Save & Generate PDF One Pager"):
            # Update DB (learning system)
            for opp, selected in updated_rows:
                mask = classification_db["Opportunity"].str.lower() == opp.lower()
                if mask.any():
                    classification_db.loc[mask, "Classification"] = selected
                else:
                    classification_db.loc[len(classification_db)] = [opp, selected]
            save_classifications(classification_db, EXCEL_FILE)

            # Create session-specific DataFrame
            session_df = pd.DataFrame(updated_rows, columns=["Opportunity", "Classification"])
            pdf_data = generate_pdf(store_num, oe_cycle, session_df)

            st.download_button(
                label="⬇️ Download PDF One Pager",
                data=pdf_data,
                file_name=f"IHOP_OE_{store_num}_{oe_cycle}_{datetime.now():%Y%m%d}.pdf",
                mime="application/pdf",
            )
else:
    st.info("Enter store info and paste OE notes to begin.")
