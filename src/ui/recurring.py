import streamlit as st
import pandas as pd
from src.data_manager import DataManager

def render_recurring(data_manager: DataManager):
    st.title("🔁 Recurring Expenses (Spese Fisse)")
    
    # --- Action Section ---
    col_act_1, col_act_2 = st.columns([3, 1])
    with col_act_1:
        st.info("Manage your fixed expenses here. The system will automatically generate transactions when they are due.")
    
    with col_act_2:
        if st.button("🔄 Check & Generate Due", type="primary", use_container_width=True):
            with st.spinner("Checking due expenses..."):
                count = data_manager.process_recurring()
                if count > 0:
                    st.success(f"Generated {count} transactions!")
                    st.toast(f"Generated {count} transactions!", icon="✅")
                    # Optional: st.rerun() if we want to show them immediately in a log, but not strictly needed here
                else:
                    st.info("No expenses due today.")
                    st.toast("No expenses due today.", icon="ℹ️")

    # --- Upcoming Projections Section ---
    from datetime import date, timedelta
    
    st.subheader("📅 Upcoming in next 30 days")
    
    # Get projections for next 30 days
    today = date.today()
    next_30 = today + timedelta(days=30)
    
    proj_idx = data_manager.get_projected_recurring(next_30)
    
    if not proj_idx.empty:
        # Sort by date
        proj_idx = proj_idx.sort_values('date')
        
        # Display nicely
        
        # Summary metrics
        total_p = proj_idx[proj_idx['amount'] < 0]['amount'].sum()
        st.caption(f"Total scheduled expenses: **€{total_p:,.2f}**")
        
        # Cards
        for i, row in proj_idx.iterrows():
            days_left = (row['date'] - today).days
            
            # Color coding
            if days_left < 0:
                 status = "⚠️ OVERDUE"
                 color = "#FFCDD2" # Red Light
            elif days_left == 0:
                 status = "🔥 TODAY"
                 color = "#FFF9C4" # Yellow Light
            elif days_left <= 7:
                 status = f"⏰ In {days_left} days"
                 color = "#E1F5FE" # Blue Light
            else:
                 status = f"🗓 In {days_left} days"
                 color = "#F5F5F5" # Grey
            
            with st.container():
                st.markdown(f"""
                <div style="background-color: {color}; padding: 10px; border-radius: 8px; margin-bottom: 8px; display: flex; align-items: center; justify-content: space-between;">
                    <div style="flex-grow: 1;">
                        <span style="font-weight: bold; font-size: 1.1em; color: #333;">{row['name']}</span>
                         <br><span style="font-size: 0.9em; color: #666;">{row['date'].strftime('%d %b %Y')} ({row['frequency']})</span>
                    </div>
                    <div style="text-align: right;">
                        <span style="font-weight: bold; color: {'red' if row['amount'] < 0 else 'green'}; font-size: 1.1em;">€{row['amount']:.2f}</span>
                        <br><span style="font-size: 0.85em; font-weight: bold; color: #555;">{status}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
    else:
        st.info("No recurring expenses scheduled for the next 30 days.")
        
    st.divider()

    # --- Subscription Suggestions ---
    suggestions = data_manager.get_subscription_suggestions()
    if suggestions:
        st.subheader("💡 Possibili abbonamenti da aggiungere")
        st.caption("Servizi ancora attivi rilevati nelle transazioni ma non tra le ricorrenti. "
                   "Frequenza e importo sono dedotti dai pagamenti recenti (gli abbonamenti "
                   "senza pagamenti recenti vengono ignorati automaticamente).")
        _freq_lbl = {'Monthly': 'mese', 'Yearly': 'anno', 'Weekly': 'sett.'}
        for s in suggestions:
            c1, c2, c3, c4 = st.columns([3, 3, 1, 1])
            c1.markdown(f"**{s['tag'].title()}** — €{s['amount']:,.2f}/{_freq_lbl.get(s['frequency'], 'mese')}")
            c2.caption(f"{s['frequency']} · {s['n']} pagamenti · ultimo {s['last']} · cat. {s['category']}")
            if c3.button("➕ Aggiungi", key=f"sug_add_{s['tag']}", use_container_width=True):
                from datetime import date
                data_manager.add_recurring(
                    name=s['tag'].title(),
                    amount=-abs(s['amount']),
                    category=s['category'],
                    account=s['account'],
                    frequency=s['frequency'],
                    start_date=date.today(),
                    description=s['tag'].title(),
                    tags=[s['tag']],
                )
                st.success(f"'{s['tag'].title()}' aggiunto ({s['frequency']}, €{s['amount']:,.2f}). "
                           "Rifinisci data/importo qui sotto se serve.")
                st.rerun()
            if c4.button("🙈 Ignora", key=f"sug_ign_{s['tag']}", use_container_width=True):
                data_manager.ignore_subscription_suggestion(s['tag'])
                st.toast(f"Suggerimento '{s['tag']}' ignorato.")
                st.rerun()
        st.divider()

    # --- Suggeritore: spese ricorrenti segnate a mano ---
    candidates = data_manager.get_recurring_candidates()
    if candidates:
        st.subheader("💡 Forse è una spesa ricorrente")
        st.caption("Spese che inserisci a mano con cadenza regolare e importo stabile. "
                   "Mettendole tra le ricorrenti eviti di riscriverle e rendi precise proiezione e calendario.")
        _fl = {'Monthly': 'mese', 'Bimonthly': 'bimestre', 'Quarterly': 'trimestre', 'Yearly': 'anno'}
        for cnd in candidates:
            k = cnd['key']
            r1, r2, r3, r4 = st.columns([3, 3, 1, 1])
            r1.markdown(f"**{k.title()}** — €{cnd['amount']:,.2f}/{_fl.get(cnd['frequency'], 'mese')}")
            r2.caption(f"{cnd['frequency']} · {cnd['months']} mesi · {cnd['source']} · cat. {cnd['category']}")
            if r3.button("➕ Aggiungi", key=f"cand_add_{cnd['source']}_{k}", use_container_width=True):
                from datetime import date
                tags = [cnd['tag']] if cnd.get('tag') else []
                data_manager.add_recurring(
                    name=k.title(), amount=-abs(cnd['amount']), category=cnd['category'],
                    account=cnd['account'], frequency=cnd['frequency'], start_date=date.today(),
                    description=k.title(), tags=tags,
                )
                st.success(f"'{k.title()}' aggiunto alle ricorrenti ({cnd['frequency']}, €{cnd['amount']:,.2f}).")
                st.rerun()
            if r4.button("🙈 Ignora", key=f"cand_ign_{cnd['source']}_{k}", use_container_width=True):
                data_manager.ignore_recurring_candidate(k)
                st.toast(f"'{k}' ignorato.")
                st.rerun()
        st.divider()

    # --- Add New Recurring ---
    st.subheader("➕ Add New Template")
    
    with st.expander("Create New Recurring Expense", expanded=True):
        with st.form("add_rec_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                r_name = st.text_input("Template Name", placeholder="e.g. Netflix Subscription")
                r_amount = st.number_input("Amount (Negative for Expense)", value=-10.0, step=1.0, help="Use negative values for expenses, positive for income.")
                r_cat = st.selectbox("Category", data_manager.get_unique_categories() + ["Other"])
                if r_cat == "Other":
                   r_cat_custom = st.text_input("New Category Name")
                   r_cat = r_cat_custom if r_cat_custom else "General"
                   
            with col2:
                r_acc = st.selectbox("Account/Wallet", data_manager.get_unique_accounts())
                r_freq = st.selectbox("Frequency", ["Monthly", "Bimonthly", "Quarterly", "Yearly", "Weekly"])
                r_date = st.date_input("Next Due Date")



            # Limits / Termination
            st.markdown("#### Duration limits (Optional)")
            r_duration_type = st.radio("Stop condition", ["Indefinite (Forever)", "Fixed Installments (Rate)", "Until Date (Ends on)"], horizontal=True, index=0)
            
            r_installments = None
            r_installments_total = None
            r_end_date = None

            if r_duration_type == "Fixed Installments (Rate)":
                ci1, ci2 = st.columns(2)
                r_inst_total = ci1.number_input("Rate totali", min_value=1, value=4, step=1)
                r_inst_paid = ci2.number_input("Rate già pagate", min_value=0, value=0, step=1)
                r_installments = max(int(r_inst_total) - int(r_inst_paid), 0)
                r_installments_total = int(r_inst_total)
                st.caption(f"Rimangono {r_installments} rate su {r_inst_total} (es. condominio: totale 4, già pagate 2).")
            elif r_duration_type == "Until Date (Ends on)":
                r_end_date = st.date_input("End Date (Inclusive)")
                st.caption("Will stop generating after this date.")

            st.markdown("#### Details")
            r_desc = st.text_input("Description for Transaction", placeholder="e.g. Monthly subscription payment")
            
            # Tags handling
            existing_tags = data_manager.get_unique_tags()
            r_tags_sel = st.multiselect("Tags", existing_tags, placeholder="Select tags...")
            r_new_tag = st.text_input("Add New Tag (Optional)", placeholder="e.g. #subscription")
            
            submitted = st.form_submit_button("Save Template")
            
            if submitted:
                if not r_name:
                    st.error("Name is required.")
                else:
                    # Merge tags
                    final_tags = r_tags_sel
                    if r_new_tag:
                        clean = r_new_tag.strip().replace('#', '').lower()
                        if clean and clean not in final_tags:
                            final_tags.append(clean)
                    
                    # Final Description fallback
                    final_desc = r_desc if r_desc else r_name
                    
                    # Final Description fallback
                    final_desc = r_desc if r_desc else r_name
                    
                    data_manager.add_recurring(r_name, r_amount, r_cat, r_acc, r_freq, r_date, final_desc, final_tags, r_installments, r_end_date, r_installments_total)
                    st.success(f"Recurring expense '{r_name}' added!")
                    st.rerun()

    st.divider()

    # --- List Existing ---
    st.subheader("📋 Active Templates")

    rec_df = data_manager.get_recurring()

    # Avanzamento rate (per gli impegni con numero di rate definito)
    if not rec_df.empty and 'installments_total' in rec_df.columns:
        with_progress = rec_df[rec_df['installments_total'].notna() &
                               rec_df['remaining_installments'].notna()]
        if not with_progress.empty:
            st.markdown("**📊 Avanzamento rate**")
            for _, r in with_progress.iterrows():
                tot = int(r['installments_total'])
                rem = int(r['remaining_installments'])
                paid = max(tot - rem, 0)
                amt = abs(float(r['amount']))
                pct = (paid / tot) if tot else 0
                st.markdown(f"**{r['name']}** — pagate {paid}/{tot} · "
                            f"restano **{rem} rate** (€{rem * amt:,.0f}) · rata €{amt:,.0f}")
                st.progress(min(pct, 1.0), text=f"{pct * 100:.0f}% completato")
            st.divider()

    if not rec_df.empty:
        # Display as a table with more details
        
        # Configure columns for editing
        column_config = {
            "name": st.column_config.TextColumn("Name", required=True),
            "amount": st.column_config.NumberColumn("Amount", format="€%.2f", required=True),
            "category": st.column_config.SelectboxColumn("Category", options=data_manager.get_unique_categories() + ["Other"], required=True),
            "account": st.column_config.SelectboxColumn("Account", options=data_manager.get_unique_accounts(), required=True),
            "frequency": st.column_config.SelectboxColumn("Frequency", options=["Monthly", "Bimonthly", "Quarterly", "Yearly", "Weekly"], required=True),
            "installments_total": st.column_config.NumberColumn("Rate totali", help="Numero totale di rate (per la barra di avanzamento)", min_value=1),
            "next_date": st.column_config.DateColumn("Next Due", required=True),
            "end_date": st.column_config.DateColumn("Ends On"),
            "remaining_installments": st.column_config.NumberColumn("Installments Left", help="Remaining payments", min_value=0),
            "tags": st.column_config.ListColumn("Tags"),
            "description": st.column_config.TextColumn("Description"),
        }
        
        # Show editor
        edited_rec_df = st.data_editor(
            rec_df,
            column_config=column_config,
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic", # Allow add/delete
            key="rec_editor"
        )
        
        if st.button("💾 Save Changes", type="primary"):
            # Detect Changes
            # Similar logic to transactions: Diff or Update All
            # Since number of recurring expenses is small, we can just update those that changed or are new.
            
            changes_count = 0
            
            # 1. Access original DF by ID to track changes
            # Convert to dict for fast lookup
            
            # --- Handle Deletions ---
            original_ids = set(rec_df['id'].dropna())
            current_ids = set(edited_rec_df['id'].dropna())
            deleted_ids = original_ids - current_ids
            
            for d_id in deleted_ids:
                data_manager.delete_recurring(d_id)
                changes_count += 1
                
            # --- Handle Updates & New ---
            for i, row in edited_rec_df.iterrows():
                # Check if New (No ID)
                if pd.isna(row.get('id')) or row.get('id') == '':
                    # It's a new row added via UI
                    # We need to map columns to add_recurring arguments
                    # Ensure minimal fields
                    if row['name']:
                         # Handle tags
                         tags_val = row['tags']
                         if hasattr(tags_val, 'tolist'): tags_val = tags_val.tolist()
                         if not isinstance(tags_val, list): tags_val = []
                         
                         data_manager.add_recurring(
                             name=row['name'],
                             amount=row['amount'],
                             category=row.get('category', 'General'),
                             account=row.get('account', 'Cash'),
                             frequency=row.get('frequency', 'Monthly'),
                             start_date=row['next_date'],
                             description=row.get('description', ''),
                             tags=tags_val,
                             installments=row.get('remaining_installments'),
                             end_date=row.get('end_date')
                         )
                         changes_count += 1
                else:
                    # It's an existing row. Check for changes.
                    # We can compare against original row with same ID
                    orig_row = rec_df[rec_df['id'] == row['id']].iloc[0]
                    
                    # Fields to check
                    fields = ['name', 'amount', 'category', 'account', 'frequency', 'next_date', 'description', 'remaining_installments', 'end_date', 'tags']
                    updates = {}
                    
                    for f in fields:
                        val_new = row.get(f)
                        val_old = orig_row.get(f)
                        
                        # Normalize for comparison
                        if f == 'tags':
                             if hasattr(val_new, 'tolist'): val_new = val_new.tolist()
                             if not isinstance(val_new, list): val_new = [] if pd.isna(val_new) else [str(val_new)]
                             
                             if hasattr(val_old, 'tolist'): val_old = val_old.tolist()
                             if not isinstance(val_old, list): val_old = [] if pd.isna(val_old) else [str(val_old)]
                             
                             if tuple(sorted(val_new)) != tuple(sorted(val_old)):
                                 updates[f] = val_new
                        else:
                             # Handle NaNs
                             if pd.isna(val_new) and pd.isna(val_old): continue
                             if val_new != val_old:
                                 updates[f] = val_new
                                 
                    if updates:
                        data_manager.update_recurring(row['id'], **updates)
                        changes_count += 1
            
            if changes_count > 0:
                st.success(f"Saved {changes_count} changes!")
                st.rerun()
            else:
                st.info("No changes detected.")

    else:
        st.info("No recurring expenses set up yet.")
