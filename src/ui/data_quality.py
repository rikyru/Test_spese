"""Controlli di qualità dei dati: segnala ciò che rende inaffidabili saldi e analisi."""
import pandas as pd
import streamlit as st
from src.utils import VIRTUAL_ACCOUNTS
from src.insights import (unmatched_transfers, negative_accounts, recurring_on_account,
                          stale_accounts, possible_duplicates, untagged_or_unclassified)


def quality_checks(df, rec_df, archived=()):
    """Esegue i controlli; ritorna dict nome → DataFrame dei casi trovati.
    I conti archiviati (fuori uso) sono esclusi dai controlli sui saldi."""
    no_tags, no_nec = untagged_or_unclassified(df)
    skip = set(VIRTUAL_ACCOUNTS) | set(archived)
    last12 = pd.to_datetime(df['date']) >= pd.Timestamp.today() - pd.DateOffset(months=12)
    return {
        'negativi': negative_accounts(df, skip),
        'trasferimenti': unmatched_transfers(df),
        'fermi': stale_accounts(df, virtual=skip),
        'doppioni': possible_duplicates(df[last12]),
        'senza_tag': no_tags[pd.to_datetime(no_tags['date']) >= pd.Timestamp.today() - pd.DateOffset(months=12)],
        'senza_necessita': no_nec,
    }


# Quali controlli contano come "problema" (gli altri sono suggerimenti)
SERIOUS = ('negativi', 'trasferimenti', 'doppioni', 'senza_necessita')


def issues_count(checks):
    return sum(1 for k in SERIOUS if not checks[k].empty)


def render_data_quality(data_manager):
    st.subheader("🩺 Qualità dei dati")
    df = data_manager.get_transactions()
    if df.empty:
        st.info("Nessun dato.")
        return
    rec = data_manager.get_recurring()
    c = quality_checks(df, rec, data_manager.rules_engine.rules.get('archived_accounts') or [])
    n = issues_count(c)
    if n == 0:
        st.success("Nessun problema rilevato: saldi e analisi si basano su dati coerenti.")
    else:
        st.warning(f"{n} controlli da guardare: possono falsare saldi dei conti o analisi.")

    # 1. Conti con saldo impossibile
    neg = c['negativi']
    with st.expander(f"{'🔴' if not neg.empty else '✅'} Conti con saldo negativo ({len(neg)})",
                     expanded=not neg.empty):
        if neg.empty:
            st.caption("Nessun conto reale in negativo.")
        for _, r in neg.iterrows():
            st.markdown(f"**{r['conto']}**: €{r['saldo']:,.2f} · negativo dal "
                        f"{pd.to_datetime(r['negativo_dal']).strftime('%d/%m/%Y')}")
            st.caption("Variazione per anno: " + " · ".join(f"{y}: €{v:+,.0f}" for y, v in r['per_anno'].items()))
            ro = recurring_on_account(rec, r['conto'])
            if not ro.empty:
                st.caption("Ricorrenti addebitate qui: " + ", ".join(
                    f"{x['name']} €{abs(x['amount']):,.0f} ({x['frequency']})" for _, x in ro.iterrows()))
            st.info("Un conto in banca non può restare in negativo per mesi: di solito mancano le **entrate** "
                    "verso questo conto (es. bonifici dal conto principale non registrati), oppure una "
                    "ricorrente è assegnata al conto sbagliato. Correzioni possibili: registrare i "
                    "trasferimenti mancanti, spostare la ricorrente sul conto da cui paghi davvero, oppure "
                    "«Allinea il saldo alla banca» qui sotto in Impostazioni.")

    # 2. Trasferimenti senza controparte
    tr = c['trasferimenti']
    with st.expander(f"{'🟠' if not tr.empty else '✅'} Trasferimenti senza la controparte ({len(tr)})"):
        if tr.empty:
            st.caption("Ogni trasferimento in uscita ha la sua entrata su un altro conto.")
        else:
            st.caption("Un trasferimento va registrato su entrambi i conti (uscita e entrata, stesso importo). "
                       "Questi hanno una sola delle due parti: il saldo di un conto risulta sbagliato.")
            st.dataframe(tr[['date', 'account', 'type', 'amount', 'description']].rename(columns={
                'date': 'Data', 'account': 'Conto', 'type': 'Tipo', 'amount': 'Importo', 'description': 'Descrizione'}),
                hide_index=True, use_container_width=True)

    # 3. Possibili doppioni
    du = c['doppioni']
    with st.expander(f"{'🟠' if not du.empty else '✅'} Possibili doppioni, ultimi 12 mesi ({len(du)})"):
        if du.empty:
            st.caption("Nessuna spesa ripetuta identica.")
        else:
            st.caption("Stessa data, importo, conto, categoria e tag: controlla se sono due spese vere o un "
                       "doppio import. Puoi eliminarli da Movimenti.")
            st.dataframe(du[['date', 'account', 'amount', 'category', 'description']], hide_index=True,
                         use_container_width=True)

    # 4. Classificazione e tag
    nn, nt = c['senza_necessita'], c['senza_tag']
    with st.expander(f"{'🟠' if not nn.empty else '✅'} Classificazione e tag"):
        st.markdown(f"- Spese senza Necessità/Desiderio: **{len(nn)}** "
                    "(non entrano in busta desideri e analisi Need/Want)")
        st.markdown(f"- Spese senza tag negli ultimi 12 mesi: **{len(nt)}** "
                    f"(€{nt['amount'].abs().sum():,.0f}) — i tag servono per il dettaglio delle categorie")
        if not nn.empty:
            st.dataframe(nn[['date', 'category', 'amount', 'description']].head(30), hide_index=True,
                         use_container_width=True)

    # 5. Conti fermi
    fe = c['fermi']
    with st.expander(f"{'ℹ️' if not fe.empty else '✅'} Conti senza movimenti da oltre 45 giorni ({len(fe)})"):
        if fe.empty:
            st.caption("Tutti i conti con saldo hanno movimenti recenti.")
        else:
            st.caption("Se il saldo in banca è cambiato nel frattempo, mancano dei movimenti (o il conto è "
                       "davvero fermo: in quel caso è tutto ok).")
            st.dataframe(fe.assign(ultimo_movimento=fe['ultimo_movimento'].dt.strftime('%d/%m/%Y'),
                                   saldo=fe['saldo'].map(lambda v: f"€{v:,.2f}"))
                         .rename(columns={'conto': 'Conto', 'ultimo_movimento': 'Ultimo movimento', 'saldo': 'Saldo'}),
                         hide_index=True, use_container_width=True)
