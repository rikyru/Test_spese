import streamlit as st
import os
import pandas as pd
import json
from src.data_manager import DataManager
from src.pdf_parser import PDFParser
from src.ocr_engine import OCREngine
from src.ui.styling import get_chart_colors

def render_importer(data_manager: DataManager):
    st.header("Import Data")
    
    # Check for Pending Imports
    pending_file = "finance_data/pending_transactions.json"
    pending_data = []
    if os.path.exists(pending_file):
        try:
            with open(pending_file, 'r') as f:
                pending_data = json.load(f)
        except:
            pass

    # Tabs
    tab_names = ["📂 Bulk Import (ZIP)", "📄 Scan Bill (PDF)", "📷 Screenshot Import"]
    if pending_data:
        tab_names.insert(0, "🧐 Review Pending Utils")
        
    tabs = st.tabs(tab_names)
    
    # Adjust index
    tab_offset = 1 if pending_data else 0
    
    if pending_data:
        with tabs[0]:
            st.subheader(f"⚠️ Pending Review ({len(pending_data)} items)")
            st.info("These transactions were detected from screenshots/chats. Please review and confirm them.")
            
            # Wizard style: Show one at a time or list? 
            # List is better for overview, but wizard ensures quality.
            # Let's do an Expander for each, open the first one by default?
            # Or a "Process Next" flow.
            
            # Let's show a table of all, and an editor for the "Current" one (first in list)
            
            if not pending_data:
                st.success("All caught up!")
            else:
                # Current item to review (always index 0)
                current_tx = pending_data[0]
                
                with st.container(border=True):
                    st.markdown(f"### Reviewing: **{current_tx.get('description')}**")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        p_date = st.date_input("Date", pd.to_datetime(current_tx.get('date')).date())
                        p_amount = st.number_input("Amount", value=float(current_tx.get('amount')), step=0.01)
                        p_type = "Expense" if p_amount < 0 else "Income"
                        
                    with col2:
                        # Category
                        cats = data_manager.get_unique_categories() + ["New..."]
                        # Try to guess category from history or rules
                        suggested_cat = "General"
                        if hasattr(data_manager, 'rules_engine'):
                             # Quick check history
                             pass 
                        
                        p_cat = st.selectbox("Category", cats, index=0)
                        if p_cat == "New...":
                            p_cat = st.text_input("New Category Name")
                            
                        # Wallet
                        accounts = data_manager.get_unique_accounts()
                        p_account = st.selectbox("Wallet / Account", accounts if accounts else ["Cash"])
                        
                    # Tags
                    p_tags_str = st.text_input("Tags (comma separated)", value="")
                    
                    p_nec = st.radio("Necessity", ["Need", "Want"], horizontal=True)
                    
                    col_b1, col_b2 = st.columns([1, 1])
                    if col_b1.button("✅ Confirm & Add", type="primary", use_container_width=True):
                         # Add to DB
                         final_tags = [t.strip() for t in p_tags_str.split(',') if t.strip()]
                         
                         new_row = pd.DataFrame([{
                            'date': pd.to_datetime(p_date),
                            'amount': p_amount,
                            'currency': 'EUR',
                            'account': p_account,
                            'category': p_cat,
                            'tags': final_tags,
                            'description': current_tx.get('description'),
                            'type': p_type,
                            'source_file': 'screenshot_review',
                            'original_description': current_tx.get('description'),
                            'necessity': p_nec
                        }])
                         
                         data_manager._process_and_insert(new_row, 'screenshot_review')
                         st.toast("Transaction Added!", icon="✅")
                         
                         # Remove from list
                         pending_data.pop(0)
                         with open(pending_file, 'w') as f:
                             json.dump(pending_data, f, indent=4)
                             
                         st.rerun()
                         
                    if col_b2.button("❌ Discard/Ignore", use_container_width=True):
                         pending_data.pop(0)
                         with open(pending_file, 'w') as f:
                             json.dump(pending_data, f, indent=4)
                         st.rerun()
                         
                st.write("---")
                st.caption(f"Remaining items: {len(pending_data)}")
                if len(pending_data) > 1:
                    with st.expander("View Upcoming Queue"):
                         st.table(pd.DataFrame(pending_data[1:]))

    with tabs[tab_offset]:
        st.subheader("Import Backup/Export")
        uploaded_file = st.file_uploader("Upload ZIP file with CSVs", type="zip")
        
        if uploaded_file:
            # Save temp file
            temp_path = uploaded_file.name
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
                
            if st.button("Process Import"):
                with st.spinner("Importing and normalizing..."):
                    success, msg = data_manager.ingest_zip(temp_path)
                    if success:
                        st.success(f"Done! {msg}")
                        # Clean up
                        try:
                            os.remove(temp_path)
                        except:
                            pass
                    else:
                        st.error(f"Error: {msg}")

    with tabs[tab_offset + 1]:
        st.subheader("Import Utility Bill")
        pdf_file = st.file_uploader("Upload PDF Bill", type="pdf")
        
        if pdf_file:
            if 'bill_data' not in st.session_state or st.session_state.get('last_pdf') != pdf_file.name:
                with st.spinner("Scanning document..."):
                    parser = PDFParser()
                    st.session_state.bill_data = parser.extract_bill_data(pdf_file)
                    st.session_state.last_pdf = pdf_file.name
            
            data = st.session_state.bill_data
            
            if "error" in data:
                st.error(data["error"])
            else:
                st.success(f"Detected: {data.get('bill_type')} Bill")
                
                with st.form("bill_confirm_form"):
                    col1, col2 = st.columns(2)
                    b_date = col1.date_input("Date", data.get('date'))
                    b_amount = col2.number_input("Amount (Expense)", value=abs(data.get('amount', 0.0)), step=0.01)
                    
                    b_desc = st.text_input("Description", data.get('description'))
                    
                    # Category selection
                    cats = data_manager.get_unique_categories() + ["Fatture"]
                    # Ensure Fatture is in list and unique
                    cats = sorted(list(set(cats)))
                    
                    default_cat_idx = 0
                    if "Fatture" in cats:
                        default_cat_idx = cats.index("Fatture")
                    
                    b_cat = st.selectbox("Category", cats, index=default_cat_idx)
                    
                    # Wallet selection
                    accounts = data_manager.get_unique_accounts()
                    b_account = st.selectbox("Pay from Account", accounts if accounts else ["Cash"])
                    
                    # Tags
                    b_tags = st.text_input("Tags (comma separated)", ", ".join(data.get('tags', [])))
                    
                    submitted = st.form_submit_button("Import Bill Transaction")
                    
                    if submitted:
                        # Prepare row
                        final_tags = [t.strip() for t in b_tags.split(',') if t.strip()]
                        
                        new_row = pd.DataFrame([{
                            'date': pd.to_datetime(b_date),
                            'amount': -abs(b_amount), # Ensure negative
                            'currency': 'EUR',
                            'account': b_account,
                            'category': b_cat,
                            'tags': final_tags,
                            'description': b_desc,
                            'type': 'Expense',
                            'source_file': 'pdf_import',
                            'original_description': b_desc,
                            'necessity': 'Need'
                        }])
                        
                        try:
                            data_manager._process_and_insert(new_row, 'pdf_import')
                            st.toast("Bill Imported Successfully!", icon="📄")
                            # Clear state
                            del st.session_state.bill_data
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error saving: {e}")

    with tabs[tab_offset + 2]:
        st.subheader("Import from Screenshot")
        st.info("Upload a screenshot of your bank app or transaction list. The app will try to read the text (OCR).")
        
        uploaded_img = st.file_uploader("Upload Screenshot", type=["png", "jpg", "jpeg"])
        
        if uploaded_img:
            st.image(uploaded_img, caption="Preview", width=300)
            
            if st.button("🔍 Process Screenshot"):
                with st.spinner("Initializing OCR Engine... (First run may be slow)"):
                    try:
                        # Initialize Engine
                        ocr = OCREngine()
                        # Process
                        results, raw_text = ocr.extract_transaction_data(uploaded_img.read())
                        
                        if results:
                            st.success(f"Found {len(results)} transactions!")
                            
                            # Append to pending
                            current_pending = []
                            if os.path.exists(pending_file):
                                try:
                                    with open(pending_file, 'r') as f:
                                        current_pending = json.load(f)
                                except:
                                    pass
                            
                            # Add new results
                            current_pending.extend(results)
                            
                            with open(pending_file, 'w') as f:
                                json.dump(current_pending, f, indent=4)
                                
                            st.toast("Transactions added to Review Queue!", icon="🚀")
                            st.rerun()
                        else:
                            st.warning("No transactions found. Try cropping the image to just the list.")
                            with st.expander("Show Debug (Raw Text)"):
                                st.write(raw_text)
                                st.caption("If you see the text here but it wasn't captured, copy this and send it to me!")
                            
                    except Exception as e:
                        st.error(f"OCR Error: {e}")

