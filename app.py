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

# Genera automaticamente le ricorrenti dovute (una volta per sessione)
if 'recurring_autogen' not in st.session_state:
    try:
        _gen = dm.process_recurring()
        st.session_state['recurring_autogen_count'] = int(_gen or 0)
    except Exception:
        st.session_state['recurring_autogen_count'] = 0
    st.session_state['recurring_autogen'] = True

# Backup automatico giornaliero (una volta per sessione)
if 'auto_backup_done' not in st.session_state:
    try:
        dm.auto_backup()
    except Exception:
        pass
    st.session_state['auto_backup_done'] = True

# Sidebar Navigation
st.sidebar.title("💰 Finance App")

if st.session_state.get('recurring_autogen_count'):
    st.sidebar.success(f"🔁 Generate {st.session_state['recurring_autogen_count']} ricorrenti dovute.")
    st.session_state['recurring_autogen_count'] = 0

# Alert ricorrenti/bollette in arrivo (prossimi 7 giorni)
try:
    from datetime import date as _date, timedelta as _td
    _upc = dm.get_projected_recurring(_date.today() + _td(days=7))
    if _upc is not None and not _upc.empty:
        _due = _upc[_upc['amount'] < 0]
        if not _due.empty:
            st.sidebar.warning(f"⏰ {len(_due)} spese ricorrenti in arrivo (7gg): €{_due['amount'].abs().sum():,.0f}")
except Exception:
    pass

# Global Search — overrides page to Transactions
global_search = st.sidebar.text_input("🔍 Search", placeholder="Cerca transazioni...")
if global_search:
    st.session_state['global_search'] = global_search
elif 'global_search' not in st.session_state:
    st.session_state['global_search'] = ''

page = st.sidebar.radio("Navigate", ["Dashboard", "Transactions", "Recurring Expenses", "Shared Expenses", "Analysis", "Tag Manager", "Import", "Settings"])

# If there's an active search, force Transactions page
if global_search:
    page = "Transactions"

st.sidebar.divider()

# ── Add Transaction (Quick Add) ──────────────────────────────────────────
main_wallet = dm.get_main_wallet()

