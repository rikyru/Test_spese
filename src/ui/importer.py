import streamlit as st
import os
import pandas as pd
from src.data_manager import DataManager
from src.pdf_parser import PDFParser

def render_importer(data_manager: DataManager):
    st.header("Import Data")
    
    tab1, tab2 = st.tabs(["📂 Bulk Import (ZIP)", "📄 Scan Bill (PDF)"])
    
    with tab1:
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

    with tab2:
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
