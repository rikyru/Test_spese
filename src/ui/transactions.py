import streamlit as st
import pandas as pd
from src.data_manager import DataManager

def render_transactions(data_manager: DataManager):
    st.header("Transactions")
    
    try:
        # Fetch data with ID
        df = data_manager.con.execute("SELECT * FROM transactions ORDER BY date DESC").df()
        
        if df.empty:
            st.info("No data available.")
            return
            
        # Filters
        col1, col2, col3 = st.columns(3)
        search = col1.text_input("Search Description")
        category_filter = col2.multiselect("Filter Category", options=df['category'].unique())
        
        # Tags options: Get all unique tags from current DF rows (flattened) or from DataManager
        all_tags = set()
        for tags_list in df['tags']:
            if isinstance(tags_list, list):
                all_tags.update(tags_list)
            elif hasattr(tags_list, 'tolist'):
                all_tags.update(tags_list.tolist())
        
        tag_filter = col3.multiselect("Filter Tags", options=sorted(list(all_tags)))
        
        filtered_df = df.copy()
        if search:
            filtered_df = filtered_df[filtered_df['description'].str.contains(search, case=False, na=False)]
        if category_filter:
            filtered_df = filtered_df[filtered_df['category'].isin(category_filter)]
        if tag_filter:
            # Filter rows where at least one tag is present
            def has_tag(row_tags):
                if not row_tags: return False
                rt = row_tags
                if hasattr(rt, 'tolist'): rt = rt.tolist()
                if not isinstance(rt, list): return False
                # Check intersection
                return bool(set(rt) & set(tag_filter))
                
            filtered_df = filtered_df[filtered_df['tags'].apply(has_tag)]
            
        # Editable Dataframe
        st.info("💡 Tip: Double click on a cell to edit. Change 'Type' to fix Income/Expense issues.")
        
        # Configure columns
        column_config = {
            "id": None, # Hide ID
            "date": st.column_config.DateColumn("Date"),
            "amount": st.column_config.NumberColumn("Amount", format="€%.2f"),
            "type": st.column_config.SelectboxColumn("Type", options=["Expense", "Income", "Transfer"]),
            "category": st.column_config.SelectboxColumn("Category", options=data_manager.get_unique_categories() + ["Other"]),
            "necessity": st.column_config.SelectboxColumn("Necessity", options=["Need", "Want"]),
            "tags": st.column_config.ListColumn("Tags"),
        }
        
        edited_df = st.data_editor(
            filtered_df,
            column_config=column_config,
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic", # Allow add/delete
            key="data_editor"
        )
        
        # Detect Changes
        # st.data_editor returns the current state of the dataframe. 
        # But to efficiently update DB we need to know what changed.
        # Streamlit session_state has details? No, return value is the new df.
        # We can compare specific rows, but without session state of 'previous', it's hard.
        # BUT: 'num_rows="dynamic"' allows adding/deleting.
        
        # Actually, for DB sync, it's better to use the `on_change` callback or Diff manually.
        # Simplest approach for local app:
        # If Save button is pressed, update changed rows?
        # OR: Detect diff between filtered_df and edited_df.
        
        if st.button("Save Changes"):
            # We can't easily diff pandas perfectly if index changes or new rows without IDs...
            # But wait: existing rows have IDs. New rows have NaN ID (if we hide it).
            
            # 1. Updates
            # Iterate and check against DB? Too slow.
            # Strategy: Delete removed IDs, Update existing IDs, Insert new (no ID).
            
            # Identify Deleted
            original_ids = set(filtered_df['id'].dropna())
            current_ids = set(edited_df['id'].dropna())
            deleted_ids = original_ids - current_ids
            
            if deleted_ids:
                ids_list = list(deleted_ids)
                if len(ids_list) == 1:
                     data_manager.con.execute("DELETE FROM transactions WHERE id = ?", [ids_list[0]])
                else:
                     placeholders = ','.join(['?'] * len(ids_list))
                     data_manager.con.execute(f"DELETE FROM transactions WHERE id IN ({placeholders})", ids_list)
                st.toast(f"Deleted {len(deleted_ids)} rows")

            # Identify Added (No ID)
            # Depending on how streamlit handles hidden columns for new rows. usually NaN or None.
            new_rows = edited_df[edited_df['id'].isna() | (edited_df['id'] == '')] 
            # Note: Hidden col might be populated with default?
            
            if not new_rows.empty:
                # Insert them
                # Need to handle ID generation (db uuid) and columns match
                for _, row in new_rows.iterrows():
                    # Sanitize
                    r_date = row['date']
                    r_amt = row['amount']
                    # Fix sign based on Type if user entered positive number for Expense
                    if row['type'] == 'Expense' and r_amt > 0:
                        r_amt = -r_amt
                    if row['type'] == 'Income' and r_amt < 0:
                        r_amt = -r_amt
                        
                    # Insert query with uuid()
                    cols = ['date', 'amount', 'currency', 'account', 'category', 'description', 'type', 'necessity']
                    vals = [r_date, r_amt, row['currency'], row['account'], row['category'], row['description'], row['type'], row['necessity']]
                    
                    # Need robust insert. Let's use simple append if possible?
                    # Manual insert string is risky. Use param binding if possible or careful formatting.
                    # DuckDB python execute supports params.
                    q = "INSERT INTO transactions (id, date, amount, currency, account, category, description, type, necessity) VALUES (uuid(), ?, ?, ?, ?, ?, ?, ?, ?)"
                    data_manager.con.execute(q, vals)
                st.toast(f"Added {len(new_rows)} new rows")

            # Identify Modified
            # Compare rows with same ID.
            # Convert both to dict by ID
            # This requires iterating current_ids.
            # Optimization: Only check visible rows (filtered_df vs edited_df subset with IDs)
            
            changes_count = 0
            
            # We need to ensure we don't re-update unchanged. Expensive loop?
            # Let's trust DuckDB speed for 40k rows? Maybe not.
            # Let's filter by modifying date/amount/etc.
            
            # Faster way: Just update ALL records present in edited_df?
            # "UPDATE transactions SET ... WHERE id = ?"
            # Yes, if dataset is small (<10k), doing 100 updates is instant. Doing 10k is slow.
            # User sees filtered view. If they edit, they edit filtered view.
            # Ideally we only update what changed.
            
            # Diff logic:
            # Merge original and edited on ID.
            merged = filtered_df.merge(edited_df, on='id', suffixes=('_old', '_new'))
            
            # Find rows where any column changed
            cols_to_check = ['date', 'amount', 'type', 'category', 'description', 'necessity', 'tags']
            
            changed_rows = pd.DataFrame()
            mask = pd.Series([False] * len(merged))
            
            for col in cols_to_check:
                # Compare handling NaNs
                # Convert to string for safer comparison? or specific type
                c_old = merged[f'{col}_old'].fillna('')
                c_new = merged[f'{col}_new'].fillna('')
                
                if col == 'tags':
                    # Special handling for list comparison
                    # Convert internal lists to tuple or string for comparison
                    # Handle case where one might be None/NaN and other []
                    def normalize_for_cmp(x):
                        if isinstance(x, list): return tuple(sorted(x))
                        if isinstance(x, str) and x == '': return ()
                        # DuckDB numpy array?
                        if hasattr(x, 'tolist'): return tuple(sorted(x.tolist()))
                        return x if x else ()
                        
                    s_old = c_old.apply(normalize_for_cmp)
                    s_new = c_new.apply(normalize_for_cmp)
                    mask |= (s_old != s_new)
                else:
                    mask |= (c_old != c_new)
            
            changed_rows = merged[mask]
            
            for _, row in changed_rows.iterrows():
                # Update DB
                # Fix signs again just in case
                r_amt = row['amount_new']
                if row['type_new'] == 'Expense' and r_amt > 0:
                    r_amt = -r_amt
                if row['type_new'] == 'Income' and r_amt < 0:
                    r_amt = -r_amt
                
                # Update Query
                q = """
                    UPDATE transactions 
                    SET date=?, amount=?, type=?, category=?, description=?, necessity=?, tags=?
                    WHERE id=?
                """
                data_manager.con.execute(q, [row['date_new'], r_amt, row['type_new'], row['category_new'], row['description_new'], row['necessity_new'], row['tags_new'], row['id']])
                changes_count += 1
                
            if changes_count > 0:
                st.toast(f"Updated {changes_count} rows")
            
            if changes_count > 0 or not new_rows.empty or deleted_ids:
                st.success("Saved successfully!")
                st.rerun()
            else:
                st.info("No changes detected.")

    except Exception as e:
        st.error(f"Error loading transactions: {e}")
