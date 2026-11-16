import base64
import io
import os
import tempfile
import unittest

_TEMP = tempfile.TemporaryDirectory(prefix="medstock-requests-")
os.environ["DATABASE_URL"] = "sqlite:///" + _TEMP.name.replace("\\", "/") + "/test.db"
os.environ["JWT_SECRET"] = "isolated-stock-request-test-secret-not-for-production"

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import SQLModel, Session, select

from auth import router as auth_router, token_yarat
from database import engine
from models import Medicine, Notification, Point, Region, StockMovement, User, UserRegion
from routes_stock import bu_gun, nokte_qaliqi
from routes_stock_requests import router
from routes_history import router as history_router

app = FastAPI()
app.include_router(auth_router)
app.include_router(router)
app.include_router(history_router)


def tearDownModule():
    engine.dispose()
    _TEMP.cleanup()


class StockRequestTests(unittest.TestCase):
    def setUp(self):
        assert engine.url.get_backend_name() == "sqlite" and _TEMP.name.replace("\\", "/") in engine.url.database
        SQLModel.metadata.drop_all(engine)
        SQLModel.metadata.create_all(engine)
        self.client = TestClient(app)
        with Session(engine) as s:
            users = [User(id=1, login="manager1", ad="Manager One", rol="manager", parol_hash="unused"),
                     User(id=2, login="manager2", ad="Manager Two", rol="manager", parol_hash="unused"),
                     User(id=3, login="rep1", ad="Rep One", rol="representative", manager_id=1, parol_hash="unused"),
                     User(id=4, login="rep2", ad="Rep Two", rol="representative", manager_id=2, parol_hash="unused"),
                     User(id=5, login="lone", ad="Lone Rep", rol="representative", parol_hash="unused"),
                     User(id=6, login="admin", ad="Admin", rol="admin", parol_hash="unused")]
            for u in users:
                s.add(u)
            s.add(Region(id=1, ad="Region One")); s.add(Region(id=2, ad="Region Two"))
            s.commit()
            for uid, rid in [(3, 1), (4, 2), (5, 1)]:
                s.add(UserRegion(user_id=uid, region_id=rid))
            for p in [Point(id=1, ad="Pharmacy One", novu="aptek", region_id=1), Point(id=2, ad="Pharmacy Two", novu="aptek", region_id=1), Point(id=3, ad="Depot", novu="depo", region_id=1), Point(id=4, ad="Other Pharmacy", novu="aptek", region_id=2), Point(id=5, ad="Inactive", novu="aptek", region_id=1, active=False)]:
                s.add(p)
            for d in [Medicine(id=1, ad="Low Medicine"), Medicine(id=2, ad="Normal Medicine"), Medicine(id=3, ad="Inactive Medicine", active=False)]:
                s.add(d)
            s.commit()
            for pid in (1, 2, 3):
                s.add(StockMovement(point_id=pid, medicine_id=2, user_id=3, novu="daxilolma", say=100, tarix=bu_gun()))
            s.add(StockMovement(point_id=1, medicine_id=1, user_id=3, novu="daxilolma", say=5, tarix=bu_gun()))
            s.commit()
            self.headers = {u.id: {"Authorization": "Bearer " + token_yarat(u)} for u in users}

    def call(self, method, path, uid=3, body=None):
        return self.client.request(method, path, headers=self.headers[uid], json=body)

    def create(self, rows=None, uid=3):
        rows = [{"point_id": 1, "medicine_id": 1, "say": 30}] if rows is None else rows
        r = self.call("POST", "/stock-requests", uid, {"setirler": rows})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["id"]

    def submit(self, rid):
        r = self.call("POST", f"/stock-requests/{rid}/submit")
        self.assertEqual(r.status_code, 200, r.text)

    def test_draft_saved_private_and_reload(self):
        rid = self.create()
        self.assertEqual(self.call("GET", "/stock-requests", 1).json(), [])
        self.assertEqual(self.call("GET", f"/stock-requests/{rid}", 1).status_code, 403)
        self.assertEqual(self.call("GET", f"/stock-requests/{rid}", 4).status_code, 403)
        self.assertEqual(self.call("GET", "/notifications", 1).json()["unread"], 0)
        r = self.call("PUT", f"/stock-requests/{rid}", body={"setirler": [{"point_id": 2, "medicine_id": 1, "say": 42}]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.call("GET", f"/stock-requests/{rid}").json()["setirler"][0]["say"], 42)
        self.assertEqual(self.call("GET", f"/stock-requests/{rid}").json()["setirler"][0]["point_id"], 2)

    def test_submit_hold_approve_notifications_and_incoming_stock(self):
        rid = self.create()
        self.submit(rid)
        self.assertEqual(self.call("POST", f"/stock-requests/{rid}/submit").status_code, 409)
        self.assertEqual(self.call("PUT", f"/stock-requests/{rid}", body={"setirler": []}).status_code, 409)
        self.assertEqual(len(self.call("GET", "/stock-requests", 1).json()), 1)
        self.assertEqual(self.call("GET", "/stock-requests", 2).json(), [])
        self.assertEqual(self.call("POST", f"/stock-requests/{rid}/decision", 2, {"status": "tesdiqlendi"}).status_code, 403)
        self.assertEqual(self.call("POST", f"/stock-requests/{rid}/decision", 3, {"status": "tesdiqlendi"}).status_code, 403)
        b = self.call("GET", "/notifications", 1).json()
        self.assertEqual(b["unread"], 1)
        nid = b["items"][0]["id"]
        self.assertEqual(self.call("POST", f"/notifications/{nid}/read", 2).status_code, 404)
        for status in ("gozleyir", "tesdiqlendi"):
            r = self.call("POST", f"/stock-requests/{rid}/decision", 1, {"status": status, "serh": "Shipment planned"})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(self.call("GET", "/notifications", 1).json()["unread"], 0)
            self.assertEqual(self.call("POST", f"/stock-requests/{rid}/decision", 1, {"status": status}).status_code, 409)
            with Session(engine) as s:
                self.assertEqual(len(s.exec(select(StockMovement)).all()), 4 if status == "gozleyir" else 5)
                self.assertEqual(nokte_qaliqi(s, 1, 1), 5 if status == "gozleyir" else 35)
        self.assertEqual(self.call("POST", f"/notifications/{nid}/read", 1).status_code, 200)
        self.assertEqual(self.call("GET", "/notifications", 3).json()["unread"], 2)
        self.assertEqual(self.call("GET", f"/stock-requests/{rid}").json()["status"], "tesdiqlendi")
        self.assertEqual(self.call("POST", f"/stock-requests/{rid}/decision", 1, {"status": "gozleyir"}).status_code, 409)
        with Session(engine) as s:
            movements = s.exec(select(StockMovement).order_by(StockMovement.id)).all()
            self.assertEqual(len(movements), 5)
            incoming = movements[-1]
            self.assertEqual((incoming.point_id, incoming.medicine_id, incoming.say, incoming.novu), (1, 1, 30, "daxilolma"))
            self.assertEqual((incoming.user_id, incoming.created_by, incoming.tarix, incoming.sebeb), (1, 1, bu_gun(), f"Stok tələbi #{rid}"))
            self.assertEqual(len(s.exec(select(Notification)).all()), 3)

    def test_direct_approval_adds_each_pharmacy_once(self):
        rid = self.create([{"point_id": 1, "medicine_id": 1, "say": 25}, {"point_id": 2, "medicine_id": 1, "say": 50}])
        self.submit(rid)
        r = self.call("POST", f"/stock-requests/{rid}/decision", 1, {"status": "tesdiqlendi"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.call("POST", f"/stock-requests/{rid}/decision", 1, {"status": "tesdiqlendi"}).status_code, 409)
        with Session(engine) as s:
            self.assertEqual(len(s.exec(select(StockMovement)).all()), 6)
            self.assertEqual(nokte_qaliqi(s, 1, 1), 30)
            self.assertEqual(nokte_qaliqi(s, 2, 1), 50)
            self.assertEqual(nokte_qaliqi(s, 3, 1), 0)
        self.assertEqual({i["point_id"] for i in self.call("GET", "/stock-requests/options").json()["items"]}, {3})
        self.assertEqual(self.call("GET", "/notifications", 3).json()["unread"], 1)

    def test_invalid_approval_target_rolls_back_all_rows(self):
        rid = self.create([{"point_id": 1, "medicine_id": 1, "say": 25}, {"point_id": 2, "medicine_id": 1, "say": 50}])
        self.submit(rid)
        with Session(engine) as s:
            point = s.get(Point, 2)
            point.active = False
            s.add(point)
            s.commit()
        r = self.call("POST", f"/stock-requests/{rid}/decision", 1, {"status": "tesdiqlendi"})
        self.assertEqual(r.status_code, 404, r.text)
        self.assertEqual(self.call("GET", f"/stock-requests/{rid}").json()["status"], "gonderildi")
        self.assertEqual(self.call("GET", "/notifications", 1).json()["unread"], 1)
        self.assertEqual(self.call("GET", "/notifications", 3).json()["unread"], 0)
        with Session(engine) as s:
            self.assertEqual(len(s.exec(select(StockMovement)).all()), 4)
            self.assertEqual(nokte_qaliqi(s, 1, 1), 5)
            self.assertEqual(len(s.exec(select(Notification)).all()), 1)

    def test_submitted_request_can_be_approved_after_stock_recovers(self):
        rid = self.create()
        self.submit(rid)
        with Session(engine) as s:
            for pid in (1, 2, 3):
                s.add(StockMovement(point_id=pid, medicine_id=1, user_id=3, novu="daxilolma", say=100, tarix=bu_gun()))
            s.commit()
        r = self.call("POST", f"/stock-requests/{rid}/decision", 1, {"status": "tesdiqlendi"})
        self.assertEqual(r.status_code, 200, r.text)
        with Session(engine) as s:
            self.assertEqual(nokte_qaliqi(s, 1, 1), 135)

    def test_input_scope_and_eligibility(self):
        for quantity in (0, -1, 100001, 1.5, "2", True):
            self.assertEqual(self.call("POST", "/stock-requests", body={"setirler": [{"point_id": 1, "medicine_id": 1, "say": quantity}]}).status_code, 422)
        row = {"point_id": 1, "medicine_id": 1, "say": 5}
        self.assertEqual(self.call("POST", "/stock-requests", body={"setirler": [row, row]}).status_code, 422)
        for pid, mid, expected in [(4, 1, 403), (3, 1, 422), (5, 1, 404), (1, 3, 404), (1, 2, 409)]:
            self.assertEqual(self.call("POST", "/stock-requests", body={"setirler": [{"point_id": pid, "medicine_id": mid, "say": 10}]}).status_code, expected)
        self.assertEqual(self.call("POST", "/stock-requests", 1, {"setirler": [row]}).status_code, 403)
        self.assertEqual(self.call("POST", "/stock-requests", 6, {"setirler": [row]}).status_code, 403)
        self.assertEqual(self.client.get("/stock-requests").status_code, 401)
        options = self.call("GET", "/stock-requests/options").json()
        self.assertEqual(len(options["items"]), 3)
        self.assertEqual(len(options["pharmacies"]), 2)
        self.assertEqual({i["medicine_id"] for i in options["items"]}, {1})
        self.assertEqual(options["manager_ad"], "Manager One")

    def test_empty_no_manager_and_recovered_stock(self):
        empty = self.create([])
        self.assertEqual(self.call("POST", f"/stock-requests/{empty}/submit").status_code, 422)
        lone = self.create(uid=5)
        self.assertEqual(self.call("POST", f"/stock-requests/{lone}/submit", 5).status_code, 409)
        rid = self.create()
        with Session(engine) as s:
            for pid in (1, 2, 3):
                s.add(StockMovement(point_id=pid, medicine_id=1, user_id=3, novu="daxilolma", say=100, tarix=bu_gun()))
            s.commit()
        self.assertEqual(self.call("POST", f"/stock-requests/{rid}/submit").status_code, 409)
        self.assertEqual(self.call("GET", f"/stock-requests/{rid}").json()["status"], "qaralama")

    def test_manager_reassignment_revokes_old_access(self):
        rid = self.create(); self.submit(rid)
        nid = self.call("GET", "/notifications", 1).json()["items"][0]["id"]
        with Session(engine) as s:
            u = s.get(User, 3); u.manager_id = 2; s.add(u); s.commit()
        self.assertEqual(self.call("GET", f"/stock-requests/{rid}", 1).status_code, 403)
        self.assertEqual(self.call("GET", "/notifications", 1).json()["unread"], 0)
        self.assertEqual(self.call("POST", f"/notifications/{nid}/read", 1).status_code, 404)
        self.assertEqual(self.call("GET", f"/stock-requests/{rid}", 2).status_code, 200)

    def test_compact_excel_preserves_records_and_text(self):
        from openpyxl import load_workbook

        note = '=HYPERLINK("https://example.invalid","note")'
        with Session(engine) as s:
            s.add(StockMovement(point_id=1, medicine_id=1, user_id=3, created_by=3,
                                novu="geri_qaytarma", say=7, tarix=bu_gun(), sebeb=note))
            s.commit()
        month = bu_gun().strftime("%Y-%m")
        r = self.call("GET", f"/history/export?region=1&month={month}")
        self.assertEqual(r.status_code, 200, r.text if r.status_code != 200 else "")
        book = load_workbook(io.BytesIO(r.content))
        sheet = book.active
        self.assertEqual(sheet.max_column, 7)
        self.assertEqual(sheet.max_row, 8)
        self.assertEqual([c.value for c in sheet[3]],
                         ["Tarix", "Növ", "Dərman", "Məntəqə", "Say", "Qeyd/Həkim", "İşçi"])
        row = next(row for row in sheet.iter_rows(min_row=4) if row[5].value == note)
        self.assertEqual([c.value for c in row],
                         [bu_gun().isoformat(), "Geri qaytarma", "Low Medicine", "Pharmacy One", 7, note, "Rep One"])
        self.assertEqual(row[5].data_type, "s")
        self.assertEqual(row[4].data_type, "n")
        self.assertTrue(row[5].alignment.wrap_text)
        self.assertLess(sum(sheet.column_dimensions[c].width for c in "ABCDEFG"), 126)
        self.assertEqual(sheet.freeze_panes, "A4")
        self.assertEqual(sheet.auto_filter.ref, "A3:G8")
        self.assertEqual(sheet.page_setup.fitToWidth, 1)
        self.assertEqual(sheet.page_setup.orientation, "landscape")
        self.assertEqual(self.call("GET", "/history/export?region=2").status_code, 403)
        book.close()

    def test_photo_validation_persistence_and_removal(self):
        out = io.BytesIO(); Image.new("RGB", (80, 60), "red").save(out, "PNG")
        data = "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()
        r = self.call("PUT", "/me/photo", body={"data": data})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["photo"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(self.call("GET", "/me").json()["photo"], r.json()["photo"])
        self.assertIsNone(self.call("GET", "/me", 4).json()["photo"])
        for bad in ("data:image/svg+xml;base64,PHN2Zy8+", "data:image/png;base64,PHN2Zy8+", "data:image/png;base64,!bad", "https://example.invalid/avatar.png"):
            self.assertEqual(self.call("PUT", "/me/photo", body={"data": bad}).status_code, 422)
        out = io.BytesIO(); Image.new("RGB", (4097, 1)).save(out, "PNG")
        self.assertEqual(self.call("PUT", "/me/photo", body={"data": "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()}).status_code, 422)
        self.assertEqual(self.call("PUT", "/me/photo", body={"data": "data:image/png;base64," + "A" * 2800001}).status_code, 422)
        self.assertIsNone(self.call("DELETE", "/me/photo").json()["photo"])
        self.assertIsNone(self.call("GET", "/me").json()["photo"])


if __name__ == "__main__":
    unittest.main()
