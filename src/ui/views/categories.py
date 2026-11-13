"""Vista Categorie."""
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from src.metrics import (
    real_expenses,
    in_progress_period,
    AVG_BASIS_NOTE,
    avg_monthly,
)


# ---------------------------------------------------------------------------
# CATEGORY DEEP-DIVE + BUDGET ADHERENCE
# ---------------------------------------------------------------------------

def render_category_deepdive(full_df, filtered_df, data_manager):
    st.subheader("📂 Deep-dive per Categoria")
    st.caption("Analisi su tutti i dati (non filtrata dal periodo in sidebar). Spese reali, trasferimenti esclusi.")

    exp_all = real_expenses(full_df)
    if exp_all.empty:
        st.info("Nessuna spesa disponibile.")
        return
    exp_all['abs_amount'] = exp_all['amount'].abs()
    exp_all['month_year'] = exp_all['date'].dt.to_period('M')

    # Budgets configurati (rules.yaml)
    try:
        budgets = data_manager.rules_engine.rules.get('budgets', {}) or {}
    except Exception:
        budgets = {}

    cats = sorted(exp_all['category'].dropna().unique().tolist())
    if not cats:
        st.info("Nessuna categoria di spesa.")
        return

    totals = exp_all.groupby('category')['abs_amount'].sum()
    default_cat = totals.idxmax()
    sel = st.selectbox("Categoria", cats, index=cats.index(default_cat), key='cat_deepdive_sel')

    cat_df = exp_all[exp_all['category'] == sel]
    monthly = cat_df.groupby('month_year')['abs_amount'].sum().sort_index()
    # Statistiche/trend/aderenza sui mesi COMPLETI: il mese in corso parziale
    # risulterebbe sempre "basso" (e sempre entro budget).
    _ip = in_progress_period(full_df)
    partial_now = float(monthly.get(_ip, 0.0)) if _ip is not None else 0.0
    if _ip is not None:
        monthly = monthly.drop(_ip, errors='ignore')

    total = cat_df['abs_amount'].sum()
    avg_month = avg_monthly(cat_df, ref_df=full_df)
    last = monthly.iloc[-1] if len(monthly) else 0
    budget = float(budgets.get(sel, 0) or 0)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Totale (all-time)", f"€{total:,.0f}")
    c2.metric("Media Mensile", f"€{avg_month:,.0f}", help=AVG_BASIS_NOTE)
    c3.metric("Ultimo mese completo", f"€{last:,.0f}")
    if budget > 0:
        over = last - budget
        c4.metric("Budget Mensile", f"€{budget:,.0f}",
                  delta=f"{over:+,.0f}€ ultimo mese", delta_color="inverse")
    else:
        c4.metric("Budget Mensile", "—", help="Imposta un budget in Impostazioni → Budget Mensile per Categoria.")

    # Trend complessivo
    if len(monthly) >= 3:
        slope = np.polyfit(np.arange(len(monthly)), monthly.values, 1)[0]
        if slope > 5:
            st.warning(f"📈 Spesa per **{sel}** in **crescita** (~{slope:+,.0f} €/mese di trend).")
        elif slope < -5:
            st.success(f"📉 Spesa per **{sel}** in **calo** (~{slope:+,.0f} €/mese di trend).")
        else:
            st.info(f"➡️ Spesa per **{sel}** **stabile** (~{slope:+,.0f} €/mese di trend).")

    # Grafico mensile con media mobile + linea budget
    m_df = monthly.reset_index()
    m_df.columns = ['mese', 'importo']
    m_df['mese'] = m_df['mese'].astype(str)
    m_df['ma3'] = m_df['importo'].rolling(3, min_periods=1).mean()

    fig = go.Figure()
    fig.add_trace(go.Bar(x=m_df['mese'], y=m_df['importo'], name='Spesa',
                         marker_color='#636EFA', opacity=0.8))
    fig.add_trace(go.Scatter(x=m_df['mese'], y=m_df['ma3'], name='Media mobile 3m',
                             mode='lines', line=dict(color='#EF553B', width=2, dash='dot')))
    if budget > 0:
        fig.add_hline(y=budget, line_dash='dash', line_color='#4CAF50',
                      annotation_text=f'Budget €{budget:,.0f}', annotation_position='top left')
    fig.update_layout(height=360, xaxis_title='Mese', yaxis_title='€',
                      hovermode='x unified', title=f"Andamento mensile — {sel}",
                      legend=dict(orientation='h', yanchor='bottom', y=1.02))
    st.plotly_chart(fig, use_container_width=True)
    if _ip is not None and partial_now > 0:
        _bud_txt = f" su €{budget:,.0f} di budget ({partial_now / budget * 100:.0f}%)" if budget > 0 else ""
        st.caption(f"Mese in corso ({_ip}), finora: €{partial_now:,.0f}{_bud_txt} — escluso da medie e trend.")

    # Aderenza al budget per la categoria selezionata
    if budget > 0 and len(monthly) >= 1:
        within = int((monthly <= budget).sum())
        tot_m = len(monthly)
        pct = within / tot_m * 100
        emoji = "🟢" if pct >= 70 else ("🟡" if pct >= 40 else "🔴")
        st.markdown(f"**🎯 Aderenza al budget:** {emoji} rientrato in **{within}/{tot_m} mesi** ({pct:.0f}%).")

    # Principali voci (descrizioni) nella categoria
    st.markdown("#### 🏪 Principali voci in questa categoria")
    md = cat_df.copy()
    md['description'] = md['description'].fillna('').replace('', '(senza descrizione)')
    top = (md.groupby('description')['abs_amount']
             .agg(['sum', 'count', 'mean']).reset_index()
             .sort_values('sum', ascending=False).head(12))
    top.columns = ['Descrizione', 'Totale', 'Volte', 'Media']
    top['Totale'] = top['Totale'].apply(lambda x: f"€{x:,.2f}")
    top['Media'] = top['Media'].apply(lambda x: f"€{x:,.2f}")
    st.dataframe(top, use_container_width=True, hide_index=True)

    # Spese per tag: i tag funzionano come sotto-categorie
    st.markdown("#### 🏷️ Spese per Tag (sotto-categorie)")
    st.caption("Es. dentro 'Spesa alimentare': supermercato, mercato, macellaio… Una transazione con più tag conta in ciascuno.")
    td = cat_df.explode('tags')
    td['tags'] = td['tags'].astype(str).str.strip()
    td = td[~td['tags'].isin(['nan', 'None', ''])]

    if td.empty:
        st.caption("Nessun tag nelle transazioni di questa categoria — aggiungi tag per avere le sotto-categorie.")
    else:
        tag_sum = (td.groupby('tags')['abs_amount']
                     .agg(['sum', 'count', 'mean']).reset_index()
                     .sort_values('sum', ascending=False))
        tag_sum.columns = ['Tag', 'Totale', 'Volte', 'Media']

        fig_tag = px.bar(tag_sum.head(15), x='Tag', y='Totale',
                         title=f"Spese per tag — {sel}", color='Tag')
        fig_tag.update_layout(height=340, showlegend=False, xaxis_title='', yaxis_title='€')
        st.plotly_chart(fig_tag, use_container_width=True)

        disp_t = tag_sum.copy()
        disp_t['Totale'] = disp_t['Totale'].apply(lambda x: f"€{x:,.2f}")
        disp_t['Media'] = disp_t['Media'].apply(lambda x: f"€{x:,.2f}")
        st.dataframe(disp_t, use_container_width=True, hide_index=True)

        def _has_tags(t):
            if hasattr(t, 'tolist'):
                t = t.tolist()
            if not isinstance(t, list):
                return False
            return any(x and str(x) not in ('nan', 'None') for x in t)

        untag_sum = cat_df[~cat_df['tags'].apply(_has_tags)]['abs_amount'].sum()
        if untag_sum > 0:
            st.caption(f"Di cui **€{untag_sum:,.0f}** senza alcun tag.")

    st.divider()

    # Storico aderenza budget — tutte le categorie con budget
    st.markdown("### 🎯 Storico Aderenza Budget (tutte le categorie)")
    budgeted = {k: float(v) for k, v in budgets.items() if v and float(v) > 0}
    if not budgeted:
        st.info("Nessun budget impostato. Vai in **Impostazioni → Budget Mensile per Categoria**.")
        return

    rows = []
    for cat, b in budgeted.items():
        cm = exp_all[exp_all['category'] == cat].groupby('month_year')['abs_amount'].sum()
        if _ip is not None:
            cm = cm.drop(_ip, errors='ignore')   # il mese parziale sarebbe sempre "entro budget"
        if cm.empty:
            continue
        within = int((cm <= b).sum())
        tot_m = len(cm)
        rows.append({
            'Categoria': cat,
            'Budget': f"€{b:,.0f}",
            'Media Mensile': f"€{avg_monthly(exp_all[exp_all['category'] == cat], ref_df=full_df):,.0f}",
            'Mesi Rientrati': f"{within}/{tot_m}",
            '_pct': within / tot_m * 100,
            'Aderenza': f"{within / tot_m * 100:.0f}%",
        })

    if rows:
        adf = pd.DataFrame(rows).sort_values('_pct')
        st.dataframe(adf[['Categoria', 'Budget', 'Media Mensile', 'Mesi Rientrati', 'Aderenza']],
                     use_container_width=True, hide_index=True)
        worst = adf.iloc[0]
        st.caption(f"⚠️ Minor aderenza: **{worst['Categoria']}** — solo {worst['Aderenza']} dei mesi entro budget.")
    else:
        st.info("Nessun dato di spesa per le categorie con budget.")
