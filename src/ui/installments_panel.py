"""Pannello 'Rate' per la Dashboard: rate attive, quando finiscono, quanto liberano."""
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from src.insights import installments_overview

MESI = ["", "gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]


def _m(p):
    return f"{MESI[p.month]} {p.year}"


def render_installments_panel(data_manager):
    rows, plan = installments_overview(data_manager.get_recurring())
    if rows.empty:
        return
    today_p = pd.Period(pd.Timestamp.today(), freq='M')
    this_month = float(plan.get(today_p, 0.0))
    next_month = float(plan.get(today_p + 1, 0.0))
    last_p = plan.index.max()
    residuo = float(rows['residuo'].sum())
    new = rows[rows['nuova']]

    with st.container(border=True):
        msg = (f"**Rate attive: {len(rows)}** · €{next_month:,.0f} il mese prossimo · "
               f"ancora da pagare €{residuo:,.0f} · **da {_m(last_p + 1)} libere**")
        st.markdown(msg)
        if not new.empty:
            st.caption("Appena aperta: " + ", ".join(f"{r['nome']} (€{r['importo']:,.0f} × {r['totali']})"
                                                      for _, r in new.iterrows())
                       + " — ogni rata nuova riduce il margine dei prossimi mesi.")
        with st.expander("Dettaglio rate"):
            show = pd.DataFrame({
                'Rata': rows['nome'],
                'Importo': rows['importo'].map(lambda v: f"€{v:,.2f}"),
                'Mancano': rows.apply(lambda r: f"{r['rimaste']}" + (f"/{r['totali']}" if r['totali'] else ""), axis=1),
                'Prossima': pd.to_datetime(rows['prossima']).dt.strftime('%d/%m/%Y'),
                'Ultima': pd.to_datetime(rows['ultima']).dt.strftime('%d/%m/%Y'),
                'Residuo': rows['residuo'].map(lambda v: f"€{v:,.0f}"),
            })
            st.dataframe(show, hide_index=True, use_container_width=True)
            future = plan[plan.index >= today_p]
            if not future.empty:
                fig = go.Figure(go.Bar(x=[_m(p) for p in future.index], y=future.values,
                                       marker_color='#7E57C2',
                                       text=[f"€{v:,.0f}" for v in future.values], textposition='outside'))
                fig.update_layout(height=240, margin=dict(t=30, b=10), yaxis_title='€',
                                  title="Rate in uscita mese per mese")
                st.plotly_chart(fig, use_container_width=True)
            if this_month:
                st.caption(f"Questo mese: €{this_month:,.0f} di rate (pagate o in arrivo).")
