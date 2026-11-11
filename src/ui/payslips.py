import json
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from src.data_manager import DataManager
from src.payslip_parser import parse_pdf
from src.salary_insights import merged_config, ral, pay_events, projection, package_value, ral_by_year, package_by_year

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

    cfg = merged_config(dm.rules_engine.rules.get('payslip_config'))
    _salary_section(dm, monthly, last, cfg)

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


EVENT_LABELS = {'contratto': '📜 Aumento contratto', 'assorbito': '🫥 Assorbito dal superminimo',
                'personale': '🙌 Aumento personale', 'riduzione': '⚠️ Superminimo ridotto',
                'scatto': '⏫ Scatto anzianità'}


def _salary_section(dm, monthly, last, cfg):
    """RAL, composizione della paga, storia aumenti, proiezione, mercato e pacchetto."""
    st.markdown("### 💶 RAL e composizione")
    has_parts = 'minimo' in monthly and monthly['minimo'].fillna(0).gt(0).any()
    comp = monthly[monthly['minimo'].fillna(0) > 0] if has_parts else monthly.iloc[0:0]
    ref = comp.iloc[-1] if len(comp) else last
    my_ral = ral(ref['paga_base'], cfg['mensilita'])
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("RAL", f"€{my_ral:,.0f}", help=f"Paga base €{ref['paga_base']:,.2f} × {cfg['mensilita']} mensilità")
    r2.metric("Livello", str(ref.get('livello') or '—'))
    if not has_parts:
        st.info("Ricarica le buste paga per vedere composizione e aumenti.")
        return
    r3.metric("Superminimo", f"€{ref['superminimo']:,.2f}/mese",
              help="'Acconto futuri aumenti': può assorbire gli aumenti del contratto")
    r4.metric("Prossimo scatto", str(ref.get('prossimo_scatto') or '—'))

    fig = go.Figure()
    for col, name, color in [('minimo', 'Minimo contrattuale', '#1565C0'), ('scatti', 'Scatti', '#43A047'),
                             ('edr', 'EDR', '#9E9E9E'), ('superminimo', 'Superminimo', '#FB8C00')]:
        fig.add_trace(go.Bar(x=comp['periodo'], y=comp[col], name=name, marker_color=color))
    fig.update_layout(barmode='stack', height=320, title="Composizione della paga base (lorda mensile)",
                      yaxis_title='€', hovermode='x unified', legend=dict(orientation='h', y=-0.25))
    st.plotly_chart(fig, use_container_width=True)

    # --- RAL negli anni ---
    st.markdown("#### 📈 RAL negli anni")
    ry = ral_by_year(comp, cfg['mensilita'], cfg.get('inflation'))
    pk_y = package_by_year(monthly, ry, cfg)
    show_pk = (pk_y['pacchetto'] - ry['ral']).abs().max() > 1
    first_y = int(ry.index[0])
    fig_r = go.Figure()
    fig_r.add_trace(go.Bar(x=ry.index.astype(str), y=ry['ral'], name='RAL', marker_color='#1565C0',
                           text=[f"€{v/1000:,.1f}k" for v in ry['ral']], textposition='outside'))
    if show_pk:
        fig_r.add_trace(go.Bar(x=ry.index.astype(str), y=pk_y['pacchetto'] - ry['ral'],
                               name='Benefit (lordo equivalente)', marker_color='#81C784',
                               text=[f"€{v/1000:,.1f}k" for v in pk_y['pacchetto']], textposition='outside'))
        fig_r.update_traces(selector=dict(name='RAL'), text=None)
    fig_r.add_trace(go.Scatter(x=ry.index.astype(str), y=ry['ral_reale'], name=f"RAL in euro {first_y}",
                               mode='lines+markers', line=dict(color='#E53935', width=3)))
    fig_r.update_layout(height=340, yaxis_title='€', hovermode='x unified', barmode='stack',
                        legend=dict(orientation='h', y=-0.2),
                        title="RAL a fine anno e potere d'acquisto (al netto dell'inflazione)")
    st.plotly_chart(fig_r, use_container_width=True)
    n_years = len(ry) - 1
    if n_years >= 1:
        tot_nom = (ry['ral'].iloc[-1] / ry['ral'].iloc[0] - 1) * 100
        tot_real = (ry['ral_reale'].iloc[-1] / ry['ral_reale'].iloc[0] - 1) * 100
        cagr = ((ry['ral'].iloc[-1] / ry['ral'].iloc[0]) ** (1 / n_years) - 1) * 100
        g1, g2, g3 = st.columns(3)
        g1.metric(f"Crescita {first_y}→{int(ry.index[-1])}", f"{tot_nom:+.0f}%",
                  f"€{ry['ral'].iloc[-1] - ry['ral'].iloc[0]:+,.0f}")
        g2.metric("Crescita reale", f"{tot_real:+.0f}%", help="Al netto dell'inflazione (parametri)")
        g3.metric("Media annua", f"{cagr:+.1f}%/anno")
        if show_pk:
            pk_tot = (pk_y['pacchetto'].iloc[-1] / pk_y['pacchetto'].iloc[0] - 1) * 100
            st.caption(f"📦 Contando anche i benefit, il pacchetto è passato da €{pk_y['pacchetto'].iloc[0]:,.0f} "
                       f"a €{pk_y['pacchetto'].iloc[-1]:,.0f} ({pk_tot:+.0f}%).")
    tbl = pd.DataFrame({
        'Anno': ry.index.astype(str),
        'RAL': ry['ral'].map(lambda v: f"€{v:,.0f}"),
        'Crescita': ry['crescita'].map(lambda v: '' if pd.isna(v) else f"{v:+.1f}%"),
        'Inflazione': ry['inflazione'].map(lambda v: '' if pd.isna(v) else f"{v:.1f}%"),
        'Crescita reale': ry['crescita_reale'].map(lambda v: '' if pd.isna(v) else f"{v:+.1f}%"),
    })
    if show_pk:
        tbl['Pacchetto'] = pk_y['pacchetto'].map(lambda v: f"€{v:,.0f}").values
        tbl['Crescita pacchetto'] = pk_y['crescita_pacchetto'].map(
            lambda v: '' if pd.isna(v) else f"{v:+.1f}%").values
    st.dataframe(tbl.iloc[::-1], hide_index=True, use_container_width=True)
    st.caption("RAL = paga base dell'ultima busta dell'anno × mensilità. Pacchetto = RAL + auto aziendale "
               "(se assegnata entro fine anno, al netto del costo fiscale), trasferte esenti annualizzate e "
               "welfare, convertiti in lordo con l'aliquota marginale. Anno in corso: inflazione stimata.")

    # --- Storia aumenti ---
    ev = pay_events(comp)
    st.markdown("#### 📜 Storia degli aumenti")
    if ev.empty:
        st.caption("Nessuna variazione della paga base nelle buste caricate.")
    else:
        absorbed = -ev.loc[ev['tipo'] == 'assorbito', 'importo'].sum()
        if absorbed > 0:
            st.warning(f"🫥 **€{absorbed:,.2f}/mese di aumenti contrattuali assorbiti** dal superminimo "
                       f"(circa €{absorbed * cfg['mensilita']:,.0f}/anno lordi che non hai visto).")
        show = ev.copy()
        show['Tipo'] = show['tipo'].map(EVENT_LABELS)
        show['€/mese lordi'] = show['importo'].map(lambda v: f"{v:+,.2f}")
        show['€/anno'] = show['importo'].map(lambda v: f"{v * cfg['mensilita']:+,.0f}")
        st.dataframe(show[['periodo', 'Tipo', '€/mese lordi', '€/anno', 'nota']]
                     .rename(columns={'periodo': 'Mese', 'nota': 'Dettaglio'}).iloc[::-1],
                     hide_index=True, use_container_width=True)

    # --- Proiezione ---
    st.markdown("#### 🔮 Prossimi aumenti attesi")
    proj, sup_left = projection(ref.to_dict(), ev, cfg)
    if not proj:
        st.caption("Nessun aumento previsto: aggiungi i minimi futuri del tuo livello nei parametri.")
    else:
        keep = 1 - cfg['marginal_rate'] / 100.0
        rows = [{'Mese': p['periodo'],
                 'Cosa': '⏫ Scatto anzianità' if p['tipo'] == 'scatto' else '📜 Aumento contratto',
                 'Lordo/mese': f"€{p['lordo_mese']:,.2f}",
                 'In busta se assorbito': f"€{p['in_busta']:,.2f}",
                 'Netto/mese (stima)': f"€{p['in_busta'] * keep:,.0f}",
                 'Assorbibile': 'sì' if p['assorbibile'] else 'no'} for p in proj]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        at_risk = sum(p['lordo_mese'] - p['in_busta'] for p in proj if p['assorbibile'])
        if at_risk > 0:
            st.caption(f"Se l'azienda continua ad assorbire, €{at_risk:,.2f}/mese di aumenti contrattuali "
                       f"non arriverebbero in busta (superminimo residuo €{sup_left:,.2f}). "
                       "Leva di negoziazione: superminimo non assorbibile o passaggio di livello senza assorbimento.")

    # --- Mercato e pacchetto ---
    st.markdown("#### 🧭 Mercato e valore del pacchetto")
    last12 = monthly.tail(12)
    trasferte_year = float(last12['trasferte'].sum()) * 12 / max(len(last12), 1)
    car_tax_year = float(last12['benefit_tassati'].sum()) * cfg['marginal_rate'] / 100.0
    if cfg['car_tax_month']:
        car_tax_year = cfg['car_tax_month'] * 12
    pk = package_value(my_ral, trasferte_year, cfg, car_tax_year)

    bench = cfg['benchmarks'] or {}
    fig_b = go.Figure()
    fig_b.add_trace(go.Bar(x=list(bench.values()), y=list(bench.keys()), orientation='h',
                           marker_color='#B0BEC5', text=[f"€{v:,.0f}" for v in bench.values()],
                           textposition='inside'))
    fig_b.add_vline(x=my_ral, line=dict(color='#1565C0', width=3),
                    annotation_text=f"La tua RAL €{my_ral:,.0f}", annotation_position="top")
    if pk['ral_equivalente'] > my_ral + 1:
        fig_b.add_vline(x=pk['ral_equivalente'], line=dict(color='#43A047', width=3, dash='dash'),
                        annotation_text=f"Pacchetto ≈ €{pk['ral_equivalente']:,.0f}",
                        annotation_position="bottom")
    fig_b.update_layout(height=280, title=cfg['benchmark_label'], xaxis_title='RAL €', showlegend=False)
    st.plotly_chart(fig_b, use_container_width=True)

    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Auto (netto/anno)", f"€{pk['auto_netto']:,.0f}",
              help="Valore di mercato dell'uso personale meno il suo costo fiscale in busta")
    p2.metric("Trasferte esenti/anno", f"€{pk['trasferte']:,.0f}", help="Ultimi 12 mesi di buste")
    p3.metric("Welfare/anno", f"€{pk['welfare']:,.0f}")
    p4.metric("RAL equivalente", f"€{pk['ral_equivalente']:,.0f}",
              help=f"RAL + benefit netti ÷ (1 − {cfg['marginal_rate']}%): la RAL che servirebbe "
                   "in un'offerta senza questi benefit")
    if not cfg['car_value_month']:
        st.caption("🚗 Imposta nei parametri il valore mensile dell'auto aziendale per includerla nel pacchetto.")

    with st.expander("⚙️ Parametri (fasce di mercato, minimi futuri, benefit)"):
        _config_form(dm, cfg, ref.get('livello') or 'C3')


