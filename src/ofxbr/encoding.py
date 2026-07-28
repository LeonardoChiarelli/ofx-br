"""Detecção de codificação e separação entre cabeçalho e corpo do OFX.

O cabeçalho do OFX 1.x é um bloco de linhas ``CHAVE:VALOR`` em ASCII puro,
terminado por uma linha em branco. Só depois dele começa o SGML. Isso permite
ler o cabeçalho como ASCII com segurança e só então decidir como decodificar o
resto do arquivo.

O par que aparece na maioria dos extratos de banco brasileiro é::

    ENCODING:USASCII
    CHARSET:1252

O que, lido ao pé da letra, é contraditório: o arquivo declara US-ASCII e em
seguida declara a página de código 1252, que não é ASCII. Na prática os bytes
são cp1252 (ou latin-1, que é um subconjunto compatível na faixa imprimível).
Decodificar como UTF-8 nesse caso levanta ``UnicodeDecodeError`` no primeiro
acento, e é a causa mais comum de "o arquivo do banco veio corrompido".
"""

from __future__ import annotations

import re

from .errors import OfxHeaderError

__all__ = ["detect", "split_header", "DetectedEncoding"]

# CHARSET declarado no cabeçalho -> codec do Python.
_CHARSET_CODECS = {
    "1252": "cp1252",
    "WINDOWS-1252": "cp1252",
    "CP1252": "cp1252",
    "8859-1": "latin-1",
    "ISO-8859-1": "latin-1",
    "LATIN-1": "latin-1",
    "NONE": "cp1252",
}

# ENCODING declarado no cabeçalho -> codec do Python.
_ENCODING_CODECS = {
    "UTF-8": "utf-8",
    "UTF8": "utf-8",
    "USASCII": None,  # inconclusivo por si só: quem decide é o CHARSET
    "US-ASCII": None,
    "ASCII": None,
}

# Fallback quando o cabeçalho não diz nada útil. cp1252 decodifica qualquer
# sequência de bytes sem levantar exceção, então nunca falha por acidente.
_DEFAULT_CODEC = "cp1252"

_HEADER_LINE = re.compile(rb"^([A-Z]+):(.*)$")


class DetectedEncoding:
    """Resultado da detecção, com o rastro de como foi decidido."""

    __slots__ = ("codec", "declared_encoding", "declared_charset", "version", "reason")

    def __init__(
        self,
        codec: str,
        declared_encoding: str | None,
        declared_charset: str | None,
        version: int,
        reason: str,
    ) -> None:
        self.codec = codec
        self.declared_encoding = declared_encoding
        self.declared_charset = declared_charset
        self.version = version
        self.reason = reason

    def __repr__(self) -> str:  # pragma: no cover - conveniência de debug
        return (
            f"DetectedEncoding(codec={self.codec!r}, version={self.version}, "
            f"reason={self.reason!r})"
        )


def _is_ofx2(raw: bytes) -> bool:
    """OFX 2.x é XML de verdade e começa com a declaração XML ou com ``<?OFX``."""
    head = raw.lstrip()[:200].upper()
    return head.startswith(b"<?XML") or head.startswith(b"<?OFX")


def _parse_header_lines(raw_header: bytes) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in raw_header.splitlines():
        match = _HEADER_LINE.match(line.strip())
        if match:
            key = match.group(1).decode("ascii")
            value = match.group(2).decode("ascii", errors="replace").strip()
            fields[key] = value
    return fields


def split_header(raw: bytes) -> tuple[dict[str, str], bytes, int]:
    """Separa cabeçalho e corpo.

    Devolve ``(campos_do_cabecalho, corpo_em_bytes, versao_ofx)``. Para OFX 2.x
    os campos saem dos atributos da instrução ``<?OFX ...?>`` e o corpo é o
    documento XML inteiro.
    """
    if not raw.strip():
        raise OfxHeaderError("arquivo vazio")

    if _is_ofx2(raw):
        fields: dict[str, str] = {}
        proc = re.search(rb"<\?OFX([^?]*)\?>", raw[:2000], re.IGNORECASE)
        if proc:
            attrs = proc.group(1).decode("ascii", errors="replace")
            for key, value in re.findall(r'([A-Za-z]+)\s*=\s*"([^"]*)"', attrs):
                fields[key.upper()] = value
        return fields, raw, 2

    # OFX 1.x: o corpo começa no primeiro '<'. Tudo antes é cabeçalho.
    start = raw.find(b"<")
    if start == -1:
        raise OfxHeaderError("nenhuma tag encontrada: o arquivo não parece ser OFX")

    fields = _parse_header_lines(raw[:start])
    if not fields:
        # Alguns exportadores omitem o cabeçalho por completo. O corpo ainda é
        # SGML válido, então seguimos com o codec padrão em vez de recusar.
        return {}, raw[start:], 1

    return fields, raw[start:], 1


def detect(raw: bytes) -> DetectedEncoding:
    """Decide qual codec usar para decodificar o corpo do arquivo."""
    fields, _body, version = split_header(raw)

    declared_encoding = fields.get("ENCODING")
    declared_charset = fields.get("CHARSET")

    if version == 2:
        # OFX 2.x é XML; a declaração XML manda, e o padrão do XML é UTF-8.
        match = re.search(rb'encoding\s*=\s*"([^"]+)"', raw[:200], re.IGNORECASE)
        codec = match.group(1).decode("ascii").lower() if match else "utf-8"
        return DetectedEncoding(
            codec, declared_encoding, declared_charset, 2, "declaração XML do OFX 2.x"
        )

    if declared_charset:
        codec = _CHARSET_CODECS.get(declared_charset.upper())
        if codec:
            return DetectedEncoding(
                codec, declared_encoding, declared_charset, 1, f"CHARSET:{declared_charset}"
            )

    if declared_encoding:
        codec = _ENCODING_CODECS.get(declared_encoding.upper())
        if codec:
            return DetectedEncoding(
                codec, declared_encoding, declared_charset, 1, f"ENCODING:{declared_encoding}"
            )

    return DetectedEncoding(
        _DEFAULT_CODEC,
        declared_encoding,
        declared_charset,
        1,
        "cabeçalho inconclusivo, usando o padrão cp1252",
    )


def decode(raw: bytes) -> tuple[dict[str, str], str, DetectedEncoding]:
    """Detecta a codificação e devolve ``(cabeçalho, corpo_str, deteccao)``."""
    detected = detect(raw)
    fields, body, _version = split_header(raw)
    # errors="replace" de propósito: um byte solto fora da página de código não
    # pode derrubar a leitura de um extrato inteiro. O caractere vira U+FFFD e
    # segue visível para quem for revisar.
    return fields, body.decode(detected.codec, errors="replace"), detected
