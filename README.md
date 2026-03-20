# Sistema web de orçamentos em PDF

Projeto pronto para subir no Render com:
- Flask
- template HTML oficial fixo
- geração de PDF com WeasyPrint
- consulta de CNPJ com fallback
- parser de texto estilo WhatsApp
- numeração automática de orçamento

## Como rodar localmente

```bash
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
pip install -r requirements.txt
python app.py
```

Acesse `http://localhost:10000`.

## Endpoint principal

### POST /gerar-orcamento

Aceita:

### 1) Texto livre
```json
{
  "texto": "ESPORTE CLUBE JUVENTUDE - CNPJ 78.626.066/0001-89\n108 tapumes 2,00m\nEndereço entrega: Rua Pedro Crispim Venancio, Pescaria Brava, SC\nValor negociado R$18,20\nFrete: R$: 279,05\nNúmero da Cotação 3339818 (Mengue transportes)\nPrazo de entrega: 5 Dias úteis após pagamento"
}
```

### 2) Payload estruturado
```json
{
  "cliente_nome": "ESPORTE CLUBE JUVENTUDE",
  "cliente_doc": "78.626.066/0001-89",
  "cliente_endereco_entrega": "Rua Pedro Crispim Venancio, Pescaria Brava, SC",
  "valor_negociado": 18.20,
  "frete": 279.05,
  "items": [
    {
      "produto": "Tapume 0,55x2,00m",
      "quantidade": 108
    }
  ]
}
```

## Deploy no Render

### Opção recomendada: Blueprint
1. Suba este projeto para um repositório GitHub.
2. No Render, crie um novo Blueprint e aponte para o repositório.
3. O arquivo `render.yaml` cria o serviço web com disk em `/app/data`.
4. O contador dos orçamentos fica persistido em `/app/data/last_number.txt`.

## Observações importantes
- Sem disk persistente, o contador volta a se perder após redeploy.
- Em produção, você pode migrar o contador para Postgres ou Redis.
- O HTML oficial fica intacto. O sistema só substitui placeholders.
