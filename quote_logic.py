import fcntl
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests
from weasyprint import HTML
from werkzeug.exceptions import NotFound

logger = logging.getLogger(__name__)

BR_TZ = ZoneInfo(os.getenv("APP_TIMEZONE", "America/Sao_Paulo"))
CNPJ_TIMEOUT_SECONDS = float(os.getenv("CNPJ_TIMEOUT_SECONDS", "4"))
MAX_CNPJ_LOOKUPS = max(1, int(os.getenv("MAX_CNPJ_LOOKUPS", "2")))

PRODUCT_TABLE = {
    "Tapume 0,55x2,00m": {"valor": Decimal("20.40"), "peso": Decimal("7.3"), "volume": Decimal("0.012")},
    "Tapume 0,80x2,00m": {"valor": Decimal("27.90"), "peso": Decimal("10.6"), "volume": Decimal("0.017")},
    "Tapume 1,00x2,00m": {"valor": Decimal("31.50"), "peso": Decimal("12.6"), "volume": Decimal("0.020")},
    "Tapume 1,20x2,00m": {"valor": Decimal("36.50"), "peso": Decimal("15.0"), "volume": Decimal("0.024")},
    "Telha 2,44x0,50m": {"valor": Decimal("18.40"), "peso": Decimal("7.6"), "volume": Decimal("0.010")},
}

CNPJ_ENDPOINTS = [
    "https://publica.cnpj.ws/cnpj/{cnpj}",
    "https://www.receitaws.com.br/v1/cnpj/{cnpj}",
    "https://brasilapi.com.br/api/cnpj/v1/{cnpj}",
]

ADDRESS_KEYWORDS = (
    "rua",
    "avenida",
    "av.",
    "travessa",
    "rodovia",
    "estrada",
    "alameda",
    "bairro",
    "cep",
    "quadra",
    "lote",
    "nº",
    "numero",
    "número",
)

ALLOWED_OUTPUT_EXTENSIONS = {".pdf", ".html"}
OUTPUT_FILENAME_RE = re.compile(r"^orcamento_\d+\.(pdf|html)$", re.IGNORECASE)


class QuoteValidationError(ValueError):
    """Erro de validação de entrada do orçamento."""


def q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def d(value: Any, default: str = "0") -> Decimal:
    if isinstance(value, Decimal):
        return q2(value)
    if value in (None, ""):
        return q2(Decimal(default))
    try:
        s = str(value).strip().replace("R$", "").replace(".", "").replace(",", ".")
        return q2(Decimal(s))
    except (InvalidOperation, ValueError, TypeError):
        raise QuoteValidationError(f"valor monetário inválido: {value!r}")


def digits_only(value: str) -> str:
    return re.sub(r"\D", "", str(value or ""))


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def sanitize_html(value: str) -> str:
    return escape(str(value or ""), quote=True)


def format_cnpj(value: str) -> str:
    digits = digits_only(value)
    if len(digits) != 14:
        return normalize_spaces(value)
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"


def format_cpf(value: str) -> str:
    digits = digits_only(value)
    if len(digits) != 11:
        return normalize_spaces(value)
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"


def format_doc(value: str) -> str:
    digits = digits_only(value)
    if len(digits) == 14:
        return format_cnpj(digits)
    if len(digits) == 11:
        return format_cpf(digits)
    return normalize_spaces(value) or "não informado"


def format_cep(value: str) -> str:
    digits = digits_only(value)
    if len(digits) != 8:
        return normalize_spaces(value)
    return f"{digits[:5]}-{digits[5:]}"


def money(value: Decimal) -> str:
    val = q2(value)
    integer, fraction = f"{val:.2f}".split(".")
    integer = f"{int(integer):,}".replace(",", ".")
    return f"R$ {integer},{fraction}"


def fmt_decimal(value: Decimal, precision: int) -> str:
    fmt = f"{{0:.{precision}f}}"
    return fmt.format(value).replace(".", ",")


