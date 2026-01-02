import streamlit as st
import yaml
from src.data_manager import DataManager

def render_settings(data_manager: DataManager):
    st.header("Settings & Rules")

    # Load current rules
    rules_engine = data_manager.rules_engine
    current_rules = rules_engine.rules

    st.subheader("Categorization Rules")
    st.info("Define keywords to automatically categorize transactions and set them as Need or Want.")

    # Display Categories
    if 'categories' in current_rules:
        # We'll use a form to allow batch updates or just simple expanders
        
        # New Category Form
        with st.expander("➕ Add New Category"):
            with st.form("add_cat_form"):
                new_cat_name = st.text_input("Category Name")
                new_cat_necessity = st.selectbox("Necessity", ["Need", "Want"])
                new_cat_keywords = st.text_area("Keywords (comma separated)", help="e.g. amazon, ebay, shop")
                submitted = st.form_submit_button("Add Category")
                
                if submitted and new_cat_name:
                    keywords = [k.strip() for k in new_cat_keywords.split(',') if k.strip()]
                    new_rule = {
                        'name': new_cat_name,
                        'necessity': new_cat_necessity,
                        'match': keywords
                    }
                    current_rules['categories'].append(new_rule)
                    rules_engine.save_rules(current_rules)
                    st.success(f"Added {new_cat_name}!")
                    st.rerun()

        # Edit Existing
        st.write("### Existing Categories")
        
        categories = current_rules.get('categories', [])
        for i, cat in enumerate(categories):
            with st.expander(f"{cat.get('name')} ({cat.get('necessity', 'Want')})"):
                name = st.text_input(f"Name #{i}", cat.get('name'), key=f"name_{i}")
                necessity = st.selectbox(f"Necessity #{i}", ["Need", "Want"], 
                                       index=0 if cat.get('necessity') == 'Need' else 1, 
                                       key=f"nec_{i}")
                
                current_keywords = ", ".join(cat.get('match', []))
                keywords_str = st.text_area(f"Keywords #{i}", current_keywords, key=f"kw_{i}")
                
                col_save, col_delete = st.columns([1, 5])
                if col_save.button("Update", key=f"btn_up_{i}"):
                    keywords = [k.strip() for k in keywords_str.split(',') if k.strip()]
                    cat['name'] = name
                    cat['necessity'] = necessity
                    cat['match'] = keywords
                    rules_engine.save_rules(current_rules)
                    st.success("Updated!")
                
                if col_delete.button("Delete Strategy", key=f"btn_del_{i}"):
                    current_rules['categories'].pop(i)
                    rules_engine.save_rules(current_rules)
                    st.rerun()

    st.divider()
    
    st.subheader("Advanced Actions")
    
    col_adv_1, col_adv_2 = st.columns(2)
    
    with col_adv_1:
        if st.button("Apply Rules to All Data"):
            with st.spinner("Re-applying rules to database..."):
                 try:
                     df = data_manager.get_transactions()
                     if not df.empty:
                         # Re-apply rules
                         df = rules_engine.apply_rules(df)
                         df = rules_engine.auto_tag_from_description(df)
                         
                         # Write back
                         data_manager.con.execute("DELETE FROM transactions")
                         
                         if 'necessity' not in df.columns:
                            df['necessity'] = 'Want'
                         
                         # Ensure ID exists, if not generate (though it should from get_transactions)
                         # But wait, df comes from get_transactions so it has id.
                         data_manager.con.execute("INSERT INTO transactions SELECT date, amount, currency, account, category, tags, description, type, source_file, original_description, necessity, id FROM df")
                         
                         st.success("Rules applied successfully!")
                     else:
                         st.warning("No data to process.")
                 except Exception as e:
                     st.error(f"Error applying rules: {e}")

    with col_adv_2:
        if st.button("Fix +/- Signs (Expense/Income)"):
            with st.spinner("Fixing signs..."):
                try:
                    # Update Expense to be negative
                    data_manager.con.execute("UPDATE transactions SET amount = -ABS(amount) WHERE type = 'Expense'")
                    # Update Income to be positive
                    data_manager.con.execute("UPDATE transactions SET amount = ABS(amount) WHERE type = 'Income'")
                    st.success("Signs fixed! Expenses are now negative, Income positive.")
                except Exception as e:
                    st.error(f"Error fixing signs: {e}")

    st.divider()
    st.subheader("⚖️ Reconcile Balances (Allineamento Saldo)")
    st.info("Use this to force the app's balance to match your real bank account. It will insert a 'Balance Adjustment' transaction.")
    
    # Get current balances
    try:
        current_bals = data_manager.con.execute("SELECT account, SUM(amount) as total FROM transactions GROUP BY account").fetchall()
        # Convert to dict
        bal_dict = {row[0]: row[1] for row in current_bals}
        
        # UI for adjustment
        col_rec_1, col_rec_2, col_rec_3 = st.columns([2, 1, 1])
        with col_rec_1:
            rec_acc = st.selectbox("Select Account", options=data_manager.get_unique_accounts() + ["New Account..."], key="rec_acc")
            if rec_acc == "New Account...":
                rec_acc = st.text_input("Account Name", key="rec_acc_new")
        
        current_val = bal_dict.get(rec_acc, 0.0)
        
        with col_rec_2:
            st.metric("Current App Balance", f"€{current_val:,.2f}")
            
        with col_rec_3:
            target_val = st.number_input("Real Balance (Realidad)", value=float(current_val), step=10.0, key="rec_target")
            
        if st.button("Update Balance"):
            diff = target_val - current_val
            if abs(diff) > 0.001:
                # Insert adjustment
                # We use a special category 'Adjustment'
                import datetime
                today = datetime.date.today()
                
                # Check column consistency
                # insert columns: date, amount, currency, account, category, tags, description, type, source_file, original_description, necessity 
                # (and uuid handles itself or we add it)
                
                q = """
                INSERT INTO transactions (id, date, amount, currency, account, category, tags, description, type, source_file, original_description, necessity)
                VALUES (uuid(), ?, ?, 'EUR', ?, 'Adjustment', [], 'Manual Balance Reconciliation', 'Adjustment', 'reconcile', 'Balance Fix', 'Need')
                """
                data_manager.con.execute(q, [today, diff, rec_acc])
                
                st.success(f"Adjusted {rec_acc} by €{diff:,.2f}. New Balance should be €{target_val:,.2f}")
                st.rerun()
            else:
                st.info("Balances match. No adjustment needed.")
                
    except Exception as e:
        st.error(f"Error checking balances: {e}")

    st.divider()
    
    # --- Wallet Management (Rename & Icon) ---
    st.subheader("👛 Manage Wallets (Rename & Icons)")
    
    # Load rules for icons
    rules = rules_engine.rules
    if 'wallets' not in rules:
        rules['wallets'] = {}
        
    # Get accounts
    accounts = data_manager.get_unique_accounts()
    
    col_w1, col_w2, col_w3 = st.columns([2, 2, 1])
    
    with col_w1:
        target_account = st.selectbox("Select Wallet to Edit", accounts, key='wallet_edit_sel')
        
    with col_w2:
        new_name = st.text_input("Rename to", value=target_account, key='wallet_rename_input')
        
    with col_w3:
        # Icon picker
        current_icon_conf = rules['wallets'].get(new_name, {}).get('icon', '👛') if new_name else '👛'
        # Try to find icon for current target if not renamed yet
        if target_account in rules['wallets']:
            current_icon_conf = rules['wallets'][target_account].get('icon', '👛')
            
        icon_options = ["👛", "🏦", "💳", "💵", "🐷", "📈", "🏠", "🚗", "👶", "✈️", "🎁", "🔧"]
        selected_icon = st.selectbox("Icon", icon_options, index=icon_options.index(current_icon_conf) if current_icon_conf in icon_options else 0)
        
    if st.button("Save Wallet Changes"):
        try:
            # 1. Update Name in DB if changed
            if target_account != new_name:
                data_manager.con.execute("UPDATE transactions SET account = ? WHERE account = ?", [new_name, target_account])
                st.toast(f"Renamed '{target_account}' to '{new_name}'")
                
                # Check if old name had config, move it
                if target_account in rules['wallets']:
                    rules['wallets'][new_name] = rules['wallets'].pop(target_account)
            
            # 2. Update Icon in Rules
            if new_name not in rules['wallets']:
                rules['wallets'][new_name] = {}
            
            rules['wallets'][new_name]['icon'] = selected_icon
            rules_engine.save_rules(rules)
            
            st.success("Wallet settings saved!")
            st.rerun()
            
            st.rerun()
            
        except Exception as e:
            st.error(f"Error saving changes: {e}")

    st.divider()


    
    # --- Backup & Export ---
    st.subheader("📦 Backup & Export")
    st.write("Download a ZIP file containing all your transactions formatted as CSVs.")
    
    zip_data = data_manager.export_backup_zip()
    st.download_button(
        label="Download Full Backup (ZIP)",
        data=zip_data,
        file_name="finance_backup.zip",
        mime="application/zip"
    )
