# ofx-br

Leitor de OFX que aguenta o que os bancos brasileiros exportam de verdade.

Sem dependência externa, só a biblioteca padrão do Python.

```bash
pip install ofx-br
```

```python
import ofxbr

doc = ofxbr.parse("extrato.ofx")

for lancamento in doc.transactions:
    print(lancamento.posted_at, lancamento.amount, lancamento.memo)
```

---

## O problema

Se você já tentou ler um extrato OFX de banco brasileiro em Python, provavelmente
esbarrou em um destes três. Nenhum é bug do banco, e nenhum é bug do seu código:
são características do formato que as ferramentas genéricas não tratam.

### 1. O OFX que os bancos daqui emitem não é XML

A versão que os bancos brasileiros exportam na prática é a 1.x, que usa uma
sintaxe derivada de SGML. As tags folha **não têm fechamento**:

```
<STMTTRN>
<TRNTYPE>DEBIT
<TRNAMT>-150.00
<FITID>202607020001
<MEMO>PAGAMENTO FORNECEDOR
</STMTTRN>
```

Jogar isso num parser de XML dá erro de documento malformado, e é daí que sai a
conclusão errada de que o arquivo do banco veio corrompido. O arquivo está
íntegro. A ferramenta é que está errada.

```python
>>> import xml.etree.ElementTree as ET
>>> ET.parse("extrato.ofx")
xml.etree.ElementTree.ParseError: mismatched tag: line 24, column 2
```

### 2. A codificação não é UTF-8

O cabeçalho da maioria dos extratos brasileiros diz isto, que lido ao pé da letra
é contraditório:

```
ENCODING:USASCII
CHARSET:1252
```

O arquivo declara US-ASCII e logo em seguida declara a página de código 1252, que
não é ASCII. Na prática os bytes são cp1252. Ler como UTF-8 estoura no primeiro
acento:

```python
>>> open("extrato.ofx", encoding="utf-8").read()
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xc7 in position 604
```

O `ofx-br` lê o cabeçalho como ASCII (ele é ASCII puro por definição), decide o
codec a partir de `CHARSET` e só então decodifica o corpo.

### 3. Reimportar o mesmo arquivo duplica lançamento

Reimportação é o caso comum, não a exceção: a pessoa baixa o extrato de novo
quando o período veio incompleto, quando o processo falhou no meio, ou quando não
lembra se já importou.

Todo lançamento carrega um identificador único atribuído pelo banco, o **FITID**.
Ele é o que torna a importação idempotente.

```python
ja_gravados = {linha.fitid for linha in meu_banco.query(...)}
novos = ofxbr.new_since(doc.transactions, ja_gravados)  # só o que falta inserir
```

---

## Uso

### Ler um arquivo

```python
import ofxbr

doc = ofxbr.parse("extrato.ofx")  # caminho, bytes ou arquivo aberto em "rb"

doc.version  # 1 ou 2
doc.encoding  # codec detectado, ex: "cp1252"
doc.statements  # um arquivo pode conter mais de uma conta
doc.transactions  # lançamentos de todas as contas, achatados
```

### Extrato e conta

```python
stmt = doc.statements[0]

stmt.account.bank_id  # "341"
stmt.account.bank_name  # "Itaú Unibanco"  (pelo código COMPE)
stmt.account.branch_id  # "1234"
stmt.account.account_id  # "56789-0"
stmt.currency  # "BRL"
stmt.start, stmt.end  # período do extrato
stmt.ledger_balance  # Decimal
stmt.total_credits  # Decimal
stmt.total_debits  # Decimal
len(stmt)  # quantidade de lançamentos
```

### Lançamento

```python
t = doc.transactions[0]

t.fitid  # "202607020001"  <- a chave contra duplicidade
t.amount  # Decimal("-150.00"), sempre Decimal, nunca float
t.posted_at  # datetime, com fuso quando o arquivo declara
t.type  # "DEBIT"
t.memo  # "PAGAMENTO FORNECEDOR"
t.payee  # contraparte, quando o banco envia
t.checknum
t.is_debit, t.is_credit
```

### Deduplicação

```python
from ofxbr import dedupe, find_duplicates, new_since

dedupe(doc.transactions)  # remove FITID repetido
dedupe(doc.transactions, use_fingerprint=True)  # + heurística de FITID reemitido
find_duplicates(doc.transactions)  # {fitid: [lançamentos]}
new_since(doc.transactions, ja_gravados)  # só o que ainda não existe
```

Sobre `use_fingerprint`: alguns bancos **reemitem o FITID** quando a transação
muda de status, de pendente para efetivada. Aí o mesmo evento chega com
identificador novo e o filtro por FITID não pega. A impressão digital compara
`(data, valor, histórico normalizado)`, ignorando a hora e as sequências longas
de dígitos, que são justamente o que o banco troca nesse caso.

