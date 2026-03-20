import os
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request, send_file
from werkzeug.exceptions import HTTPException

from quote_logic import QuoteBuilder, QuoteValidationError

BASE_DIR = Path(__file__).resolve().parent
GENERATED_DIR = BASE_DIR / "generated"
TEMPLATE_HTML = (BASE_DIR / "templates" / "Layout_oficial_orcamento.html").read_text(encoding="utf-8")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_CONTENT_LENGTH_BYTES", str(512 * 1024)))
builder = QuoteBuilder(base_dir=BASE_DIR)

FORM_HTML = """
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <title>Gerador de Orçamentos</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: Arial, Helvetica, sans-serif; max-width: 980px; margin: 24px auto; padding: 0 16px; }
    textarea, input { width: 100%; padding: 12px; font-size: 16px; }
    textarea { min-height: 260px; }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 16px 0; }
    button { padding: 12px 18px; font-size: 16px; cursor: pointer; }
    .card { border: 1px solid #ddd; padding: 18px; border-radius: 12px; }
    code { background: #f4f4f4; padding: 2px 6px; border-radius: 6px; }
  </style>
</head>
<body>
  <h1>Gerador de Orçamentos</h1>
  <p>Cole o texto no estilo WhatsApp ou envie JSON para <code>POST /gerar-orcamento</code>.</p>
  <div class="card">
    <form method="post" action="/gerar-orcamento?download=1">
      <textarea name="texto" placeholder="Cole aqui o texto do orçamento..."></textarea>
      <div style="margin-top:16px;">
        <button type="submit">Gerar PDF</button>
      </div>
    </form>
  </div>
</body>
</html>
"""


@app.get("/")
def index():
    return render_template_string(FORM_HTML)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.errorhandler(QuoteValidationError)
def handle_quote_validation_error(error: QuoteValidationError):
    return jsonify({"erro": str(error)}), 400


@app.errorhandler(413)
def handle_too_large(_error):
    return jsonify({"erro": "payload excede o tamanho máximo permitido"}), 413


@app.errorhandler(Exception)
def handle_unexpected_error(error: Exception):
    if isinstance(error, HTTPException):
        return error
    app.logger.exception("Erro não tratado ao processar requisição", exc_info=error)
    return jsonify({"erro": "erro interno ao processar o orçamento"}), 500


@app.post("/gerar-orcamento")
def gerar_orcamento():
    download = request.args.get("download") == "1"

    if request.is_json:
        payload = request.get_json(silent=True) or {}
    else:
        payload = request.form.to_dict(flat=True)

    quote = builder.build(payload)
    html = builder.render_official_html(TEMPLATE_HTML, quote)
    html_path, pdf_path = builder.write_outputs(html, quote["numero_orcamento"])

    if download:
        return send_file(
            pdf_path,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=pdf_path.name,
            conditional=True,
        )

    return jsonify(
        {
            "numero_orcamento": quote["numero_orcamento"],
            "cliente": quote["cliente"],
            "resumo": quote["resumo"],
            "arquivos": {
                "html": html_path.name,
                "pdf": pdf_path.name,
            },
            "download_pdf": f"/arquivos/{pdf_path.name}",
            "download_html": f"/arquivos/{html_path.name}",
        }
    )


@app.get("/arquivos/<path:filename>")
def arquivos(filename: str):
    safe_path = builder.resolve_generated_file(filename)
    mimetype = "application/pdf" if safe_path.suffix.lower() == ".pdf" else "text/html; charset=utf-8"
    return send_file(
        safe_path,
        mimetype=mimetype,
        as_attachment=True,
        download_name=safe_path.name,
        conditional=True,
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    app.run(host="0.0.0.0", port=port, debug=False)
