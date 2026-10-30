"""
Rimborsi del partner sulle spese condivise.

I rimborsi (es. tag #rimborsocri) arrivano come entrate, mentre le spese
condivise che paghi tu sono registrate al 100%. Così entrate e spese risultano
entrambe gonfiate. `net_partner_reimbursements` riporta le analisi alla TUA quota:
ogni rimborso copre le spese condivise del mese PRECEDENTE e viene ripartito
su di esse in proporzione alla quota del partner calcolata con le regole di
Spese Condivise (le regole danno i pesi, l'importo vero è il rimborso).
Se quel mese non ha spese condivise si guarda fino a `lookback_months` indietro.
L'importo abbinato viene tolto dal rimborso (il totale dei saldi non cambia);
l'eventuale eccedenza resta un'entrata.
"""
import pandas as pd

DEFAULT_REIMBURSEMENT_TAGS = ['rimborsocri', 'rimborso_partner']
DEFAULT_SPLIT_TAGS = {'split', 'condiviso', 'shared', 'comune'}


def _norm_tags(t):
    if hasattr(t, 'tolist'):
        t = t.tolist()
    if not isinstance(t, (list, tuple)):
        return []
    return [str(x).lower().replace('#', '').strip() for x in t]


def partner_share(category, tags, conf):
    """Quota (0..1) a carico del partner per una spesa, con la stessa logica della
    pagina Spese Condivise: prestiti 100%, regola tag > regola categoria >
    default solo se taggata come condivisa; spese pagate dal partner 0."""
    tags = _norm_tags(tags)
    if 'partner_paid' in tags:
        return 0.0
    loan_tags = {str(t).lower().replace('#', '').strip() for t in conf.get('loan_tags', [])}
    if loan_tags & set(tags):
        return 1.0
    rules = conf.get('rules', [])
    for r in rules:
        if r.get('type') == 'tag' and str(r.get('match', '')).lower().replace('#', '').strip() in tags:
            return 1.0 - r['my_share'] / 100.0
    for r in rules:
        if r.get('type') == 'category' and r.get('match') == category:
            return 1.0 - r['my_share'] / 100.0
    if DEFAULT_SPLIT_TAGS & set(tags):
        return 1.0 - conf.get('default_share_pct', 50) / 100.0
    return 0.0


def net_partner_reimbursements(df, conf, lookback_months=3):
    """Ritorna una copia di `df` con i rimborsi del partner scalati dalle spese
    condivise (vedi docstring del modulo). Colonne aggiunte: 'partner_reimbursed'
    (quota rimborsata scalata da ogni spesa)."""
    if df is None or df.empty or not conf:
        return df
    out = df.copy()
    out['partner_reimbursed'] = 0.0
    reimb_tags = {t.lower() for t in conf.get('reimbursement_tags', DEFAULT_REIMBURSEMENT_TAGS)}
    dates = pd.to_datetime(out['date'])
    tag_lists = out['tags'].apply(_norm_tags)

    is_reimb = (out['type'] == 'Income') & tag_lists.apply(lambda t: bool(reimb_tags & set(t)))
    if not is_reimb.any():
        return out

    is_exp = out['type'] == 'Expense'
    # Peso = quota del partner secondo le regole; spazio = importo della spesa
    # (il rimborso reale può differire dalle regole, ma una spesa non diventa positiva)
    weight = pd.Series(0.0, index=out.index)
    weight[is_exp] = [abs(a) * partner_share(c, t, conf) for a, c, t in
                      zip(out.loc[is_exp, 'amount'], out.loc[is_exp, 'category'], tag_lists[is_exp])]
    room = out['amount'].where(is_exp, 0.0).abs()
    exp_months = dates.dt.to_period('M')
    shared = weight[weight > 0].index

    for ri in sorted(out.index[is_reimb], key=lambda i: dates[i]):
        left = float(out.at[ri, 'amount'])
        # Il rimborso copre le spese condivise del mese PRECEDENTE; solo se quel
        # mese non ne ha si guarda indietro, per ultimo il mese stesso.
        r_month = dates[ri].to_period('M')
        months = [r_month - k for k in range(1, lookback_months + 1)] + [r_month]
        for mo in months:
            ids = [i for i in shared if exp_months[i] == mo and room[i] > 0.005]
            while left > 0.005 and ids:
                w = float(weight[ids].sum())
                given = 0.0
                for i in ids:
                    part = min(room[i], left * weight[i] / w)
                    room[i] -= part
                    out.at[i, 'amount'] += part
                    out.at[i, 'partner_reimbursed'] += part
                    given += part
                left -= given
                ids = [i for i in ids if room[i] > 0.005]
            if left <= 0.005:
                break
        out.at[ri, 'amount'] = left
        if left <= 0.005:
            out.at[ri, 'amount'] = 0.0
            out.at[ri, 'type'] = 'Reimbursement'
    return out
