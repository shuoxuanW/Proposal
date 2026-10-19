"""售前选型顾问（交互式问诊）回归测试：字段提取 + mock 回复 + 输出隔离。"""
import pathlib
import sys
import unittest
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mv_proposal.advisor import _mock_reply, advise, extract_fields


class _FakeKB:
    def __init__(self, hits):
        self._hits = hits
    def retrieve(self, collection, query, top_k=3):
        return self._hits


class _FakeLLM:
    is_mock = True


class AdvisorTest(unittest.TestCase):

    def test_extract_fields(self):
        text = "检测电池螺丝有无漏装，产品560*460*120mm，金属材质，精度0.1mm，节拍120件/分钟，流水线在线"
        f = extract_fields(text)
        for k in ("产品外形尺寸/材质", "检测目标", "检测精度", "生产节拍/产能", "安装方式"):
            self.assertTrue(f[k], k)
        for k in ("安装空间限制", "现场环境"):
            self.assertFalse(f[k], k)

    def test_mock_reply_asks_missing(self):
        r = _mock_reply(["检测精度", "现场环境"])
        self.assertIn("检测精度", r)
        self.assertIn("现场环境", r)

    def test_mock_reply_complete(self):
        self.assertIn("信息已齐全", _mock_reply([]))

    def test_mock_requirement_filled_when_complete(self):
        ctx = SimpleNamespace(kb=_FakeKB([]), llm=_FakeLLM())
        text = ("检测金属表面缺陷，产品100×80mm，金属材质，精度0.05mm，"
                "速度120件/分钟，流水线在线检测，环境有粉尘，安装空间500×500mm")
        res = advise(ctx, [], text, ctx.llm)
        self.assertTrue(res["sufficient"])
        self.assertTrue(res["requirement"])
        self.assertIn("100×80mm", res["requirement"])

    def test_advise_no_case_goes_dynamic(self):
        ctx = SimpleNamespace(kb=_FakeKB([]), llm=_FakeLLM())
        res = advise(ctx, [], "检测陶瓷基板表面镀层气泡，精度0.01mm", ctx.llm)
        self.assertEqual(res["debug"]["selected_source"], "AI动态选型")
        self.assertIn("missing_fields", res["debug"])
        self.assertNotIn("相似度", res["reply"])          # 客户侧不泄露内部元数据

    def test_advise_case_recall_keeps_meta_in_debug(self):
        ctx = SimpleNamespace(kb=_FakeKB([{"source": "proposals/x.md", "score": 0.8,
            "text": "# X\n\n## 项目概述\n检测螺丝漏装"}]), llm=_FakeLLM())
        res = advise(ctx, [], "检测螺丝漏装", ctx.llm)
        self.assertEqual(res["debug"]["selected_source"], "案例库召回")
        self.assertEqual(res["debug"]["matched"][0]["source"], "proposals/x.md")
        self.assertNotIn("proposals", res["reply"])       # 路径只进 debug，不进回复


if __name__ == "__main__":
    unittest.main()
