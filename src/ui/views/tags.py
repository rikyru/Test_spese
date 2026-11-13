"""Vista Analisi Tag."""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from src.metrics import (
    real_expenses,
    in_progress_period,
)


# ---------------------------------------------------------------------------
# TAG ANALYSIS
# ---------------------------------------------------------------------------

def render_tag_analysis(df):
    st.subheader("🏷️ Analisi Tag")

    df_tags = df.copy().explode('tags')
    df_tags['tags'] = df_tags['tags'].astype(str)
    df_tags = df_tags[~df_tags['tags'].isin(['nan', '', 'None'])]

    if df_tags.empty:
        st.info("Nessun tag trovato nei dati.")
        return

    all_tags = sorted(df_tags['tags'].unique())
    selected_tag = st.selectbox("Tag da analizzare", all_tags)

    if not selected_tag:
        return

    tag_data = df_tags[df_tags['tags'] == selected_tag].copy()
    tag_data['date'] = pd.to_datetime(tag_data['date'])

    expenses_only = real_expenses(tag_data)
    expenses_only['abs_amount'] = expenses_only['amount'].abs()

    total_tag = expenses_only['abs_amount'].sum() if not expenses_only.empty else 0
    avg_tag = expenses_only['abs_amount'].mean() if not expenses_only.empty else 0
    count_tag = len(expenses_only)

    cols = st.columns(3)
    cols[0].metric(f"Totale Speso ({selected_tag})", f"€{total_tag:,.2f}")
    cols[1].metric("Media per Transazione", f"€{avg_tag:,.2f}")
    cols[2].metric("Numero Transazioni", str(count_tag))

    if expenses_only.empty:
        st.info("Nessuna spesa con questo tag.")
        return

    # Monthly trend
    expenses_only['month_year'] = expenses_only['date'].dt.to_period('M')
    monthly_tag = expenses_only.groupby('month_year')['abs_amount'].sum().reset_index()
    _ip = in_progress_period(df)
    if _ip is not None and (monthly_tag['month_year'] == _ip).any():
        _now = float(monthly_tag.loc[monthly_tag['month_year'] == _ip, 'abs_amount'].sum())
        monthly_tag = monthly_tag[monthly_tag['month_year'] != _ip]   # trend su mesi completi
        st.caption(f"Mese in corso ({_ip}) escluso dal trend — finora €{_now:,.0f}.")
    monthly_tag['month_str'] = monthly_tag['month_year'].astype(str)

    fig_trend = go.Figure()
    fig_trend.add_trace(go.Bar(
        x=monthly_tag['month_str'], y=monthly_tag['abs_amount'],
        name='Spesa mensile', marker_color='#636EFA', opacity=0.7
    ))
    if len(monthly_tag) >= 3:
        # Moving average
        monthly_tag['ma3'] = monthly_tag['abs_amount'].rolling(3, min_periods=1).mean()
        fig_trend.add_trace(go.Scatter(
            x=monthly_tag['month_str'], y=monthly_tag['ma3'],
            name='Media mobile 3m', mode='lines+markers',
            line=dict(color='#EF553B', width=2, dash='dot')
        ))
    fig_trend.update_layout(title=f"Trend Mensile — #{selected_tag}", xaxis_title="Mese",
                             yaxis_title="€", hovermode="x unified", height=350)
    st.plotly_chart(fig_trend, use_container_width=True)

    # Top transactions for this tag
    st.markdown("**Transazioni più recenti con questo tag**")
    display = expenses_only.sort_values('date', ascending=False)[['date', 'description', 'category', 'abs_amount']].head(15).copy()
    display['abs_amount'] = display['abs_amount'].apply(lambda x: f"€{x:,.2f}")
    display.columns = ['Data', 'Descrizione', 'Categoria', 'Importo']
    st.dataframe(display, use_container_width=True, hide_index=True)
