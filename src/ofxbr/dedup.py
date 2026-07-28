"""Deduplicação de lançamentos.

Reimportar o mesmo extrato é o caso comum, não a exceção: a pessoa baixa de
novo quando o período veio incompleto, quando o processo falhou no meio, ou
simplesmente quando não lembra se já importou. Uma rotina que não trata isso
duplica lançamento no ERP.

Duas camadas, porque o FITID sozinho não cobre tudo:

1. **FITID**, o identificador que o banco atribui. É a chave primária.
2. **Impressão digital** de ``(data, valor, histórico normalizado)``, para o
   caso em que o banco reemite o FITID quando a transação muda de status, de
   pendente para efetivada. Aí o mesmo lançamento chega com identificador novo
   e a camada 1 não pega.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from .models import Transaction

__all__ = ["dedupe", "find_duplicates", "fingerprint", "new_since"]

_SPACES = re.compile(r"\s+")
# Sequências longas de dígitos costumam ser o identificador interno da
# operação, que muda entre pendente e efetivado no mesmo lançamento. Remover
# faz a impressão digital sobreviver a essa troca.
_LONG_DIGITS = re.compile(r"\d{6,}")


def _normalize_memo(memo: str) -> str:
    text = unicodedata.normalize("NFKD", memo)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = _LONG_DIGITS.sub("", text)
    text = _SPACES.sub(" ", text)
    return text.strip().upper()


def fingerprint(transaction: Transaction) -> tuple[str, str, str]:
    """Chave secundária, imune à troca de FITID entre pendente e efetivado.

    Usa a **data** (sem hora), o valor e o histórico normalizado. A hora fica
    de fora de propósito: o banco costuma alterá-la quando a transação é
    efetivada, mesmo mantendo o dia.
    """
    day = transaction.posted_at.date().isoformat() if transaction.posted_at else ""
    return (day, str(transaction.amount), _normalize_memo(transaction.memo))


def dedupe(
    transactions: Iterable[Transaction],
    *,
    use_fingerprint: bool = False,
) -> list[Transaction]:
    """Devolve os lançamentos sem repetição, preservando a ordem de entrada.

    Com ``use_fingerprint=True``, também descarta lançamento cujo FITID é novo
    mas cuja impressão digital já apareceu. Deixe desligado quando o banco
    emitir FITID estável: nesse caso a segunda camada só cria risco de
    descartar duas compras legítimas de mesmo valor no mesmo dia.
    """
    seen_ids: set[str] = set()
    seen_prints: set[tuple[str, str, str]] = set()
    out: list[Transaction] = []

    for transaction in transactions:
        if transaction.fitid:
            if transaction.fitid in seen_ids:
                continue
            seen_ids.add(transaction.fitid)

        if use_fingerprint:
            print_key = fingerprint(transaction)
            if print_key in seen_prints:
                continue
            seen_prints.add(print_key)

        out.append(transaction)

    return out


def find_duplicates(transactions: Iterable[Transaction]) -> dict[str, list[Transaction]]:
    """Agrupa por FITID os lançamentos que aparecem mais de uma vez."""
    groups: dict[str, list[Transaction]] = {}
    for transaction in transactions:
        if transaction.fitid:
            groups.setdefault(transaction.fitid, []).append(transaction)
    return {k: v for k, v in groups.items() if len(v) > 1}


def new_since(
    transactions: Iterable[Transaction],
    known_fitids: Iterable[str],
) -> list[Transaction]:
    """Filtra o que ainda não existe no destino.

    É a chamada que torna a importação idempotente: passe os FITID que já estão
    gravados no seu banco e receba de volta só o que falta inserir.

    >>> ja_gravados = {"202607020001"}
    >>> novos = new_since(doc.transactions, ja_gravados)
    """
    known = set(known_fitids)
    return [t for t in transactions if t.fitid and t.fitid not in known]
