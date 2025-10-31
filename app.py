import os
import re
import pandas as pd
import streamlit as st
from datetime import datetime
from io import BytesIO
from fpdf import FPDF
from pathlib import Path

# ------------------------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------------------------
st.set_page_config(page_title="IHOP OE One Pager", layout="wide")
LOGO_PATH = "ihop_logo.png"
EXCEL_FILE = "OE_Opportunities_Classification.xlsx"

# ------------------------------------------------------------------------------------
# DATA HELPERS
# ------------------------------------------------------------------------------------
@st.cache_data
def load_classifications(file_path: str):
    """Load Excel classification database, create if missing."""
    if os.path.exists(file_path):
        df = pd.read_excel(file_path)
    else:
        df = pd.DataFrame(columns=["Opportunity", "Classification"])
    df["Opportunity"] = df["Opportunity"].astype(str).str.strip()
    df["Classification"] = df["Classification"].astype(str).str.strip()
    return df


def save_classifications(df: pd.DataFrame, file_path: str):
    """Persist updates to Excel."""
    df.to_excel(file_path, index=False)
    st.toast("✅ Classification database saved!")


def extract_opportunities(text: str):
    """Extract potential opportunities from text input."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    opps = []
    for l in lines:
        if len(l.split()) < 3:
            continue
        if l.endswith(":"):
            continue
        if re.match(r"^[A-Z\s]+:$", l):
            continue
        opps.append(l)
    return opps


def sync_new(class_df, new_opps):
    """Add new opportunities to DB if missing."""
    existing = set(class_df["Opportunity"].str.lower())
    missing = [o for o in new_opps if o.lower() not in existing]
    if missing:
        st.info(f"🆕 Added {len(missing)} new opportunities.")
        new_df = pd.DataFrame({"Opportunity": missing, "Classification": [""] * len(missing)})
        class_df = pd.concat([class_df, new_df], ignore_index=True)
    return class_df


# ------------------------------------------------------------------------------------
# PDF GENERATOR (Unicode-safe, FOH/BOH split)
# ------------------------------------------------------------------------------------
def generate_pdf(store_num: str, oe_cycle: str, df: pd.DataFrame) -> BytesIO:
    """Generate PDF with FOH / BOH sections; 'BOTH' appears in both."""
    pdf = FPDF()
    pdf.add_page()

    # ✅ Use Unicode-safe font (DejaVu bundled with fpdf2)
    font_dir = Path(__file__).parent / "DejaVuSans.ttf"
    if not font_dir.exists():
        from fpdf import fonts
        font_dir = Path(fonts.__file__).parent / "DejaVuSans.ttf"

    pdf.add_font("DejaVu", "", str(font_dir))
    pdf.set_font("DejaVu", "", 16)

    # Header
    if os.path.exists(LOGO_PATH):
        pdf.image(LOGO_PATH, x=10, y=8, w=30)
    pdf.cell(200, 10, "IHOP OE One Pager", new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.set_font("DejaVu", "", 12)
    pdf.cell(200, 10, f"Store #{store_num} | OE Cycle: {oe_cycle}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(10)

    # Split FOH/BOH
    foh_items = df[df["Classification"].isin(["FOH", "BOTH"])]
    boh_items = df[df["Classification"].isin(["BOH", "BOTH"])]

    def section(title, items):
        pdf.set_font("DejaVu", "B", 13)
        pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("DejaVu", "", 11)
        if items.empty:
            pdf.multi_cell(0, 6, "— None —", align="L")
        else:
            for _, row in items.iterrows():
                text = f"• {row['Opportunity']}"
                pdf.multi_cell(0, 6, text, align="L")
        pdf.ln(5)

    section("FRONT OF HOUSE (FOH)", foh_items)
    section("BACK OF HOUSE (BOH)", boh_items)

    pdf.set_font("DejaVu", "", 9)
    pdf.cell(0, 10, f"Generated on {datetime.now():%Y-%m-%d %H:%M}", align="R")

    # Output to memory buffer
    pdf_bytes = BytesIO()
    pdf.output(pdf_bytes)
    pdf_bytes.seek(0)
    return pdf_bytes


# ------------------------------------------------------------------------------------
# STREAMLIT UI
# ------------------------------------------------------------------------------------
if os.path.exists(LOGO_PATH):
    st.image(LOGO_PATH, width=120)
st.title("🥞 IHOP OE One Pager")

store_num = st.text_input("Store Number")
oe_cycle = st.text_input("OE Cycle")
user_input = st.text_area("Paste OE Notes or Opportunities Below:", height=250)

classification_db = load_classifications(EXCEL_FILE)

if user_input.strip():
    opportunities = extract_opportunities(user_input)
    st.write(f"✅ Found **{len(opportunities)}** potential opportunities.")

    if opportunities:
        classification_db = sync_new(classification_db, opportunities)
        st.divider()
        st.markdown("### 🏷️ Review & Confirm Classifications")

        updated_rows = []
        for opp in opportunities:
            current_val = classification_db.loc[
                classification_db["Opportunity"].str.lower() == opp.lower(), "Classification"
            ].values
            preselect = current_val[0] if len(current_val) > 0 and current_val[0] else "FOH"

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
            # Save classifications (system learning)
            for opp, selected in updated_rows:
                mask = classification_db["Opportunity"].str.lower() == opp.lower()
                if mask.any():
                    classification_db.loc[mask, "Classification"] = selected
                else:
                    classification_db.loc[len(classification_db)] = [opp, selected]
            save_classifications(classification_db, EXCEL_FILE)

            # Generate PDF from current session only
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
