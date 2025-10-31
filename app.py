import streamlit as st
import pandas as pd
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
import requests
from PIL import Image as PILImage

st.set_page_config(page_title="IHOP OE One Pager", layout="centered")

st.title("🥞 IHOP OE One Pager Generator")
st.write("Paste or upload opportunities, and I'll help sort them into FOH/BOH before generating a one-pager.")

# Load classification database
@st.cache_data
def load_classifications(file_path):
    df = pd.read_excel(file_path)
    df.columns = df.columns.str.strip().str.lower()
    return df

classification_db = load_classifications("OE_Opportunities_Classification.xlsx")

# User input
input_method = st.radio("How would you like to add opportunities?", ("Paste text", "Upload file"))

if input_method == "Paste text":
    opportunities_text = st.text_area("Paste opportunity list (one per line):")
    if opportunities_text:
        opportunities = [line.strip() for line in opportunities_text.splitlines() if line.strip()]
    else:
        opportunities = []
else:
    uploaded_file = st.file_uploader("Upload a .txt or .csv file", type=["txt", "csv"])
    opportunities = []
    if uploaded_file:
        if uploaded_file.name.endswith(".csv"):
            df_uploaded = pd.read_csv(uploaded_file, header=None)
            opportunities = df_uploaded[0].dropna().tolist()
        else:
            text = uploaded_file.read().decode("utf-8")
            opportunities = [line.strip() for line in text.splitlines() if line.strip()]

# Classification logic
def classify_item(item, db):
    match = db[db["opportunity"].str.lower() == item.lower()]
    if not match.empty:
        return match.iloc[0]["classification"]
    return None

classified_data = []
for opp in opportunities:
    classification = classify_item(opp, classification_db)
    if not classification:
        classification = st.selectbox(f"Classify this opportunity:", ["FOH", "BOH", "BOTH"], key=opp)
    classified_data.append({"Opportunity": opp, "Classification": classification})

if classified_data:
    df_classified = pd.DataFrame(classified_data)
    st.dataframe(df_classified)

    # Inputs for header
    store_number = st.text_input("Store Number:")
    oe_cycle = st.text_input("OE Cycle:")

    if st.button("Generate One Pager"):
        # Separate by category
        foh_items = df_classified[df_classified["Classification"].isin(["FOH", "BOTH"])]
        boh_items = df_classified[df_classified["Classification"].isin(["BOH", "BOTH"])]

        # Create PDF
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        elements = []
        styles = getSampleStyleSheet()

        # Logo
        logo_url = "https://raw.githubusercontent.com/LumpsRGood/OEOnePager/main/ihop_logo.png"
        try:
            response = requests.get(logo_url)
            logo = PILImage.open(BytesIO(response.content))
            logo_path = BytesIO()
            logo.save(logo_path, format="PNG")
            logo_path.seek(0)
            elements.append(Image(logo_path, width=2*inch, height=1*inch))
        except Exception:
            elements.append(Paragraph("IHOP Logo", styles['Title']))

        elements.append(Paragraph(f"Store #: {store_number}", styles['Heading2']))
        elements.append(Paragraph(f"OE Cycle: {oe_cycle}", styles['Heading3']))
        elements.append(Spacer(1, 12))

        elements.append(Paragraph("<b>Front of House (FOH)</b>", styles['Heading2']))
        for _, row in foh_items.iterrows():
            elements.append(Paragraph(f"• {row['Opportunity']}", styles['Normal']))

        elements.append(Spacer(1, 12))
        elements.append(Paragraph("<b>Back of House (BOH)</b>", styles['Heading2']))
        for _, row in boh_items.iterrows():
            elements.append(Paragraph(f"• {row['Opportunity']}", styles['Normal']))

        doc.build(elements)
        pdf_data = buffer.getvalue()

        st.download_button(
            label="📄 Download One Pager",
            data=pdf_data,
            file_name=f"OE_OnePager_{store_number}_Cycle{oe_cycle}.pdf",
            mime="application/pdf",
        )
