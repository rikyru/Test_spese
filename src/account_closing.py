"""
Chiusura conti mensile: confronta i saldi reali con quelli dell'app e li allinea.

La differenza TOTALE (reale − app) è denaro non registrato: diventa una spesa
"Non registrate" (o un'entrata, es. interessi) sul conto principale — oppure un
aggiustamento neutro alla prima chiusura. Lo spostamento TRA conti (passaggi
interni non registrati) diventa trasferimenti dal/al conto principale, neutri
per le analisi. Lo storico non viene modificato: si aggiungono solo movimenti
con la data della chiusura.
"""
UNTRACKED_CATEGORY = 'Non registrate'
CLOSING_DESC = 'Chiusura conti'

DEFAULT_GROUPS = {
    'Conto BNL': ['Conto MPS'],
    'Portafoglio - (Unicredit e Revolut)': ['Unicredit', 'Revolut corrente', 'Satispay', 'Contanti'],
    'Risparmi Revolut': ['Revolut salvadanaio', 'Revolut investito'],
}


def closing_config(rules):
    cfg = rules.get('closing_accounts') or {}
    groups = cfg.get('groups') or DEFAULT_GROUPS
    return {'groups': groups, 'main': cfg.get('main')}


def plan_closing(app_bal, real_bal, main, first=False, tol=0.01):
    """Operazioni per portare ogni conto al saldo reale.
    app_bal/real_bal: conto → saldo. Ritorna lista di dict:
      {'kind': 'untracked'|'adjustment', 'account', 'amount'}  (amount con segno)
      {'kind': 'transfer', 'from', 'to', 'amount'}             (amount > 0)"""
    ops = []
    accounts = list(real_bal)
    gap = round(sum(real_bal[a] for a in accounts) - sum(app_bal.get(a, 0.0) for a in accounts), 2)
    after = {a: app_bal.get(a, 0.0) for a in accounts}
    if abs(gap) >= tol:
        ops.append({'kind': 'adjustment' if first else 'untracked', 'account': main, 'amount': gap})
        after[main] = after.get(main, 0.0) + gap
    for a in accounts:
        if a == main:
            continue
        d = round(real_bal[a] - after[a], 2)
        if abs(d) < tol:
            continue
        if d > 0:
            ops.append({'kind': 'transfer', 'from': main, 'to': a, 'amount': d})
        else:
            ops.append({'kind': 'transfer', 'from': a, 'to': main, 'amount': -d})
    return ops


def apply_closing(dm, ops, date):
    """Registra le operazioni pianificate (solo inserimenti datati `date`)."""
    for op in ops:
        if op['kind'] == 'transfer':
            dm.add_transfer(op['from'], op['to'], op['amount'], date,
                            description=f"{CLOSING_DESC}: riallineamento {op['from']} → {op['to']}",
                            tag='chiusura', source='closing')
            continue
        amt = op['amount']
        if op['kind'] == 'adjustment':
            typ, cat, nec, desc = 'Adjustment', 'Adjustment', None, f"{CLOSING_DESC}: allineamento iniziale"
        elif amt < 0:
            typ, cat, nec, desc = 'Expense', UNTRACKED_CATEGORY, 'Want', f"{CLOSING_DESC}: spese non registrate"
        else:
            typ, cat, nec, desc = 'Income', UNTRACKED_CATEGORY, None, f"{CLOSING_DESC}: entrate non registrate (es. interessi)"
        dm.con.execute("""
            INSERT INTO transactions (id, date, amount, currency, account, category, tags, description,
                                      type, source_file, original_description, necessity)
            VALUES (uuid(), ?, ?, 'EUR', ?, ?, ['chiusura'], ?, ?, 'closing', ?, ?)
        """, [date, amt, op['account'], cat, desc, typ, desc, nec])
