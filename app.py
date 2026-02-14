import streamlit as st
import os
import pandas as pd
from datetime import datetime
from src.data_manager import DataManager
from src.ui.dashboard import render_dashboard
from src.ui.importer import render_importer
from src.ui.transactions import render_transactions
from src.ui.analysis import render_analysis
from src.ui.settings import render_settings
from src.ui.recurring import render_recurring
from src.ui.split import render_split
from src.ui.tag_manager import render_tag_manager
from src.ui.styling import apply_custom_styles

st.set_page_config(page_title="Finance Dashboard", layout="wide", page_icon="💸")

# Apply Aesthetics
apply_custom_styles()

# Initialize DataManager
if 'data_manager' not in st.session_state:
    st.session_state.data_manager = DataManager()

dm = st.session_state.data_manager

# Sidebar Navigation
st.sidebar.title("💰 Finance App")
page = st.sidebar.radio("Navigate", ["Dashboard", "Transactions", "Recurring Expenses", "Shared Expenses", "📊 Analysis", "Tag Manager", "Import", "Settings"])

st.sidebar.divider()

# Quick Add Transaction
with st.sidebar.expander("➕ Quick Add Transaction", expanded=False):
    with st.form("quick_add_form"):
        # Fetch options
        cats = dm.get_unique_categories()
        accounts = dm.get_unique_accounts()
        existing_tags = dm.get_unique_tags()
        # Also include tags from Rules
        if hasattr(dm, 'rules_engine') and 'tags' in dm.rules_engine.rules:
             rules_tags = [t['tag'] for t in dm.rules_engine.rules['tags']]
             existing_tags = sorted(list(set(existing_tags + rules_tags)))
        
        qa_date = st.date_input("Date", datetime.today())
        qa_amount = st.number_input("Amount", step=0.01)
        qa_type = st.selectbox("Type", ["Expense", "Income"])
        qa_desc = st.text_input("Description", placeholder="e.g. Dinner with friends")
        
        # Category: Select or Type
        qa_cat_sel = st.selectbox("Category", ["Select..."] + cats + ["Create New..."])
        qa_cat_new = ""
        if qa_cat_sel == "Create New...":
            qa_cat_new = st.text_input("New Category Name")
        
        qa_cat = qa_cat_new if qa_cat_sel == "Create New..." else (qa_cat_sel if qa_cat_sel != "Select..." else "General")

        # Account/Wallet
        default_acc_idx = 0
        if accounts:
            qa_account_sel = st.selectbox("Wallet/Account", accounts + ["New Account..."])
        else:
            qa_account_sel = st.text_input("Wallet/Account", value="Cash")
            
        qa_account = qa_account_sel
        if qa_account_sel == "New Account...":
            qa_account = st.text_input("New Account Name")

        # Tags
        qa_tags_sel = st.multiselect("Tags", existing_tags)
        qa_new_tag = st.text_input("New Tag (Optional)", placeholder="#holiday")
        
        qa_nec = st.selectbox("Necessity", ["Want", "Need"])
        
        submitted = st.form_submit_button("Add Transaction")
        if submitted:
            if qa_amount > 0:
                final_cat = qa_cat if qa_cat else "General"
                final_acc = qa_account if qa_account else "Manual"
                
                final_tags = list(qa_tags_sel)
                if qa_new_tag:
                    clean = qa_new_tag.strip().replace('#', '').lower()
                    if clean:
                        final_tags.append(clean)
                
                # Prepare DF
                new_row = pd.DataFrame([{
                    'date': pd.to_datetime(qa_date),
                    'amount': -qa_amount if qa_type == 'Expense' else qa_amount,
                    'currency': 'EUR',
                    'account': final_acc,
                    'category': final_cat,
                    'tags': final_tags,
                    'description': qa_desc,
                    'type': qa_type,
                    'source_file': 'manual_entry',
                    'original_description': qa_desc,
                    'necessity': qa_nec
                }])
                
                # Insert
                try:
                    dm._process_and_insert(new_row, 'manual_entry')
                    st.toast(f"Transaction Added! Tags: {final_tags}", icon="✅")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
            else:
                st.warning("Amount must be > 0")

if page == "Dashboard":
    render_dashboard(dm)
elif page == "Transactions":
    render_transactions(dm)
elif page == "Recurring Expenses":
    render_recurring(dm)
elif page == "Shared Expenses":
    render_split(dm)
elif page == "📊 Analysis":
    render_analysis(dm)
elif page == "Tag Manager":
    render_tag_manager(dm)
elif page == "Import":
    render_importer(dm)
elif page == "Settings":
    render_settings(dm)
