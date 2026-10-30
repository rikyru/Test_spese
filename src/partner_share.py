"""
Vista "Mia quota": spese condivise ridotte alla tua parte STIMATA con le regole
di Spese Condivise, applicate allo stesso modo su tutto lo storico (nessun salto
tra periodi). Non usa i rimborsi effettivi: vale solo per le viste di spesa,
non per entrate, risparmio o saldi.
"""
import pandas as pd

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


def my_share_view(df, conf):
    """Copia di `df` con ogni spesa ridotta alla tua quota stimata."""
    if df is None or df.empty or not conf:
        return df
    out = df.copy()
    is_exp = out['type'] == 'Expense'
    factors = [1.0 - partner_share(c, t, conf)
               for c, t in zip(out.loc[is_exp, 'category'], out.loc[is_exp, 'tags'])]
    out.loc[is_exp, 'amount'] = out.loc[is_exp, 'amount'] * pd.Series(factors, index=out.index[is_exp])
    return out
