"""Ponto de entrada da leitura: bytes ou caminho -> :class:`OfxDocument`."""

from __future__ import annotations

import os
from typing import IO, Any

from . import encoding as _encoding
from . import sgml
from .errors import OfxParseError
from .models import Account, OfxDocument, Statement, Transaction
from .values import parse_amount, parse_datetime

__all__ = ["parse", "parse_file", "parse_bytes", "parse_string"]

# Agregados que descrevem a conta, por tipo de extrato.
_ACCT_TAGS = ("BANKACCTFROM", "CCACCTFROM")
# Agregados que contêm um extrato.
_STMT_TAGS = ("STMTRS", "CCSTMTRS")


def _build_account(stmt: sgml.Node) -> Account:
    node = None
    for tag in _ACCT_TAGS:
        node = stmt.find(tag)
        if node is not None:
            break
    if node is None:
        return Account()
    return Account(
        bank_id=node.text("BANKID", "") or "",
        branch_id=node.text("BRANCHID", "") or "",
        # Cartão de crédito usa ACCTID no CCACCTFROM do mesmo jeito.
        account_id=node.text("ACCTID", "") or "",
        account_type=node.text("ACCTTYPE", "") or "",
    )


def _build_transaction(node: sgml.Node) -> Transaction | None:
    amount = parse_amount(node.text("TRNAMT"))
    if amount is None:
        # Lançamento sem valor não é lançamento. Melhor descartar do que
        # importar uma linha de R$ 0,00 que ninguém consegue explicar depois.
        return None

    fitid = (node.text("FITID", "") or "").strip()
    return Transaction(
        fitid=fitid,
        amount=amount,
        posted_at=parse_datetime(node.text("DTPOSTED")),
        type=(node.text("TRNTYPE", "") or "").strip().upper(),
        memo=(node.text("MEMO", "") or "").strip(),
        payee=(node.text("NAME", "") or "").strip(),
        checknum=(node.text("CHECKNUM", "") or "").strip(),
        ref_num=(node.text("REFNUM", "") or "").strip(),
    )


def _build_statement(stmt: sgml.Node) -> Statement:
    tranlist = stmt.find("BANKTRANLIST") or stmt.find("CCTRANLIST")

    transactions: list[Transaction] = []
    if tranlist is not None:
        for node in tranlist.findall("STMTTRN"):
            built = _build_transaction(node)
            if built is not None:
                transactions.append(built)

    ledger = stmt.find("LEDGERBAL")
    available = stmt.find("AVAILBAL")

    return Statement(
        account=_build_account(stmt),
        currency=(stmt.text("CURDEF", "BRL") or "BRL").strip().upper(),
        start=parse_datetime(tranlist.text("DTSTART")) if tranlist else None,
        end=parse_datetime(tranlist.text("DTEND")) if tranlist else None,
        ledger_balance=parse_amount(ledger.text("BALAMT")) if ledger else None,
        ledger_balance_date=parse_datetime(ledger.text("DTASOF")) if ledger else None,
        available_balance=parse_amount(available.text("BALAMT")) if available else None,
        transactions=transactions,
    )


def parse_bytes(raw: bytes) -> OfxDocument:
    """Lê um OFX a partir dos bytes crus. É por aqui que tudo passa."""
    header, body, detected = _encoding.decode(raw)

    root = sgml.parse_xml(body) if detected.version == 2 else sgml.parse_sgml(body)

    statements: list[Statement] = []
    for tag in _STMT_TAGS:
        for node in root.findall(tag):
            statements.append(_build_statement(node))

    if not statements:
        raise OfxParseError(
            "nenhum extrato encontrado no arquivo (esperado STMTRS ou CCSTMTRS dentro de OFX)"
        )

    return OfxDocument(
        statements=statements,
        header=header,
        version=detected.version,
        encoding=detected.codec,
    )


def parse_string(text: str) -> OfxDocument:
    """Lê um OFX já decodificado. Prefira :func:`parse_bytes` quando possível.

    Se o texto já chegou como ``str``, alguém escolheu uma codificação antes de
    você, e essa escolha é exatamente onde o extrato brasileiro costuma quebrar.
    """
    return parse_bytes(text.encode("utf-8"))


def parse_file(path: str | os.PathLike[str] | IO[bytes]) -> OfxDocument:
    """Lê um OFX de um caminho ou de um arquivo aberto em modo binário."""
    if hasattr(path, "read"):
        data: Any = path.read()  # type: ignore[union-attr]
        if isinstance(data, str):
            return parse_string(data)
        return parse_bytes(data)
    with open(path, "rb") as handle:
        return parse_bytes(handle.read())


def parse(source: str | bytes | os.PathLike[str] | IO[bytes]) -> OfxDocument:
    """Lê um OFX de bytes, caminho ou arquivo aberto.

    >>> doc = parse("extrato.ofx")
    >>> for lancamento in doc.transactions:
    ...     print(lancamento.fitid, lancamento.amount)
    """
    if isinstance(source, bytes):
        return parse_bytes(source)
    if isinstance(source, str) and ("<" in source and ">" in source):
        # Conteúdo colado direto em vez de caminho.
        return parse_string(source)
    return parse_file(source)