with st.sidebar.expander("➕ Aggiungi Transazione", expanded=False):
    # Fetch options
    cats = dm.get_unique_categories()
    accounts = dm.get_unique_accounts()
    existing_tags = dm.get_unique_tags()
    if hasattr(dm, 'rules_engine') and 'tags' in dm.rules_engine.rules:
        rules_tags = [t['tag'] for t in dm.rules_engine.rules['tags']]
        existing_tags = sorted(list(set(existing_tags + rules_tags)))

    # Ultimo wallet usato come default (fallback: principale)
    default_wallet = st.session_state.get('last_wallet') or main_wallet
    if default_wallet and default_wallet in accounts:
        wallet_opts = [default_wallet] + [a for a in accounts if a != default_wallet]
    else:
        wallet_opts = list(accounts)

    def _wallet_label(w):
        return f"⭐ {w}" if w == main_wallet else w

    # Scorciatoie rapide: categoria+tag più frequenti, con importo tipico precompilato
    tpl = st.session_state.get('qa_tpl')
    combos = dm.get_frequent_combos(8)
    if not combos.empty:
        st.caption("🔁 Rapidi (in base a cosa usi di recente) — precompilano categoria, tag e importo:")
        chip_cols = st.columns(2)
        for i, crow in combos.reset_index(drop=True).iterrows():
            _c = str(crow['category']); _t = str(crow['tag']); _a = float(crow['amt'] or 0)
            if chip_cols[i % 2].button(f"{_c[:10]} #{_t}", key=f"qa_chip_{i}", use_container_width=True):
                st.session_state['qa_tpl'] = {'category': _c, 'tag': _t, 'amount': round(_a, 2)}
                st.rerun()
        if tpl:
            st.caption(f"✍️ Precompilato: **{tpl['category']} #{tpl['tag']}** — controlla l'importo e aggiungi.")

    cat_options = ["Seleziona..."] + cats
    _cat_index = cat_options.index(tpl['category']) if (tpl and tpl['category'] in cat_options) else 0
    _default_amt = float(tpl['amount']) if tpl else 0.0
    _default_tags = [tpl['tag']] if (tpl and tpl['tag'] in existing_tags) else []

    with st.form("quick_add_form", clear_on_submit=True):
        qa_type_label = st.radio("Tipo", ["💸 Spesa", "💰 Entrata"], horizontal=True)
        qa_type = "Expense" if "Spesa" in qa_type_label else "Income"

        c_amt, c_date = st.columns(2)
        qa_amount = c_amt.number_input("Importo €", min_value=0.0, step=0.01, format="%.2f", value=_default_amt)
        qa_date = c_date.date_input("Data", datetime.today())

        qa_desc = st.text_input("Descrizione (opzionale)", placeholder="es. Spesa Coop")

        # Category: select or type a new one (both always visible → works inside a form)
        qa_cat_sel = st.selectbox("Categoria", cat_options, index=_cat_index)
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

        qa_tags_sel = st.multiselect("Tag (opzionale)", existing_tags, default=_default_tags)
        qa_new_tag = st.text_input("Nuovo tag (opzionale)", placeholder="#vacanze")
        qa_nec = st.selectbox("Necessità", ["Auto", "Need", "Want"],
                              help="Auto = completata dalle regole in base a categoria/descrizione.")
        st.caption("💡 Categoria, necessità e tag mancanti vengono completati automaticamente dalle regole.")

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
                    st.session_state['last_wallet'] = final_wallet
                    st.session_state.pop('qa_tpl', None)
                    kind = "Spesa" if qa_type == "Expense" else "Entrata"
                    st.toast(f"{kind} aggiunta: €{qa_amount:,.2f} su {final_wallet}", icon="✅")
                    st.rerun()
                except Exception as e:
                    st.error(f"Errore: {e}")
            else:
                st.warning("L'importo deve essere > 0")

st.sidebar.divider()

# Trasferimento tra conti
with st.sidebar.expander("🔄 Trasferimento tra conti", expanded=False):
    _tf_accs = dm.get_unique_accounts()
    if len(_tf_accs) >= 2:
        with st.form("transfer_form", clear_on_submit=True):
            tf_from = st.selectbox("Da", _tf_accs, key='tf_from')
            tf_to = st.selectbox("A", _tf_accs, index=1, key='tf_to')
            tf_amount = st.number_input("Importo €", min_value=0.0, step=0.01, format="%.2f", key='tf_amt')
            tf_date = st.date_input("Data", datetime.today(), key='tf_date')
            if st.form_submit_button("🔄 Trasferisci", use_container_width=True, type="primary"):
                if tf_from == tf_to:
                    st.warning("Scegli due conti diversi.")
                elif tf_amount <= 0:
                    st.warning("L'importo deve essere > 0.")
                else:
                    if dm.add_transfer(tf_from, tf_to, tf_amount, pd.to_datetime(tf_date).date()):
                        st.toast(f"Trasferiti €{tf_amount:,.2f}: {tf_from} → {tf_to}", icon="🔄")
                        st.rerun()
    else:
        st.caption("Servono almeno 2 conti per un trasferimento.")

st.sidebar.divider()

# Backup & Restore
with st.sidebar.expander("💾 Backup & Ripristino", expanded=False):
    _bks = dm.list_backups()
    if _bks:
        _last = os.path.basename(_bks[0]).replace('finance_backup_', '').replace('.zip', '')
        st.caption(f"🗂️ Backup automatici: {len(_bks)} · ultimo {_last}")
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
elif page == "Analysis":
    render_analysis(dm)
elif page == "Tag Manager":
    render_tag_manager(dm)
elif page == "Import":
    render_importer(dm)
elif page == "Settings":
    render_settings(dm)
