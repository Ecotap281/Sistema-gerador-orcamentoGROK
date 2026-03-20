# === ARQUIVO COMPLETO ATUALIZADO: quote_logic.py ===
import html as html_lib
import os
import re
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

import requests
from weasyprint import HTML

TWOPLACES = Decimal("0.01")

PRODUCT_TABLE = {
    "Tapume 0,55x2,00m": {"peso": Decimal("3.0"), "volume": Decimal("0.011"), "valor": Decimal("20.95")},
    "Tapume 0,55x2,20m": {"peso": Decimal("3.3"), "volume": Decimal("0.012"), "valor": Decimal("22.95")},
    "Tapume 0,55x2,44m": {"peso": Decimal("4.0"), "volume": Decimal("0.013"), "valor": Decimal("29.95")},
    "Telha 0,55x2,00m": {"peso": Decimal("3.2"), "volume": Decimal("0.011"), "valor": Decimal("22.95")},
    "Telha 0,55x2,20m": {"peso": Decimal("3.4"), "volume": Decimal("0.012"), "valor": Decimal("24.95")},
    "Telha 0,55x2,44m": {"peso": Decimal("4.4"), "volume": Decimal("0.013"), "valor": Decimal("29.95")},
}

SIZE_MAP = {
    "2": "2,00",
    "2,0": "2,00",
    "2,00": "2,00",
    "2.00": "2,00",
    "2,20": "2,20",
    "2.20": "2,20",
    "2,2": "2,20",
    "2.2": "2,20",
    "2,44": "2,44",
    "2.44": "2,44",
}

CNPJ_ENDPOINTS = [
    "https://brasilapi.com.br/api/cnpj/v1/{cnpj}",
    "https://www.receitaws.com.br/v1/cnpj/{cnpj}",
    "https://publica.cnpj.ws/cnpj/{cnpj}",
]

ADDRESS_KEYWORDS = [
    "rua", "r.", "avenida", "av.", "estrada", "rodovia", "travessa", "tv.",
    "alameda", "praça", "praca", "bairro", "cep", "km", "rod.", "br-"
]

INLINE_LABELS = [
    "endereço de entrega",
    "endereco de entrega",
    "endereço entrega",
    "endereco entrega",
    "valor negociado",
    "número da cotação",
    "numero da cotação",
    "numero da cotacao",
    "prazo de entrega",
    "frete",
]

lock = Lock()


