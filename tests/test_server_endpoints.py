"""FastAPI 只读接口回归测试。"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from src.mv_proposal.server import app


class ServerEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_health(self):
        r = self.client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_stats_has_station_library(self):
        r = self.client.get("/kb/stats")
        assert r.status_code == 200
        d = r.json()
        assert d["stations"] >= 30
        assert d["station_projects"] >= 20

    def test_station_library_list_and_image(self):
        r = self.client.get("/station-library/list?limit=3")
        assert r.status_code == 200
        d = r.json()
        assert d["total"] >= 30
        assert 1 <= len(d["items"]) <= 3
        item = d["items"][0]
        assert item["image_url"].startswith("/station-lib/")
        img = self.client.get(item["image_url"])
        assert img.status_code == 200
        assert img.headers["content-type"].startswith("image/")

    def test_station_library_search(self):
        r = self.client.post("/station-library/search", json={"query": "陶瓷片尺寸检测", "top_k": 3})
        assert r.status_code == 200
        items = r.json()["items"]
        assert items
        assert any("陶瓷" in (it.get("project") or "") for it in items)

    def test_debug_status(self):
        r = self.client.get("/debug/status")
        assert r.status_code == 200
        d = r.json()
        for key in ("stations", "station_projects", "llm_provider", "ppt_profile"):
            assert key in d
