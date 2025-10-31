import streamlit as st
import pandas as pd
import os
from fpdf import FPDF
import io

st.set_page_config(page_title="IHOP OE One Pager", layout="wide")

FILE_PATH = "OE_Opportunities_Classification.xlsx"

# Initialize or load data
if os.path.exists(FILE_PATH):
    df = pd.read_excel(FILE_PATH)
else:
    df = pd.DataFrame(columns=["Opportunity", "Classification"])

st.title("🥞 IHOP OE One Pager")

st.markdown("### Paste text here *(one line per row)*")
user_input = st.text_area(
    "",
    placeholder="Paste text here (one line per row)",
    height=150
)

# Handle pasted text
if user_input.strip():
    new_items = [line.strip() for line in user_input.split("\n") if line.strip()]
    new_df = pd.DataFrame(new_items, columns=["Opportunity"])
    df = pd.concat([df, new_df], ignore_index=True).drop_duplicates(subset=["Opportunity"])

# Interface for verification/classification
st.markdown("## Please Verify Each Opportunity (FOH / BOH / BOTH)")

updated_rows = []
for i, row in df.iterrows():
    if pd.isna(row["Classification"]) or row["Classification"] == "":
        st.markdown(f"⚠️ **{row['Opportunity']}**")
    else:
        st.markdown(f"**{row['Opportunity']}**")

    classification = st.radio(
        f"Select category for: {row['Opportunity']}",
        ["", "FOH", "BOH", "BOTH"],
        index=["", "FOH", "BOH", "BOTH"].index(row["Classification"]) if row["Classification"] in ["FOH", "BOH", "BOTH"] else 0,
        key=f"class_{i}",
        horizontal=True
    )
    updated_rows.append({"Opportunity": row["Opportunity"], "Classification": classification})

# Save updates
df = pd.DataFrame(updated_rows)
df.to_excel(FILE_PATH, index=False)
st.success(f"✅ Classifications saved to {FILE_PATH}")

# Status banner
unclassified = df["Classification"].isna().sum() + (df["Classification"] == "").sum()
if unclassified > 0:
    st.warning(f"⚠ {unclassified} opportunities still need classification.")
else:
    st.success("✅ All opportunities have been verified and classified!")

# PDF download generation
def generate_pdf(dataframe):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(200, 10, txt="IHOP OE One Pager", ln=True, align="C")
    pdf.ln(10)

    pdf.set_font("Arial", size=12)
    for _, row in dataframe.iterrows():
        opp = row["Opportunity"]
        cat = row["Classification"] if row["Classification"] else "UNCLASSIFIED"
        pdf.multi_cell(0, 10, f"- {opp} ({cat})")

    buffer = io.BytesIO()
    pdf.output(buffer)
    return buffer.getvalue()

pdf_bytes = generate_pdf(df)

st.download_button(
    label="📄 Download One-Pager PDF",
    data=pdf_bytes,
    file_name="OE_OnePager.pdf",
    mime="application/pdf"
)
