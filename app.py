import streamlit as st
import pandas as pd
from fpdf import FPDF
import os

# ---------- PAGE CONFIG ----------
st.set_page_config(page_title="IHOP OE One Pager", layout="centered")
st.title("🥞 IHOP OE One Pager")

# ---------- LOGO ----------
logo_path = "logo.png"  # make sure logo.png is in your project root
if os.path.exists(logo_path):
    st.image(logo_path, use_column_width=False, width=150)
else:
    st.warning("Logo not found — add a file named 'logo.png' in the app root.")

st.markdown("---")

# ---------- TEXT INPUT ----------
text_input = st.text_area(
    "Paste text here (one line per row)",
    height=150,
    placeholder="Paste text here (one line per row). Each opportunity should be on its own line."
)

# Create DataFrame only if there’s input
if text_input:
    # ignore lines that are headers or section titles
    lines = [line.strip() for line in text_input.split("\n") if line.strip() and ":" not in line]
    df = pd.DataFrame(lines, columns=["Opportunity"])
else:
    df = pd.DataFrame(columns=["Opportunity"])

# ---------- CLASSIFICATION ----------
if not df.empty:
    st.subheader("Please Verify Each Opportunity (FOH / BOH / BOTH)")

    classifications = []
    for i, row in df.iterrows():
        col1, col2 = st.columns([3, 1])
        with col1:
            st.text(row["Opportunity"])
        with col2:
            choice = st.radio(
                "Select", ["FOH", "BOH", "BOTH"],
                horizontal=True,
                key=f"class_{i}"
            )
        classifications.append(choice)
    df["Classification"] = classifications

    st.markdown("---")

    # ---------- GROUPING ----------
    grouped = df.groupby("Classification")["Opportunity"].apply(list).to_dict()

    st.success("All items verified! Ready to generate your one-pager PDF.")

    # ---------- PDF GENERATION ----------
    st.subheader("📄 Generate PDF")

    store_number = st.text_input("Enter Store Number:")
    oe_cycle = st.text_input("Enter OE Cycle (e.g. 'Cycle 2, 2025')")

    if st.button("Generate One Pager PDF"):
        if not store_number or not oe_cycle:
            st.error("Please enter both Store Number and OE Cycle.")
        else:
            pdf = FPDF()
            pdf.add_page()
            pdf.set_auto_page_break(auto=True, margin=15)

            # Header / Logo
            if os.path.exists(logo_path):
                pdf.image(logo_path, x=80, w=50)  # centered
            pdf.ln(30)
            pdf.set_font("Helvetica", "B", 16)
            pdf.cell(0, 10, f"IHOP OE One Pager", ln=True, align="C")
            pdf.set_font("Helvetica", "", 12)
            pdf.cell(0, 10, f"Store: {store_number} | {oe_cycle}", ln=True, align="C")
            pdf.ln(10)

            # Add grouped items
            for section in ["FOH", "BOH", "BOTH"]:
                if section in grouped:
                    pdf.set_font("Helvetica", "B", 14)
                    pdf.cell(0, 10, section, ln=True)
                    pdf.set_font("Helvetica", "", 12)
                    for item in grouped[section]:
                        pdf.multi_cell(0, 8, f"• {item}")
                    pdf.ln(5)

            output_path = "IHOP_OE_OnePager.pdf"
            pdf.output(output_path)
            with open(output_path, "rb") as f:
                st.download_button(
                    label="⬇️ Download One Pager PDF",
                    data=f,
                    file_name=f"IHOP_OE_{store_number}.pdf",
                    mime="application/pdf"
                )
else:
    st.info("Paste opportunities above to begin classification.")
