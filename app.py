import streamlit as st
import pandas as pd
import os
import re

st.set_page_config(page_title="IHOP OE One Pager", layout="wide")

st.title("🥞 IHOP OE One Pager")

EXCEL_FILE = "OE_Opportunities_Classification.xlsx"


# --- Utility functions ---

@st.cache_data
def load_classifications(file_path: str):
    """Load the Excel file or return a default DataFrame if missing."""
    if os.path.exists(file_path):
        df = pd.read_excel(file_path)
        df["Opportunity"] = df["Opportunity"].astype(str)
        df["Classification"] = df["Classification"].astype(str)
        return df
    else:
        st.warning("⚠️ Classification file not found. Creating a new one in memory.")
        df = pd.DataFrame(columns=["Opportunity", "Classification"])
        return df


def save_classifications(df: pd.DataFrame, file_path: str):
    """Save updates to Excel file."""
    df.to_excel(file_path, index=False)
    st.success(f"✅ Classifications saved to {file_path}")


def extract_opportunities(raw_text: str):
    """
    Extract potential 'opportunity' lines.
    Ignore section headers or lines that end with ':' or are very short.
    """
    lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
    opportunities = []
    for line in lines:
        # Skip section headers and nonsense lines
        if line.endswith(":"):
            continue
        if len(line.split()) < 3:
            continue
        if re.match(r"^[A-Z\s]+:$", line):  # all caps header
            continue
        opportunities.append(line)
    return opportunities


def sync_classifications(class_db, new_opps):
    """Add new opportunities to classification DB if not already present."""
    existing = set(class_db["Opportunity"].str.lower())
    missing = [o for o in new_opps if o.lower() not in existing]
    if missing:
        st.info(f"🆕 Added {len(missing)} new opportunities to the database.")
        new_df = pd.DataFrame({"Opportunity": missing, "Classification": [""] * len(missing)})
        class_db = pd.concat([class_db, new_df], ignore_index=True)
    return class_db


# --- Load or create classification DB ---
classification_db = load_classifications(EXCEL_FILE)

st.markdown("### 🧾 Paste OE Notes or Opportunities Below")
user_input = st.text_area("Paste text here:", height=300, placeholder="Paste your OE notes...")

if user_input:
    opportunities = extract_opportunities(user_input)
    st.write(f"✅ Found **{len(opportunities)}** possible opportunities.")

    if opportunities:
        # Merge new items into DB if needed
        classification_db = sync_classifications(classification_db, opportunities)

        st.divider()
        st.markdown("### 🏷️ Classify Each Opportunity (FOH / BOH / BOTH)")

        updated_rows = []
        for opp in opportunities:
            current_value = classification_db.loc[
                classification_db["Opportunity"].str.lower() == opp.lower(), "Classification"
            ].values
            preselect = current_value[0] if len(current_value) > 0 and current_value[0] else None

            selected = st.radio(
                f"**{opp}**",
                ["FOH", "BOH", "BOTH"],
                horizontal=True,
                index=["FOH", "BOH", "BOTH"].index(preselect) if preselect in ["FOH", "BOH", "BOTH"] else 0,
                key=opp,
            )

            updated_rows.append((opp, selected))

        st.divider()

        if st.button("💾 Save Updates"):
            for opp, selected in updated_rows:
                mask = classification_db["Opportunity"].str.lower() == opp.lower()
                if mask.any():
                    classification_db.loc[mask, "Classification"] = selected
                else:
                    classification_db.loc[len(classification_db)] = [opp, selected]
            save_classifications(classification_db, EXCEL_FILE)

    else:
        st.warning("No valid opportunity lines found.")


# --- Show current database ---
st.divider()
st.markdown("### 📊 Current Classification Database")
st.dataframe(classification_db, width="stretch")
