import streamlit as st
import pandas as pd
from datetime import datetime, date
from src.data_manager import DataManager

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
    
    tab_report, tab_settings = st.tabs(["📅 Monthly Report", "⚙️ Rules Configuration"])
    
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
        
        total_partner_owes = 0.0
        
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
        st.divider()
        col_res1, col_res2 = st.columns(2)
        
        with col_res1:
             st.metric("Total Partner Owes", f"€{total_partner_owes:,.2f}")
             
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
                
        with tab_debug:
            st.warning("Use this to check why a transaction is (or isn't) being split.")
            debug_cols = ['date', 'description', 'category', 'amount', 'debug_tags_clean', 'debug_log']
            st.dataframe(df_m[debug_cols], use_container_width=True)
            
        # Generatore Messaggio
        st.subheader("📲 WhatsApp Export")
        
        msg_lines = [f"📊 *Riassunto Spese {sel_month}/{sel_year}*"]
        msg_lines.append(f"Totale da dare: *€{total_partner_owes:,.2f}*")
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
                 
        st.text_area("Copia questo messaggio", "\n".join(msg_lines), height=300)
