import json
import os
from pathlib import Path
from flask import Flask, request, jsonify, send_file, render_template_string
from weasyprint import HTML
from quote_logic import QuoteBuilder

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_HTML = (BASE_DIR / "templates" / "Layout_oficial_orcamento.html").read_text(encoding="utf-8")

app = Flask(__name__)
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
        return send_file(pdf_path, mimetype="application/pdf", as_attachment=True, download_name=pdf_path.name)

    return jsonify({
        "numero_orcamento": quote["numero_orcamento"],
        "cliente": quote["cliente"],
        "resumo": quote["resumo"],
        "arquivos": {
            "html": str(html_path.name),
            "pdf": str(pdf_path.name),
        },
        "download_pdf": f"/arquivos/{pdf_path.name}",
        "download_html": f"/arquivos/{html_path.name}",
    })

@app.get("/arquivos/<path:filename>")
def arquivos(filename):
    path = BASE_DIR / "generated" / filename
    if not path.exists():
        return jsonify({"erro": "arquivo não encontrado"}), 404
    if path.suffix.lower() == ".pdf":
        mimetype = "application/pdf"
    else:
        mimetype = "text/html"
    return send_file(path, mimetype=mimetype, as_attachment=True, download_name=path.name)

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)
