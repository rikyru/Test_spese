import json
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from src.data_manager import DataManager
from src.payslip_parser import parse_pdf

MONTHS = ["", "Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]


def _label(r):
    lbl = f"{MONTHS[int(r['month'])]} {int(r['year'])}"
    return lbl + (" (13ª)" if r['kind'] == 'tredicesima' else "")


def netto_base(r):
    """Netto 'ricorrente': senza trasferte, premi e rimborsi 730 (che variano)."""
    return r['netto'] - r['trasferte'] - r['premi'] - r['rimborso_730']


def explain_change(a, b):
    """Scompone la differenza di netto tra due buste (b − a) nelle sue cause.
    Ritorna una lista di (voce, effetto sul netto in €)."""
    d = lambda k: float(b[k]) - float(a[k])
    other_comp = d('competenze') - d('trasferte') - d('premi') - d('rimborso_730')
    items = [
        ("Retribuzione e altre competenze", other_comp),
        ("Trasferte", d('trasferte')),
        ("Premi", d('premi')),
        ("Rimborso 730", d('rimborso_730')),
        ("IRPEF", -d('ritenute_irpef')),
        ("Contributi INPS", -d('inps')),
        ("Addizionali regionali/comunali", -d('addizionali')),
    ]
    explained = sum(v for _, v in items)
    rest = d('netto') - explained
    if abs(rest) >= 1:
        items.append(("Altro (arrotondamenti, altre trattenute)", rest))
    return items


def payslip_alerts(a, b):
    """Spiegazioni in parole delle differenze principali tra due buste."""
    notes = []
    if abs(b['paga_base'] - a['paga_base']) >= 1:
        notes.append(f"💶 **Paga base** cambiata: €{a['paga_base']:,.2f} → €{b['paga_base']:,.2f} "
                     f"({b['paga_base'] - a['paga_base']:+,.2f} lordi).")
    if b['benefit_tassati'] > 0:
        notes.append(f"🚗 **Benefit tassati €{b['benefit_tassati']:,.2f}**: si aggiungono all'imponibile "
                     "(paghi IRPEF e INPS) ma non sono soldi in busta. Tipico del fringe benefit auto "
                     "oltre la soglia esente annua.")
    if b['benefit'] > 0 and b['benefit_tassati'] == 0:
        notes.append(f"🚗 Fringe benefit €{b['benefit']:,.2f} presente ma ancora **non tassato** "
                     "(entro la soglia esente).")
    if b['detrazioni'] + 5 < a['detrazioni']:
        notes.append(f"📉 **Detrazioni** scese da €{a['detrazioni']:,.2f} a €{b['detrazioni']:,.2f}: "
                     "calano quando il reddito imponibile sale.")
    if b['addizionali'] - a['addizionali'] >= 5:
        notes.append(f"🏛️ **Addizionali** salite di €{b['addizionali'] - a['addizionali']:,.2f}/mese "
                     "(si pagano a rate sul reddito dell'anno prima).")
    if b['rimborso_730'] > 0:
        notes.append(f"🧾 Rimborso 730 in busta: €{b['rimborso_730']:,.2f} (una tantum).")
    return notes


def _import_section(dm: DataManager):
    with st.expander("📤 Carica buste paga (PDF)", expanded=False):
        files = st.file_uploader("Buste paga PDF", type="pdf", accept_multiple_files=True,
                                 key="payslip_upload", label_visibility="collapsed")
        if files and st.button(f"Analizza e salva {len(files)} file", key="payslip_save"):
            ok, ko = [], []
            for f in files:
                try:
                    rec = parse_pdf(f, f.name)
                except Exception as e:
                    rec = None
                if rec and rec['year'] and rec['month']:
                    ok.append(dm.save_payslip(rec, f.name))
                else:
                    ko.append(f.name)
            if ok:
                st.success(f"Salvate {len(ok)} buste.")
            if ko:
                st.warning("Non riconosciute (PDF senza testo o formato diverso): " + ", ".join(ko))


def render_payslips(dm: DataManager):
    st.header("💼 Buste Paga")
    _import_section(dm)

    df = dm.get_payslips()
    if df.empty:
        st.info("Nessuna busta caricata. Usa «Carica buste paga» qui sopra.")
        return

    df['label'] = df.apply(_label, axis=1)
    df['netto_base'] = df.apply(netto_base, axis=1)
    df['periodo'] = pd.to_datetime(dict(year=df['year'], month=df['month'], day=1))
    monthly = df[df['kind'] == 'mensile'].sort_values('periodo').reset_index(drop=True)
    if monthly.empty:
        st.info("Servono buste mensili per l'analisi.")
        return
    last = monthly.iloc[-1]

    # --- Ultima busta ---
    st.subheader(f"Ultima busta: {last['label']}")
    tax_rate = (last['ritenute_irpef'] + last['inps'] + last['addizionali']) / last['competenze'] * 100 \
        if last['competenze'] else 0
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Netto", f"€{last['netto']:,.0f}")
    m2.metric("Netto ricorrente", f"€{last['netto_base']:,.0f}",
              help="Senza trasferte, premi e rimborsi 730: confrontabile mese su mese")
    m3.metric("Lordo (competenze)", f"€{last['competenze']:,.0f}")
    m4.metric("Tasse e contributi", f"{tax_rate:.0f}%", help="IRPEF + INPS + addizionali sul lordo")

    # --- Andamento ---
    st.markdown("### 📈 Andamento")
    fig = go.Figure()
    fig.add_trace(go.Bar(x=monthly['periodo'], y=monthly['netto'], name='Netto', marker_color='#90CAF9'))
    fig.add_trace(go.Scatter(x=monthly['periodo'], y=monthly['netto_base'], name='Netto ricorrente',
                             mode='lines+markers', line=dict(color='#1565C0', width=3)))
    fig.add_trace(go.Scatter(x=monthly['periodo'], y=monthly['paga_base'], name='Paga base (lorda)',
                             mode='lines', line=dict(color='#9E9E9E', dash='dot')))
    fig.update_layout(height=360, hovermode='x unified', yaxis_title='€',
                      legend=dict(orientation='h', y=-0.2))
    st.plotly_chart(fig, use_container_width=True)

    fig2 = go.Figure()
    for col, name, color in [('ritenute_irpef', 'IRPEF', '#EF5350'), ('inps', 'INPS', '#FFA726'),
                             ('addizionali', 'Addizionali', '#AB47BC')]:
        fig2.add_trace(go.Bar(x=monthly['periodo'], y=monthly[col], name=name, marker_color=color))
    fig2.add_trace(go.Scatter(x=monthly['periodo'], y=monthly['benefit_tassati'], name='Benefit tassati',
                              mode='markers', marker=dict(color='#212121', size=8, symbol='diamond')))
    fig2.update_layout(barmode='stack', height=320, title="Dove va il lordo: trattenute mese per mese",
                       yaxis_title='€', hovermode='x unified', legend=dict(orientation='h', y=-0.25))
    st.plotly_chart(fig2, use_container_width=True)

    # --- Confronto e spiegazione ---
    st.markdown("### 🔍 Perché il netto è cambiato?")
    labels = monthly['label'].tolist()
    same_last_year = monthly[(monthly['year'] == last['year'] - 1) & (monthly['month'] == last['month'])]
    default_a = labels.index(same_last_year.iloc[0]['label']) if not same_last_year.empty else max(len(labels) - 2, 0)
    c1, c2 = st.columns(2)
    la = c1.selectbox("Da", labels, index=default_a, key='ps_a')
    lb = c2.selectbox("A", labels, index=len(labels) - 1, key='ps_b')
    a = monthly[monthly['label'] == la].iloc[0]
    b = monthly[monthly['label'] == lb].iloc[0]

    items = explain_change(a, b)
    dn = b['netto'] - a['netto']
    st.markdown(f"Netto **€{a['netto']:,.0f} → €{b['netto']:,.0f}** ({dn:+,.0f}€) · "
                f"netto ricorrente **€{a['netto_base']:,.0f} → €{b['netto_base']:,.0f}** "
                f"({b['netto_base'] - a['netto_base']:+,.0f}€)")
    wf = go.Figure(go.Waterfall(
        x=[la] + [n for n, _ in items] + [lb],
        y=[a['netto']] + [v for _, v in items] + [b['netto']],
        measure=['absolute'] + ['relative'] * len(items) + ['total'],
        increasing=dict(marker=dict(color='#66BB6A')), decreasing=dict(marker=dict(color='#EF5350')),
        totals=dict(marker=dict(color='#1565C0')),
        text=[f"€{a['netto']:,.0f}"] + [f"{v:+,.0f}" for _, v in items] + [f"€{b['netto']:,.0f}"],
        textposition='outside'))
    wf.update_layout(height=380, yaxis_title='€', showlegend=False)
    st.plotly_chart(wf, use_container_width=True)
    for n in payslip_alerts(a, b):
        st.markdown("- " + n)

    # --- Riepilogo annuo ---
    st.markdown("### 📅 Per anno")
    y = df.groupby('year').agg(Buste=('netto', 'size'), Netto=('netto', 'sum'), Lordo=('competenze', 'sum'),
                               IRPEF=('ritenute_irpef', 'sum'), INPS=('inps', 'sum'),
                               Addizionali=('addizionali', 'sum'), Trasferte=('trasferte', 'sum'),
                               Benefit_tassati=('benefit_tassati', 'sum'))
    y = y.rename(columns={'Benefit_tassati': 'Benefit tassati'}).sort_index(ascending=False)
    st.dataframe(y.style.format({c: "€{:,.0f}" for c in y.columns if c != 'Buste'}),
                 use_container_width=True)

    # --- Dettaglio voci e gestione ---
    with st.expander("🧾 Dettaglio voci di una busta"):
        sel = st.selectbox("Busta", df['label'].tolist()[::-1], key='ps_detail')
        row = df[df['label'] == sel].iloc[0]
        voci = pd.DataFrame(json.loads(row['voci'] or '[]'))
        if not voci.empty:
            st.dataframe(voci.rename(columns={'code': 'Codice', 'desc': 'Voce', 'amount': 'Importo',
                                              'figurative': 'Figurativo'}),
                         hide_index=True, use_container_width=True)
        st.caption(f"File: {row['filename']}")
        if st.button("🗑️ Elimina questa busta", key='ps_del'):
            dm.delete_payslip(row['period_key'])
            st.rerun()
