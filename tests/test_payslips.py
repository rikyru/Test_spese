"""Test del parser buste paga (testo sintetico in formato Zucchetti) e della
scomposizione delle differenze di netto."""
import pytest
from src.payslip_parser import parse_payslip, to_float
from src.ui.payslips import explain_change, netto_base, payslip_alerts
from tests.test_data_manager import dm  # noqa: F401

SAMPLE = """VOCIsVARIABILIsDELsMESE RIFERIMENTO TRATTENUTE COMPETENZE
Agosto 2026
MINIMO SCATTI PRE.PROD Acc. FUT. A.
PROSSIMOSCATTO TOTALE
3-2027 3.000,00000
TE* * Z00001Retribuzione 17,00000 160,00000ORE 2.900,00
U* * 000111 Premio 50,00
D 000218 FRINGE BENEFIT AUTO ( 150,00)
IR 000577 TRASFERTA ITALIA 30,00000 5,00000GG 150,00
w* Z00000Contributo IVS 3.250,00 9,19000% 298,68
ste F02000Imponibile IRPEF 2.951,32
n re F02010IRPEF lorda 740,00
tn Iso F02500Detrazioni lav.dip. 80,00
zz F03020Ritenute IRPEF 660,00
F09110Addizionale regionale 2025 PIEMONTE Residuo 196,00 65,00
F09130Addizionale comunale 2025 TORINO Residuo 60,00 20,00
RATEI TOTALEsCOMPETENZE 3.100,00
Ferie 160,00000 220,00000 -60,00000 ORE TOTALEsTRATTENUTE 1.043,68
NETTOsDELsMESE
2.056,00€
"""


def test_to_float():
    assert to_float('1.234,56') == 1234.56


def test_parse_sample():
    r = parse_payslip(SAMPLE, '202608_x.pdf')
    assert (r['year'], r['month'], r['kind']) == (2026, 8, 'mensile')
    assert r['netto'] == 2056.0
    assert r['competenze'] == 3100.0 and r['trattenute'] == 1043.68
    assert r['paga_base'] == 3000.0
    assert r['inps'] == 298.68 and r['ritenute_irpef'] == 660.0
    assert r['addizionali'] == 85.0
    assert r['trasferte'] == 150.0 and r['premi'] == 50.0
    assert r['benefit'] == 150.0
    # imponibile 2951.32 + inps 298.68 = 3250 vs competenze tassabili 3100-150 = 2950
    assert r['benefit_tassati'] == pytest.approx(300.0)


def test_inps_fallback_and_13th():
    text = SAMPLE.replace("w* Z00000Contributo IVS 3.250,00 9,19000% 298,68\n", "")
    r = parse_payslip(text, '202608tred_x.pdf')
    assert r['inps'] == pytest.approx(1043.68 - 660.0 - 85.0)
    assert r['kind'] == 'tredicesima' and r['benefit_tassati'] == 0.0


def test_not_a_payslip():
    assert parse_payslip("fattura qualsiasi", "x.pdf") is None
    assert parse_payslip("NETTO COMPETENZE senza numeri", "x.pdf") is None


def _slip(**kw):
    base = dict(netto=2000.0, competenze=3000.0, trasferte=100.0, premi=0.0, rimborso_730=0.0,
                ritenute_irpef=600.0, inps=280.0, addizionali=86.0, paga_base=3000.0,
                detrazioni=100.0, benefit=0.0, benefit_tassati=0.0)
    base.update(kw)
    return base


def test_explain_change_adds_up():
    a = _slip()
    b = _slip(netto=1900.0, competenze=3050.0, trasferte=150.0, ritenute_irpef=660.0, inps=300.0,
              addizionali=96.0, benefit_tassati=150.0, detrazioni=80.0)
    items = dict(explain_change(a, b))
    assert sum(items.values()) == pytest.approx(b['netto'] - a['netto'])
    assert items['IRPEF'] == -60.0 and items['Trasferte'] == 50.0
    notes = ' '.join(payslip_alerts(a, b))
    assert 'Benefit tassati' in notes and 'Detrazioni' in notes and 'Addizionali' in notes


def test_netto_base():
    assert netto_base(_slip(trasferte=150.0, premi=50.0, rimborso_730=1000.0, netto=3200.0)) == 2000.0


def test_save_and_replace(dm):
    r = parse_payslip(SAMPLE, '202608_x.pdf')
    key = dm.save_payslip(r, '202608_x.pdf')
    assert key == '2026-08-mensile'
    r['netto'] = 2100.0
    dm.save_payslip(r, '202608_x.pdf')
    df = dm.get_payslips()
    assert len(df) == 1 and df.iloc[0]['netto'] == 2100.0
    dm.delete_payslip(key)
    assert dm.get_payslips().empty


def test_year_end_irpef_refund_is_not_addizionale():
    text = SAMPLE.replace("RATEI TOTALEsCOMPETENZE", "F09100IRPEF netta Cong. -100,15\nRATEI TOTALEsCOMPETENZE")
    r = parse_payslip(text, '202612_x.pdf')
    assert r['addizionali'] == 85.0
    assert r['ritenute_irpef'] == pytest.approx(660.0 - 100.15)


