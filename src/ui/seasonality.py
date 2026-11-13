"""Stagionalità: quando spendi di più, per categoria e in totale."""
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from src.metrics import real_expenses, monthly_totals, last_complete_period
from src.insights import seasonal_index

MESI = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]


def category_by_calendar_month(df, months=36, top=10):
    """Media per mese di calendario (Gen..Dic) delle spese per categoria, sugli
    ultimi `months` mesi completi (mesi a zero inclusi)."""
    end = last_complete_period(df)
    if end is None:
        return pd.DataFrame()
    rng = pd.period_range(end - months + 1, end, freq='M')
    e = real_expenses(df)
    e = e.assign(p=pd.to_datetime(e['date']).dt.to_period('M'), a=e['amount'].abs())
    e = e[e['p'].isin(rng)]
    if e.empty:
        return pd.DataFrame()
    cats = e.groupby('category')['a'].sum().nlargest(top).index
    tbl = {}
    for cat in cats:
        by_m = e[e['category'] == cat].groupby('p')['a'].sum().reindex(rng, fill_value=0.0)
        tbl[cat] = by_m.groupby([p.month for p in by_m.index]).mean().reindex(range(1, 13))
    return pd.DataFrame(tbl).T


def render_seasonality(df):
    st.divider()
    st.markdown("### 🗓️ Quando spendi di più (stagionalità)")
    t = category_by_calendar_month(df)
    if t.empty:
        st.info("Servono più mesi di dati.")
        return
    st.caption("Spesa media per categoria in ogni mese dell'anno (ultimi 3 anni). Utile per prevedere i mesi "
               "pesanti: regali a dicembre, viaggi d'estate, assicurazioni o bolli in un mese preciso.")
    z = t.values
    fig = go.Figure(go.Heatmap(z=z, x=MESI, y=list(t.index), colorscale='Oranges',
                               text=[[f"€{v:,.0f}" for v in row] for row in z], texttemplate="%{text}",
                               hovertemplate="%{y} · %{x}: %{text}<extra></extra>", showscale=False))
    fig.update_layout(height=60 + 34 * len(t), margin=dict(t=10, b=10), yaxis=dict(autorange='reversed'))
    st.plotly_chart(fig, use_container_width=True)

    # Picchi: per ogni categoria il mese più caro se nettamente sopra la sua media
    peaks = []
    for cat, row in t.iterrows():
        avg = row.mean()
        m = int(row.idxmax())
        if avg > 0 and row[m] > avg * 1.6 and row[m] - avg > 60:
            peaks.append(f"**{cat}** a {MESI[m - 1].lower()} (≈€{row[m]:,.0f} contro €{avg:,.0f} di media)")
    if peaks:
        st.markdown("**Mesi da mettere in conto:** " + " · ".join(peaks))

    si = seasonal_index(monthly_totals(df, 'expense'))
    if (si['n_anni'] >= 2).any():
        tot = (si['indice'] - 1) * 100
        st.caption("Totale spese per mese rispetto alla media: " + " · ".join(
            f"{MESI[m - 1]} {v:+.0f}%" for m, v in tot.items() if abs(v) >= 5) +
            ". Nota: con questi anni di dati la stagionalità **non** migliora la previsione del totale "
            "(provata sul passato), quindi le Previsioni non la usano.")
