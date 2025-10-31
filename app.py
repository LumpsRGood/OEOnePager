# app.py
import os
import re
from pathlib import Path
from datetime import datetime
from typing import List

import pandas as pd
import streamlit as st

# --- App/UX setup ---
st.set_page_config(page_title="IHOP OE One Pager", layout="wide")
st.title("🥞 IHOP OE One Pager")

EXCEL_FILE = "OE_Opportunities_Classification.xlsx"
EXCEL_PATH = Path.cwd() / EXCEL_FILE
CLASS_CHOICES = ("FOH", "BOH", "BOTH")

# --- Utility functions ---

def _coerce_class(value: str) -> str:
    """Keep classes within allowed set; else empty.
    Why: Prevents typos from propagating into storage."""
    if not isinstance(value, str):
        return ""
    v = value.strip().upper()
    return v if v in CLASS_CHOICES else ""

@st.cache_data(show_spinner=False)
def load_classifications(file_path: str) -> pd.DataFrame:
    """Load Excel or return empty DF; ensure schema/dtypes."""
    if os.path.exists(file_path):
        df = pd.read_excel(file_path, dtype={"Opportunity": "string", "Classification": "string"})
        if "Opportunity" not in df or "Classification" not in df:
            df = pd.DataFrame(columns=["Opportunity", "Classification"])
    else:
        st.warning("⚠️ Classification file not found. A new file will be created on first save.")
        df = pd.DataFrame(columns=["Opportunity", "Classification"])

    # Normalize
    if not df.empty:
        df["Opportunity"] = df["Opportunity"].astype("string").fillna("").str.strip()
        df["Classification"] = df["Classification"].astype("string").map(_coerce_class)
        # Drop blank rows just in case
        df = df[df["Opportunity"].str.len() > 0].drop_duplicates(subset=["Opportunity"], keep="first")
        df = df.reset_index(drop=True)
    else:
        df = pd.DataFrame(columns=["Opportunity", "Classification"]).astype({"Opportunity": "string", "Classification": "string"})
    return df

def save_classifications(df: pd.DataFrame, file_path: str) -> None:
    """Persist Excel and clear cache for immediate UI freshness."""
    # Ensure columns exist in correct order
    out = df[["Opportunity", "Classification"]].copy()
    # Sanitize classification values
    out["Classification"] = out["Classification"].map(_coerce_class).fillna("")
    try:
        out.to_excel(file_path, index=False)
        st.success(f"✅ Classifications saved to {file_path}")
    except Exception as e:
        st.error(f"Failed to save Excel: {e}")
        return
    # Clear cache so subsequent loads reflect latest file
    load_classifications.clear()

def _strip_bullet_prefix(line: str) -> str:
    """Remove common bullets/numbering. Why: Users paste raw notes."""
    # bullets like -, *, •, 1., 1), (1), a), -, —
    line = re.sub(r"^\s*[\-\*\u2022\u2013\u2014]\s+", "", line)  # bullets/dashes
    line = re.sub(r"^\s*\(?[0-9a-zA-Z]{1,3}\)?[.)]\s+", "", line)  # 1. / 1) / (1) / a)
    return line.strip()

def _looks_like_header(line: str) -> bool:
    """Detect section headers."""
    if line.endswith(":"):
        return True
    if re.match(r"^[A-Z0-9\s\-/]{3,}:?$", line) and line.isupper():
        return True
    return False

def extract_opportunities(raw_text: str) -> List[str]:
    """
    Extract candidate opportunity lines from free text.
    Rules:
    - Skip headers/labels and very short lines.
    - Strip bullets/numbers.
    - Keep order; deduplicate case-insensitively.
    """
    if not raw_text:
        return []

    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    cleaned: List[str] = []
    seen_lower = set()

    for ln in lines:
        ln = _strip_bullet_prefix(ln)
        if not ln or _looks_like_header(ln):
            continue
        if len(ln.split()) < 3:
            continue
        # remove trailing punctuation-only
        ln = re.sub(r"[;,:.\-\s]+$", "", ln).strip()
        low = ln.lower()
        if low and low not in seen_lower:
            cleaned.append(ln)
            seen_lower.add(low)
    return cleaned

