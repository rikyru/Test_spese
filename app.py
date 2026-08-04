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

# Global Search — overrides page to Transactions
global_search = st.sidebar.text_input("🔍 Search", placeholder="Cerca transazioni...")
if global_search:
    st.session_state['global_search'] = global_search
elif 'global_search' not in st.session_state:
    st.session_state['global_search'] = ''

page = st.sidebar.radio("Navigate", ["Dashboard", "Transactions", "Recurring Expenses", "Shared Expenses", "📊 Analysis", "Tag Manager", "Import", "Settings"])

# If there's an active search, force Transactions page
if global_search:
    page = "Transactions"

st.sidebar.divider()

# ── Add Transaction (Quick Add) ──────────────────────────────────────────
main_wallet = dm.get_main_wallet()

with st.sidebar.expander("➕ Aggiungi Transazione", expanded=True):
    # Fetch options
    cats = dm.get_unique_categories()
    accounts = dm.get_unique_accounts()
    existing_tags = dm.get_unique_tags()
    if hasattr(dm, 'rules_engine') and 'tags' in dm.rules_engine.rules:
        rules_tags = [t['tag'] for t in dm.rules_engine.rules['tags']]
        existing_tags = sorted(list(set(existing_tags + rules_tags)))

    # Main wallet first, so it is the default selection
    if main_wallet and main_wallet in accounts:
        wallet_opts = [main_wallet] + [a for a in accounts if a != main_wallet]
    else:
        wallet_opts = list(accounts)

    def _wallet_label(w):
        return f"⭐ {w}" if w == main_wallet else w

    with st.form("quick_add_form", clear_on_submit=True):
        qa_type_label = st.radio("Tipo", ["💸 Spesa", "💰 Entrata"], horizontal=True)
        qa_type = "Expense" if "Spesa" in qa_type_label else "Income"

        c_amt, c_date = st.columns(2)
        qa_amount = c_amt.number_input("Importo €", min_value=0.0, step=0.01, format="%.2f")
        qa_date = c_date.date_input("Data", datetime.today())

        qa_desc = st.text_input("Descrizione", placeholder="es. Spesa Coop")

        # Category: select or type a new one (both always visible → works inside a form)
        qa_cat_sel = st.selectbox("Categoria", ["Seleziona..."] + cats)
        qa_cat_new = st.text_input("… oppure nuova categoria", placeholder="lascia vuoto se scelta sopra")
        if qa_cat_new.strip():
            qa_cat = qa_cat_new.strip()
        elif qa_cat_sel != "Seleziona...":
            qa_cat = qa_cat_sel
        else:
            qa_cat = "Generale"

        # Wallet: default = portafoglio principale
        if wallet_opts:
            qa_wallet_sel = st.selectbox("Portafoglio", wallet_opts, index=0,
                                         format_func=_wallet_label,
                                         help="⭐ = portafoglio principale (impostabile in Settings).")
        else:
            qa_wallet_sel = None
            st.caption("Nessun conto ancora: creane uno qui sotto.")
        qa_wallet_new = st.text_input("… oppure nuovo conto",
                                      placeholder="lascia vuoto per usare quello selezionato")
        if qa_wallet_new.strip():
            qa_wallet = qa_wallet_new.strip()
        elif qa_wallet_sel:
            qa_wallet = qa_wallet_sel
        else:
            qa_wallet = main_wallet or "Contanti"

        with st.expander("Altro (tag, necessità)", expanded=False):
            qa_tags_sel = st.multiselect("Tag", existing_tags)
            qa_new_tag = st.text_input("Nuovo tag", placeholder="#vacanze")
            qa_nec = st.selectbox("Necessità", ["Auto", "Need", "Want"],
                                  help="Auto = deriva dalle regole della categoria")

        submitted = st.form_submit_button("➕ Aggiungi", use_container_width=True, type="primary")
        if submitted:
            if qa_amount and qa_amount > 0:
                final_cat = qa_cat if qa_cat else "Generale"
                final_wallet = qa_wallet if qa_wallet else (main_wallet or "Contanti")

                final_tags = list(qa_tags_sel)
                if qa_new_tag:
                    clean = qa_new_tag.strip().replace('#', '').lower()
                    if clean:
                        final_tags.append(clean)

                necessity = None if qa_nec == "Auto" else qa_nec

                try:
                    dm.add_transaction(
                        date=pd.to_datetime(qa_date).date(),
                        amount=qa_amount,
                        ttype=qa_type,
                        category=final_cat,
                        account=final_wallet,
                        description=qa_desc,
                        tags=final_tags,
                        necessity=necessity,
                    )
                    kind = "Spesa" if qa_type == "Expense" else "Entrata"
                    st.toast(f"{kind} aggiunta: €{qa_amount:,.2f} su {final_wallet}", icon="✅")
                    st.rerun()
                except Exception as e:
                    st.error(f"Errore: {e}")
            else:
                st.warning("L'importo deve essere > 0")

st.sidebar.divider()

# Backup & Restore
with st.sidebar.expander("💾 Backup & Ripristino", expanded=False):
    zip_data = dm.export_backup_zip()
    st.download_button(
        label="⬇️ Esporta Backup",
        data=zip_data,
        file_name=f"finance_backup_{datetime.today().strftime('%Y%m%d')}.zip",
        mime="application/zip",
        use_container_width=True,
        key="sidebar_export_btn"
    )
    st.caption("Ripristina da un backup:")
    uploaded_zip = st.file_uploader("Carica ZIP", type="zip", key="sidebar_zip_import", label_visibility="collapsed")
    if uploaded_zip:
        if st.button("📥 Importa", key="sidebar_import_btn", use_container_width=True):
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp:
                tmp.write(uploaded_zip.getbuffer())
                tmp_path = tmp.name
            success, msg = dm.ingest_zip(tmp_path)
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            if success:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

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
