import streamlit as st
import pandas as pd
import io
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
import base64
import os

st.set_page_config(page_title="IHOP OE One Pager", layout="centered")

# --- FILE CONSTANTS ---
DB_PATH = "OE_Opportunities_Classification.xlsx"
LOGO_URL = "https://raw.githubusercontent.com/LumpsRGood/OEOnePager/main/ihop_logo.png"

# --- FUNCTIONS ---

@st.cache_data
def load_classifications(file_path: str):
    """Load classification reference or create blank."""
    try:
        df = pd.read_excel(file_path)
        df.columns = [c.strip().lower() for c in df.columns]
        if "opportunity" not in df.columns or "classification" not in df.columns:
            raise ValueError
        return df
    except Exception:
        return pd.DataFrame(columns=["opportunity", "classification"])

def save_classifications(df, path=DB_PATH):
    """Save updated classification database."""
    df_sorted = df.sort_values("opportunity", key=lambda s: s.str.lower()).reset_index(drop=True)
    df_sorted.to_excel(path, index=False)

def filter_opportunities(text):
    """Split text into clean opportunity lines, skipping section headers."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    opps = []
    for l in lines:
        if ":" in l and len(l.split()) <= 4:  # skip headers like 'Food Safety:'
            continue
        if len(l) < 5:
            continue
        opps.append(l)
    return opps

def auto_classify(opp, db):
    """Return saved classification if found in DB."""
    if db.empty:
        return None
    match = db[db["opportunity"].str.lower().str.strip() == opp.lower().strip()]
    if not match.empty:
        return match.iloc[0]["classification"]
    return None

def generate_pdf(store_num, cycle, data, logo_path):
    """Builds PDF and returns it as BytesIO."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    styles = getSampleStyleSheet()
    style_normal = styles["Normal"]
    style_heading = styles["Heading1"]

    # Header with logo
    if logo_path:
        try:
            logo = Image(logo_path, width=1.5*inch, height=1.5*inch)
            elements.append(logo)
        except Exception:
            pass

    elements.append(Paragraph(f"IHOP OE One Pager", style_heading))
    elements.append(Paragraph(f"Store #{store_num} | {cycle}", style_normal))
    elements.append(Spacer(1, 0.25 * inch))

    # Table of opportunities
    data_table = [["Opportunity", "Classification"]] + data
    table = Table(data_table, colWidths=[4.5 * inch, 1.5 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightblue),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("BACKGROUND", (0, 1), (-1, -1), colors.whitesmoke),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
    ]))
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)
    return buffer

# --- UI ---

st.title("IHOP OE One Pager")

st.markdown("Paste your opportunities below or upload a text/Excel file.")

uploaded_file = st.file_uploader("Upload Opportunities File", type=["txt", "xlsx"])
input_text = st.text_area("Or paste opportunities here:")

# Load database
classification_db = load_classifications(DB_PATH)

opportunities = []

if uploaded_file:
    if uploaded_file.name.endswith(".txt"):
        text = uploaded_file.read().decode("utf-8")
        opportunities = filter_opportunities(text)
    elif uploaded_file.name.endswith(".xlsx"):
        df = pd.read_excel(uploaded_file)
        col = df.columns[0]
        opportunities = filter_opportunities("\n".join(df[col].astype(str)))
elif input_text:
    opportunities = filter_opportunities(input_text)

# --- Classification Section ---
if opportunities:
    st.subheader("Classify Opportunities")

    use_auto = st.toggle("Auto-classify from existing database", value=True)

    classifications = []
    for opp in opportunities:
        preset = auto_classify(opp, classification_db) if use_auto else None
        classification = st.selectbox(
            f"Classify this opportunity:\n> {opp}",
            ["FOH", "BOH", "BOTH"],
            index=["FOH", "BOH", "BOTH"].index(preset) if preset in ["FOH", "BOH", "BOTH"] else 0,
            key=opp
        )
        classifications.append((opp, classification))

    df_display = pd.DataFrame(classifications, columns=["Opportunity", "Classification"])
    st.dataframe(df_display, use_container_width=True)

    store_num = st.text_input("Store Number:")
    cycle = st.text_input("OE Cycle:")

    if st.button("Generate One Pager"):
        pdf = generate_pdf(store_num, cycle, classifications, LOGO_URL)

        # Update and save database
        updated_db = classification_db.copy()

        for opp, cls in classifications:
            match_idx = updated_db[
                updated_db["opportunity"].str.lower().str.strip() == opp.lower().strip()
            ].index
            if not match_idx.empty:
                # Update classification if changed
                if updated_db.loc[match_idx[0], "classification"] != cls:
                    updated_db.loc[match_idx[0], "classification"] = cls
            else:
                # Add new opportunity
                updated_db = pd.concat(
                    [updated_db, pd.DataFrame([[opp, cls]], columns=["opportunity", "classification"])],
                    ignore_index=True
                )

        save_classifications(updated_db)
        st.success("✅ PDF generated and classification database updated successfully!")

        # PDF Preview
        b64_pdf = base64.b64encode(pdf.getvalue()).decode("utf-8")
        st.markdown(
            f'<iframe src="data:application/pdf;base64,{b64_pdf}" width="700" height="1000" type="application/pdf"></iframe>',
            unsafe_allow_html=True,
        )

        st.download_button(
            label="Download One Pager PDF",
            data=pdf,
            file_name=f"IHOP_OE_OnePager_{store_num}.pdf",
            mime="application/pdf",
        )
else:
    st.info("Paste or upload opportunities above to start classifying.")
