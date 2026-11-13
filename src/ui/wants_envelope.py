"""
Busta desideri: tetto mensile alle spese 'Want' (shopping, svago, mangiare fuori,
hobby...), mostrato in Dashboard durante il mese. Spese condivise alla tua quota;
alcune categorie (es. Viaggi, Regali) possono essere escluse.
"""
import calendar
import datetime
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from src.partner_share import my_share_view
from src.metrics import real_expenses

DEFAULT_ENVELOPE = {'enabled': True, 'monthly': 600, 'excluded': ['Viaggi', 'Regali']}


def envelope_config(rules):
    cfg = dict(DEFAULT_ENVELOPE)
    cfg.update(rules.get('wants_envelope') or {})
    return cfg


def wants_by_month(df, split_conf, excluded):
    """Spese Want (tua quota) per mese, escluse le categorie indicate."""
    if df.empty:
        return pd.DataFrame(columns=['date', 'category', 'description', 'a'])
    e = real_expenses(my_share_view(df, split_conf))
    e = e[(e['necessity'] == 'Want') & ~e['category'].isin(excluded or [])].copy()
    e['date'] = pd.to_datetime(e['date'])
    e['a'] = e['amount'].abs()
    e['mese'] = e['date'].dt.to_period('M')
    return e


def envelope_status(spent, budget, today):
    """Stato della busta nel mese di `today`: speso, residuo, giorni rimasti,
    disponibile al giorno e 'ritmo' (speso vs quota del mese trascorsa)."""
    days = calendar.monthrange(today.year, today.month)[1]
    elapsed = today.day / days
    left = budget - spent
    days_left = days - today.day + 1
    expected = budget * elapsed
    if spent > budget:
        state = 'sforata'
    elif spent > expected * 1.1:
        state = 'veloce'
    else:
        state = 'ok'
    return {'spent': spent, 'budget': budget, 'left': left, 'days_left': days_left,
            'per_day': max(left, 0) / days_left, 'expected': expected, 'state': state,
            'pct': spent / budget if budget else 0.0}


def render_wants_envelope(df, rules_engine):
    rules = rules_engine.rules
    cfg = envelope_config(rules)
    if not cfg['enabled'] or not cfg['monthly']:
        return
    today = datetime.date.today()
    e = wants_by_month(df, rules.get('split_config', {}), cfg['excluded'])
    cur = e[e['mese'] == pd.Period(today, freq='M')]
    s = envelope_status(float(cur['a'].sum()), float(cfg['monthly']), today)

    colors = {'ok': '#43A047', 'veloce': '#FB8C00', 'sforata': '#E53935'}
    msg = {'ok': f"restano **€{s['left']:,.0f}** per {s['days_left']} giorni (≈ €{s['per_day']:,.0f}/giorno)",
           'veloce': f"stai andando veloce: a oggi saresti a ~€{s['expected']:,.0f}. "
                     f"Restano €{s['left']:,.0f} per {s['days_left']} giorni (≈ €{s['per_day']:,.0f}/giorno)",
           'sforata': f"busta superata di **€{-s['left']:,.0f}**"}[s['state']]
    with st.container(border=True):
        st.markdown(f"**👛 Busta desideri — {today.strftime('%m/%Y')}**: speso €{s['spent']:,.0f} "
                    f"di €{s['budget']:,.0f} · {msg}")
        pct = min(s['pct'], 1.0) * 100
        marker = min(s['expected'] / s['budget'], 1.0) * 100 if s['budget'] else 0
        st.markdown(
            f"<div style='position:relative;height:14px;background:#ECEFF1;border-radius:7px;'>"
            f"<div style='width:{pct:.0f}%;height:14px;background:{colors[s['state']]};border-radius:7px;'></div>"
            f"<div title='dove dovresti essere oggi' style='position:absolute;left:{marker:.0f}%;top:-3px;"
            f"width:2px;height:20px;background:#37474F;'></div></div>", unsafe_allow_html=True)

        with st.expander("Dettaglio e impostazioni"):
            if not cur.empty:
                st.caption("Questo mese per categoria:")
                st.dataframe(cur.groupby('category')['a'].sum().sort_values(ascending=False)
                             .map(lambda v: f"€{v:,.0f}").rename('Speso'), use_container_width=True)
            hist = e[e['mese'] < pd.Period(today, freq='M')].groupby('mese')['a'].sum().tail(12)
            if not hist.empty:
                fig = go.Figure(go.Bar(x=hist.index.astype(str), y=hist.values,
                                       marker_color=['#E53935' if v > cfg['monthly'] else '#43A047'
                                                     for v in hist.values]))
                fig.add_hline(y=cfg['monthly'], line=dict(color='#37474F', dash='dash'),
                              annotation_text=f"busta €{cfg['monthly']:,.0f}")
                fig.update_layout(height=240, margin=dict(t=30, b=10), yaxis_title='€',
                                  title=f"Ultimi mesi · media €{hist.mean():,.0f} · "
                                        f"{int((hist <= cfg['monthly']).sum())}/{len(hist)} entro la busta")
                st.plotly_chart(fig, use_container_width=True)
            st.caption("Conta le spese classificate *Want* (spese condivise alla tua quota), "
                       "escluse le categorie qui sotto.")
            all_cats = sorted(df['category'].dropna().unique().tolist())
            with st.form("wants_env_cfg"):
                c1, c2 = st.columns([1, 2])
                b = c1.number_input("Busta €/mese", 0, 10000, int(cfg['monthly']), step=50)
                ex = c2.multiselect("Escludi categorie", all_cats,
                                    default=[c for c in cfg['excluded'] if c in all_cats])
                if st.form_submit_button("💾 Salva"):
                    rules['wants_envelope'] = {'enabled': True, 'monthly': int(b), 'excluded': ex}
                    rules_engine.save_rules(rules)
                    st.rerun()