def d(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None or value == "":
        return Decimal("0")
    text = str(value).strip()
    text = text.replace("R$", "").replace(".", "").replace(" ", "").replace(",", ".")
    return Decimal(text)


def money(value: Decimal) -> str:
    value = value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    s = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def fmt_decimal(value: Decimal, places: int = 3) -> str:
    q = Decimal("1") if places == 0 else Decimal("1." + ("0" * places))
    value = value.quantize(q, rounding=ROUND_HALF_UP)
    return f"{value:.{places}f}".replace(".", ",")


def digits_only(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def format_cnpj(cnpj: str) -> str:
    digits = digits_only(cnpj)
    if len(digits) != 14:
        return cnpj or "não informado"
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"


def format_cpf(cpf: str) -> str:
    digits = digits_only(cpf)
    if len(digits) != 11:
        return cpf or "não informado"
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"


def format_doc(doc: str) -> str:
    digits = digits_only(doc)
    if len(digits) == 14:
        return format_cnpj(doc)
    if len(digits) == 11:
        return format_cpf(doc)
    return doc or "não informado"


def format_cep(cep: str) -> str:
    digits = digits_only(cep)
    if len(digits) != 8:
        return cep or ""
    return f"{digits[:5]}-{digits[5:]}"


def br_date(dt: date) -> str:
    return dt.strftime("%d/%m/%Y")


def sanitize_html(value: str) -> str:
    return html_lib.escape(value or "").replace("\n", "<br>")


def normalize_spaces(text: str) -> str:
    text = (text or "").replace("\u00a0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def split_inline_labels(text: str) -> str:
    out = text or ""
    for label in INLINE_LABELS:
        out = re.sub(rf"(?<!^)(?<!\n)\s+(?={re.escape(label)}\b)", "\n", out, flags=re.IGNORECASE)
    return out


def preprocess_text(raw_text: str) -> List[str]:
    text = normalize_spaces(raw_text)
    text = split_inline_labels(text)
    lines = [normalize_spaces(line.strip(" -\t")) for line in text.splitlines()]
    return [line for line in lines if line]


def extract_cnpj(text: str) -> str:
    if not text:
        return "não informado"
    m = re.search(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b", text)
    if m:
        return format_cnpj(m.group(0))
    compact = digits_only(text)
    if len(compact) == 14 and len(compact) >= max(8, len(normalize_spaces(text)) - 6):
        return format_cnpj(compact)
    return "não informado"


def normalize_product(raw_name: str, raw_size: str) -> str:
    name = (raw_name or "").strip().lower()
    size_raw = (raw_size or "").replace("m", "").strip()
    size = SIZE_MAP.get(size_raw, size_raw.replace(".", ","))
    if "tap" in name:
        base = "Tapume"
    elif "telh" in name:
        base = "Telha"
    else:
        return raw_name.strip() or "Produto não informado"
    return f"{base} 0,55x{size}m"


def first_meaningful(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = normalize_spaces(str(value))
        if text and text.lower() != "não informado":
            return text
    return ""


def join_address(parts: List[str]) -> str:
    cleaned: List[str] = []
    for part in parts:
        value = normalize_spaces(str(part)) if part is not None else ""
        if not value:
            continue
        if value.lower() in {"s/n", "sn"}:
            continue
        cleaned.append(value.strip(" ,-/"))
    return ", ".join(cleaned) if cleaned else "não informado"


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
        m = re.search(pattern, original)
        if m:
            raw_doc = m.group(0)
            doc = format_cnpj(raw_doc) if kind == "cnpj" else format_cpf(raw_doc)
            cleaned = normalize_spaces((original[:m.start()] + " " + original[m.end():]).strip(" -,"))
            return doc, cleaned

    stripped = strip_known_label(original)
    compact = digits_only(stripped)
    if len(compact) == 14 and compact:
        return format_cnpj(compact), ""
    if len(compact) == 11 and compact:
        return format_cpf(compact), ""
    return None, original


def looks_like_address(text: str) -> bool:
    t = (text or "").lower()
    return any(keyword in t for keyword in ADDRESS_KEYWORDS) or bool(re.search(r"\b\d{5}-?\d{3}\b", t))


def looks_like_product_line(text: str) -> bool:
    t = (text or "").lower()
    return bool(re.search(r"\b\d+\s+(tapume|tapumes|telha|telhas)\b", t))


def extract_money_after_label(line: str) -> Optional[Decimal]:
    candidate = normalize_spaces(line)
    m = re.search(r"r\$\s*([\d\.,]+)", candidate, flags=re.IGNORECASE)
    if m:
        return d(m.group(1))
    m = re.search(r"(?<!\d)(\d+[\.,]\d{2})(?!\d)", candidate)
    if m:
        return d(m.group(1))
    return None


def extract_label_value(line: str, labels: List[str]) -> Optional[str]:
    candidate = normalize_spaces(line)
    for label in labels:
        m = re.search(rf"^{label}\s*:?\s*(.+)$", candidate, flags=re.IGNORECASE)
        if m:
            return normalize_spaces(m.group(1))
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


class QuoteBuilder:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.generated_dir = self.base_dir / "generated"
        self.data_dir = self.base_dir / "data"
        self.counter_file = Path(os.getenv("COUNTER_FILE", self.data_dir / "last_number.txt"))
        self.initial_number = int(os.getenv("INITIAL_QUOTE_NUMBER", "1500"))

    def next_number(self) -> int:
        self.counter_file.parent.mkdir(parents=True, exist_ok=True)
        with lock:
            if self.counter_file.exists():
                current = int(self.counter_file.read_text(encoding="utf-8").strip() or self.initial_number)
            else:
                current = self.initial_number
            nxt = current + 1
            self.counter_file.write_text(str(nxt), encoding="utf-8")
        return nxt

    def fetch_cnpj_data(self, cnpj: str) -> Dict[str, str]:
        digits = digits_only(cnpj)
        if len(digits) != 14:
            return {}
        headers = {"User-Agent": "Mozilla/5.0"}
        for url in CNPJ_ENDPOINTS:
            try:
                response = requests.get(url.format(cnpj=digits), headers=headers, timeout=15)
                if response.status_code != 200:
                    continue
                normalized = self.normalize_cnpj_payload(response.json())
                if normalized.get("nome") or normalized.get("endereco"):
                    return normalized
            except Exception:
                continue
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

        endereco = join_address([
            logradouro,
            numero,
            complemento,
            bairro,
            f"{municipio}/{uf}" if municipio and uf else municipio or uf,
            cep,
        ])
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

        # === FILTRO DE CABEÇALHOS/METADADOS (PRIORIDADE 1) ===
        # Ignora linhas como "Orçamento nº XXXX", "Cotação nº XXXX" ou similares
        # para resolver o bug crítico onde viravam nome do cliente.
        # Colocado no INÍCIO da função conforme solicitado.
        header_patterns = [
            r"orçamento\s*n[º°]?\s*\d",
            r"orcamento\s*n[º°]?\s*\d",
            r"cotação\s*n[º°]?\s*\d",
            r"cotacao\s*n[º°]?\s*\d",
            r"orç\.?\s*n[º°]?\s*\d",
            r"cot\.?\s*n[º°]?\s*\d",
        ]
        lines = [
            line for line in lines
            if not any(re.search(pat, line.lower()) for pat in header_patterns)
        ]

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
            lower = line.lower()

            m = item_pattern.search(line)
            if m:
                data["items"].append({
                    "produto": normalize_product(m.group("produto"), m.group("medida")),
                    "quantidade": int(m.group("qtd")),
                })
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

            value = extract_label_value(line, [r"número da cotação", r"numero da cotação", r"numero da cotacao", r"cotação", r"cotacao"])
            if value is not None:
                data["numero_cotacao"] = value
                continue

            value = extract_label_value(line, [r"endereço de entrega", r"endereco de entrega", r"endereço entrega", r"endereco entrega"])
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

    def build(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        text = normalize_spaces((payload.get("texto") or payload.get("mensagem") or "").strip())
        extracted = self.parse_text(text) if text else {
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

        cliente_nome = first_meaningful(
            payload.get("cliente_nome"),
            nome_extraido,
            cnpj_data.get("nome"),
        ) or "não informado"

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

        items = payload.get("items") or extracted.get("items") or []
        linhas: List[Dict[str, Any]] = []
        subtotal = Decimal("0")
        desconto = Decimal("0")

        for item in items:
            produto = item.get("produto", "Produto não informado")
            quantidade = int(item.get("quantidade", 0))
            oficial = PRODUCT_TABLE.get(produto)
            if not oficial:
                raise ValueError(f"Produto não cadastrado: {produto}")

            unit = oficial["valor"]
            peso_total = oficial["peso"] * quantidade
            volume_total = oficial["volume"] * quantidade
            total = unit * quantidade
            subtotal += total

            if valor_negociado is not None and valor_negociado < unit:
                desconto += (unit - valor_negociado) * quantidade

            linhas.append({
                "produto": produto,
                "quantidade": quantidade,
                "unitario": unit,
                "peso_total": peso_total,
                "volume_total": volume_total,
                "total": total,
            })

        total_geral = subtotal - desconto + frete
        numero_orcamento = self.next_number()

        observacoes: List[str] = []
        if entrega != "não informado":
            observacoes.append(
                "<strong>⚠ ENDEREÇO DE ENTREGA:</strong><br>"
                f"<strong>{sanitize_html(entrega)}</strong>"
            )
        if extracted.get("numero_cotacao"):
            observacoes.append(
                f"<strong>Número da cotação:</strong> {sanitize_html(extracted['numero_cotacao'])}"
            )
        if extracted.get("prazo_entrega"):
            observacoes.append(
                f"<strong>Prazo de entrega:</strong> {sanitize_html(extracted['prazo_entrega'])}"
            )
        for line in extracted.get("observacoes_adicionais", []):
            line_clean = normalize_spaces(str(line))
            if line_clean and line_clean.lower() != "não informado":
                observacoes.append(sanitize_html(line_clean))

        return {
            "numero_orcamento": numero_orcamento,
            "data": br_date(date.today()),
            "validade": br_date(date.today() + timedelta(days=7)),
            "cliente": {
                "nome": cliente_nome or "não informado",
                "doc": format_doc(doc_final),
                "endereco": cliente_endereco,
                "endereco_entrega": entrega,
            },
            "itens": linhas,
            "observacoes_html": "<br><br>".join(observacoes) if observacoes else "não informado",
            "resumo": {
                "subtotal": subtotal,
                "frete": frete,
                "desconto": desconto,
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
