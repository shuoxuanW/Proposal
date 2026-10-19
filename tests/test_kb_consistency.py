"""入库自检工具回归测试：用合成数据验证「能抓到真问题」，不触碰真实知识库。"""
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mv_proposal.config import Config
from src.mv_proposal.knowledge import MIN_CHUNK, KnowledgeBase

sys.path.insert(0, str(ROOT / "scripts"))
import check_kb_consistency as check_kb      # noqa: E402  (入库自检工具)


class ModelColorTest(unittest.TestCase):
    """[B] 型号后缀 ↔ 颜色描述（真实发生过的错误：-10GC 被写成黑白）"""

    def _run(self, text: str):
        with tempfile.TemporaryDirectory() as td:
            base = pathlib.Path(td) / "proposals"
            base.mkdir(parents=True)
            (base / "t.md").write_text(text, encoding="utf-8")
            cfg = Config(project_root=ROOT)
            cfg.knowledge_dir = pathlib.Path(td)
            rep = check_kb.Report()
            check_kb.check_model_color(cfg, rep)
            return rep

    def test_wrong_color_flagged(self):
        rep = self._run("# T\n\n## 设备选型\n- 工业相机：MV-CS050-10GC（500万全局黑白）\n")
        self.assertEqual(rep.count("error"), 1)
        self.assertIn("彩色", rep.findings[0].message)

    def test_multi_camera_line_attributed_per_model(self):
        """同一行两台相机、各自带颜色描述时，必须按型号就近归因，不能互相污染。"""
        rep = self._run("# T\n\n## 设备选型\n- 工业相机：MV-CS050-10GC（500万全局彩色）；MV-CH120-10GM（1200万全局黑白）\n")
        self.assertEqual(rep.count("error"), 0)

    def test_lens_model_not_misjudged(self):
        """镜头型号里的 M（如 YDA-1250-25M）不应被当成黑白相机。"""
        rep = self._run("# T\n\n## 镜头\n- 型号/焦距/接口：YDA-1250-25M，50mm FA，C口\n")
        self.assertEqual(rep.count("error"), 0)


class ChunkingTest(unittest.TestCase):
    """[A] 切块：结构化 JSON 被按长度硬切后，尾部碎块应回并，不产生单字块。"""

    def test_tail_fragment_merged(self):
        text = "x" * 480 + "\n}"          # 复现 光路图例规范.json 的 "}" 碎块
        chunks = KnowledgeBase._chunk_text(text)
        self.assertEqual(len(chunks), 1)
        self.assertTrue(all(len(c) >= MIN_CHUNK for c in chunks))

    def test_sections_stay_separate(self):
        """回并只在节内进行，不能把下一节并进上一节。"""
        text = "# T\n\n## A\n" + "a" * 600 + "\n\n## B\n" + "b" * 600
        chunks = KnowledgeBase._chunk_text(text)
        self.assertTrue(any("## B" in c for c in chunks))
        self.assertTrue(all(len(c) >= MIN_CHUNK for c in chunks))


def _run_in_tmp(files: dict, fn):
    """在临时知识库上跑某个检查函数。"""
    with tempfile.TemporaryDirectory() as td:
        base = pathlib.Path(td) / "proposals"
        base.mkdir(parents=True)
        for name, text in files.items():
            (base / name).write_text(text, encoding="utf-8")
        cfg = Config(project_root=ROOT)
        cfg.knowledge_dir = pathlib.Path(td)
        rep = check_kb.Report()
        fn(cfg, rep)
        return rep


