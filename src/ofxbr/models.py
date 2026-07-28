"""Modelos de dados devolvidos pela leitura."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

__all__ = ["Transaction", "Account", "Statement", "OfxDocument", "BANK_NAMES"]

# Código COMPE dos bancos que mais aparecem em extrato brasileiro. Serve só
# para deixar a saída legível: a leitura não depende disso e um código
# desconhecido não é erro.
BANK_NAMES = {
    "001": "Banco do Brasil",
    "033": "Santander",
    "077": "Banco Inter",
    "104": "Caixa Econômica Federal",
    "208": "BTG Pactual",
    "212": "Banco Original",
    "237": "Bradesco",
    "260": "Nu Pagamentos (Nubank)",
    "290": "PagBank",
    "323": "Mercado Pago",
    "336": "C6 Bank",
    "341": "Itaú Unibanco",
    "356": "Banco Real",
    "364": "Gerencianet",
    "380": "PicPay",
    "422": "Banco Safra",
    "745": "Citibank",
    "748": "Sicredi",
    "756": "Sicoob",
}


@dataclass(slots=True)
class Transaction:
    """Um lançamento do extrato (``STMTTRN``)."""

    fitid: str
    """Identificador único do lançamento atribuído pelo banco.

    É a chave que torna a importação idempotente. Grave com restrição de
    unicidade e verifique antes de inserir: reimportar o mesmo arquivo é o caso
    comum, não a exceção.
    """

    amount: Decimal
    """Valor com sinal. Negativo é saída."""

    posted_at: datetime | None = None
    type: str = ""
    memo: str = ""
    payee: str = ""
    checknum: str = ""
    ref_num: str = ""

    @property
    def is_credit(self) -> bool:
        return self.amount > 0

    @property
    def is_debit(self) -> bool:
        return self.amount < 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "fitid": self.fitid,
            "posted_at": self.posted_at.isoformat() if self.posted_at else None,
            "amount": str(self.amount),
            "type": self.type,
            "memo": self.memo,
            "payee": self.payee,
            "checknum": self.checknum,
            "ref_num": self.ref_num,
        }


@dataclass(slots=True)
class Account:
    """Conta a que o extrato se refere (``BANKACCTFROM`` / ``CCACCTFROM``)."""

    bank_id: str = ""
    branch_id: str = ""
    account_id: str = ""
    account_type: str = ""

    @property
    def bank_name(self) -> str:
        """Nome do banco pelo código COMPE, ou string vazia se desconhecido."""
        return BANK_NAMES.get(self.bank_id.strip().zfill(3), "")

    def as_dict(self) -> dict[str, Any]:
        return {
            "bank_id": self.bank_id,
            "bank_name": self.bank_name,
            "branch_id": self.branch_id,
            "account_id": self.account_id,
            "account_type": self.account_type,
        }


@dataclass(slots=True)
class Statement:
    """Extrato de uma conta dentro do arquivo."""

    account: Account = field(default_factory=Account)
    currency: str = "BRL"
    start: datetime | None = None
    end: datetime | None = None
    ledger_balance: Decimal | None = None
    ledger_balance_date: datetime | None = None
    available_balance: Decimal | None = None
    transactions: list[Transaction] = field(default_factory=list)

    def __iter__(self) -> Iterator[Transaction]:
        return iter(self.transactions)

    def __len__(self) -> int:
        return len(self.transactions)

    @property
    def total_credits(self) -> Decimal:
        return sum((t.amount for t in self.transactions if t.is_credit), Decimal("0"))

    @property
    def total_debits(self) -> Decimal:
        return sum((t.amount for t in self.transactions if t.is_debit), Decimal("0"))

    def as_dict(self) -> dict[str, Any]:
        return {
            "account": self.account.as_dict(),
            "currency": self.currency,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "ledger_balance": str(self.ledger_balance) if self.ledger_balance is not None else None,
            "ledger_balance_date": (
                self.ledger_balance_date.isoformat() if self.ledger_balance_date else None
            ),
            "available_balance": (
                str(self.available_balance) if self.available_balance is not None else None
            ),
            "transactions": [t.as_dict() for t in self.transactions],
        }


@dataclass(slots=True)
class OfxDocument:
    """Arquivo OFX inteiro. Um arquivo pode conter mais de um extrato."""

    statements: list[Statement] = field(default_factory=list)
    header: dict[str, str] = field(default_factory=dict)
    version: int = 1
    encoding: str = ""

    def __iter__(self) -> Iterator[Statement]:
        return iter(self.statements)

    def __len__(self) -> int:
        return len(self.statements)

    @property
    def transactions(self) -> list[Transaction]:
        """Lançamentos de todos os extratos do arquivo, achatados."""
        return [t for s in self.statements for t in s.transactions]

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "encoding": self.encoding,
            "header": self.header,
            "statements": [s.as_dict() for s in self.statements],
        }
