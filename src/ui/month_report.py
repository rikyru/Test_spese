"""Resoconto di un mese chiuso: tutto quello che serve sapere, in una pagina."""
import pandas as pd
import streamlit as st
from src.metrics import (real_expenses, real_income, monthly_totals, last_complete_period,
                             salary_coverage, MONTH_ABBR, AVG_WINDOW_MONTHS)
from src.ui.wants_envelope import envelope_config, wants_by_month

MESI_LUNGHI = ["", "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
               "agosto", "settembre", "ottobre", "novembre", "dicembre"]


def month_summary(df, period, split_conf, env_cfg):
    """Numeri del resoconto per `period` (pd.Period mensile), confrontati con i 12
    mesi PRECEDENTI (il mese stesso escluso dalla media)."""
    d = pd.to_datetime(df['date']).dt.to_period('M')
    mdf = df[d == period]
    exp = real_expenses(mdf)
    inc = real_income(mdf)
    spent = float(exp['amount'].abs().sum())
    income = float(inc['amount'].sum())
    hist = monthly_totals(df[d <= period], 'expense', ref_df=df[d <= period])
    prev12 = hist[hist.index < period].tail(AVG_WINDOW_MONTHS)
    same_last_year = float(hist.get(period - 12, float('nan')))

    # Categorie vs media dei 12 mesi precedenti (mesi a zero inclusi)
    all_exp = real_expenses(df)
    ap = pd.to_datetime(all_exp['date']).dt.to_period('M')
    months = pd.period_range(period - AVG_WINDOW_MONTHS, period - 1, freq='M')
    cats = []
    for cat, g in all_exp.groupby('category'):
        gp = ap[g.index]
        by_m = g['amount'].abs().groupby(gp).sum()
        avg = float(by_m.reindex(months, fill_value=0.0).mean())
        now = float(by_m.get(period, 0.0))
        if avg == 0 and now == 0:
            continue
        cats.append({'categoria': cat, 'mese': now, 'media': avg, 'scarto': now - avg})
    cats = pd.DataFrame(cats)

    w = wants_by_month(df, split_conf, env_cfg['excluded'])
    wants = float(w[w['mese'] == period]['a'].sum()) if not w.empty else 0.0
    sc = salary_coverage(df[d <= period], split_conf)
    sal = sc.loc[period] if period in sc.index else None
    rec = exp[exp['source_file'] == 'Recurring'] if 'source_file' in exp else exp.iloc[0:0]
    return {
        'spent': spent, 'income': income, 'net': income - spent,
        'rate': (income - spent) / income * 100 if income > 0 else None,
        'avg12': float(prev12.mean()) if len(prev12) else None,
        'same_last_year': same_last_year,
        'cats': cats, 'wants': wants, 'salary': sal,
        'recurring': rec, 'top': exp.assign(a=exp['amount'].abs()).nlargest(5, 'a'),
    }


