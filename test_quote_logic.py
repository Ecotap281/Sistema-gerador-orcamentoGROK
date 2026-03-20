"""
/mnt/data/gerador_orcamento_work/Sistema-gerador-orcamentoGROK-main/tests/test_quote_logic.py

Run:
    python -m pip install -r requirements-dev.txt
    pytest -q
"""
from pathlib import Path

from quote_logic import QuoteBuilder


def _builder() -> QuoteBuilder:
    repo_root = Path(__file__).resolve().parents[1]
    return QuoteBuilder(base_dir=repo_root)


def test_numero_orcamento_custom_explicit_line_first():
    text = """numero orcamento :1573
CNPJ 33740915000192
100 tapumes 2,00m
Endereço de entrega: Condominio Algarve Jaú - Av. do Parque, 346 - Jaú
Frete: R$ 200,00
"""
    extracted = _builder().parse_text(text)
    assert extracted["numero_orcamento_custom"] == "1573"
    assert extracted["cliente_doc"] != "não informado"
    assert "33740915000192" in extracted["cliente_doc"].replace(".", "").replace("/", "").replace("-", "")


def test_numero_orcamento_custom_after_cnpj_must_not_capture_cnpj():
    text = """CNPJ 33740915000192
100 tapumes 2,00m
numero orcamento:1596
Endereço de entrega: Condominio Algarve Jaú - Av. do Parque, 346 - Jaú
Frete: R$ 100,00
"""
    extracted = _builder().parse_text(text)
    assert extracted["numero_orcamento_custom"] == "1596"
    assert extracted["numero_orcamento_custom"] != "33740915000192"


def test_cotacao_keyword_line_is_extracted_safely():
    text = """CNPJ 33740915000192
Cotação nº 3339818 (HB transportes)
100 tapumes 2,00m
"""
    extracted = _builder().parse_text(text)
    assert extracted["numero_cotacao"] == "3339818"
