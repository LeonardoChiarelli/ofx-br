"""ofx-br: leitor de OFX que aguenta o que os bancos brasileiros exportam.

Resolve os três problemas que derrubam quem tenta ler extrato bancário no
Brasil com ferramenta genérica:

1. O OFX 1.x que os bancos daqui emitem não é XML. Parser de XML rejeita o
   arquivo como malformado mesmo estando íntegro.
2. A codificação é cp1252 ou latin-1, não UTF-8, e o cabeçalho declara
   ``ENCODING:USASCII`` junto com ``CHARSET:1252``, que é contraditório.
3. Reimportação duplica lançamento quando a rotina ignora o FITID.

Uso:

    >>> import ofxbr
    >>> doc = ofxbr.parse("extrato.ofx")
    >>> for lancamento in doc.transactions:
    ...     print(lancamento.posted_at, lancamento.amount, lancamento.memo)

Sem dependência externa: só a biblioteca padrão do Python.
"""

from __future__ import annotations

from .dedup import dedupe, find_duplicates, fingerprint, new_since
from .encoding import detect
from .errors import (
    OfxError,
    OfxHeaderError,
    OfxParseError,
    OfxValueError,
)
from .models import Account, OfxDocument, Statement, Transaction
from .parser import parse, parse_bytes, parse_file, parse_string
from .values import parse_amount, parse_datetime

__version__ = "0.1.0"

__all__ = [
    "parse",
    "parse_bytes",
    "parse_file",
    "parse_string",
    "detect",
    "dedupe",
    "find_duplicates",
    "fingerprint",
    "new_since",
    "parse_amount",
    "parse_datetime",
    "OfxDocument",
    "Statement",
    "Account",
    "Transaction",
    "OfxError",
    "OfxHeaderError",
    "OfxParseError",
    "OfxValueError",
    "__version__",
]
