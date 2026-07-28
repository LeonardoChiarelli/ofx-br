"""Linha de comando: ``python -m ofxbr extrato.ofx``."""

from __future__ import annotations

import argparse
import contextlib
import csv
import json
import sys

from . import __version__
from .dedup import dedupe, find_duplicates
from .errors import OfxError
from .parser import parse_file


def _cmd_summary(doc, out) -> None:
    print(f"OFX {doc.version}.x  ·  codificação detectada: {doc.encoding}", file=out)
    for i, stmt in enumerate(doc.statements, 1):
        acct = stmt.account
        name = f" ({acct.bank_name})" if acct.bank_name else ""
        print(f"\nExtrato {i}", file=out)
        print(f"  Banco .......... {acct.bank_id}{name}", file=out)
        print(f"  Agência/Conta .. {acct.branch_id} / {acct.account_id}", file=out)
        print(f"  Moeda .......... {stmt.currency}", file=out)
        if stmt.start and stmt.end:
            print(
                f"  Período ........ {stmt.start.date()} a {stmt.end.date()}",
                file=out,
            )
        print(f"  Lançamentos .... {len(stmt.transactions)}", file=out)
        print(f"  Créditos ....... {stmt.total_credits}", file=out)
        print(f"  Débitos ........ {stmt.total_debits}", file=out)
        if stmt.ledger_balance is not None:
            print(f"  Saldo .......... {stmt.ledger_balance}", file=out)

    dups = find_duplicates(doc.transactions)
    if dups:
        print(
            f"\nAtenção: {len(dups)} FITID aparecem mais de uma vez no arquivo.",
            file=out,
        )
        for fitid, group in list(dups.items())[:10]:
            print(f"  {fitid} ({len(group)}x)", file=out)


def _cmd_json(doc, out) -> None:
    json.dump(doc.as_dict(), out, ensure_ascii=False, indent=2)
    out.write("\n")


def _cmd_csv(doc, out) -> None:
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["banco", "agencia", "conta", "fitid", "data", "valor", "tipo", "historico"])
    for stmt in doc.statements:
        acct = stmt.account
        for t in stmt.transactions:
            writer.writerow(
                [
                    acct.bank_id,
                    acct.branch_id,
                    acct.account_id,
                    t.fitid,
                    t.posted_at.date().isoformat() if t.posted_at else "",
                    str(t.amount),
                    t.type,
                    t.memo,
                ]
            )


def _force_utf8_output() -> None:
    """Faz o console do Windows imprimir acento corretamente.

    O terminal do Windows abre em cp850 ou cp1252 por padrão, e "Itaú" sai como
    "Ita·". O dado está certo: quem não aguenta é o console. `reconfigure` está
    disponível desde o Python 3.7 em `TextIOWrapper`, mas o stdout pode ter sido
    substituído por outro objeto (pytest faz isso), então a checagem é
    necessária.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(ValueError, OSError):
                reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    parser = argparse.ArgumentParser(
        prog="ofxbr",
        description="Lê extrato bancário OFX de banco brasileiro.",
    )
    parser.add_argument("arquivo", help="caminho do .ofx")
    parser.add_argument(
        "--formato",
        choices=("resumo", "json", "csv"),
        default="resumo",
        help="formato de saída (padrão: resumo)",
    )
    parser.add_argument(
        "--dedup",
        action="store_true",
        help="remove lançamentos com FITID repetido antes de exibir",
    )
    parser.add_argument("--version", action="version", version=f"ofx-br {__version__}")
    args = parser.parse_args(argv)

    try:
        doc = parse_file(args.arquivo)
    except OfxError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"erro ao abrir o arquivo: {exc}", file=sys.stderr)
        return 1

    if args.dedup:
        for stmt in doc.statements:
            stmt.transactions = dedupe(stmt.transactions)

    if args.formato == "json":
        _cmd_json(doc, sys.stdout)
    elif args.formato == "csv":
        _cmd_csv(doc, sys.stdout)
    else:
        _cmd_summary(doc, sys.stdout)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
