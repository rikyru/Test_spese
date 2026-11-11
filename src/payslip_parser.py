"""
Parser delle buste paga in PDF (formato Zucchetti).

Estrae dal testo: periodo, tipo (mensile/tredicesima), netto, totale competenze
e trattenute, contributi INPS, IRPEF (imponibile, lorda, detrazioni, ritenute),
addizionali regionali/comunali, rimborsi 730, paga base e le singole voci
(retribuzione, ferie, straordinari, trasferte, premi...).
"""
import re

MONTHS_IT = {'gennaio': 1, 'febbraio': 2, 'marzo': 3, 'aprile': 4, 'maggio': 5, 'giugno': 6,
             'luglio': 7, 'agosto': 8, 'settembre': 9, 'ottobre': 10, 'novembre': 11, 'dicembre': 12}

# Codici voce (Zucchetti): trasferte esenti, premi, fringe benefit
TRAVEL_CODES = {'000577'}
BONUS_CODES = {'000111'}
BENEFIT_CODES = {'000218'}
ADDIZ_PREFIXES = {'F0911', 'F0912', 'F0913', 'F0914'}

_NUM = r'-?\d{1,3}(?:\.\d{3})*,\d+'
_CODE = re.compile(r'(Z\d{5}|F\d{5}|\d{6})\s?(\S.*)$')
_AMOUNT_END = re.compile(r'(' + _NUM + r')\s*$')


def to_float(s):
    """'1.234,56' -> 1234.56"""
    return float(s.replace('.', '').replace(',', '.'))


def _period(text, filename):
    m = re.search(r'^(' + '|'.join(MONTHS_IT) + r')\s+(20\d\d)\s*$', text, re.I | re.M)
    if m:
        return int(m.group(2)), MONTHS_IT[m.group(1).lower()]
    m = re.search(r'(20\d\d)(\d\d)?', filename or '')
    if m:
        return int(m.group(1)), int(m.group(2) or 12)
    return None, None


def _voci(text):
    """Righe di voce: codice, descrizione, importo. Gli importi tra parentesi sono
    figurativi (es. fringe benefit: tassati ma non pagati): importo None,
    valore in 'figurative'."""
    out = []
    for line in text.splitlines():
        m = _CODE.search(line)
        if not m:
            continue
        code, rest = m.group(1), m.group(2).strip()
        desc = re.split(r'\s+' + _NUM + r'|\s+\(', ' ' + rest, maxsplit=1)[0].strip()
        if not desc or not re.search(r'[A-Za-z]{3}', desc):
            continue
        fig = re.search(r'\(\s*(' + _NUM + r')\s*\)\s*$', rest)
        if fig:
            out.append({'code': code, 'desc': desc, 'amount': None, 'figurative': to_float(fig.group(1))})
            continue
        else:
            a = _AMOUNT_END.search(rest)
            if not a or (a.start() == 0):
                continue
            amount = to_float(a.group(1))
        out.append({'code': code, 'desc': desc, 'amount': amount, 'figurative': None})
    return out


def _first(voci, code):
    for v in voci:
        if v['code'] == code and v['amount'] is not None:
            return v['amount']
    return 0.0


# Elementi della paga base nell'intestazione Zucchetti (riga etichette + riga valori)
_PAY_LABELS = [('MINIMO', 'minimo'), ('SCATTI', 'scatti'), ('PRE.PROD', 'edr'),
               ('Acc. FUT. A.', 'superminimo'), ('SUPERMINIMO', 'superminimo')]


def _pay_elements(text):
    """Minimo contrattuale, scatti, EDR e superminimo (acconto futuri aumenti)."""
    out = {'minimo': 0.0, 'scatti': 0.0, 'edr': 0.0, 'superminimo': 0.0}
    m = re.search(r'^(MINIMO[^\n]*)\n((?:' + _NUM + r'[ \t]*)+)$', text, re.M)
    if not m:
        return out
    header, values = m.group(1), re.findall(_NUM, m.group(2))
    labels = sorted(((header.find(lbl), key) for lbl, key in _PAY_LABELS if lbl in header))
    for (_, key), v in zip(labels, values):
        out[key] = to_float(v)
    return out


