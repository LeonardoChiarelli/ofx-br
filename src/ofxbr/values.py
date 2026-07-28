"""Conversão dos tipos escalares do OFX: data e valor monetário."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from .errors import OfxValueError

__all__ = ["parse_datetime", "parse_amount"]

# AAAAMMDD[HHMMSS][.fff][[offset:FUSO]]
# Exemplos reais de banco brasileiro:
#   20260702
#   20260702120000
#   20260702120000[-3:BRT]
#   20260702120000.000[-03:EST]
_DATETIME = re.compile(
    r"^\s*(\d{4})(\d{2})(\d{2})"
    r"(?:(\d{2})(\d{2})(\d{2}))?"
    r"(?:\.(\d{1,6}))?"
    r"(?:\[\s*([+-]?\d{1,2}(?:\.\d+)?)\s*(?::([^\]]*))?\])?"
    r"\s*$"
)


def parse_datetime(raw: str | None) -> datetime | None:
    """Converte uma data do OFX para ``datetime``.

    O offset de fuso vem entre colchetes e em **horas**, podendo ser
    fracionário (``[-3.5:NST]``). Quem trata o colchete como texto e descarta
    acaba com lançamento no dia errado sempre que a data cai perto da
    meia-noite, que é justamente quando o extrato vira o dia.

    Sem offset declarado, devolve um ``datetime`` ingênuo (sem fuso). A
    biblioteca não inventa America/Sao_Paulo: assumir fuso que o arquivo não
    declarou é como o lançamento acaba um dia fora.
    """
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None

    match = _DATETIME.match(text)
    if not match:
        raise OfxValueError(f"data OFX irreconhecível: {raw!r}")

    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
    hour = int(match.group(4) or 0)
    minute = int(match.group(5) or 0)
    second = int(match.group(6) or 0)
    micro = int((match.group(7) or "0").ljust(6, "0")[:6])

    tzinfo = None
    if match.group(8) is not None:
        offset_hours = float(match.group(8))
        tzinfo = timezone(timedelta(hours=offset_hours), match.group(9) or "")

    try:
        return datetime(year, month, day, hour, minute, second, micro, tzinfo=tzinfo)
    except ValueError as exc:
        raise OfxValueError(f"data OFX fora do calendário: {raw!r}") from exc


def parse_amount(raw: str | None) -> Decimal | None:
    """Converte um valor monetário do OFX para ``Decimal``.

    Sempre ``Decimal``, nunca ``float``: ``0.1 + 0.2`` em ponto flutuante não é
    ``0.3``, e num extrato com milhares de lançamentos esse erro acumula até
    aparecer como divergência de centavos na conciliação.

    A especificação manda usar ponto como separador decimal, mas parte dos
    exportadores brasileiros emite vírgula. Os dois são aceitos aqui, com a
    regra de que o separador decimal é o último que aparecer.
    """
    if raw is None:
        return None
    text = raw.strip().replace(" ", "").replace("\xa0", "")
    if not text:
        return None

    negative = text.startswith("-") or (text.startswith("(") and text.endswith(")"))
    text = text.strip("()").lstrip("+-")

    has_dot, has_comma = "." in text, "," in text
    if has_dot and has_comma:
        # O separador decimal é o que aparecer por último; o outro é milhar.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif has_comma:
        text = text.replace(",", ".")

    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise OfxValueError(f"valor monetário irreconhecível: {raw!r}") from exc

    return -value if negative else value
