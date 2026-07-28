"""Testes de ofx-br.

As fixtures são sintéticas (ver ``tests/make_fixtures.py``), escritas para
exercitar cada variação de formato que o README descreve. Nenhuma delas é um
extrato real, e nenhuma contém dado de pessoa ou empresa.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

import ofxbr
from ofxbr import dedup, encoding, sgml
from ofxbr.errors import OfxHeaderError, OfxParseError, OfxValueError

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# --------------------------------------------------------------------------
# Codificação
# --------------------------------------------------------------------------


class TestEncoding:
    def test_charset_1252_vira_cp1252(self):
        detected = encoding.detect(load("sgml_unclosed_cp1252.ofx"))
        assert detected.codec == "cp1252"
        assert detected.version == 1
        assert detected.declared_encoding == "USASCII"
        assert detected.declared_charset == "1252"

    def test_ofx2_usa_declaracao_xml(self):
        detected = encoding.detect(load("ofx2_xml_utf8.ofx"))
        assert detected.codec == "utf-8"
        assert detected.version == 2

    def test_acento_sobrevive_a_leitura(self):
        doc = ofxbr.parse_bytes(load("sgml_unclosed_cp1252.ofx"))
        memos = [t.memo for t in doc.transactions]
        assert "PAGAMENTO FORNECEDOR MANUTENÇÃO" in memos
        assert "TARIFA MANUTENÇÃO CONTA" in memos

    def test_utf8_falharia_neste_arquivo(self):
        """Prova de que o problema que a lib resolve é real."""
        raw = load("sgml_unclosed_cp1252.ofx")
        with pytest.raises(UnicodeDecodeError):
            raw.decode("utf-8")

    def test_cabecalho_sem_charset_cai_no_padrao(self):
        raw = b"OFXHEADER:100\r\nDATA:OFXSGML\r\n\r\n<OFX><X>1</X></OFX>"
        assert encoding.detect(raw).codec == "cp1252"

    def test_arquivo_vazio(self):
        with pytest.raises(OfxHeaderError):
            encoding.split_header(b"   ")

    def test_arquivo_sem_tag(self):
        with pytest.raises(OfxHeaderError):
            encoding.split_header(b"isto nao e um ofx")


# --------------------------------------------------------------------------
# SGML
# --------------------------------------------------------------------------


class TestSgml:
    def test_folha_sem_fechamento(self):
        root = sgml.parse_sgml("<OFX><A><B>valor\n</A></OFX>")
        assert root.text("B") == "valor"

    def test_folha_com_fechamento(self):
        root = sgml.parse_sgml("<OFX><A><B>valor</B></A></OFX>")
        assert root.text("B") == "valor"

    def test_folha_vazia_vira_string_vazia(self):
        root = sgml.parse_sgml("<OFX><A><B></B></A></OFX>")
        assert root.text("B") == ""

    def test_agregado_aninhado(self):
        root = sgml.parse_sgml("<OFX><A><B><C>1\n</B></A></OFX>")
        assert root.find("A").find("B").text("C") == "1"

    def test_findall_nao_desce_no_que_ja_casou(self):
        root = sgml.parse_sgml("<OFX><L><T><X>1\n</T><T><X>2\n</T></L></OFX>")
        assert len(root.findall("T")) == 2

    def test_corpo_sem_tag(self):
        with pytest.raises(OfxParseError):
            sgml.parse_sgml("texto solto")

    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("SILVA &amp; SILVA", "SILVA & SILVA"),
            ("A &lt;B&gt; C", "A <B> C"),
            ("&#65;&#66;", "AB"),
            ("&#x41;", "A"),
            # Conservador de propósito: "&nbsp" sem ponto e vírgula fica intacto.
            ("PAGTO &nbsp COISA", "PAGTO &nbsp COISA"),
            ("R$ 10 & 20", "R$ 10 & 20"),
        ],
    )
    def test_desescapamento(self, entrada, esperado):
        assert sgml.unescape(entrada) == esperado


# --------------------------------------------------------------------------
# Data e valor
# --------------------------------------------------------------------------


class TestValues:
    def test_data_com_fuso_entre_colchetes(self):
        got = ofxbr.parse_datetime("20260702000000[-3:BRT]")
        assert got == datetime(2026, 7, 2, tzinfo=timezone(timedelta(hours=-3), "BRT"))

    def test_data_com_fuso_fracionario(self):
        got = ofxbr.parse_datetime("20260702000000[-3.5:NST]")
        assert got.utcoffset() == timedelta(hours=-3.5)

    def test_data_sem_hora(self):
        assert ofxbr.parse_datetime("20260702") == datetime(2026, 7, 2)

    def test_data_sem_fuso_fica_ingenua(self):
        """Não inventamos fuso: assumir um é como o lançamento cai no dia errado."""
        assert ofxbr.parse_datetime("20260702120000").tzinfo is None

    def test_data_com_milissegundo(self):
        got = ofxbr.parse_datetime("20260702120000.123[-3:BRT]")
        assert got.microsecond == 123000

    def test_data_invalida(self):
        with pytest.raises(OfxValueError):
            ofxbr.parse_datetime("02/07/2026")

    def test_data_fora_do_calendario(self):
        with pytest.raises(OfxValueError):
            ofxbr.parse_datetime("20260230")

    def test_data_vazia(self):
        assert ofxbr.parse_datetime("") is None
        assert ofxbr.parse_datetime(None) is None

    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("-150.00", Decimal("-150.00")),
            ("2500.50", Decimal("2500.50")),
            ("1.234,56", Decimal("1234.56")),
            ("1,234.56", Decimal("1234.56")),
            ("-1.000,00", Decimal("-1000.00")),
            ("1234,5", Decimal("1234.5")),
            ("+42", Decimal("42")),
            ("(35.00)", Decimal("-35.00")),
            ("0", Decimal("0")),
        ],
    )
    def test_valor(self, entrada, esperado):
        assert ofxbr.parse_amount(entrada) == esperado

    def test_valor_e_decimal_nunca_float(self):
        assert isinstance(ofxbr.parse_amount("0.1"), Decimal)

    def test_soma_nao_acumula_erro_de_ponto_flutuante(self):
        total = sum(ofxbr.parse_amount(v) for v in ["0.1", "0.2"])
        assert total == Decimal("0.3")

    def test_valor_invalido(self):
        with pytest.raises(OfxValueError):
            ofxbr.parse_amount("abc")


# --------------------------------------------------------------------------
# Leitura completa
# --------------------------------------------------------------------------


class TestParse:
    def test_sgml_sem_fechamento(self):
        doc = ofxbr.parse_bytes(load("sgml_unclosed_cp1252.ofx"))
        assert doc.version == 1
        assert len(doc.statements) == 1

        stmt = doc.statements[0]
        assert stmt.currency == "BRL"
        assert stmt.account.bank_id == "341"
        assert stmt.account.bank_name == "Itaú Unibanco"
        assert stmt.account.branch_id == "1234"
        assert stmt.account.account_id == "56789-0"
        assert len(stmt) == 3
        assert stmt.ledger_balance == Decimal("2260.60")

    def test_totais_batem_com_o_saldo(self):
        stmt = ofxbr.parse_bytes(load("sgml_unclosed_cp1252.ofx")).statements[0]
        assert stmt.total_credits == Decimal("2500.50")
        assert stmt.total_debits == Decimal("-239.90")
        assert stmt.total_credits + stmt.total_debits == stmt.ledger_balance

    def test_primeiro_lancamento(self):
        t = ofxbr.parse_bytes(load("sgml_unclosed_cp1252.ofx")).transactions[0]
        assert t.fitid == "202607020001"
        assert t.amount == Decimal("-150.00")
        assert t.type == "DEBIT"
        assert t.is_debit and not t.is_credit
        assert t.posted_at.date() == datetime(2026, 7, 2).date()

    def test_tags_fechadas(self):
        doc = ofxbr.parse_bytes(load("sgml_closed_tags.ofx"))
        stmt = doc.statements[0]
        assert stmt.account.bank_name == "Bradesco"
        assert len(stmt) == 1
        assert stmt.transactions[0].memo == "COMPRA CARTÃO"

    def test_virgula_decimal(self):
        doc = ofxbr.parse_bytes(load("sgml_comma_decimal.ofx"))
        valores = [t.amount for t in doc.transactions]
        assert valores == [Decimal("1234.56"), Decimal("-1000.00")]
        assert doc.statements[0].account.bank_name == "Caixa Econômica Federal"

    def test_ofx2_xml(self):
        doc = ofxbr.parse_bytes(load("ofx2_xml_utf8.ofx"))
        assert doc.version == 2
        stmt = doc.statements[0]
        assert stmt.account.bank_name == "Santander"
        assert stmt.transactions[0].amount == Decimal("310.75")
        assert stmt.transactions[0].memo == "ESTORNO DE TARIFA"

    def test_entidades_no_historico(self):
        doc = ofxbr.parse_bytes(load("sgml_entities.ofx"))
        assert doc.transactions[0].memo == "SILVA & SILVA LTDA"

    def test_historico_vazio_nao_derruba(self):
        doc = ofxbr.parse_bytes(load("sgml_entities.ofx"))
        assert doc.transactions[1].memo == ""
        assert doc.transactions[1].amount == Decimal("-30.00")

    def test_parse_de_caminho(self):
        doc = ofxbr.parse(str(FIXTURES / "sgml_unclosed_cp1252.ofx"))
        assert len(doc.transactions) == 3

    def test_parse_de_arquivo_aberto(self):
        with open(FIXTURES / "sgml_unclosed_cp1252.ofx", "rb") as handle:
            assert len(ofxbr.parse_file(handle).transactions) == 3

    def test_arquivo_sem_extrato(self):
        with pytest.raises(OfxParseError, match="nenhum extrato"):
            ofxbr.parse_bytes(b"OFXHEADER:100\r\n\r\n<OFX><SIGNONMSGSRSV1></SIGNONMSGSRSV1></OFX>")

    def test_as_dict_serializa(self):
        import json

        doc = ofxbr.parse_bytes(load("sgml_unclosed_cp1252.ofx"))
        blob = json.dumps(doc.as_dict(), ensure_ascii=False)
        assert "202607020001" in blob
        assert "-150.00" in blob


# --------------------------------------------------------------------------
# Deduplicação
# --------------------------------------------------------------------------


class TestDedup:
    def test_fitid_repetido_e_removido(self):
        doc = ofxbr.parse_bytes(load("sgml_duplicated_fitid.ofx"))
        assert len(doc.transactions) == 3
        assert len(dedup.dedupe(doc.transactions)) == 2

    def test_find_duplicates_aponta_o_fitid(self):
        doc = ofxbr.parse_bytes(load("sgml_duplicated_fitid.ofx"))
        dups = dedup.find_duplicates(doc.transactions)
        assert list(dups) == ["DUP-1"]
        assert len(dups["DUP-1"]) == 2

    def test_impressao_digital_pega_o_fitid_reemitido(self):
        """O terceiro lançamento tem FITID novo mas é o mesmo evento."""
        doc = ofxbr.parse_bytes(load("sgml_duplicated_fitid.ofx"))
        assert len(dedup.dedupe(doc.transactions, use_fingerprint=True)) == 1

    def test_impressao_digital_ignora_hora_e_numero_longo(self):
        doc = ofxbr.parse_bytes(load("sgml_duplicated_fitid.ofx"))
        a, _b, c = doc.transactions
        assert dedup.fingerprint(a) == dedup.fingerprint(c)

    def test_dedupe_preserva_a_ordem(self):
        doc = ofxbr.parse_bytes(load("sgml_duplicated_fitid.ofx"))
        got = dedup.dedupe(doc.transactions)
        assert [t.fitid for t in got] == ["DUP-1", "DUP-1-EFETIVADO"]

    def test_new_since_e_a_chave_da_idempotencia(self):
        doc = ofxbr.parse_bytes(load("sgml_unclosed_cp1252.ofx"))
        ja_gravados = {"202607020001"}
        novos = dedup.new_since(doc.transactions, ja_gravados)
        assert [t.fitid for t in novos] == ["202607050002", "202607100003"]

    def test_reimportar_o_mesmo_arquivo_nao_gera_nada_novo(self):
        doc = ofxbr.parse_bytes(load("sgml_unclosed_cp1252.ofx"))
        gravados = {t.fitid for t in doc.transactions}
        de_novo = ofxbr.parse_bytes(load("sgml_unclosed_cp1252.ofx"))
        assert dedup.new_since(de_novo.transactions, gravados) == []


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


class TestCli:
    def test_resumo(self, capsys):
        from ofxbr.__main__ import main

        assert main([str(FIXTURES / "sgml_unclosed_cp1252.ofx")]) == 0
        out = capsys.readouterr().out
        assert "Itaú Unibanco" in out
        assert "cp1252" in out

    def test_json(self, capsys):
        import json

        from ofxbr.__main__ import main

        assert main([str(FIXTURES / "ofx2_xml_utf8.ofx"), "--formato", "json"]) == 0
        parsed = json.loads(capsys.readouterr().out)
        assert parsed["version"] == 2

    def test_csv(self, capsys):
        from ofxbr.__main__ import main

        assert main([str(FIXTURES / "sgml_unclosed_cp1252.ofx"), "--formato", "csv"]) == 0
        linhas = capsys.readouterr().out.strip().splitlines()
        assert linhas[0].startswith("banco,agencia,conta,fitid")
        assert len(linhas) == 4

    def test_dedup_na_cli(self, capsys):
        from ofxbr.__main__ import main

        args = [str(FIXTURES / "sgml_duplicated_fitid.ofx"), "--formato", "csv", "--dedup"]
        assert main(args) == 0
        assert len(capsys.readouterr().out.strip().splitlines()) == 3

    def test_arquivo_inexistente(self, capsys):
        from ofxbr.__main__ import main

        assert main(["nao_existe.ofx"]) == 1
        assert "erro" in capsys.readouterr().err
