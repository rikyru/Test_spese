"""Pagina Analisi: selettore delle viste e filtro periodo. Le viste sono in src/ui/views/,
i calcoli condivisi in src/metrics.py."""
import streamlit as st
import pandas as pd
from src.data_manager import DataManager
from src.partner_share import my_share_view
from src.ui.views.smart_insights import render_smart_insights
from src.ui.views.tags import render_tag_analysis
from src.ui.views.needs_wants import render_needs_vs_wants
from src.ui.views.forecasting import render_forecasting
from src.ui.views.income import render_income_analysis
from src.ui.views.yoy import render_yoy_comparison
from src.ui.views.categories import render_category_deepdive
from src.ui.views.health import render_financial_health


def render_analysis(data_manager: DataManager):
    st.header("📊 Analisi e Previsioni")

    df = data_manager.get_transactions()
    if df.empty:
        st.info("Nessun dato disponibile.")
        return
    df['date'] = pd.to_datetime(df['date'])
    df['year'] = df['date'].dt.year
    df['month'] = df['date'].dt.month

    # Freschezza dati: le analisi "a oggi" sono affidabili solo se i dati sono recenti
    _ref = df['date'].max()
    _age = (pd.Timestamp.today().normalize() - _ref.normalize()).days
    if _age <= 3:
        st.caption(f"🟢 Dati aggiornati al {_ref.strftime('%d/%m/%Y')}")
    elif _age <= 20:
        st.caption(f"🟡 Dati aggiornati al {_ref.strftime('%d/%m/%Y')} · {_age} giorni fa")
    else:
        st.warning(f"⚠️ Ultimo dato: {_ref.strftime('%d/%m/%Y')} ({_age} giorni fa). "
                   "Alcune analisi 'a oggi' potrebbero non riflettere i movimenti recenti — "
                   "aggiungi/importa le transazioni mancanti.")

    # Selettore vista: renderizza SOLO l'analisi scelta (molto più fluido delle st.tabs,
    # che invece calcolano tutte le schede a ogni interazione).
    views = ["Resoconto mese", "Smart Insights", "Entrate", "Tag", "Necessità vs Desideri",
             "Previsioni", "Anno vs Anno", "Categorie", "Salute"]
    # Solo queste viste usano il filtro periodo; le altre lavorano su tutto lo storico
    period_views = {"Smart Insights", "Entrate", "Tag", "Necessità vs Desideri"}
    view = st.segmented_control("Vista analisi", views, default=views[0],
                                key='ana_view', label_visibility="collapsed")
    view = view or views[0]

    # Interruttore "Mia quota": solo nelle viste di SPESA (entrate/risparmio/saldi
    # restano sui movimenti reali). Stima con le regole di Spese Condivise.
    share_views = {"Tag", "Necessità vs Desideri", "Previsioni", "Categorie"}
    raw_df = df
    if view in share_views:
        if st.toggle("👤 Mia quota (spese condivise)", key='ana_my_share',
                     help="Riduce le spese condivise alla tua parte stimata con le regole "
                          "di Spese Condivise, su tutto lo storico. Non usa i rimborsi effettivi."):
            df = my_share_view(df, data_manager.rules_engine.rules.get('split_config', {}))
            st.caption("👤 Spese condivise alla tua quota **stimata** (regole di Spese Condivise). "
                       "Entrate, risparmio e saldi non cambiano.")

    filtered_df = df
    if view in period_views:
        filtered_df = _period_filter(df)
    elif view != "Resoconto mese":
        st.caption("🗂️ Questa vista usa tutto lo storico (il filtro periodo non si applica).")

    if view == "Resoconto mese":
        from src.ui.month_report import render_month_report
        render_month_report(raw_df, data_manager)
    elif view == "Smart Insights":
        render_smart_insights(df, filtered_df, data_manager)
    elif view == "Entrate":
        render_income_analysis(df, filtered_df)
    elif view == "Tag":
        render_tag_analysis(filtered_df)
    elif view == "Necessità vs Desideri":
        render_needs_vs_wants(df, filtered_df)
    elif view == "Previsioni":
        # Previsione spese sulla vista scelta; scenario e calendario liquidità sui movimenti reali
        render_forecasting(df, raw_df, data_manager)
    elif view == "Anno vs Anno":
        render_yoy_comparison(df)
    elif view == "Categorie":
        render_category_deepdive(df, filtered_df, data_manager)
    elif view == "Salute":
        render_financial_health(df, data_manager)


def _period_filter(df):
    """Barra filtri periodo (Tutto/Anno/Mese/Personalizzato); ritorna il df filtrato."""
    min_date = df['date'].min().date()
    max_date = df['date'].max().date()
    today = pd.Timestamp.today()
    month_names = {1:"Gen",2:"Feb",3:"Mar",4:"Apr",5:"Mag",6:"Giu",
                   7:"Lug",8:"Ago",9:"Set",10:"Ott",11:"Nov",12:"Dic"}

    modes = ["Tutto", "Anno", "Mese", "Personalizzato"]
    af1, af2, af3 = st.columns([1.4, 1.3, 1.3])
    mode = af1.selectbox("Periodo", modes, index=0, key='ana_mode')
    years = sorted(df['year'].unique(), reverse=True)

    if mode == "Anno":
        selected_year = af2.selectbox("Anno", years, key='ana_year')
        return df[df['year'] == selected_year]
    if mode == "Mese":
        selected_year = af2.selectbox("Anno", years, key='ana_year_m')
        selected_month = af3.selectbox("Mese", list(range(1, 13)), index=int(today.month) - 1,
                                       format_func=lambda m: month_names[m], key='ana_month')
        return df[(df['year'] == selected_year) & (df['month'] == selected_month)]
    if mode == "Personalizzato":
        start_date = af2.date_input("Da", min_date, key='ana_start')
        end_date = af3.date_input("A", max_date, key='ana_end')
        if start_date <= end_date:
            return df[(df['date'].dt.date >= start_date) & (df['date'].dt.date <= end_date)]
        st.error("La data iniziale deve precedere quella finale.")
    return df