def br_date(value: datetime) -> str:
    return value.strftime("%d/%m/%Y")


def now_br() -> datetime:
    return datetime.now(BR_TZ)


def first_meaningful(*values: Any) -> str:
    for value in values:
        normalized = normalize_spaces(value)
        if normalized and normalized.lower() != "não informado":
            return normalized
    return ""


def preprocess_text(text: str) -> List[str]:
    raw_lines = re.split(r"[\r\n]+", str(text or ""))
    lines: List[str] = []
    for line in raw_lines:
        cleaned = normalize_spaces(line)
        if cleaned:
            lines.append(cleaned)
    return lines


def extract_cnpj(text: str) -> str:
    found, _ = extract_document_from_text(text)
    return found or "não informado"


def normalize_product(product: str, medida: str) -> str:
    normalized_measure = str(medida).replace(".", ",")
    normalized_product = str(product or "").strip().lower()
    if "tapume" in normalized_product:
        return f"Tapume 0,55x{normalized_measure}m" if normalized_measure == "2,00" else f"Tapume {normalized_measure}x2,00m"
    if "telha" in normalized_product:
        return f"Telha 2,44x{normalized_measure}m" if normalized_measure != "2,44" else "Telha 2,44x0,50m"
    return normalize_spaces(product)


def join_address(parts: List[str]) -> str:
    filtered = [normalize_spaces(part) for part in parts if normalize_spaces(part)]
    return ", ".join(filtered) if filtered else "não informado"


def strip_known_label(text: str) -> str:
    t = normalize_spaces(text)
    patterns = [
        r"^(nome)\s*:?\s*",
        r"^(cliente)\s*:?\s*",
        r"^(cpf\/cnpj)\s*:?\s*",
        r"^(cpf)\s*:?\s*",
        r"^(cnpj)\s*:?\s*",
        r"^(endereço de entrega)\s*:?\s*",
        r"^(endereco de entrega)\s*:?\s*",
        r"^(endereço entrega)\s*:?\s*",
        r"^(endereco entrega)\s*:?\s*",
        r"^(endereço)\s*:?\s*",
        r"^(endereco)\s*:?\s*",
        r"^(frete)\s*:?\s*",
        r"^(valor negociado)\s*:?\s*",
        r"^(número da cotação)\s*:?\s*",
        r"^(numero da cotação)\s*:?\s*",
        r"^(numero da cotacao)\s*:?\s*",
        r"^(cotação)\s*:?\s*",
        r"^(cotacao)\s*:?\s*",
        r"^(prazo de entrega)\s*:?\s*",
        r"^(observações)\s*:?\s*",
        r"^(observacoes)\s*:?\s*",
    ]
    for pattern in patterns:
        t = re.sub(pattern, "", t, flags=re.IGNORECASE).strip()
    return t