class SameModelConsistencyTest(unittest.TestCase):
    """[F] 同一型号在库内描述矛盾（真实发生过：MV-CS200-10GM 一处写全局、三处写卷帘）"""

    def test_conflicting_shutter_flagged(self):
        rep = _run_in_tmp({
            "a.md": "# A\n\n## 设备选型\n- 工业相机：MV-CS200-10GM，2000万卷帘网口黑白相机\n",
            "b.md": "# B\n\n## 设备选型\n- 工业相机：MV-CS200-10GM，2000万全局网口黑白相机\n",
        }, check_kb.check_same_model_consistency)
        self.assertGreaterEqual(rep.count("warning"), 1)
        self.assertTrue(any("快门" in f.message for f in rep.findings))

    def test_opt_brand_color_suffix(self):
        """OPT-CC1-C050/-M250 系列也要做颜色一致性检查（此前只认海康 -10GC/GM）。"""
        rep = _run_in_tmp({
            "a.md": "# A\n\n## 设备选型\n- 工业相机：OPT-CC1-M250-GG3-00，2500万黑白面阵相机\n",
            "b.md": "# B\n\n## 设备选型\n- 工业相机：OPT-CC1-M250-GG3-00，2500万彩色面阵相机\n",
        }, check_kb.check_same_model_consistency)
        self.assertTrue(any("颜色" in f.message for f in rep.findings))

    def test_opt_color_rule_does_not_touch_unrelated_models(self):
        """规则不能误伤：镜头/IPC 型号不得被当成相机颜色后缀。"""
        for m in ("MGA-2325-10M", "MVL-LF6040M-013-M72", "IPC-I5T6-10-05G-A",
                  "YD-FL-COX2-85W", "PCIE-N0808-T", "YD-VM-3500"):
            self.assertIsNone(check_kb.expected_color(m), m)
        # 海康 G[C|M] 规则原有行为不受影响
        self.assertEqual(check_kb.expected_color("MV-CE120-10GM"), "黑白")
        self.assertEqual(check_kb.expected_color("MV-CS200-10GC"), "彩色")
    def test_lens_focal_conflict_flagged(self):
        """同型号镜头在不同文件里焦距矛盾（真实案例：YDA-2350-10M 一处 50mm、一处 35mm）。"""
        rep = _run_in_tmp({
            "a.md": "# A\n\n## 镜头\n- 型号/焦距/接口：YDA-2350-10M 50mm FA，C口\n",
            "b.md": "# B\n\n## 镜头\n- 型号/焦距/接口：YDA-2350-10M 35mm FA，C口\n",
        }, check_kb.check_same_model_consistency)
        self.assertTrue(any("焦距" in f.message for f in rep.findings))

    def test_lens_same_focal_passes(self):
        rep = _run_in_tmp({
            "a.md": "# A\n\n## 镜头\n- 型号/焦距/接口：YDA-2350-10M 50mm FA，C口\n",
            "b.md": "# B\n\n## 镜头\n- 型号/焦距/接口：YDA-2350-10M 50mm FA，C口\n",
        }, check_kb.check_same_model_consistency)
        self.assertEqual(rep.count("warning"), 0)
    def test_non_hikvision_camera_color_conflict(self):
        """非 MV- 品牌的相机同样要做描述一致性检查（如 OPT-CC1-C050）。"""
        rep = _run_in_tmp({
            "a.md": "# A\n\n## 设备选型\n- 工业相机：OPT-CC1-C050-GG3-10，500万彩色卷帘相机\n",
            "b.md": "# B\n\n## 设备选型\n- 工业相机：OPT-CC1-C050-GG3-10，500万黑白卷帘相机\n",
        }, check_kb.check_same_model_consistency)
        self.assertTrue(any("颜色" in f.message for f in rep.findings))
    def test_consistent_shutter_passes(self):
        rep = _run_in_tmp({
            "a.md": "# A\n\n## 设备选型\n- 工业相机：MV-CS200-10GM，2000万卷帘网口黑白相机\n",
            "b.md": "# B\n\n## 设备选型\n- 工业相机：MV-CS200-10GM，2000万卷帘网口黑白相机\n",
        }, check_kb.check_same_model_consistency)
        self.assertEqual(rep.count("warning"), 0)


