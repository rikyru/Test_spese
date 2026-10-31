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