# --- Composizione paga e valutazioni ---
import pandas as pd
from src.payslip_parser import _pay_elements
from src.salary_insights import pay_events, projection, package_value, merged_config, ral


def test_pay_elements_header_variants():
    t1 = "MINIMO SCATTI PRE.PROD Acc. FUT. A.\n2.211,43000 59,28000 3,96000 829,98000\n"
    assert _pay_elements(t1) == {'minimo': 2211.43, 'scatti': 59.28, 'edr': 3.96, 'superminimo': 829.98}
    t2 = "MINIMO PRE.PROD Acc. FUT. A.\n1.819,64000 3,96000 330,45000\n"
    assert _pay_elements(t2) == {'minimo': 1819.64, 'scatti': 0.0, 'edr': 3.96, 'superminimo': 330.45}


def _months(rows):
    return pd.DataFrame(rows, columns=['year', 'month', 'minimo', 'scatti', 'superminimo', 'paga_base'])


def test_pay_events_detects_absorption_raise_and_step():
    m = _months([
        (2025, 3, 2130.56, 29.64, 511.02, 0), (2025, 4, 2130.56, 59.28, 511.02, 0),   # scatto
        (2025, 5, 2130.56, 59.28, 883.15, 0),                                           # personale
        (2025, 6, 2158.26, 59.28, 883.15, 0),                                           # contratto pieno
        (2026, 6, 2211.43, 59.28, 829.98, 0),                                           # assorbito
    ])
    ev = pay_events(m)
    kinds = list(zip(ev['periodo'], ev['tipo'], ev['importo']))
    assert ('2025-04', 'scatto', 29.64) in kinds
    assert ('2025-05', 'personale', 372.13) in kinds
    assert ('2025-06', 'contratto', 27.7) in kinds
    assert ('2026-06', 'contratto', 53.17) in kinds and ('2026-06', 'assorbito', -53.17) in kinds
    assert not ((ev['periodo'] == '2026-06') & (ev['tipo'] == 'riduzione')).any()


def test_projection_absorbs_until_superminimo_runs_out():
    ev = pd.DataFrame([{'periodo': '2025-03', 'tipo': 'scatto', 'importo': 29.64, 'nota': ''}])
    last = {'minimo': 2211.43, 'superminimo': 100.0, 'livello': 'C3', 'prossimo_scatto': '2027-03'}
    cfg = merged_config({'future_minimi': {'C3': {'2027-06': 2271.01, '2028-06': 2335.88}}})
    proj, left = projection(last, ev, cfg, today='2026-11-01')
    assert [p['periodo'] for p in proj] == ['2027-03', '2027-06', '2028-06']
    assert proj[0]['in_busta'] == 29.64 and not proj[0]['assorbibile']
    assert proj[1]['in_busta'] == 0.0                       # 59.58 assorbiti (100 disponibili)
    assert proj[2]['in_busta'] == pytest.approx(64.87 - 40.42)
    assert left == pytest.approx(0.0)


def test_package_value_and_ral():
    assert ral(3104.65, 13) == pytest.approx(40360.45)
    cfg = merged_config({'car_value_month': 500, 'welfare_year': 250, 'marginal_rate': 46})
    pk = package_value(40000, 2000, cfg, car_tax_year=800)
    assert pk['auto_netto'] == 5200 and pk['benefit_netti'] == 7450
    assert pk['ral_equivalente'] == pytest.approx(40000 + 7450 / 0.54)


def test_ral_by_year_nominal_and_real():
    from src.salary_insights import ral_by_year
    comp = pd.DataFrame({'year': [2021, 2022, 2022, 2023], 'month': [12, 6, 12, 12],
                         'paga_base': [2000.0, 2000.0, 2100.0, 2310.0]})
    ry = ral_by_year(comp, 13, {2022: 5.0, 2023: 10.0})
    assert list(ry['ral']) == [26000.0, 27300.0, 30030.0]
    assert ry.loc[2022, 'crescita'] == pytest.approx(5.0)
    assert ry.loc[2022, 'crescita_reale'] == pytest.approx(0.0)
    assert ry.loc[2023, 'ral_reale'] == pytest.approx(30030 / (1.05 * 1.10))


def test_package_by_year_includes_car_from_assignment():
    from src.salary_insights import ral_by_year, package_by_year
    monthly = pd.DataFrame({'year': [2024] * 12 + [2025] * 12, 'month': list(range(1, 13)) * 2,
                            'paga_base': [2000.0] * 24, 'trasferte': [100.0] * 24,
                            'benefit': [0.0] * 20 + [150.0] * 4})
    ry = ral_by_year(monthly, 13)
    cfg = merged_config({'car_value_month': 500, 'car_start': '2025-09', 'marginal_rate': 50})
    pk = package_by_year(monthly, ry, cfg)
    assert pk.loc[2024, 'auto_netto'] == 0
    assert pk.loc[2024, 'pacchetto'] == pytest.approx(26000 + 1200 / 0.5)
    # 150*12 = 1800 > soglia 1000 → tassato al 50%: 6000 - 900
    assert pk.loc[2025, 'auto_netto'] == pytest.approx(5100)
    assert pk.loc[2025, 'pacchetto'] == pytest.approx(26000 + (5100 + 1200) / 0.5)