class AliasModelTest(unittest.TestCase):
    """[E] 疑似同款异写：只提示、不改数据（如 YDA-1216-25M / YD-1216-25M）"""

    def test_alias_detected(self):
        rep = _run_in_tmp({
            "a.md": "# A\n\n## 镜头\n- 型号/焦距/接口：YDA-1216-25M，16mm FA\n",
            "b.md": "# B\n\n## 镜头\n- 型号/焦距/接口：YD-1216-25M，16mm FA\n",
        }, check_kb.check_alias_models)
        self.assertTrue(any("同款" in f.message for f in rep.findings))
        self.assertEqual(rep.count("error"), 0)      # 提示级，不影响退出码

    def test_prefix_segment_variance(self):
        """少一个厂牌段也算同款异写（FL-ACD-4824-2 vs YD-FL-ACD-4824-2）。"""
        rep = _run_in_tmp({
            "a.md": "# A\n\n- 光源控制器：FL-ACD-4824-2\n",
            "b.md": "# B\n\n- 光源控制器：YD-FL-ACD-4824-2\n",
        }, check_kb.check_alias_models)
        self.assertTrue(any("同款" in f.message for f in rep.findings))

    def test_hyphen_placement_variance(self):
        """连字符位置不同也算同款（FL-DM-100-W vs YD-FL-DM-100W）。"""
        rep = _run_in_tmp({
            "a.md": "# A\n\n- 光源：FL-DM-100-W白色球积分\n",
            "b.md": "# B\n\n- 光源：YD-FL-DM-100W白色球积分\n",
        }, check_kb.check_alias_models)
        self.assertTrue(any("同款" in f.message for f in rep.findings))
    def test_different_spec_same_series_not_flagged(self):
        """同系列但规格不同（85mm / 50mm 同轴光）不能误报成同款。"""
        rep = _run_in_tmp({
            "a.md": "# A\n\n- 同轴光源：FL-COX2-85W\n",
            "b.md": "# B\n\n- 同轴光源：YD-FL-COX2-50W\n",
        }, check_kb.check_alias_models)
        self.assertFalse(any("同款" in f.message for f in rep.findings))
    def test_model_followed_by_chinese_not_truncated(self):
        """型号紧跟汉字时不能被截断（Python \\w 含中文，不能用 \\b）。"""
        rep = _run_in_tmp({
            "a.md": "# A\n\n## 设备选型\n- 光源：YD-FLK600600-60-W开孔面光源，共1套\n",
        }, check_kb.check_alias_models)
        self.assertTrue(any("YD-FLK600600-60-W" in f.message and "-60」" not in f.message
                            for f in rep.findings) or rep.count("error") == 0)
        self.assertEqual(rep.count("error"), 0)

class RequirementFitTest(unittest.TestCase):
    """[G] 需求要求颜色检测、相机却是黑白（真实案例：PIN线「线序颜色错乱」+ MV-CS200-10GM）"""

    def test_color_block_method_with_mono_camera(self):
        """需求用「色块」判缺陷、相机却写黑白（真实案例：电路板焊锡）。"""
        rep = _run_in_tmp({
            "a.md": "# A\n\n## 总体方案设计\n通过图像色块特征进行缺陷判定：红色区域出现黄色判定少锡\n\n## 设备选型\n- 工业相机：MV-CS200-10GC，2000万全局网口黑白相机\n",
        }, check_kb.check_requirement_fit)
        self.assertTrue(any("黑白" in f.message for f in rep.findings))

    def test_metadata_color_line_not_demand(self):
        """设备参数里的「型号与颜色：…」是元数据，不能误判成辨色需求。"""
        rep = _run_in_tmp({
            "a.md": "# A\n\n## 光源\n- 型号与颜色：TSD-FL2534，白光\n\n## 工业相机\n- 型号：MV-CS200-10GM\n",
        }, check_kb.check_requirement_fit)
        self.assertEqual(len(rep.findings), 0)
    def test_mono_camera_with_color_demand(self):
        rep = _run_in_tmp({
            "a.md": "# A\n\n## 检测要求\n- 检测项：线序颜色错乱\n\n## 设备选型\n- 工业相机：MV-CS200-10GM，2000万卷帘黑白相机\n",
        }, check_kb.check_requirement_fit)
        self.assertEqual(rep.count("warning"), 0)      # 提示级
        self.assertTrue(any("黑白" in f.message for f in rep.findings))

    def test_color_camera_passes(self):
        rep = _run_in_tmp({
            "a.md": "# A\n\n## 检测要求\n- 检测项：线序颜色错乱\n\n## 设备选型\n- 工业相机：MV-CS200-10GC，2000万彩色相机\n",
        }, check_kb.check_requirement_fit)
        self.assertEqual(len(rep.findings), 0)