def _parse_pairs(txt, num=float):
    """'Nome = valore' per riga → dict (righe non valide ignorate)."""
    out = {}
    for line in txt.splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            try:
                out[k.strip()] = num(v.strip().replace('€', '').replace('.', '').replace(',', '.')
                                     if v.count(',') == 1 else v.strip().replace('€', ''))
            except ValueError:
                pass
    return out


def _config_form(dm, cfg, level):
    with st.form("payslip_cfg"):
        c1, c2, c3 = st.columns(3)
        mens = c1.number_input("Mensilità", 12, 15, int(cfg['mensilita']))
        marg = c2.number_input("Aliquota marginale %", 20, 60, int(cfg['marginal_rate']),
                               help="Tasse + contributi su ogni euro lordo in più (IRPEF 35% + INPS 9,19% + addiz.)")
        welf = c3.number_input("Welfare €/anno", 0, 10000, int(cfg['welfare_year']), step=50)
        c4, c5 = st.columns(2)
        car = c4.number_input("Auto aziendale: valore di mercato €/mese", 0, 3000, int(cfg['car_value_month']),
                              step=25, help="Quanto pagheresti un noleggio equivalente (0 = nessuna auto)")
        cart = c5.number_input("Auto: costo fiscale €/mese (0 = calcolato dalle buste)", 0, 1000,
                               int(cfg['car_tax_month']), step=5)
        cstart = st.text_input("Auto: assegnata dal (AAAA-MM, vuoto = nessuna)", cfg.get('car_start') or '')
        label = st.text_input("Fasce di mercato: fonte / descrizione", cfg['benchmark_label'])
        bench_txt = st.text_area("Fasce di mercato, una per riga: Nome = RAL",
                                 "\n".join(f"{k} = {v}" for k, v in cfg['benchmarks'].items()))
        infl_txt = st.text_area("Inflazione media annua % (ISTAT NIC; anno = %)",
                                "\n".join(f"{k} = {v}" for k, v in sorted(cfg.get('inflation', {}).items())))
        fut = cfg.get('future_minimi', {}).get(level, {})
        fut_txt = st.text_area(f"Minimi futuri del livello {level} (AAAA-MM = €/mese)",
                               "\n".join(f"{k} = {v}" for k, v in fut.items()),
                               help="Dalle tabelle del CCNL: da aggiornare a ogni rinnovo")
        if st.form_submit_button("💾 Salva parametri"):
            fm = dict(cfg.get('future_minimi', {}))
            fm[level] = _parse_pairs(fut_txt)
            rules = dm.rules_engine.rules
            rules['payslip_config'] = {
                'mensilita': int(mens), 'marginal_rate': int(marg), 'welfare_year': int(welf),
                'car_value_month': int(car), 'car_tax_month': int(cart), 'car_start': cstart.strip(),
                'benchmark_label': label, 'benchmarks': _parse_pairs(bench_txt, lambda x: int(float(x))),
                'future_minimi': fm,
                'inflation': {int(k): v for k, v in _parse_pairs(infl_txt).items() if k.strip().isdigit()},
            }
            dm.rules_engine.save_rules(rules)
            st.success("Parametri salvati.")
            st.rerun()
