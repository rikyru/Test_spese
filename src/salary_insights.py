"""
Valutazioni sullo stipendio ricavate dalle buste paga: RAL, storia degli aumenti
(contrattuali, personali, scatti, assorbimenti nel superminimo), proiezione dei
prossimi aumenti e confronto con il mercato / valore del pacchetto.
"""
import pandas as pd

# Valori di default modificabili dalla pagina (salvati in rules.yaml → payslip_config).
# Fasce di mercato: embedded software Italia 2026 (EgoValeo); minimi futuri: CCNL
# Metalmeccanica Industria 2025-2028, livello C3. Da aggiornare a ogni rinnovo.
DEFAULT_CONFIG = {
    'mensilita': 13,
    'marginal_rate': 46,          # % di tasse+contributi su ogni euro lordo in più
    'car_value_month': 0,         # valore di mercato mensile dell'auto aziendale (uso personale)
    'car_tax_month': 0,           # costo fiscale mensile dell'auto (calcolato dalle buste se 0)
    'welfare_year': 0,
    'benchmark_label': 'Embedded software, Italia 2026 (EgoValeo)',
    'benchmarks': {'Junior': 32500, 'Middle': 40000, 'Senior': 47500, 'Senior (75° pct)': 52500},
    'future_minimi': {'C3': {'2027-06': 2271.01, '2028-06': 2335.88}},
    # Inflazione media annua ISTAT NIC (%); l'anno in corso è una stima
    'inflation': {2022: 8.1, 2023: 5.7, 2024: 1.0, 2025: 1.5, 2026: 1.5},
}


def merged_config(saved):
    cfg = {k: (v.copy() if isinstance(v, dict) else v) for k, v in DEFAULT_CONFIG.items()}
    for k, v in (saved or {}).items():
        cfg[k] = v
    return cfg


def ral(paga_base, mensilita=13):
    return float(paga_base or 0) * int(mensilita)


def ral_by_year(comp, mensilita=13, inflation=None):
    """RAL a fine anno (paga base dell'ultima busta dell'anno × mensilità), con
    crescita nominale, inflazione e crescita reale anno su anno, più la RAL
    espressa in euro del primo anno (potere d'acquisto)."""
    inflation = {int(k): float(v) for k, v in (inflation or {}).items()}
    last = (comp[comp['paga_base'].fillna(0) > 0].sort_values(['year', 'month'])
            .groupby('year').tail(1).set_index('year'))
    out = pd.DataFrame({'paga_base': last['paga_base'],
                        'ral': last['paga_base'] * int(mensilita)})
    out['crescita'] = out['ral'].pct_change() * 100
    out['inflazione'] = [inflation.get(int(y)) for y in out.index]
    out.loc[out.index[0], 'inflazione'] = None
    out['crescita_reale'] = ((1 + out['crescita'] / 100) / (1 + out['inflazione'] / 100) - 1) * 100
    deflator = (1 + out['inflazione'].fillna(0) / 100).cumprod()
    out['ral_reale'] = out['ral'] / deflator
    return out


def pay_events(monthly):
    """Eventi sulla paga base tra buste consecutive (DataFrame ordinato con
    year, month, minimo, scatti, superminimo, paga_base). Tipi: 'contratto'
    (aumento del minimo), 'assorbito' (parte dell'aumento contrattuale tolta dal
    superminimo), 'personale' (superminimo aumentato), 'riduzione', 'scatto'."""
    ev = []
    rows = monthly[(monthly['minimo'].fillna(0) > 0)].sort_values(['year', 'month'])
    prev = None
    for _, r in rows.iterrows():
        if prev is not None:
            per = f"{int(r['year'])}-{int(r['month']):02d}"
            d_min = r['minimo'] - prev['minimo']
            d_sup = (r['superminimo'] or 0) - (prev['superminimo'] or 0)
            d_sca = (r['scatti'] or 0) - (prev['scatti'] or 0)
            if d_min > 0.5:
                ev.append({'periodo': per, 'tipo': 'contratto', 'importo': round(d_min, 2),
                           'nota': f"Minimo contrattuale €{prev['minimo']:,.2f} → €{r['minimo']:,.2f}"})
                if d_sup < -0.5:
                    absorbed = min(-d_sup, d_min)
                    ev.append({'periodo': per, 'tipo': 'assorbito', 'importo': round(-absorbed, 2),
                               'nota': f"Superminimo €{prev['superminimo']:,.2f} → €{r['superminimo']:,.2f}: "
                                       "l'aumento del contratto non arriva in busta"})
                    d_sup += absorbed
            if d_sup > 0.5:
                ev.append({'periodo': per, 'tipo': 'personale', 'importo': round(d_sup, 2),
                           'nota': f"Superminimo €{prev['superminimo']:,.2f} → €{r['superminimo']:,.2f}"})
            elif d_sup < -0.5:
                ev.append({'periodo': per, 'tipo': 'riduzione', 'importo': round(d_sup, 2),
                           'nota': "Superminimo ridotto senza aumento del minimo"})
            if d_sca > 0.5:
                ev.append({'periodo': per, 'tipo': 'scatto', 'importo': round(d_sca, 2),
                           'nota': f"Scatti di anzianità €{prev['scatti']:,.2f} → €{r['scatti']:,.2f}"})
        prev = r
    return pd.DataFrame(ev, columns=['periodo', 'tipo', 'importo', 'nota'])


def step_amount(events):
    """Valore dell'ultimo scatto di anzianità (0 se mai visto)."""
    sc = events[events['tipo'] == 'scatto'] if not events.empty else events
    return float(sc['importo'].iloc[-1]) if len(sc) else 0.0


def projection(last, events, cfg, today=None):
    """Prossimi aumenti attesi dalla busta più recente: scatto (non assorbibile) e
    minimi contrattuali futuri per il livello (assorbibili nel superminimo).
    Ritorna (lista eventi, superminimo residuo)."""
    today = pd.Timestamp(today or pd.Timestamp.today())
    out = []
    step = step_amount(events)
    if last.get('prossimo_scatto') and step > 0:
        out.append({'periodo': last['prossimo_scatto'], 'tipo': 'scatto', 'lordo_mese': step,
                    'assorbibile': False, 'in_busta': step})
    sup = float(last.get('superminimo') or 0)
    cur_min = float(last.get('minimo') or 0)
    for per, new_min in sorted((cfg.get('future_minimi', {}).get(last.get('livello') or '', {}) or {}).items()):
        if pd.Period(per, freq='M').end_time < today or new_min <= cur_min:
            continue
        inc = new_min - cur_min
        absorbed = min(inc, sup)
        sup -= absorbed
        out.append({'periodo': per, 'tipo': 'contratto', 'lordo_mese': round(inc, 2),
                    'assorbibile': True, 'in_busta': round(inc - absorbed, 2)})
        cur_min = new_min
    return sorted(out, key=lambda x: x['periodo']), sup


def package_value(ral_value, trasferte_year, cfg, car_tax_year=0.0):
    """RAL equivalente del pacchetto: i benefit netti (auto al netto del suo costo
    fiscale, trasferte esenti, welfare) convertiti in lordo con l'aliquota marginale."""
    keep = 1 - cfg['marginal_rate'] / 100.0
    car_net = max(cfg['car_value_month'] * 12 - car_tax_year, 0.0)
    benefits_net = car_net + trasferte_year + cfg['welfare_year']
    return {
        'auto_netto': car_net,
        'trasferte': trasferte_year,
        'welfare': cfg['welfare_year'],
        'benefit_netti': benefits_net,
        'ral_equivalente': ral_value + (benefits_net / keep if keep > 0 else 0.0),
    }
