from decimal import Decimal

from ingest.excel_reader import ReadReport, WorkbookData
from ingest.loader import load_workbook_data, to_dynamo
from ingest.run_ingest import DEFAULT_FILE, main


class FakeBatch:
    def __init__(self, t): self.t = t
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def put_item(self, Item): self.t.store[(Item["PK"], Item["SK"])] = Item
    def delete_item(self, Key): self.t.store.pop((Key["PK"], Key["SK"]), None)


class FakeTable:
    def __init__(self): self.store = {}; self.queries = 0
    def batch_writer(self): return FakeBatch(self)
    def query(self, **kw):
        self.queries += 1
        sheet = kw["KeyConditionExpression"]._values[1]
        return {"Items": [{"PK": p, "SK": s} for (p, s), v in self.store.items() if v["sheet"] == sheet]}


def wb(sheets):
    return WorkbookData(sheets=sheets, columns={}, auth_sheets={"role_user": [{"Password": "x"}]}, report=ReadReport())


Q2 = {"tofas_etadate": "t1", "supplier_code": "1", "shipment_id": "S1", "materialno": "M1", "quantity": 5, "mip": "9",
      "question2": '{"Malzeme no": "M1", "Seferle": [{"seferno": "S1", "mikta": 5.0, "Eta Zamanı": "t1"}]}'}


def test_dry_run_no_table_and_report():
    bad = dict(Q2, materialno="M2", question2="{bozuk")
    r = load_workbook_data(wb({"question2": [Q2, bad], "summary_df": [{"Durum": "a", "Adet": 1}]}))
    c = r.sheets["question2"]
    assert (c.read, c.loaded, c.skipped) == (2, 1, 1)
    assert [(i.sheet, i.row, i.kind) for i in r.skipped] == [("question2", 3, "invalid_json")]
    assert "role_user" not in r.sheets and not r.applied


def test_question2_mismatch_reported_but_loaded():
    row = dict(Q2, quantity=6, materialno="M1")
    r = load_workbook_data(wb({"question2": [row]}))
    assert r.sheets["question2"].loaded == 1
    assert [w.kind for w in r.warnings] == ["q2_quantity_mismatch"]


def test_apply_idempotent_decimal_and_parsed():
    t = FakeTable()
    sheets = {"question2": [Q2], "question4": [{"shipment_id": "S", "delay_time": 76.5, "question4": '{"a": 1.5}'}]}
    load_workbook_data(wb(sheets), apply=True, table=t)
    n = len(t.store)
    r = load_workbook_data(wb(sheets), apply=True, table=t)
    assert len(t.store) == n == 2 and r.sheets["question2"].deleted == 1
    it = t.store[("question4#ALL", "0000")]
    assert it["data"]["delay_time"] == Decimal("76.5") and it["data"]["question4_parsed"] == {"a": Decimal("1.5")}
    assert t.store[("question2#M1", "S1")]["sheet"] == "question2"


def test_to_dynamo_nan():
    assert to_dynamo(float("nan")) is None


def test_real_file_dry_run(capsys):
    if not DEFAULT_FILE.exists():
        return
    assert main(["--file", str(DEFAULT_FILE)]) == 0
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and "question1" in out and "role_user" not in out
