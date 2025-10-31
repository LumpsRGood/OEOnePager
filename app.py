import streamlit as st
import pandas as pd
from fpdf import FPDF
import os

# ---------- PAGE CONFIG ----------
st.set_page_config(page_title="IHOP OE One Pager", layout="centered")
st.title("🥞 IHOP OE One Pager")
st.markdown("---")

# ---------- FILE PATH ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
excel_path = os.path.join(BASE_DIR, "OE_Opportunities_Classification.xlsx")

# ---------- LOAD EXISTING DATA ----------
if os.path.exists(excel_path):
    df = pd.read_excel(excel_path)
    st.success("Loaded existing OE_Opportunities_Classification.xlsx file.")
else:
    df = pd.DataFrame(columns=["Opportunity", "Classification"])
    st.warning("No existing classification file found — a new one will be created after saving.")

# ---------- TEXT INPUT ----------
text_input = st.text_area(
    "Paste text here (one line per row)",
    height=150,
    placeholder="Paste text here. Each opportunity should be on its own line."
)

# ---------- ADD NEW LINES IF PROVIDED ----------
if text_input:
    new_lines = [line.strip() for line in text_input.split("\n") if line.strip() and ":" not in line]
    for line in new_lines:
        if line not in df["Opportunity"].values:
            df.loc[len(df)] = [line, ""]

# ---------- CONTROL DISPLAY ----------
if df.empty and not text_input:
    st.info("Paste opportunities above to begin classification.")
else:
    st.subheader("Please Verify Each Opportunity (FOH / BOH / BOTH)")

    for i, row in df.iterrows():
        col1, col2 = st.columns([3, 1])
        with col1:
            st.text(row["Opportunity"])
        with col2:
            df.at[i, "Classification"] = st.radio(
                "Select",
                ["FOH", "BOH", "BOTH"],
                horizontal=True,
                key=f"class_{i}",
                index=["FOH", "BOH", "BOTH"].index(row["Classification"])
                if row["Classification"] in ["FOH", "BOH", "BOTH"] else 0
            )

    if st.button("💾 Update Database"):
        df.to_excel(excel_path, index=False)
        st.success("✅ Database updated successfully!")

    st.markdown("---")

    # ---------- GROUP + DISPLAY ----------
    grouped = df.groupby("Classification")["Opportunity"].apply(list).to_dict()
    st.subheader("✅ Verified Opportunities Summary")
    for section in ["FOH", "BOH", "BOTH"]:
        if section in grouped:
            st.write(f"**{section} ({len(grouped[section])})**")
            for item in grouped[section]:
                st.markdown(f"- {item}")
            st.markdown("")

    # ---------- PDF GENERATION ----------
    st.subheader("📄 Generate One Pager PDF")
    store_number = st.text_input("Enter Store Number:")
    oe_cycle = st.text_input("Enter OE Cycle (e.g., 'Cycle 2, 2025')")

    if st.button("Generate One Pager PDF"):
        if not store_number or not oe_cycle:
            st.error("Please enter both Store Number and OE Cycle before generating the PDF.")
        else:
            pdf = FPDF()
            pdf.add_page()
            pdf.set_auto_page_break(auto=True, margin=15)

            def safe_text(s):
                return s.encode("latin-1", "replace").decode("latin-1")

            pdf.set_font("Helvetica", "B", 16)
            pdf.cell(0, 10, safe_text("IHOP OE One Pager"), ln=True, align="C")

            pdf.set_font("Helvetica", "", 12)
            pdf.cell(0, 10, safe_text(f"Store: {store_number} | {oe_cycle}"), ln=True, align="C")
            pdf.ln(10)

            for section in ["FOH", "BOH", "BOTH"]:
                if section in grouped and len(grouped[section]) > 0:
                    pdf.set_font("Helvetica", "B", 14)
                    pdf.cell(0, 10, safe_text(section), ln=True)
                    pdf.set_font("Helvetica", "", 12)
                    for item in grouped[section]:
                        pdf.multi_cell(0, 8, safe_text(f"• {item}"))
                    pdf.ln(5)

            output_path = os.path.join(BASE_DIR, f"IHOP_OE_OnePager_{store_number}.pdf")
            pdf.output(output_path)

            with open(output_path, "rb") as f:
                st.download_button(
                    label="⬇️ Download One Pager PDF",
                    data=f,
                    file_name=f"IHOP_OE_{store_number}.pdf",
                    mime="application/pdf"
                )