def render_month_report(df, data_manager):
    st.subheader("🗓️ Resoconto del mese")
    if df.empty:
        st.info("Nessun dato.")
        return
    last = last_complete_period(df)
    periods = sorted(pd.to_datetime(df['date']).dt.to_period('M').unique(), reverse=True)
    periods = [p for p in periods if p <= last][:24]
    if not periods:
        st.info("Nessun mese completo.")
        return
    period = st.selectbox("Mese", periods, index=0, key='mr_period',
                          format_func=lambda p: f"{MESI_LUNGHI[p.month].capitalize()} {p.year}")
    rules = data_manager.rules_engine.rules
    env = envelope_config(rules)
    s = month_summary(df, period, rules.get('split_config', {}), env)
    name = f"{MESI_LUNGHI[period.month]} {period.year}"

    # --- In sintesi ---
    bullets = []
    if s['avg12']:
        diff = s['spent'] - s['avg12']
        bullets.append(f"Hai speso **€{s['spent']:,.0f}**, "
                       + (f"**€{diff:,.0f} in più**" if diff > 0 else f"**€{-diff:,.0f} in meno**")
                       + f" della tua media (€{s['avg12']:,.0f}).")
    if s['rate'] is not None:
        bullets.append(f"Entrate €{s['income']:,.0f} → hai " + ("messo da parte" if s['net'] >= 0 else "intaccato i risparmi per")
                       + f" **€{abs(s['net']):,.0f}** ({s['rate']:.0f}% delle entrate).")
    if env['enabled'] and env['monthly']:
        ok = s['wants'] <= env['monthly']
        bullets.append(f"Busta desideri: €{s['wants']:,.0f} su €{env['monthly']:,.0f} — "
                       + ("✅ rispettata." if ok else f"❌ superata di €{s['wants'] - env['monthly']:,.0f}."))
    if s['salary'] is not None:
        sb = s['salary']['saldo']
        bullets.append("Solo con lo stipendio: " + (f"✅ coperto, avanzano €{sb:,.0f}." if sb >= 0
                                                    else f"❌ mancano €{-sb:,.0f}."))
    st.markdown("\n".join(f"- {b}" for b in bullets))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Speso", f"€{s['spent']:,.0f}",
              delta=(f"{s['spent'] - s['avg12']:+,.0f}€ vs media" if s['avg12'] else None), delta_color="inverse")
    c2.metric("Entrate", f"€{s['income']:,.0f}")
    c3.metric("Risparmio", f"€{s['net']:,.0f}")
    if pd.notna(s['same_last_year']):
        c4.metric(f"{MONTH_ABBR[period.month].capitalize()} {period.year - 1}", f"€{s['same_last_year']:,.0f}",
                  delta=f"{s['spent'] - s['same_last_year']:+,.0f}€ quest'anno", delta_color="inverse")

    # --- Categorie ---
    cats = s['cats']
    if not cats.empty:
        thr = cats['media'].mul(0.25).clip(lower=40)
        out = cats[cats['scarto'].abs() > thr].sort_values('scarto', ascending=False)
        st.markdown("#### 📂 Categorie fuori dal solito")
        st.caption(f"{name.capitalize()} confrontato con la media dei 12 mesi precedenti (scarto oltre 25% e €40).")
        if out.empty:
            st.success("Tutte nella norma.")
        else:
            st.dataframe(pd.DataFrame({
                'Categoria': out['categoria'],
                '': out['scarto'].map(lambda v: "🔴" if v > 0 else "🟢"),
                name.capitalize(): out['mese'].map(lambda v: f"€{v:,.0f}"),
                'Media': out['media'].map(lambda v: f"€{v:,.0f}"),
                'Differenza': out['scarto'].map(lambda v: f"{v:+,.0f}€"),
            }), hide_index=True, use_container_width=True)

    # --- Spese grandi e ricorrenti ---
    c_a, c_b = st.columns(2)
    with c_a:
        st.markdown("#### 🏆 Le 5 spese più grandi")
        top = s['top']
        if not top.empty:
            st.dataframe(pd.DataFrame({'Data': pd.to_datetime(top['date']).dt.strftime('%d/%m'),
                                       'Descrizione': top['description'].fillna(''),
                                       'Categoria': top['category'],
                                       'Importo': top['a'].map(lambda v: f"€{v:,.0f}")}),
                         hide_index=True, use_container_width=True)
    with c_b:
        st.markdown("#### 🔁 Ricorrenti e rate addebitate")
        rec = s['recurring']
        if rec.empty:
            st.caption("Nessuna.")
        else:
            st.caption(f"Totale €{rec['amount'].abs().sum():,.0f} ({len(rec)} addebiti)")
            st.dataframe(pd.DataFrame({'Voce': rec['description'].fillna(''),
                                       'Importo': rec['amount'].abs().map(lambda v: f"€{v:,.0f}")})
                         .groupby('Voce', as_index=False).first(), hide_index=True, use_container_width=True)
