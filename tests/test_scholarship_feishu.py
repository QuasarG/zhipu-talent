"""飞书问卷 webhook：token 校验、幂等、平铺/反查双模式、附件落库、docx 提取。"""
from __future__ import annotations

import io
import json
import os
import unittest
import zipfile
from unittest.mock import patch

from agi_talent_radar.core.db.orm import Base
from agi_talent_radar.core.db.runtime import get_engine, get_session
from agi_talent_radar.scholarship import ingest
from agi_talent_radar.web.workbench import create_app


def _docx_bytes(text: str = "张三的个人简历") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", f"<w:p><w:t>{text}</w:t></w:p>")
    return buf.getvalue()


class FeishuWebhookTest(unittest.TestCase):
    _saved_url: str | None = None

    @classmethod
    def setUpClass(cls) -> None:
        cls._saved_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = "sqlite://"
        Base.metadata.create_all(get_engine())

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._saved_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = cls._saved_url

    def setUp(self) -> None:
        # webhook 本身不需要登录；详情接口用 mock 放行
        self._auth = patch("agi_talent_radar.web.auth.is_authenticated", return_value=True)
        self._auth.start()
        self._token = patch.dict(os.environ, {"SCHOLARSHIP_WEBHOOK_TOKEN": "tok123"})
        self._token.start()
        self.client = create_app().test_client()

    def tearDown(self) -> None:
        self._auth.stop()
        self._token.stop()
        # 清掉本测试建的申请，避免 sqlite 内存库跨用例污染
        with get_session() as session:
            from agi_talent_radar.core.db.orm import ScholarshipApplicationORM

            for row in session.query(ScholarshipApplicationORM).all():
                session.delete(row)
            session.commit()

    def _post(self, body: dict, token: str = "tok123"):
        return self.client.post(
            f"/api/scholarship/feishu-webhook/{token}",
            data=json.dumps(body),
            content_type="application/json",
        )

    def test_rejects_bad_token(self) -> None:
        self.assertEqual(self._post({}, token="wrong").status_code, 404)

    def test_ping_reports_pull_mode_off(self) -> None:
        with patch.dict(os.environ, {"FEISHU_APP_ID": ""}):
            resp = self.client.get("/api/scholarship/feishu-webhook/tok123")
        self.assertEqual(resp.get_json(), {"ok": True, "pull_mode": False})

    def test_flat_body_creates_and_screens(self) -> None:
        resp = self._post({
            "record_id": "recTEST1",
            "中文姓名": "测试甲",
            "当前年级": ["博士二年级｜Second-year PhD Student"],
            "预计毕业时间": "2028-06-30T00:00:00.000+08:00",
            "主要研究方向": ["基础模型｜Foundation Models"],
            "学校/科研机构": "测试大学",
            "导师姓名": "李教授",
            "邮箱 | Email": "[a@b.edu](mailto:a@b.edu)",
        })
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertFalse(data["duplicate"])
        # 方向是基础模型 → 资格过；但缺材料 → material_incomplete
        self.assertEqual(data["status"], "material_incomplete")

        detail = self.client.get(f"/api/scholarship/applications/{data['application_id']}").get_json()
        self.assertEqual(detail["name"], "测试甲")
        self.assertEqual(detail["degree_type"], "phd")
        self.assertEqual(detail["expected_graduation"], "2028-06")
        self.assertEqual(detail["school"], "测试大学")
        self.assertEqual(detail["advisors"], ["李教授"])
        self.assertEqual(detail["email"], "a@b.edu")
        self.assertEqual(detail["feishu_record_id"], "recTEST1")

    def test_idempotent_same_record(self) -> None:
        body = {"record_id": "recDUP", "中文姓名": "测试乙", "当前年级": "硕士一年级", "主要研究方向": "强化学习"}
        first = self._post(body).get_json()
        second = self._post(body)
        self.assertTrue(second.get_json()["duplicate"])
        self.assertEqual(second.get_json()["application_id"], first["application_id"])

    def test_requires_name(self) -> None:
        resp = self._post({"record_id": "recNO", "学校/科研机构": "无名大学"})
        self.assertEqual(resp.status_code, 400)

    def test_unauthenticated_push_not_401(self) -> None:
        """飞书没有登录会话：白名单路径未登录也必须放行（非 401）。"""
        with patch("agi_talent_radar.web.auth.is_authenticated", return_value=False):
            resp = self._post({"中文姓名": "白名单", "主要研究方向": "AI Infrastructure"})
        self.assertNotEqual(resp.status_code, 401)

    def test_docx_extraction(self) -> None:
        from agi_talent_radar.scholarship.ingest import _extract_docx_text

        self.assertIn("张三的个人简历", _extract_docx_text(_docx_bytes()))

    def test_upsert_attachments_replace_on_dup(self) -> None:
        blob = _docx_bytes("简历内容v1")
        with get_session() as session:
            app1, created1 = ingest.upsert_application_from_feishu(session, {
                "record_id": "recATT", "name": "附件人",
                "attachments": [{"kind": "resume", "filename": "简历.docx", "bytes": blob}],
            })
            self.assertTrue(created1)
            self.assertEqual(len(app1.materials), 1)

            blob2 = _docx_bytes("简历内容v2")
            app2, created2 = ingest.upsert_application_from_feishu(session, {
                "record_id": "recATT", "name": "附件人",
                "attachments": [
                    {"kind": "resume", "filename": "简历.docx", "bytes": blob2},
                    {"kind": "form", "filename": "申请表.docx", "bytes": blob2},
                ],
            })
            self.assertFalse(created2)
            self.assertEqual(app2.id, app1.id)
            # 旧简历被清掉重落，不重复堆叠
            self.assertEqual(len(app2.materials), 2)
            texts = {m.filename: m.raw_text for m in app2.materials}
            self.assertIn("简历内容v2", texts["简历.docx"])


if __name__ == "__main__":
    unittest.main()
