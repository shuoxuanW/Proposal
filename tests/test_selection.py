"""选型流程与硬件配套校验的回归测试（纯合成数据，不加载向量模型）。"""
import pathlib
import sys
import unittest
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mv_proposal.compat import DeviceItem, check_compat
from src.mv_proposal.selection import format_selection, recall_cases, run_selection


class CompatTest(unittest.TestCase):
    """[配套校验] 工程强制配套关系"""

    def test_mount_mismatch(self):
        items = [
            DeviceItem("camera", "MV-CS200-10GC", "C口 网口相机", 1),
            DeviceItem("lens", "SFA30L-Y3528-M42", "M42口 35mm线扫镜头", 1),
        ]
        rep = check_compat(items)
        self.assertTrue(any(c.rule == "镜头卡口" and c.passed is False for c in rep.checks))

    def test_light_channel_shortage(self):
        items = [
            DeviceItem("light_source", "X", "白光环形", 3),
            DeviceItem("controller", "YD-FL-ACD-4824-2", "双通道数字光源控制器", 1),
        ]
        rep = check_compat(items)
        self.assertTrue(any(c.rule == "光源通道" and c.passed is False for c in rep.checks))

    def test_lens_resolution_short(self):
        items = [
            DeviceItem("camera", "OPT-CC1-M250-GG3-00", "2500万黑白面阵相机", 1),
            DeviceItem("lens", "YDA-1216-25M", "16mm FA C口", 1),   # 25M → 25MP ≥ 25MP 会通过，改用小镜头
        ]
        items[1] = DeviceItem("lens", "X-05M", "C口 5MP 定焦", 1)
        rep = check_compat(items)
        self.assertTrue(any(c.rule == "镜头分辨率" and c.passed is False for c in rep.checks))

    def test_all_pass(self):
        items = [
            DeviceItem("camera", "MV-CS200-10GC", "2000万彩色 C口 GigE 网口", 2),
            DeviceItem("lens", "YDA-1250-25M", "50mm FA C口", 2),
            DeviceItem("light_source", "YD-FL-R-12090W", "白光环形", 2),
            DeviceItem("controller", "YD-SZ24W42-4T", "四通道光源控制器", 1),
            DeviceItem("ipc", "IPC-I7T6-20-05G10-A-YF", "I7-6代，双网口", 1),
        ]
        rep = check_compat(items)
        self.assertTrue(rep.passed, [c.message for c in rep.failed])


class _FakeKB:
    def __init__(self, hits):
        self._hits = hits
    def retrieve(self, collection, query, top_k=3):
        return self._hits


class _FakeLLM:
    is_mock = True


class SelectionTest(unittest.TestCase):
    """[选型流程] 案例优先 → 动态兜底"""

    def _ctx(self, hits):
        return SimpleNamespace(kb=_FakeKB(hits), llm=_FakeLLM())

    def test_case_recall_wins(self):
        ctx = self._ctx([{"source": "proposals/电池螺丝有无检测视觉方案.md", "score": 0.81,
                          "text": "# 电池螺丝有无检测视觉方案\n\n## 项目概述\n..."}])
        res = run_selection(ctx, "检测螺丝有无漏装")
        self.assertEqual(res.source, "案例库召回")

    def test_case_recall_dedupes_same_source(self):
        """同一份方案命中多个块时，只保留分数最高的一条。"""
        ctx = self._ctx([
            {"source": "proposals/A.md", "score": 0.92, "text": "a1"},
            {"source": "proposals/A.md", "score": 0.85, "text": "a2"},
            {"source": "proposals/B.md", "score": 0.80, "text": "b1"},
            {"source": "proposals/C.md", "score": 0.70, "text": "c1"},
        ])
        hits = recall_cases(ctx, "x", top_k=2)
        self.assertEqual([h["source"] for h in hits], ["proposals/A.md", "proposals/B.md"])
        self.assertEqual(hits[0]["text"], "a1")

    def test_dynamic_fallback(self):
        ctx = self._ctx([])
        res = run_selection(ctx, "检测金属表面划痕，精度0.05mm，视野100mm，工作距离200mm")
        self.assertEqual(res.source, "AI动态选型")
        self.assertIsNotNone(res.compat)
        self.assertTrue(any(it.device_type == "camera" for it in res.device_list))

    def test_format_contains_sections(self):
        ctx = self._ctx([])
        res = run_selection(ctx, "检测金属表面划痕，精度0.05mm，视野100mm，工作距离200mm")
        text = format_selection(res)
        for sec in ("【选型来源】", "【匹配说明】", "【硬件方案清单】", "【配套校验结果】", "【风险提示】"):
            self.assertIn(sec, text, sec)


    def test_catalog_provides_params_and_cable_rule(self):
        """设备目录是权威参数来源：接口/卡口/像素/通道从目录读，且出现线缆配套规则。"""
        items = [
            DeviceItem("camera", "MV-CS200-10GC", "", 1),      # 目录：GigE / C口 / 2000万
            DeviceItem("lens", "YDA-1235-25M", "", 1),         # 目录：C口 / 25MP
            DeviceItem("ipc", "IPC-I7T13-20-05G10-A-YF", "", 1),  # 目录：双网口
        ]
        rep = check_compat(items)
        msgs = " ".join(c.message for c in rep.checks)
        self.assertIn("GigE", msgs)
        self.assertIn("25MP", msgs)
        self.assertTrue(any(c.rule == "相机线缆" for c in rep.checks))

    def test_cable_matching_interface(self):
        """清单里配了 GigE 线缆且接口匹配 → 通过。"""
        items = [
            DeviceItem("camera", "MV-CS200-10GC", "", 1),
            DeviceItem("lens", "YDA-1235-25M", "", 1),
            DeviceItem("ipc", "IPC-I7T13-20-05G10-A-YF", "", 1),
            DeviceItem("cable", "MV-AC-GigE-5M", "GigE 千兆线", 1),
        ]
        rep = check_compat(items)
        self.assertTrue(any(c.rule == "相机线缆" and c.passed is True for c in rep.checks))
if __name__ == "__main__":
    unittest.main()
