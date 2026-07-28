"""Leitura do corpo SGML do OFX 1.x.

O OFX 1.x **não é XML**. Ele usa uma sintaxe derivada de SGML em que as tags
folha dispensam fechamento::

    <STMTTRN>
    <TRNTYPE>DEBIT
    <TRNAMT>-150.00
    <FITID>202607020001
    </STMTTRN>

Passar isso para um parser de XML resulta em "documento malformado", e é daí
que vem a conclusão equivocada de que o arquivo do banco veio corrompido. O
arquivo está íntegro: a ferramenta é que está errada.

Regra de desambiguação usada aqui, que é a mesma que a especificação implica:

* ``<TAG>`` seguido de texto antes da próxima tag  -> folha, com aquele valor
* ``<TAG>`` seguido imediatamente de outra tag     -> agregado (tem filhos)
* ``</TAG>``                                       -> fecha o agregado aberto

Alguns exportadores fecham também as folhas (``<FITID>1</FITID>``). Isso é
válido e está tratado.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .errors import OfxParseError

__all__ = ["Node", "parse_sgml", "parse_xml"]

_TOKEN = re.compile(r"<\s*(/?)\s*([A-Za-z0-9_.:-]+)[^>]*>")

# Desescapamento conservador. `html.unescape` é agressivo demais para texto de
# extrato: ele converteria "&nbsp" sem ponto e vírgula e outras sequências que
# aparecem literalmente em histórico de lançamento. Aqui só tratamos as
# entidades que o OFX realmente usa.
_ENTITIES = {
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&apos;": "'",
    "&nbsp;": " ",
}
_NUMERIC_ENTITY = re.compile(r"&#(x?)([0-9A-Fa-f]+);")


def unescape(text: str) -> str:
    """Converte as entidades que aparecem em OFX, e só elas."""
    for entity, char in _ENTITIES.items():
        text = text.replace(entity, char)

    def _replace(match: re.Match[str]) -> str:
        base = 16 if match.group(1) else 10
        try:
            return chr(int(match.group(2), base))
        except (ValueError, OverflowError):
            return match.group(0)

    return _NUMERIC_ENTITY.sub(_replace, text)


class Node:
    """Nó da árvore. Ou tem ``value`` (folha) ou tem ``children`` (agregado)."""

    __slots__ = ("tag", "value", "children")

    def __init__(self, tag: str, value: str | None = None) -> None:
        self.tag = tag.upper()
        self.value = value
        self.children: list[Node] = []

    # -- navegação -------------------------------------------------------

    def find(self, tag: str) -> Node | None:
        """Primeiro descendente com essa tag, em busca em profundidade."""
        tag = tag.upper()
        for child in self.children:
            if child.tag == tag:
                return child
            found = child.find(tag)
            if found is not None:
                return found
        return None

    def findall(self, tag: str) -> list[Node]:
        """Todos os descendentes com essa tag."""
        tag = tag.upper()
        out: list[Node] = []
        for child in self.children:
            if child.tag == tag:
                out.append(child)
            else:
                # Não desce dentro de um nó que já casou: evita aninhar
                # STMTTRN dentro de STMTTRN em arquivos malformados.
                out.extend(child.findall(tag))
        return out

    def text(self, tag: str, default: str | None = None) -> str | None:
        """Valor da primeira folha com essa tag."""
        node = self.find(tag)
        if node is None or node.value is None:
            return default
        return node.value

    def __repr__(self) -> str:  # pragma: no cover - conveniência de debug
        if self.value is not None:
            return f"<{self.tag}>{self.value!r}"
        return f"<{self.tag} children={len(self.children)}>"


def parse_sgml(body: str) -> Node:
    """Interpreta o corpo do OFX 1.x e devolve a raiz da árvore."""
    root = Node("__ROOT__")
    stack: list[Node] = [root]
    pos = 0

    for match in _TOKEN.finditer(body):
        closing, tag = match.group(1) == "/", match.group(2).upper()

        # O texto entre a tag anterior e esta é o valor da tag anterior.
        between = body[pos : match.start()]
        pos = match.end()

        if between.strip() and stack[-1] is not root:
            current = stack[-1]
            if current.value is None and not current.children:
                current.value = unescape(between.strip())

        if closing:
            # Fecha o agregado correspondente. Tolera tag de fechamento órfã
            # (alguns exportadores fecham folha que já foi resolvida acima).
            for depth in range(len(stack) - 1, 0, -1):
                if stack[depth].tag == tag:
                    del stack[depth:]
                    break
            continue

        node = Node(tag)
        stack[-1].children.append(node)
        stack.append(node)

    if not root.children:
        raise OfxParseError("nenhuma tag encontrada no corpo do arquivo")

    _collapse_empty(root)
    ofx = root.find("OFX")
    return ofx if ofx is not None else root


def _collapse_empty(node: Node) -> None:
    """Normaliza folha vazia (``<MEMO></MEMO>``) para valor string vazia.

    Sem isso, um campo vazio fecha como agregado sem filhos e some do modelo,
    o que é pior que aparecer como texto vazio.
    """
    for child in node.children:
        _collapse_empty(child)
    if node.value is None and not node.children and node.tag != "__ROOT__":
        node.value = ""


def _from_element(element: ET.Element) -> Node:
    tag = element.tag.split("}")[-1]
    node = Node(tag)
    children = list(element)
    if children:
        for child in children:
            node.children.append(_from_element(child))
    else:
        node.value = (element.text or "").strip()
    return node


def parse_xml(body: str) -> Node:
    """Interpreta o corpo do OFX 2.x, que é XML válido."""
    try:
        element = ET.fromstring(body)
    except ET.ParseError as exc:  # pragma: no cover - depende de arquivo inválido
        raise OfxParseError(f"OFX 2.x inválido: {exc}") from exc
    return _from_element(element)