def extract_document_from_text(text: str) -> Tuple[Optional[str], str]:
    original = normalize_spaces(text)
    patterns = [
        (r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b", "cnpj"),
        (r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b", "cpf"),
        (r"(?<!\d)\d{14}(?!\d)", "cnpj"),
        (r"(?<!\d)\d{11}(?!\d)", "cpf"),
    ]
    for pattern, kind in patterns:
        match = re.search(pattern, original)
        if match:
            raw_doc = match.group(0)
            doc = format_cnpj(raw_doc) if kind == "cnpj" else format_cpf(raw_doc)
            cleaned = normalize_spaces((original[:match.start()] + " " + original[match.end():]).strip(" -,"))
            return doc, cleaned

    stripped = strip_known_label(original)
    compact = digits_only(stripped)
    if len(compact) == 14 and compact:
        return format_cnpj(compact), ""
    if len(compact) == 11 and compact:
        return format_cpf(compact), ""
    return None, original


def looks_like_address(text: str) -> bool:
    candidate = (text or "").lower()
    return any(keyword in candidate for keyword in ADDRESS_KEYWORDS) or bool(re.search(r"\b\d{5}-?\d{3}\b", candidate))


def looks_like_product_line(text: str) -> bool:
    candidate = (text or "").lower()
    return bool(re.search(r"\b\d+\s+(tapume|tapumes|telha|telhas)\b", candidate))


def extract_money_after_label(line: str) -> Optional[Decimal]:
    candidate = normalize_spaces(line)
    match = re.search(r"r\$\s*([\d\.,]+)", candidate, flags=re.IGNORECASE)
    if match:
        return d(match.group(1))
    match = re.search(r"(?<!\d)(\d+[\.,]\d{2})(?!\d)", candidate)
    if match:
        return d(match.group(1))
    return None


def extract_label_value(line: str, labels: List[str]) -> Optional[str]:
    candidate = normalize_spaces(line)
    for label in labels:
        match = re.search(rf"^{label}\s*:?\s*(.+)$", candidate, flags=re.IGNORECASE)
        if match:
            return normalize_spaces(match.group(1))
    return None


def classify_customer_line(text: str) -> Dict[str, str]:
    raw = normalize_spaces(text)
    lower = raw.lower()

    if re.match(r"^(cnpj|cpf|cpf/cnpj)\b", lower):
        found_doc, _ = extract_document_from_text(raw)
        return {"cliente_doc": found_doc} if found_doc else {}

    no_label = strip_known_label(raw)
    found_doc, remainder = extract_document_from_text(no_label)
    result: Dict[str, str] = {}
    if found_doc:
        result["cliente_doc"] = found_doc

    remainder = remainder.strip(" -,")
    if not remainder:
        return result
    if looks_like_address(remainder) or looks_like_product_line(remainder):
        return result
    remainder = re.sub(r"\s*-\s*(cpf|cnpj)\b.*$", "", remainder, flags=re.IGNORECASE).strip()
    if digits_only(remainder) == remainder.replace(" ", ""):
        return result
    result["cliente_nome"] = normalize_spaces(remainder)
    return result


@dataclass
class CounterState:
    current: int
    next_value: int


class QuoteBuilder:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.generated_dir = self.base_dir / "generated"
        self.data_dir = self.base_dir / "data"
        self.counter_file = Path(os.getenv("COUNTER_FILE", self.data_dir / "last_number.txt"))
        self.initial_number = int(os.getenv("INITIAL_QUOTE_NUMBER", "1500"))
        self.generated_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _safe_parse_counter(self, raw_value: str) -> int:
        cleaned = normalize_spaces(raw_value)
        if not cleaned:
            return self.initial_number
        try:
            value = int(cleaned)
        except ValueError:
            logger.warning("Counter file corrompido, resetando para valor inicial: %r", raw_value)
            return self.initial_number
        if value < self.initial_number:
            return self.initial_number
        return value

    def next_number(self) -> int:
        self.counter_file.parent.mkdir(parents=True, exist_ok=True)
        initial_payload = f"{self.initial_number}".encode("utf-8")
        with open(self.counter_file, "a+b") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            fh.seek(0)
            raw = fh.read()
            if not raw:
                fh.seek(0)
                fh.write(initial_payload)
                fh.flush()
                fh.seek(0)
                raw = fh.read()

            current = self._safe_parse_counter(raw.decode("utf-8", errors="replace"))
            next_value = current + 1

            fh.seek(0)
            fh.truncate()
            fh.write(str(next_value).encode("utf-8"))
            fh.flush()
            os.fsync(fh.fileno())
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

        return next_value

    def fetch_cnpj_data(self, cnpj: str) -> Dict[str, str]:
        digits = digits_only(cnpj)
        if len(digits) != 14:
            return {}

        headers = {"User-Agent": "Mozilla/5.0"}
        endpoints = CNPJ_ENDPOINTS[:MAX_CNPJ_LOOKUPS]

        for url in endpoints:
            try:
                response = requests.get(url.format(cnpj=digits), headers=headers, timeout=CNPJ_TIMEOUT_SECONDS)
                if response.status_code != 200:
                    logger.warning("Consulta de CNPJ falhou em %s com status %s", url, response.status_code)
                    continue
                normalized = self.normalize_cnpj_payload(response.json())
                if normalized.get("nome") or normalized.get("endereco"):
                    return normalized
            except requests.RequestException as exc:
                logger.warning("Erro de rede na consulta de CNPJ em %s: %s", url, exc)
            except ValueError as exc:
                logger.warning("Resposta inválida ao consultar CNPJ em %s: %s", url, exc)

        return {}

    def normalize_cnpj_payload(self, data: Dict[str, Any]) -> Dict[str, str]:
        if not isinstance(data, dict):
            return {}

        company = data.get("company", {}) if isinstance(data.get("company"), dict) else {}
        estabelecimento = data.get("estabelecimento", {}) if isinstance(data.get("estabelecimento"), dict) else {}
        endereco_data = estabelecimento or data

        nome = (
            data.get("razao_social")
            or data.get("nome")
            or data.get("nome_fantasia")
            or company.get("name")
            or estabelecimento.get("razao_social")
            or estabelecimento.get("nome_fantasia")
            or ""
        )
        nome = normalize_spaces(str(nome))
        nome = re.sub(r"^\d+\s+", "", nome)

        tipo_logradouro = endereco_data.get("tipo_logradouro") or endereco_data.get("descricao_tipo_de_logradouro") or ""
        logradouro_base = endereco_data.get("logradouro") or endereco_data.get("street") or ""
        logradouro = normalize_spaces(f"{tipo_logradouro} {logradouro_base}".strip()) or normalize_spaces(logradouro_base)
        numero = normalize_spaces(endereco_data.get("numero") or endereco_data.get("number") or "")
        complemento = normalize_spaces(endereco_data.get("complemento") or endereco_data.get("details") or "")
        bairro = normalize_spaces(endereco_data.get("bairro") or endereco_data.get("district") or "")
        municipio = normalize_spaces(
            endereco_data.get("cidade")
            or endereco_data.get("municipio")
            or endereco_data.get("city")
            or endereco_data.get("cidade_exterior")
            or ""
        )
        uf = normalize_spaces(endereco_data.get("estado") or endereco_data.get("uf") or endereco_data.get("state") or "")
        cep = format_cep(str(endereco_data.get("cep") or endereco_data.get("zip") or ""))

        endereco = join_address(
            [
                logradouro,
                numero,
                complemento,
                bairro,
                f"{municipio}/{uf}" if municipio and uf else municipio or uf,
                cep,
            ]
        )
        if endereco == "não informado":
            endereco = ""

        return {
            "nome": nome,
            "logradouro": logradouro,
            "numero": numero,
            "complemento": complemento,
            "bairro": bairro,
            "municipio": municipio,
            "uf": uf,
            "cep": cep,
            "endereco": endereco,
        }

    def parse_text(self, text: str) -> Dict[str, Any]:
        lines = preprocess_text(text)
        explicit_cnpj = extract_cnpj(text)

        data: Dict[str, Any] = {
            "cliente_nome": "",
            "cliente_doc": "",
            "cliente_endereco": "",
            "cliente_endereco_entrega": "",
            "frete": Decimal("0"),
            "valor_negociado": None,
            "prazo_entrega": None,
            "numero_cotacao": None,
            "items": [],
            "observacoes_adicionais": [],
            "texto_original": text,
        }

        item_pattern = re.compile(
            r"(?P<qtd>\d+)\s+(?P<produto>tapumes?|telhas?)\s+(?P<medida>\d+[.,]?\d*)m?\b",
            re.I,
        )

        for line in lines:
            match = item_pattern.search(line)
            if match:
                data["items"].append(
                    {
                        "produto": normalize_product(match.group("produto"), match.group("medida")),
                        "quantidade": int(match.group("qtd")),
                    }
                )
                continue

            value = extract_label_value(line, [r"frete"])
            if value is not None:
                parsed = extract_money_after_label(value) or extract_money_after_label(line)
                if parsed is not None:
                    data["frete"] = parsed
                continue

            value = extract_label_value(line, [r"valor negociado"])
            if value is not None:
                parsed = extract_money_after_label(value) or extract_money_after_label(line)
                if parsed is not None:
                    data["valor_negociado"] = parsed
                continue

            value = extract_label_value(line, [r"prazo de entrega"])
            if value is not None:
                data["prazo_entrega"] = value
                continue

            value = extract_label_value(
                line,
                [r"número da cotação", r"numero da cotação", r"numero da cotacao", r"cotação", r"cotacao"],
            )
            if value is not None:
                data["numero_cotacao"] = value
                continue

            value = extract_label_value(
                line,
                [r"endereço de entrega", r"endereco de entrega", r"endereço entrega", r"endereco entrega"],
            )
            if value is not None:
                data["cliente_endereco_entrega"] = value
                continue

            value = extract_label_value(line, [r"endereço", r"endereco"])
            if value is not None:
                data["cliente_endereco"] = value
                continue

            value = extract_label_value(line, [r"nome", r"cliente"])
            if value is not None:
                customer_info = classify_customer_line(value)
                if customer_info.get("cliente_nome") and not data["cliente_nome"]:
                    data["cliente_nome"] = customer_info["cliente_nome"]
                if customer_info.get("cliente_doc") and not data["cliente_doc"]:
                    data["cliente_doc"] = customer_info["cliente_doc"]
                continue

            value = extract_label_value(line, [r"cnpj", r"cpf", r"cpf/cnpj"])
            if value is not None:
                customer_info = classify_customer_line(line)
                if customer_info.get("cliente_doc") and not data["cliente_doc"]:
                    data["cliente_doc"] = customer_info["cliente_doc"]
                continue

            customer_info = classify_customer_line(line)
            if customer_info:
                if customer_info.get("cliente_nome") and not data["cliente_nome"]:
                    data["cliente_nome"] = customer_info["cliente_nome"]
                if customer_info.get("cliente_doc") and not data["cliente_doc"]:
                    data["cliente_doc"] = customer_info["cliente_doc"]
                continue

            if looks_like_address(line) and not data["cliente_endereco"]:
                data["cliente_endereco"] = normalize_spaces(line)
                continue

            data["observacoes_adicionais"].append(line)

        if not data["cliente_doc"] and explicit_cnpj != "não informado":
            data["cliente_doc"] = explicit_cnpj

        if not data["cliente_nome"] and lines:
            first_line = strip_known_label(lines[0])
            _, cleaned = extract_document_from_text(first_line)
            cleaned = re.sub(r"\s*-\s*(cpf|cnpj)\b.*$", "", cleaned, flags=re.IGNORECASE).strip()
            if cleaned and not looks_like_address(cleaned) and not looks_like_product_line(cleaned):
                if digits_only(cleaned) != cleaned.replace(" ", ""):
                    data["cliente_nome"] = normalize_spaces(cleaned)

        data["cliente_doc"] = data["cliente_doc"] or "não informado"
        data["cliente_endereco"] = normalize_spaces(data["cliente_endereco"]) or "não informado"
        data["cliente_endereco_entrega"] = normalize_spaces(data["cliente_endereco_entrega"]) or "não informado"
        data["cliente_nome"] = normalize_spaces(data["cliente_nome"])
        return data

    def _validate_items(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not items:
            raise QuoteValidationError("nenhum item informado para o orçamento")

        validated: List[Dict[str, Any]] = []
        for item in items:
            produto = normalize_spaces(item.get("produto", ""))
            if not produto:
                raise QuoteValidationError("item com produto vazio")
            if produto not in PRODUCT_TABLE:
                raise QuoteValidationError(f"produto não cadastrado: {produto}")

            try:
                quantidade = int(item.get("quantidade", 0))
            except (TypeError, ValueError):
                raise QuoteValidationError(f"quantidade inválida para o produto {produto!r}")
            if quantidade <= 0:
                raise QuoteValidationError(f"quantidade deve ser maior que zero para o produto {produto!r}")

            validated.append({"produto": produto, "quantidade": quantidade})
        return validated

    def _current_dates(self) -> Tuple[str, str]:
        current = now_br()
        return br_date(current), br_date(current + timedelta(days=7))

    def build(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise QuoteValidationError("payload inválido")

        text = str(payload.get("texto") or payload.get("mensagem") or "")
        extracted = self.parse_text(text) if normalize_spaces(text) else {
            "cliente_nome": "",
            "cliente_doc": "não informado",
            "cliente_endereco": "não informado",
            "cliente_endereco_entrega": "não informado",
            "frete": Decimal("0"),
            "valor_negociado": None,
            "prazo_entrega": None,
            "numero_cotacao": None,
            "items": [],
            "observacoes_adicionais": [],
        }

        doc_final = payload.get("cliente_doc") or extracted.get("cliente_doc") or "não informado"
        cnpj_data = self.fetch_cnpj_data(doc_final) if len(digits_only(doc_final)) == 14 else {}

        nome_extraido = normalize_spaces(extracted.get("cliente_nome") or "")
        if digits_only(nome_extraido) == digits_only(doc_final):
            nome_extraido = ""

        cliente_nome = first_meaningful(payload.get("cliente_nome"), nome_extraido, cnpj_data.get("nome")) or "não informado"
        cliente_endereco = first_meaningful(
            payload.get("cliente_endereco"),
            extracted.get("cliente_endereco"),
            cnpj_data.get("endereco"),
        ) or "não informado"
        entrega = first_meaningful(
            payload.get("cliente_endereco_entrega"),
            extracted.get("cliente_endereco_entrega"),
        ) or "não informado"

        frete = d(payload.get("frete")) if payload.get("frete") not in (None, "") else d(extracted.get("frete") or "0")

        valor_negociado_raw = payload.get("valor_negociado")
        if valor_negociado_raw in (None, ""):
            valor_negociado_raw = extracted.get("valor_negociado")
        valor_negociado = d(valor_negociado_raw) if valor_negociado_raw not in (None, "") else None
        if valor_negociado is not None and valor_negociado < Decimal("0"):
            raise QuoteValidationError("valor negociado não pode ser negativo")

        items = self._validate_items(payload.get("items") or extracted.get("items") or [])
        linhas: List[Dict[str, Any]] = []
        subtotal = Decimal("0")
        desconto = Decimal("0")

        for item in items:
            produto = item["produto"]
            quantidade = item["quantidade"]
            oficial = PRODUCT_TABLE[produto]

            unit = oficial["valor"]
            peso_total = oficial["peso"] * quantidade
            volume_total = oficial["volume"] * quantidade
            total = unit * quantidade
            subtotal += total

            if valor_negociado is not None and valor_negociado < unit:
                desconto += (unit - valor_negociado) * quantidade

            linhas.append(
                {
                    "produto": produto,
                    "quantidade": quantidade,
                    "unitario": q2(unit),
                    "peso_total": peso_total,
                    "volume_total": volume_total,
                    "total": q2(total),
                }
            )

        total_geral = q2(subtotal - desconto + frete)
        numero_orcamento = self.next_number()
        data_emissao, data_validade = self._current_dates()

        observacoes: List[str] = []
        if entrega != "não informado":
            observacoes.append(
                "<strong>⚠ ENDEREÇO DE ENTREGA:</strong><br>"
                f"<strong>{sanitize_html(entrega)}</strong>"
            )
        if extracted.get("numero_cotacao"):
            observacoes.append(f"<strong>Número da cotação:</strong> {sanitize_html(extracted['numero_cotacao'])}")
        if extracted.get("prazo_entrega"):
            observacoes.append(f"<strong>Prazo de entrega:</strong> {sanitize_html(extracted['prazo_entrega'])}")
        for line in extracted.get("observacoes_adicionais", []):
            line_clean = normalize_spaces(str(line))
            if line_clean and line_clean.lower() != "não informado":
                observacoes.append(sanitize_html(line_clean))

        return {
            "numero_orcamento": numero_orcamento,
            "data": data_emissao,
            "validade": data_validade,
            "cliente": {
                "nome": cliente_nome,
                "doc": format_doc(doc_final),
                "endereco": cliente_endereco,
                "endereco_entrega": entrega,
            },
            "itens": linhas,
            "observacoes_html": "<br><br>".join(observacoes) if observacoes else "não informado",
            "resumo": {
                "subtotal": q2(subtotal),
                "frete": q2(frete),
                "desconto": q2(desconto),
                "total_geral": total_geral,
            },
        }

    def make_rows_html(self, linhas: List[Dict[str, Any]]) -> str:
        rows: List[str] = []
        for item in linhas:
            rows.append(
                f"""
                <tr>
                    <td class="col-prod">{sanitize_html(item['produto'])}</td>
                    <td class="num col-qtd">{item['quantidade']}</td>
                    <td class="num col-unit">{money(item['unitario'])}</td>
                    <td class="num col-peso">{fmt_decimal(item['peso_total'], 1)} kg</td>
                    <td class="num col-m3">{fmt_decimal(item['volume_total'], 3)} m³</td>
                    <td class="num col-total">{money(item['total'])}</td>
                </tr>
                """
            )
        return "\n".join(rows)

    def render_official_html(self, template_html: str, quote: Dict[str, Any]) -> str:
        replacements = {
            "{{numero_orcamento}}": str(quote["numero_orcamento"]),
            "{{data}}": quote["data"],
            "{{cliente_nome}}": sanitize_html(quote["cliente"]["nome"]),
            "{{cliente_doc}}": sanitize_html(quote["cliente"]["doc"]),
            "{{cliente_endereco}}": sanitize_html(quote["cliente"]["endereco"]),
            "{{validade}}": quote["validade"],
            "{{linhas_itens}}": self.make_rows_html(quote["itens"]),
            "{{subtotal}}": money(quote["resumo"]["subtotal"]),
            "{{frete}}": money(quote["resumo"]["frete"]),
            "{{desconto}}": money(quote["resumo"]["desconto"]),
            "{{total_geral}}": money(quote["resumo"]["total_geral"]),
            "{{observacoes_dinamicas}}": quote["observacoes_html"],
        }

        html_out = template_html
        asset_root = self.base_dir / "assets"
        html_out = html_out.replace("logo_ecotap.png", str((asset_root / "logo_ecotap.png").as_uri()))
        html_out = html_out.replace("logo_GreenWall.png", str((asset_root / "logo_GreenWall.png").as_uri()))
        html_out = html_out.replace("qr_pix.png", str((asset_root / "qr_pix.png").as_uri()))

        for old, new in replacements.items():
            html_out = html_out.replace(old, str(new))
        return html_out

    def write_outputs(self, html: str, numero_orcamento: int):
        self.generated_dir.mkdir(parents=True, exist_ok=True)
        html_path = self.generated_dir / f"orcamento_{numero_orcamento}.html"
        pdf_path = self.generated_dir / f"orcamento_{numero_orcamento}.pdf"
        html_path.write_text(html, encoding="utf-8")
        HTML(string=html, base_url=str(self.base_dir)).write_pdf(str(pdf_path))
        return html_path, pdf_path

    def resolve_generated_file(self, filename: str) -> Path:
        name = Path(filename).name
        if name != filename:
            raise NotFound("arquivo não encontrado")
        if not OUTPUT_FILENAME_RE.fullmatch(name):
            raise NotFound("arquivo não encontrado")

        path = (self.generated_dir / name).resolve()
        generated_root = self.generated_dir.resolve()
        if generated_root not in path.parents:
            raise NotFound("arquivo não encontrado")
        if path.suffix.lower() not in ALLOWED_OUTPUT_EXTENSIONS or not path.exists():
            raise NotFound("arquivo não encontrado")
        return path