def sync_classifications(class_db: pd.DataFrame, new_opps: List[str]) -> pd.DataFrame:
    """Append missing opportunities to DB."""
    if class_db.empty and not new_opps:
        return class_db
    existing = set(class_db["Opportunity"].str.lower())
    missing = [o for o in new_opps if o.lower() not in existing]
    if missing:
        st.info(f"🆕 Added {len(missing)} new opportunities to the working table.")
        new_df = pd.DataFrame({"Opportunity": pd.Series(missing, dtype="string"),
                               "Classification": pd.Series([""] * len(missing), dtype="string")})
        class_db = pd.concat([class_db, new_df], ignore_index=True)
    return class_db

def class_stats(df: pd.DataFrame) -> dict:
    counts = df["Classification"].map(_coerce_class).value_counts(dropna=False)
    return {k: int(counts.get(k, 0)) for k in ["FOH", "BOH", "BOTH"]}

# --- Data ---
classification_db = load_classifications(str(EXCEL_PATH))

# --- Sidebar: file actions ---
with st.sidebar:
    st.subheader("📁 File")
    st.code(str(EXCEL_PATH), language="bash")
    if st.button("🔄 Reload from disk", use_container_width=True):
        load_classifications.clear()
        classification_db = load_classifications(str(EXCEL_PATH))
        st.toast("Reloaded from disk.")

# --- Input ---
st.markdown("### 🧾 Paste OE Notes or Opportunities")
user_input = st.text_area("Paste text here:", height=260, placeholder="Paste your OE notes... (bullets, numbers, headers OK)")

opportunities = extract_opportunities(user_input) if user_input else []
st.write(f"✅ Found **{len(opportunities)}** possible opportunities.")
if opportunities:
    with st.expander("Preview parsed lines", expanded=False):
        for i, ln in enumerate(opportunities, 1):
            st.write(f"{i}. {ln}")

# --- Merge & Edit ---
working_df = classification_db.copy()
if opportunities:
    working_df = sync_classifications(working_df, opportunities)

# Editor with validation
st.divider()
st.markdown("### 🏷️ Classify Opportunities")
if working_df.empty:
    st.info("No opportunities to classify yet.")
else:
    col_left, col_right, col_mid = st.columns(3)
    stats = class_stats(working_df)
    col_left.metric("FOH", stats["FOH"])
    col_mid.metric("BOH", stats["BOH"])
    col_right.metric("BOTH", stats["BOTH"])

    edited = st.data_editor(
        working_df,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={
            "Opportunity": st.column_config.TextColumn(required=True, help="Opportunity description"),
            "Classification": st.column_config.SelectboxColumn(options=list(CLASS_CHOICES), required=False, help="Pick FOH / BOH / BOTH"),
        },
        key="editor_table",
    )

    # Save / Tools
    c1, c2, c3 = st.columns([1, 1, 2])
    if c1.button("💾 Save Updates", type="primary"):
        save_classifications(edited, str(EXCEL_PATH))
        # Refresh view
        classification_db = load_classifications(str(EXCEL_PATH))
        st.rerun()

    if c2.button("🧹 Clear Unsaved Edits"):
        st.session_state.pop("editor_table", None)
        st.toast("Cleared unsaved edits.")
        st.rerun()

# --- Browse/Filter current DB ---
st.divider()
st.markdown("### 📊 Current Classification Database")

if not classification_db.empty:
    sel = st.multiselect("Filter by Classification", options=list(CLASS_CHOICES), default=[])
    view_df = classification_db.copy()
    if sel:
        view_df = view_df[view_df["Classification"].isin(sel)]
    st.dataframe(view_df, use_container_width=True)

    # Download CSV (lightweight sharing/backups)
    csv_bytes = view_df.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Download CSV", data=csv_bytes, file_name=f"OE_Opportunities_{datetime.now():%Y%m%d_%H%M%S}.csv", mime="text/csv")
else:
    st.info("No saved classifications yet. Add notes above and save.")