Deixe desligado quando o seu banco emitir FITID estável: com ela ligada, duas
compras legítimas de mesmo valor, no mesmo dia e no mesmo estabelecimento seriam
tratadas como uma só.

### Linha de comando

```bash
ofxbr extrato.ofx                        # resumo legível
ofxbr extrato.ofx --formato csv          # csv para planilha
ofxbr extrato.ofx --formato json         # json para pipeline
ofxbr extrato.ofx --dedup --formato csv  # sem FITID repetido
```

O resumo também avisa quando o arquivo traz FITID repetido, que costuma ser
sinal de exportação com período sobreposto.

---

## O que está tratado

| Situação | Tratamento |
|---|---|
| OFX 1.x SGML com folha sem fechamento | Sim, é o caminho principal |
| OFX 1.x com folha fechada (`<FITID>1</FITID>`) | Sim, as duas formas convivem |
| OFX 2.x (XML de verdade) | Sim, cai no parser de XML e produz o mesmo modelo |
| `CHARSET:1252`, `ISO-8859-1`, UTF-8 | Sim, decidido pelo cabeçalho |
| Cabeçalho ausente | Sim, assume cp1252, que nunca levanta exceção |
| Fuso entre colchetes: `20260702000000[-3:BRT]` | Sim, inclusive fracionário `[-3.5:NST]` |
| Data sem hora: `20260702` | Sim |
| Vírgula como separador decimal: `1.234,56` | Sim, fora da especificação mas acontece |
| Valor entre parênteses para negativo | Sim |
| Entidades `&amp;` `&lt;` `&#39;` no histórico | Sim, desescapamento conservador |
| Campo vazio (`<MEMO></MEMO>`) | Sim, vira string vazia em vez de sumir |
| Conta corrente e cartão de crédito | Sim, `STMTRS` e `CCSTMTRS` |
| Mais de uma conta no mesmo arquivo | Sim, `doc.statements` é lista |
| Valores em `Decimal` | Sempre. Nunca `float` |

### Por que Decimal e não float

Porque `0.1 + 0.2 != 0.3` em ponto flutuante binário, e num extrato com milhares
de lançamentos esse erro acumula até virar divergência de centavos na
conciliação. Dinheiro não vai em `float`. Toda entrada e saída da biblioteca usa
`decimal.Decimal`.

### Fuso horário: o que a biblioteca não faz

Quando o arquivo **não declara** fuso, o `datetime` volta ingênuo (sem `tzinfo`).
A biblioteca não assume `America/Sao_Paulo` por conta própria. Inventar um fuso
que o arquivo não declarou é exatamente como o lançamento acaba no dia errado
perto da virada. A decisão fica com você, que conhece a origem do arquivo.

---

## Limitações, com honestidade

- **As fixtures de teste são sintéticas.** Foram escritas à mão para exercitar
  cada variação de formato descrita acima (veja `tests/make_fixtures.py`). Não
  são extratos reais e não contêm dado de ninguém. Isso significa que o
  comportamento está verificado contra o **formato**, não contra o parque de
  exportadores de todos os bancos.
- **Se o seu banco quebrar, abra uma issue.** Anexe um trecho do arquivo com os
  dados substituídos por valores fictícios: as primeiras linhas do cabeçalho e um
  bloco `STMTTRN` bastam para diagnosticar. Nunca anexe extrato real.
- Investimento, `INVSTMTRS` e mensagens que não sejam de extrato bancário ou de
  cartão não estão implementados.
- Não faz conciliação. A biblioteca lê o extrato; casar com o seu ERP é outro
  problema, e a regra de casamento depende do seu negócio.

## Alternativas

`ofxparse` e `ofxtools` são bibliotecas maduras e cobrem mais do padrão OFX,
incluindo investimento. Se o seu caso não esbarra nos três problemas do começo
deste README, use uma delas. O `ofx-br` existe para o recorte brasileiro:
SGML sem fechamento, cp1252 e idempotência por FITID.

## Desenvolvimento

```bash
git clone https://github.com/LeonardoChiarelli/ofx-br
cd ofx-br
pip install -e ".[dev]"
python tests/make_fixtures.py   # regera as fixtures
pytest
ruff check .
```

## Licença

MIT.

## Contexto

Extraído de uma ferramenta de conciliação financeira em produção, que lê extrato
em PDF e OFX e concilia contra o ERP do cliente, rodando totalmente offline.

Escrevi um guia mais longo sobre a decisão entre OFX, CNAB e Open Finance para
levar extrato ao ERP, incluindo a regra de casamento em camadas que a
deduplicação aqui não cobre:
[chiarelli.dev/guias/integrar-extrato-bancario-com-erp](https://chiarelli.dev/guias/integrar-extrato-bancario-com-erp).
