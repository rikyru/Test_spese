import streamlit as st
import pandas as pd
from datetime import datetime, date
from src.data_manager import DataManager


def _my_share_pct(category, tags, conf):
    """Quota % a mio carico per categoria/tag, secondo le regole di split (Tag > Categoria > Default)."""
    tset = [str(t).lower().replace('#', '').strip() for t in (tags or [])]
    for r in conf.get('rules', []):
        if r.get('type') == 'tag' and r.get('match', '').lower().replace('#', '').strip() in tset:
            return r['my_share']
    for r in conf.get('rules', []):
        if r.get('type') == 'category' and r.get('match') == category:
            return r['my_share']
    return conf.get('default_share_pct', 50)


def render_split(data_manager: DataManager):
    st.header("💞 Expense Splitting (Granular)")
    
    # Load Config
    rules_engine = data_manager.rules_engine
    full_rules = rules_engine.rules
    
    # Config schema update
    if 'split_config' not in full_rules:
        full_rules['split_config'] = {}
        
    conf = full_rules['split_config']
    
    # Defaut values if missing
    if 'partner_name' not in conf: conf['partner_name'] = 'Partner'
    if 'default_share_pct' not in conf: conf['default_share_pct'] = 50
    if 'rules' not in conf: conf['rules'] = [] # List of {type, match, my_share}
    if 'loan_tags' not in conf: conf['loan_tags'] = ['prestito', 'loan', 'anticipo']
    
    tab_report, tab_loans, tab_settings = st.tabs(["📅 Monthly Report", "💸 Prestiti / Crediti", "⚙️ Rules Configuration"])
    
    # --- SETTINGS TAB ---
    with tab_settings:
        st.subheader("General Settings")
        with st.form("general_split_config"):
            new_name = st.text_input("Partner Name", conf['partner_name'])
            new_def_pct = st.slider("Default My Share (%)", 0, 100, conf['default_share_pct'], help="Fallback if no specific rule matches.")
            new_loan_tags = st.text_input("Loan Tags (100% Owed)", ", ".join(conf['loan_tags']))
            
            if st.form_submit_button("Save General"):
                conf['partner_name'] = new_name
                conf['default_share_pct'] = new_def_pct
                conf['loan_tags'] = [t.strip() for t in new_loan_tags.split(',') if t.strip()]
                full_rules['split_config'] = conf
                rules_engine.save_rules(full_rules)
                st.success("Saved!")
                st.rerun()
                
        st.divider()
        st.subheader("Specific Splitting Rules")
        st.info("Define specific shares for categories or tags. Rules are applied in order (Tag > Category > Default).")
        
        # Rule Editor
        rules_list = conf.get('rules', [])
        
        # Display existing rules
        for i, rule in enumerate(rules_list):
            c1, c2, c3, c4 = st.columns([2, 3, 2, 1])
            with c1:
                st.write(f"**{rule['type'].capitalize()}**")
            with c2:
                st.write(f"`{rule['match']}`")
            with c3:
                st.write(f"My Share: **{rule['my_share']}%**")
            with c4:
                if st.button("🗑️", key=f"del_rule_{i}"):
                    rules_list.pop(i)
                    conf['rules'] = rules_list
                    rules_engine.save_rules(full_rules)
                    st.rerun()
                    
        # Add New Rule Form
        with st.expander("➕ Add New Rule"):
            with st.form("add_rule_form"):
                r_type = st.selectbox("Type", ["Category", "Tag"])
                
                if r_type == "Category":
                    avail_cats = data_manager.get_unique_categories()
                    r_match = st.selectbox("Select Category", avail_cats)
                else:
                    r_match_input = st.text_input("Tag Name (e.g. luce)", placeholder="Enter tag without #")
                    r_match = r_match_input.strip().lower()
                    
                r_share = st.slider("My Share % for this", 0, 100, 50)
                
                if st.form_submit_button("Add Rule"):
                    if r_match:
                        # Check duplicate
                        exists = any(r['type'] == r_type.lower() and r['match'] == r_match for r in rules_list)
                        if not exists:
                            rules_list.append({
                                'type': r_type.lower(),
                                'match': r_match,
                                'my_share': r_share
                            })
                            conf['rules'] = rules_list
                            rules_engine.save_rules(full_rules)
                            st.rerun()
                        else:
                            st.error("Rule already exists!")
                    else:
                        st.error("Please define a match value.")

    # --- REPORT TAB ---
    with tab_report:
        # Date Filter
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            today = date.today()
            # Year select
            df_all = data_manager.get_transactions()
            if not df_all.empty:
                years = sorted(df_all['date'].dt.year.unique(), reverse=True)
                if today.year not in years: years.insert(0, today.year)
                sel_year = st.selectbox("Year", years)
            else:
                sel_year = today.year
                
        with col_d2:
            sel_month = st.selectbox("Month", range(1, 13), index=today.month - 1)

        # --- Ha pagato il partner (spesa condivisa pagata da lui/lei) ---
        with st.expander(f"🛒 Ha pagato {conf['partner_name']} (spesa condivisa)", expanded=False):
            st.caption(f"La tua quota diventa una tua spesa e **riduce** quanto {conf['partner_name']} ti deve. "
                       "Registrata su un conto virtuale 'Partner' (non tocca i tuoi conti reali).")
            with st.form("partner_paid_form", clear_on_submit=True):
                pp1, pp2 = st.columns([3, 2])
                pp_name = pp1.text_input("Descrizione", placeholder="es. Spesa alimentare Coop")
                pp_amount = pp2.number_input("Importo pagato dal partner €", min_value=0.0, step=1.0)
                pp3, pp4, pp5 = st.columns(3)
                pp_cat = pp3.selectbox("Categoria", data_manager.get_unique_categories())
                pp_date = pp4.date_input("Data", today, key="pp_date")
                pp_share = pp5.slider("La mia quota %", 0, 100,
                                      int(_my_share_pct(pp_cat, [], conf)), key="pp_share")
                pp_tags_sel = st.multiselect("Tag", data_manager.get_unique_tags(), key="pp_tags")
                pp_new_tag = st.text_input("Nuovo tag (opzionale)", placeholder="#coop", key="pp_new_tag")
                if st.form_submit_button("Registra spesa del partner"):
                    if pp_name and pp_amount > 0:
                        pp_tags = list(pp_tags_sel)
                        if pp_new_tag.strip():
                            pp_tags.append(pp_new_tag.strip().replace('#', '').lower())
                        my_amt = data_manager.add_partner_paid_expense(pp_name, pp_amount, pp_cat, pp_date,
                                                                       pp_share, extra_tags=pp_tags)
                        st.success(f"Registrata la tua quota €{my_amt:,.2f} ({pp_share}% di €{pp_amount:,.0f}). "
                                   f"{conf['partner_name']} ti deve €{my_amt:,.2f} in meno.")
                        st.rerun()
                    else:
                        st.warning("Inserisci descrizione e importo.")

        # Filter Data
        if df_all.empty:
            st.info("No transactions found.")
            return

        df_all['date'] = pd.to_datetime(df_all['date'])
        mask = (df_all['date'].dt.year == sel_year) & (df_all['date'].dt.month == sel_month) & (df_all['type'] == 'Expense')
        df_m = df_all[mask].copy()
        
        if df_m.empty:
            st.warning("No expenses found.")
            return

        # Initialize Debug Columns to avoid KeyError
        df_m['debug_tags_clean'] = ""
        df_m['debug_log'] = ""

        # --- CALCULATION LOGIC ---
        
        loan_tags = conf.get('loan_tags', [])
        rules_list = conf.get('rules', [])
        default_pct = conf.get('default_share_pct', 50) / 100.0
        
        split_transactions = []
        loan_transactions = []
        partner_paid_transactions = []

        total_partner_owes = 0.0
        partner_paid_total = 0.0

        for idx, row in df_m.iterrows():
            amount = abs(row['amount'])
            
            # Robust tag normalization
            raw_tags = row['tags']
            tags = []
            parse_log = []
            
            parse_log.append(f"Type: {type(raw_tags).__name__}")
            parse_log.append(f"Val: {str(raw_tags)}")
            
            try:
                # 1. String check
                if isinstance(raw_tags, str):
                    parse_log.append("Is String")
                    clean_str = raw_tags.strip()
                    if clean_str.startswith('[') and clean_str.endswith(']'):
                         parse_log.append("Is Bracketed")
                         content = clean_str[1:-1]
                         if content:
                             parts = content.split(',')
                             tags = [p.replace("'", "").replace('"', "").lower().replace('#', '').strip() for p in parts]
                         else:
                             tags = []
                    else:
                        parse_log.append("Is CSV")
                        if clean_str:
                             tags = [t.lower().replace('#', '').strip() for t in clean_str.split(',')]
                        else:
                             tags = []
                
                # 2. Iterable Check (List, Tuple, Numpy Array)
                elif hasattr(raw_tags, '__iter__'):
                     parse_log.append("Is Iterable")
                     # Convert to list safely
                     tags = [str(t).lower().replace('#', '').strip() for t in raw_tags]
                     
                # 3. NA Check (float/None) - ONLY if not iterable
                elif pd.isna(raw_tags):
                     parse_log.append("Is Na")
                     tags = []
                     
                else:
                     parse_log.append("Unknown Type")
                     tags = []
                     
            except Exception as e:
                parse_log.append(f"Error: {str(e)}")
                tags = []
                
            category = row['category']

            # 0. Ha pagato il partner: è una TUA quota già a tuo carico -> scomputa
            if 'partner_paid' in tags:
                partner_paid_transactions.append(row)
                partner_paid_total += amount
                df_m.at[idx, 'debug_tags_clean'] = str(tags)
                df_m.at[idx, 'debug_log'] = "Partner ha pagato (tua quota, scomputata)"
                continue

            # 1. Check Loan
            clean_loan_tags = [t.lower().replace('#', '').strip() for t in loan_tags]
            is_loan = any(t in tags for t in clean_loan_tags)
            
            if is_loan:
                # Store result but also continue to next (loan overrides split)
                loan_transactions.append(row)
                total_partner_owes += amount
                
                # Update debug info in DF
                df_m.at[idx, 'debug_tags_clean'] = str(tags)
                df_m.at[idx, 'debug_log'] = "Identified as LOAN"
                continue
                
            # 2. Check Split Rules
            match_log = []
            
            # Tag Rule
            tag_rule = None
            for r in rules_list:
                if r['type'] == 'tag':
                    rule_match = r['match'].lower().replace('#', '').strip()
                    is_match = rule_match in tags
                    match_log.append(f"TagRule '{rule_match}' in {tags}? {is_match}")
                    if is_match:
                        tag_rule = r
                        break
            
            # Category Rule
            cat_rule = None
            if not tag_rule:
                for r in rules_list:
                    if r['type'] == 'category':
                        rule_match = r['match']
                        is_match = rule_match == category
                        match_log.append(f"CatRule '{rule_match}' vs '{category}'? {is_match}")
                        if is_match:
                            cat_rule = r
                            break
            
            active_rule = tag_rule if tag_rule else cat_rule
            
            if active_rule:
                my_share = active_rule['my_share'] / 100.0
                partner_share = 1.0 - my_share
                
                if partner_share > 0:
                    owed_amount = amount * partner_share
                    total_partner_owes += owed_amount
                    
                    # Store enriched row
                    row_data = row.to_dict()
                    row_data['owed'] = owed_amount
                    row_data['share_desc'] = f"{int(partner_share*100)}% ({active_rule['match']})"
                    split_transactions.append(row_data)
            
            else:
                # Default
                defaults = ['split', 'condiviso', 'shared', 'comune']
                is_default_split = any(k in tags for k in defaults)
                match_log.append(f"Defaults {defaults} in {tags}? {is_default_split}")
                
                if is_default_split:
                     partner_share = 1.0 - default_pct
                     owed_amount = amount * partner_share
                     total_partner_owes += owed_amount
                     
                     row_data = row.to_dict()
                     row_data['owed'] = owed_amount
                     row_data['share_desc'] = f"{int(partner_share*100)}% (Default)"
                     split_transactions.append(row_data)

            # Update debug info in DF using index
            df_m.at[idx, 'debug_tags_clean'] = str(tags)
            df_m.at[idx, 'debug_log'] =  "[" + "; ".join(parse_log) + "] " + " | ".join(match_log)


        # --- RESULTS ---
        partner_loan_bal = data_manager.get_partner_loan_balance()  # saldo aperto (all-time)
        net_owed = total_partner_owes - partner_paid_total + partner_loan_bal
        st.divider()
        col_res1, col_res2, col_res3 = st.columns(3)

        _help = (f"Spese condivise del mese €{total_partner_owes:,.2f} "
                 f"− tua quota su spese pagate da {conf['partner_name']} €{partner_paid_total:,.2f}")
        if partner_loan_bal:
            _help += f" {'+' if partner_loan_bal >= 0 else '−'} prestiti col partner (aperti) €{abs(partner_loan_bal):,.2f}"
        with col_res1:
            st.metric(f"Saldo: {conf['partner_name']} ti deve", f"€{net_owed:,.2f}", help=_help)
        with col_res2:
            if partner_paid_total > 0:
                st.metric(f"Ha pagato {conf['partner_name']} (tua quota)", f"€{partner_paid_total:,.2f}",
                          delta=f"-€{partner_paid_total:,.2f}", delta_color="inverse")
        with col_res3:
            if partner_loan_bal:
                st.metric("Prestiti col partner (aperti)", f"€{partner_loan_bal:,.2f}",
                          help="Saldo prestiti col partner ancora aperti (a prescindere dal mese)")
        if net_owed < 0:
            st.info(f"Saldo a favore di {conf['partner_name']}: sei tu a dovergli **€{abs(net_owed):,.2f}**.")

        # Breakdown
        st.subheader("Details")
        
        tab_det, tab_debug = st.tabs(["View Data", "Debug Inspector"])
        
        with tab_det:
            if split_transactions:
                st.write("### Shared Expenses")
                s_df = pd.DataFrame(split_transactions)
                st.dataframe(s_df[['date', 'description', 'category', 'amount', 'owed', 'share_desc']], use_container_width=True)
                
            if loan_transactions:
                st.write("### Direct Loans (100%)")
                # Handle if loan_transactions is list of Series or Dicts.
                # If Series, pd.DataFrame works. If Mixed, careful.
                # Currently loan_transactions appends 'row' which is Series.
                l_df = pd.DataFrame(loan_transactions)
                st.dataframe(l_df[['date', 'description', 'tags', 'amount']], use_container_width=True)

            if partner_paid_transactions:
                st.write(f"### Pagate da {conf['partner_name']} (tua quota, a tuo carico)")
                pp_df = pd.DataFrame(partner_paid_transactions).copy()
                pp_df['tua_quota'] = pp_df['amount'].abs()
                pp_show = pp_df[['date', 'description', 'category', 'tua_quota', 'id']]
                pp_ev = st.dataframe(pp_show, use_container_width=True, hide_index=True,
                                     on_select="rerun", selection_mode="single-row",
                                     key="pp_del_sel", column_config={"id": None})
                if pp_ev and pp_ev.selection and pp_ev.selection.rows:
                    _pid = pp_show.iloc[pp_ev.selection.rows[0]]['id']
                    if st.button("🗑️ Elimina la voce selezionata", key="pp_del_btn"):
                        data_manager.delete_transactions([_pid])
                        st.rerun()
                
        with tab_debug:
            st.warning("Use this to check why a transaction is (or isn't) being split.")
            debug_cols = ['date', 'description', 'category', 'amount', 'debug_tags_clean', 'debug_log']
            st.dataframe(df_m[debug_cols], use_container_width=True)
            
        # Generatore Messaggio
        st.subheader("📲 WhatsApp Export")
        
        msg_lines = [f"📊 *Riassunto Spese {sel_month}/{sel_year}*"]
        if net_owed >= 0:
            msg_lines.append(f"Saldo: mi devi *€{net_owed:,.2f}*")
        else:
            msg_lines.append(f"Saldo: ti devo *€{abs(net_owed):,.2f}*")
        if partner_paid_total > 0 or partner_loan_bal:
            _b = f"(spese condivise €{total_partner_owes:,.2f}"
            if partner_paid_total > 0:
                _b += f" − tua quota su spese che hai pagato tu €{partner_paid_total:,.2f}"
            if partner_loan_bal:
                _b += f" {'+' if partner_loan_bal >= 0 else '−'} prestiti aperti €{abs(partner_loan_bal):,.2f}"
            _b += ")"
            msg_lines.append(_b)
        msg_lines.append("")
        
        if split_transactions:
            msg_lines.append("🔸 *Spese Condivise:*")
            
            # Convert to DF for grouping
            s_df = pd.DataFrame(split_transactions)
            
            # Ensure group_key exists (we added it in the loop logic below? No, wait, I need to add it to the loop first!)
            # Let's aggregate by 'share_desc' which effectively captures the Rule+Percentage
            # Or better, let's group by the Rule Name/Match.
            # I will modify the loop above to add a 'rule_name' field.
            # But since I can't touch the loop in this replacement chunk which is at the bottom, strictly speaking...
            # I can rely on 'category' for category rules, but tag rules are tricky.
            # actually, 'share_desc' contains "50% (Rule: gas)". I can extract "gas".
            # But it's cleaner to just group by 'share_desc' to keep same-rule items together.
            
            # Let's try to group by the visible description used in the table
            # share_desc format: "{pct}% (Rule: {match})" or "{pct}% (Default)"
            
            grouped = s_df.groupby('share_desc')[['amount', 'owed']].sum().reset_index()
            
            for _, grp in grouped.iterrows():
                # Clean up label
                label = grp['share_desc']
                # Try to make it nicer: "50% (Rule: gas)" -> "Gas (50%)"
                if "(Rule:" in label:
                    # extract match
                    match_part = label.split("Rule:")[1].replace(")", "").strip().capitalize()
                    pct_part = label.split("%")[0] + "%"
                    display_label = f"{match_part} ({pct_part})"
                elif "Default" in label:
                     display_label = "Varie/Generiche (Default)"
                else:
                    display_label = label
                
                msg_lines.append(f"- *{display_label}*: Tot. €{grp['amount']:.2f} ➡ *€{grp['owed']:.2f}*")
            
            msg_lines.append("")
            
        if loan_transactions:
             msg_lines.append("🔹 *Prestiti/Anticipi (100%):*")
             for t in loan_transactions:
                 d_str = t['date'].strftime('%d/%m') if hasattr(t['date'], 'strftime') else str(t['date'])[:10]
                 msg_lines.append(f"- {d_str} {t['description']}: €{abs(t['amount']):.2f}")

        if partner_paid_transactions:
            msg_lines.append("")
            msg_lines.append(f"🔻 *Hai pagato tu (mia quota, a mio carico):*")
            for t in partner_paid_transactions:
                d_str = t['date'].strftime('%d/%m') if hasattr(t['date'], 'strftime') else str(t['date'])[:10]
                msg_lines.append(f"- {d_str} {t['description']}: €{abs(t['amount']):.2f}")

        st.text_area("Copia questo messaggio", "\n".join(msg_lines), height=300)

    # --- PRESTITI / CREDITI TAB ---
    with tab_loans:
        st.subheader("💸 Prestiti / Crediti")
        st.caption("I soldi che presti escono dal conto ma NON sono una spesa (sono un credito): "
                   "quando ti restituiscono rientrano nel conto, nel mese in cui li segni.")

        ledger = data_manager.get_loans_ledger()
        prestato = float(ledger[ledger['source_file'] == 'loan']['amount'].sum()) if not ledger.empty else 0.0
        restituito = float(-ledger[ledger['source_file'] == 'loan_repay']['amount'].sum()) if not ledger.empty else 0.0
        da_ricevere = prestato - restituito

        lc1, lc2, lc3 = st.columns(3)
        lc1.metric("💰 Da ricevere (aperti)", f"€{da_ricevere:,.2f}", help="Crediti ancora da incassare")
        lc2.metric("✅ Già restituiti", f"€{restituito:,.2f}")
        lc3.metric("Totale prestato", f"€{prestato:,.2f}")

        accts = data_manager.get_unique_accounts() or ["Contanti"]
        c1, c2 = st.columns(2)
        with c1:
            with st.form("loan_add_form", clear_on_submit=True):
                st.markdown("**➕ Ho prestato**")
                ln_name = st.text_input("A chi / per cosa", placeholder="es. Marco")
                ln_amt = st.number_input("Importo €", min_value=0.0, step=10.0, key="ln_amt")
                ln_acc = st.selectbox("Dal conto", accts, key="ln_acc")
                ln_date = st.date_input("Data", date.today(), key="ln_date")
                ln_partner = st.checkbox(f"Conta nel dovuto di {conf['partner_name']}", key="ln_partner")
                if st.form_submit_button("Registra prestito"):
                    if ln_name and ln_amt > 0:
                        data_manager.add_loan(ln_name, ln_amt, ln_acc, ln_date, to_partner=ln_partner)
                        extra = f" — aggiunto al dovuto di {conf['partner_name']}" if ln_partner else ""
                        st.success(f"Prestati €{ln_amt:,.2f} a {ln_name} (usciti da {ln_acc}){extra}.")
                        st.rerun()
                    else:
                        st.warning("Inserisci nome e importo.")
        with c2:
            with st.form("loan_repay_form", clear_on_submit=True):
                st.markdown("**✅ Mi hanno restituito**")
                rp_name = st.text_input("Da chi / per cosa", placeholder="es. Marco", key="rp_name")
                rp_amt = st.number_input("Importo €", min_value=0.0, step=10.0, key="rp_amt")
                rp_acc = st.selectbox("Sul conto", accts, key="rp_acc")
                rp_date = st.date_input("Data", date.today(), key="rp_date")
                rp_partner = st.checkbox(f"Era un prestito a {conf['partner_name']}", key="rp_partner")
                if st.form_submit_button("Registra restituzione"):
                    if rp_name and rp_amt > 0:
                        data_manager.repay_loan(rp_name, rp_amt, rp_acc, rp_date, from_partner=rp_partner)
                        st.success(f"Restituiti €{rp_amt:,.2f} da {rp_name} su {rp_acc}.")
                        st.rerun()
                    else:
                        st.warning("Inserisci nome e importo.")

        if not ledger.empty:
            st.markdown("#### Movimenti")
            show = ledger.copy()
            show['tipo'] = show['source_file'].map({'loan': '➖ Prestito', 'loan_repay': '➕ Restituzione'}).fillna('—')
            show['data'] = pd.to_datetime(show['date']).dt.strftime('%d/%m/%Y')
            show['importo'] = show['amount'].apply(lambda x: f"€{x:,.2f}")
            ev = st.dataframe(show[['data', 'tipo', 'description', 'importo', 'id']],
                              use_container_width=True, hide_index=True, on_select="rerun",
                              selection_mode="single-row", key="loan_del_sel",
                              column_config={"id": None})
            if ev and ev.selection and ev.selection.rows:
                _r = show.iloc[ev.selection.rows[0]]
                _name = str(_r['description']).replace('Prestato: ', '').replace('Restituito: ', '')
                _amt = abs(float(_r['amount']))
                if _r['source_file'] == 'loan':
                    st.markdown(f"**Azioni su:** {_r['description']} — €{_amt:,.2f}")
                    ac1, ac2, ac3 = st.columns(3)
                    rec_acc = ac1.selectbox("Conto rientro", accts, key="loan_rec_acc")
                    if ac2.button("✅ Segna ricevuto", key="loan_rec_btn"):
                        data_manager.repay_loan(_name, _amt, rec_acc, date.today())
                        st.success(f"Segnato ricevuto €{_amt:,.2f} da {_name} su {rec_acc}.")
                        st.rerun()
                    if ac3.button(f"🤝 Sposta nel dovuto {conf['partner_name']}", key="loan_mv_btn"):
                        data_manager.move_loan_to_partner(_r['id'])
                        st.success(f"Prestito spostato nel dovuto di {conf['partner_name']}.")
                        st.rerun()
                if st.button("🗑️ Elimina questo movimento", key="loan_del_btn"):
                    ids = data_manager.con.execute(
                        "SELECT id FROM transactions WHERE description=? AND date=? AND source_file=? AND abs(amount)=?",
                        [_r['description'], pd.to_datetime(_r['date']).date(), _r['source_file'], abs(float(_r['amount']))]
                    ).fetchall()
                    data_manager.delete_transactions([x[0] for x in ids])
                    st.rerun()
        else:
            st.caption("Nessun prestito registrato. Aggiungine uno qui sopra.")
