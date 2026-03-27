import streamlit as st
import yaml
import pandas as pd
from src.data_manager import DataManager

def render_settings(data_manager: DataManager):
    import pandas as pd
    st.header("Settings & Rules")
    
    # --- Initial Balance ---
    st.subheader("💰 Initial Balance (Patrimonio Iniziale)")
    st.info("Set the starting point for your Net Worth calculation.")
    
    current_init = data_manager.get_initial_balance()
    
    default_date = pd.to_datetime('2022-01-01').date()
    default_amount = 0.0
    
    if current_init:
        # Safe conversion
        try:
             # If duckdb returns date object or datetime
             d = current_init['date']
             if hasattr(d, 'date'):
                 default_date = d.date()
             else:
                 default_date = d # assume date object
             default_amount = float(current_init['amount'])
        except:
             pass

    col_ib1, col_ib2, col_ib3 = st.columns([1, 1, 1])
    with col_ib1:
        init_date = st.date_input("Start Date", value=default_date)
    with col_ib2:
        init_amount = st.number_input("Starting Amount (€)", value=default_amount, step=100.0)
        
    if st.button("Save Initial Balance"):
        data_manager.set_initial_balance(init_date, init_amount)
        st.success(f"Initial Balance updated: €{init_amount:,.2f} on {init_date}")
        st.rerun()

    st.divider()

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

    # --- Necessity by Category & Tag ---
    st.subheader("⚖️ Necessity Rules")
    st.caption("Classifica categorie e tag come **Need** (bisogno) o **Want** (desiderio). Verrà applicato ad ogni transazione corrispondente.")

    # Fetch transaction counts for context
    try:
        cat_counts = data_manager.con.execute(
            "SELECT category, COUNT(*) as cnt FROM transactions WHERE category IS NOT NULL GROUP BY category"
        ).df().set_index('category')['cnt'].to_dict()
    except Exception:
        cat_counts = {}

    try:
        tag_counts_rows = data_manager.con.execute(
            "SELECT tag, COUNT(*) as cnt FROM (SELECT unnest(tags) as tag FROM transactions) t WHERE tag IS NOT NULL GROUP BY tag"
        ).fetchall()
        tag_counts = {r[0]: r[1] for r in tag_counts_rows if r[0]}
    except Exception:
        tag_counts = {}

    db_cats = data_manager.get_unique_categories()
    rule_cats = [c['name'] for c in current_rules.get('categories', [])]
    all_cats = sorted(set(db_cats + rule_cats))

    cat_necessity_map = current_rules.get('category_necessity', {})
    for r in current_rules.get('categories', []):
        if r.get('necessity') and r['name'] not in cat_necessity_map:
            cat_necessity_map[r['name']] = r['necessity']

    db_tags = data_manager.get_unique_tags()
    tag_necessity_map = current_rules.get('tag_necessity', {})

    nec_tab1, nec_tab2 = st.tabs([f"📂 Categorie ({len(all_cats)})", f"🏷️ Tag ({len(db_tags)})"])

    def _nec_badge(nec):
        if nec == 'Need':
            return '<span style="background:#e8f5e9;color:#2e7d32;border-radius:4px;padding:2px 8px;font-size:0.75em;font-weight:600;">✅ NEED</span>'
        return '<span style="background:#fff3e0;color:#e65100;border-radius:4px;padding:2px 8px;font-size:0.75em;font-weight:600;">🛍️ WANT</span>'

    with nec_tab1:
        new_cat_necessity = {}

        # Summary bar
        n_need = sum(1 for c in all_cats if cat_necessity_map.get(c, 'Want') == 'Need')
        n_want = len(all_cats) - n_need
        st.markdown(
            f'<div style="margin-bottom:12px">'
            f'<span style="background:#e8f5e9;color:#2e7d32;border-radius:4px;padding:3px 10px;font-weight:600;margin-right:8px;">✅ Need: {n_need}</span>'
            f'<span style="background:#fff3e0;color:#e65100;border-radius:4px;padding:3px 10px;font-weight:600;">🛍️ Want: {n_want}</span>'
            f'</div>',
            unsafe_allow_html=True
        )

        n_cols = 3
        rows = [all_cats[i:i+n_cols] for i in range(0, len(all_cats), n_cols)]
        for row_cats in rows:
            cols = st.columns(n_cols)
            for col, cat in zip(cols, row_cats):
                with col:
                    current_nec = cat_necessity_map.get(cat, 'Want')
                    count = cat_counts.get(cat, 0)
                    border = "#4CAF50" if current_nec == 'Need' else "#FF7043"
                    st.markdown(
                        f'<div style="border-left:4px solid {border};padding:4px 10px;border-radius:0 6px 6px 0;background:{"#f9fbe7" if current_nec=="Need" else "#fff8f5"};margin-bottom:2px">'
                        f'<strong style="font-size:0.9em">{cat}</strong><br>'
                        f'<span style="color:#888;font-size:0.75em">{count} transazioni</span>&nbsp;'
                        f'{_nec_badge(current_nec)}'
                        f'</div>',
                        unsafe_allow_html=True
                    )
                    val = st.radio("", ['Need', 'Want'],
                                   index=0 if current_nec == 'Need' else 1,
                                   key=f"catnec_{cat}",
                                   horizontal=True,
                                   label_visibility="collapsed")
                    new_cat_necessity[cat] = val

        if st.button("💾 Salva Necessity Categorie", type="primary"):
            current_rules['category_necessity'] = new_cat_necessity
            rules_engine.save_rules(current_rules)
            st.success(f"Salvato! {sum(1 for v in new_cat_necessity.values() if v=='Need')} Need · {sum(1 for v in new_cat_necessity.values() if v=='Want')} Want")
            st.rerun()

    with nec_tab2:
        new_tag_necessity = {}

        if not db_tags:
            st.info("Nessun tag trovato nel database.")
        else:
            n_need_t = sum(1 for t in db_tags if tag_necessity_map.get(t, 'Want') == 'Need')
            n_want_t = len(db_tags) - n_need_t
            st.markdown(
                f'<div style="margin-bottom:12px">'
                f'<span style="background:#e8f5e9;color:#2e7d32;border-radius:4px;padding:3px 10px;font-weight:600;margin-right:8px;">✅ Need: {n_need_t}</span>'
                f'<span style="background:#fff3e0;color:#e65100;border-radius:4px;padding:3px 10px;font-weight:600;">🛍️ Want: {n_want_t}</span>'
                f'</div>',
                unsafe_allow_html=True
            )

            n_cols = 4
            sorted_tags = sorted(db_tags)
            rows = [sorted_tags[i:i+n_cols] for i in range(0, len(sorted_tags), n_cols)]
            for row_tags in rows:
                cols = st.columns(n_cols)
                for col, tag in zip(cols, row_tags):
                    with col:
                        current_nec = tag_necessity_map.get(tag, 'Want')
                        count = tag_counts.get(tag, 0)
                        border = "#4CAF50" if current_nec == 'Need' else "#FF7043"
                        st.markdown(
                            f'<div style="border-left:4px solid {border};padding:4px 10px;border-radius:0 6px 6px 0;background:{"#f9fbe7" if current_nec=="Need" else "#fff8f5"};margin-bottom:2px">'
                            f'<strong style="font-size:0.9em">#{tag}</strong><br>'
                            f'<span style="color:#888;font-size:0.75em">{count} transazioni</span>&nbsp;'
                            f'{_nec_badge(current_nec)}'
                            f'</div>',
                            unsafe_allow_html=True
                        )
                        val = st.radio("", ['Need', 'Want'],
                                       index=0 if current_nec == 'Need' else 1,
                                       key=f"tagnec_{tag}",
                                       horizontal=True,
                                       label_visibility="collapsed")
                        new_tag_necessity[tag] = val

            if st.button("💾 Salva Necessity Tag", type="primary"):
                current_rules['tag_necessity'] = new_tag_necessity
                rules_engine.save_rules(current_rules)
                st.success(f"Salvato! {sum(1 for v in new_tag_necessity.values() if v=='Need')} Need · {sum(1 for v in new_tag_necessity.values() if v=='Want')} Want")
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
                         before_cat = df[['id', 'category', 'necessity']].copy()

                         # Re-apply rules in memory
                         df = rules_engine.apply_rules(df)
                         df = rules_engine.auto_tag_from_description(df)

                         if 'notes' not in df.columns:
                             df['notes'] = None

                         # Count what changed
                         changed_cat = (df['category'] != before_cat['category']).sum()
                         changed_nec = (df['necessity'] != before_cat['necessity']).sum()

                         # Wrap DELETE + INSERT in a transaction to avoid data loss on failure
                         data_manager.con.execute("BEGIN TRANSACTION")
                         try:
                             data_manager.con.execute("DELETE FROM transactions")
                             data_manager.con.execute("INSERT INTO transactions SELECT date, amount, currency, account, category, tags, description, type, source_file, original_description, necessity, id, notes FROM df")
                             data_manager.con.execute("COMMIT")
                         except Exception as inner_e:
                             data_manager.con.execute("ROLLBACK")
                             raise inner_e

                         st.success(f"Rules applied to {len(df)} transactions — {changed_cat} categorie aggiornate, {changed_nec} necessity aggiornate.")
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




    st.divider()

    # --- Budget per Category ---
    st.subheader("🎯 Budget Mensile per Categoria")
    st.info("Imposta un budget mensile per categoria. Verrà mostrato come progress bar nella Dashboard.")

    budgets = current_rules.get('budgets', {})
    db_cats = data_manager.get_unique_categories()
    rule_cats = [c['name'] for c in current_rules.get('categories', [])]
    all_cats = sorted(set(db_cats + rule_cats))

    if all_cats:
        updated_budgets = {}
        n_cols = 3
        rows = [all_cats[i:i+n_cols] for i in range(0, len(all_cats), n_cols)]
        for row_cats in rows:
            cols = st.columns(n_cols)
            for col, cat in zip(cols, row_cats):
                current_val = float(budgets.get(cat, 0.0))
                val = col.number_input(f"{cat}", value=current_val, step=50.0, min_value=0.0, key=f"budget_{cat}")
                if val > 0:
                    updated_budgets[cat] = val

        if st.button("💾 Save Budgets"):
            current_rules['budgets'] = updated_budgets
            rules_engine.save_rules(current_rules)
            st.success(f"Budgets salvati per {len(updated_budgets)} categorie.")
            st.rerun()
    else:
        st.warning("Nessuna categoria trovata. Importa dei dati o crea categorie prima.")

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