class OpticsTest(unittest.TestCase):
    """[H] 光路合理性（真实案例：12mm 镜头 + 1700mm 工作距离 + 120mm 视野 → 反推传感器 0.85mm）"""

    def test_impossible_optics_flagged(self):
        rep = _run_in_tmp({
            "a.md": "# A\n\n## 工位与光路布局\n- 500万彩色相机搭配12mm FA镜头；\n- 相机工作距离1700±1mm；\n- 视野120*100mm，像素精度0.05mm/pixel；\n",
        }, check_kb.check_optics)
        self.assertGreaterEqual(rep.count("warning"), 1)
        self.assertTrue(any("传感器" in f.message for f in rep.findings))

    def test_reasonable_optics_passes(self):
        """真实数据：16mm + 1100mm + 900mm视野 → 反推 13.3mm（2000万 1" 传感器 13.1mm）"""
        rep = _run_in_tmp({
            "a.md": "# A\n\n## 工位与光路布局\n- 2000万相机搭配16mm FA镜头；\n- 相机工作距离1100±10mm；\n- 视野900*600mm；\n",
        }, check_kb.check_optics)
        self.assertEqual(rep.count("warning"), 0)

    def test_telecentric_skipped(self):
        """远心镜头的焦距与视野无此关系，必须跳过，否则会误报。"""
        rep = _run_in_tmp({
            "a.md": "# A\n\n## 工位与光路布局\n- 相机搭配0.8倍远心镜头；\n- 相机工作距离178±5mm；\n- 视野7.1*5.3mm；\n",
        }, check_kb.check_optics)
        self.assertEqual(len(rep.findings), 0)

    def test_stitched_total_fov_excluded(self):
        """多相机拼图的「总视野」不能按单相机分辨率反算（真实案例：拼图后 240*310mm）。"""
        rep = _run_in_tmp({
            "a.md": "# A\n\n## 工位与光路布局\n- 单相机视野240*160mm，拼图后总视野240*310mm，像素精度0.044mm/pixel。\n\n## 设备选型\n- 工业相机：MV-CS200-10GC，2000万卷帘网口彩色相机，共2台\n",
        }, check_kb.check_precision)
        msgs = [f.message for f in rep.findings]
        self.assertTrue(any("240×160" in m for m in msgs), msgs)
        self.assertFalse(any("240×310" in m for m in msgs), msgs)

    def test_resolution_pix_abbreviation(self):
        """分辨率单位兼容「mm/pix」「mm/px」缩写（真实案例：泓博螺丝漏装 0.047mm/pix）。"""
        rep = _run_in_tmp({
            "a.md": "# A\n\n## 工位与光路布局\n- 相机工作距离690±10mm；\n- 视野259mm*173mm，像素精度0.047mm/pix。\n\n## 设备选型\n- 工业相机：OPT-CC1-M200-GR1-10，2000万黑白卷帘相机\n",
        }, check_kb.check_precision)
        self.assertTrue(any("259×173" in f.message for f in rep.findings))
if __name__ == "__main__":
    unittest.main()
