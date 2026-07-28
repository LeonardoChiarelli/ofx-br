"""Exceções da biblioteca."""

from __future__ import annotations


class OfxError(Exception):
    """Base de todos os erros de ofx-br."""


class OfxHeaderError(OfxError):
    """Cabeçalho ausente ou irreconhecível."""


class OfxParseError(OfxError):
    """Corpo do arquivo não pôde ser interpretado."""


class OfxValueError(OfxError):
    """Um campo existe mas o valor não é interpretável (data, valor monetário)."""
