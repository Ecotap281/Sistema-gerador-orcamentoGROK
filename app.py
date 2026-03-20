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
  <link rel="stylesheet" href="/static/ui.css">
</head>
<body>
  <main class="page">
    <header class="header">
      <div class="brand">
        <div class="brand__mark" aria-hidden="true"></div>
        <div class="brand__text">
          <div class="brand__title">Gerador de Orçamentos</div>
          <div class="brand__subtitle">Cole a mensagem e gere o PDF em 1 clique.</div>
        </div>
      </div>
      <div class="header__hint">
        <span class="pill">Aceita variações: <strong>nº</strong>, <strong>num</strong>, <strong>:</strong>, <strong>=</strong>, <strong>_</strong>, com/sem acento</span>
      </div>
    </header>

    <section class="card">
      <form method="post" action="/gerar-orcamento?download=1" class="form" autocomplete="off">
        <label for="texto" class="label">Texto do orçamento</label>
        <textarea
          id="texto"
          name="texto"
          class="textarea"
          spellcheck="false"
          placeholder="Cole aqui... (ex.: CNPJ, itens, frete, número do orçamento, etc.)"
        ></textarea>

        <div class="actions">
          <button type="submit" class="btn btn--primary">
            <span class="btn__dot" aria-hidden="true"></span>
            Gerar PDF
          </button>

          <button type="button" class="btn btn--ghost" id="btn-clear">Limpar</button>
        </div>

        <div class="micro">
          <div class="micro__left">
            Dica: pode colar do WhatsApp - o sistema tenta interpretar "como humano".
          </div>
          <div class="micro__right">
            API: <code>POST /gerar-orcamento</code>
          </div>
        </div>
      </form>
    </section>

    <footer class="footer">
      <div class="footer__line">
        <span>PDF oficial não é alterado.</span>
        <span class="sep">•</span>
        <span>Interface feita sob medida.</span>
      </div>
    </footer>
  </main>

  <script src="/static/ui.js"></script>
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