def parse_payslip(text, filename=''):
    """Ritorna un dict con i campi principali della busta, o None se il testo
    non sembra una busta paga."""
    if 'NETTO' not in text or 'COMPETENZE' not in text:
        return None
    year, month = _period(text, filename)
    is_13 = bool(re.search(r"13ma Mensilita|13a|tred", text + ' ' + (filename or ''), re.I))
    voci = _voci(text)

    def tot(label):
        m = re.search(label + r'\s+(' + _NUM + ')', text)
        return to_float(m.group(1)) if m else 0.0

    net = re.search(r'NETTO\S*DEL\S*MESE\s*\n\s*(' + _NUM + r')\s*€', text)
    base = re.search(r'PROSSIMO\S*SCATTO\s+TOTALE\s*\n(?:\S+\s+)?(' + _NUM + ')', text)
    # Addizionali regionale/comunale e acconto (F0911x–F0914x). F09100 è invece il
    # conguaglio IRPEF di fine anno (negativo = rimborso): va sommato all'IRPEF.
    addiz = sum(v['amount'] for v in voci if v['code'][:5] in ADDIZ_PREFIXES and v['amount'])
    competenze = tot(r'TOTALE\S*COMPETENZE')
    trattenute = tot(r'TOTALE\S*TRATTENUTE')
    ritenute = _first(voci, 'F03020') + _first(voci, 'F09100')
    rimborso_730 = _first(voci, 'F00880')
    trasferte = sum(v['amount'] or 0 for v in voci if v['code'] in TRAVEL_CODES)
    premi = sum(v['amount'] or 0 for v in voci if v['code'] in BONUS_CODES)
    inps = _first(voci, 'Z00000')
    if not inps and trattenute:
        # Riga INPS non leggibile: per differenza dalle altre trattenute
        inps = round(max(trattenute - ritenute - addiz, 0.0), 2)
    imponibile = _first(voci, 'F02000') or _first(voci, 'F06000')
    benefit = sum(v['figurative'] or 0 for v in voci if v['code'] in BENEFIT_CODES)
    # Imponibile in più rispetto ai soldi tassabili ricevuti = benefit tassati
    # (fringe benefit, conguagli): fanno pagare tasse senza aumentare il netto.
    taxed_benefit = 0.0
    if imponibile and not is_13:
        taxed_benefit = round(max(imponibile + inps - (competenze - trasferte - rimborso_730), 0.0), 2)
        if taxed_benefit < 5:   # arrotondamenti
            taxed_benefit = 0.0
    netto = to_float(net.group(1)) if net else 0.0
    level = re.search(r'Livello\s+([A-Z]\d|\d+S?)\b', text)
    next_step = re.search(r'PROSSIMO\S*SCATTO\s+TOTALE\s*\n(\d{1,2})-(20\d\d)', text)
    if not netto and not competenze:
        return None   # PDF senza importi leggibili (es. scansione)
    return {
        'year': year, 'month': month,
        'kind': 'tredicesima' if is_13 else 'mensile',
        'netto': netto,
        'competenze': competenze,
        'trattenute': trattenute,
        'paga_base': to_float(base.group(1)) if base else 0.0,
        'inps': inps,
        'imponibile_irpef': imponibile,
        'irpef_lorda': _first(voci, 'F02010'),
        'detrazioni': _first(voci, 'F02500'),
        'ritenute_irpef': ritenute,
        'addizionali': round(addiz, 2),
        'rimborso_730': rimborso_730,
        'trasferte': round(trasferte, 2),
        'premi': round(premi, 2),
        'benefit': round(benefit, 2),
        'benefit_tassati': taxed_benefit,
        **_pay_elements(text),
        'livello': level.group(1) if level else None,
        'prossimo_scatto': f"{next_step.group(2)}-{int(next_step.group(1)):02d}" if next_step else None,
        'voci': voci,
    }


def parse_pdf(path_or_file, filename=''):
    import pdfplumber
    with pdfplumber.open(path_or_file) as pdf:
        text = '\n'.join(p.extract_text() or '' for p in pdf.pages)
    return parse_payslip(text, filename or str(path_or_file))
