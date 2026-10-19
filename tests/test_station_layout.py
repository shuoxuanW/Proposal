"""多工位布局推理与渲染回归测试（合成数据，不调用外部 API）。"""
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mv_proposal import diagram
from src.mv_proposal.config import Config
from src.mv_proposal.agents.drawing import DrawingAgent
from src.mv_proposal.agents.requirement import RequirementAgent
from src.mv_proposal.agents.verification import VerificationAgent
from src.mv_proposal.models import DiagramSpec, StationCamera, StationLayoutSpec, StationLight, StationUnit, TaskPlan
from src.mv_proposal.station import reason_station_layout
from src.mv_proposal.station_library import StationLibrary


class _FakeLLM:
    is_mock = False

    def __init__(self, data):
        self.data = data

    def complete_json(self, system, user):
        return self.data


def _unit(name: str, detection: str = "检测4处牙套孔漏装") -> StationUnit:
    return StationUnit(
        name=name, detection=detection, accuracy="0.008mm/pixel",
        working_distance="130±20mm", fov="40×27mm",
        workpiece_shape="矩形", workpiece_label="金属加工件", workpiece_size="156×94mm",
        cameras=[StationCamera(label="MV-CS200-10GM", x=0, y=4.2, lens="50mm FA", resolution="2000万像素")],
        lights=[StationLight(label="白色圆顶光源", x=-1.2, y=1.9, angle=45, kind="圆顶")],
    )


class StationLayoutTest(unittest.TestCase):
    def test_parse_multi_station_json(self):
        data = {"stations": [
            {"name": "工位1", "detection": "牙套漏装", "working_distance": "130±20mm",
             "workpiece": {"shape": "矩形", "label": "金属加工件", "size": "156×94mm"},
             "cameras": [{"label": "MV-CS200-10GM", "x": 0, "y": 4.2, "orientation": "down",
                          "lens": "50mm FA", "resolution": "2000万像素"}],
             "lights": [{"label": "白色圆顶光源", "x": -1.2, "y": 1.9, "angle": 45, "kind": "圆顶"}]},
            {"name": "工位2", "detection": "牙套漏装",
             "workpiece": {"shape": "矩形", "label": "金属加工件", "size": "156×94mm"},
             "cameras": [{"label": "MV-CS200-10GM", "x": 0, "y": 4.2, "orientation": "down",
                          "lens": "50mm FA"}],
             "lights": [{"label": "白色圆顶光源", "x": -1.2, "y": 1.9, "angle": 45, "kind": "圆顶"}]},
            {"name": "工位3", "detection": "小孔毛边",
             "workpiece": {"shape": "矩形", "label": "金属加工件", "size": "156×94mm"},
             "cameras": [{"label": "MV-CS200-10GM", "x": 0, "y": 4.2, "orientation": "down",
                          "lens": "35mm FA"}],
             "lights": [{"label": "90°环形光源", "x": -1.2, "y": 1.9, "angle": 90, "kind": "环形"}]},
        ], "notes": "三工位独立布置"}
        spec, ok, reason = reason_station_layout("三工位需求", _FakeLLM(data))
        self.assertTrue(ok, reason)
        self.assertEqual(len(spec.stations), 3)
        self.assertEqual(spec.camera_count, 3)
        self.assertEqual(spec.stations[2].working_distance, "")
        self.assertEqual(spec.workpiece_label, "金属加工件")

    def test_identical_stations_merge(self):
        spec = StationLayoutSpec(stations=[_unit("工位1"), _unit("工位2"), _unit("工位3", "小孔毛边")])
        merged = diagram._station_units(spec)
        self.assertEqual(len(merged), 2)
        self.assertIn("工位1", merged[0].name)
        self.assertIn("工位2", merged[0].name)
        self.assertIn("2套相同配置", merged[0].detection)

    def test_project_from_stem(self):
        self.assertEqual(
            StationLibrary._project_from_stem("铨讯-陶瓷片尺寸检测方案-0513(1)_slide5"),
            "铨讯 陶瓷片尺寸检测方案 0513(1)")
        self.assertEqual(
            StationLibrary._project_from_stem("20260812 电池外壳缺陷检测_slide4"),
            "20260812 电池外壳缺陷检测")

    def test_station_ref_injected_into_prompt(self):
        class _CaptureLLM:
            is_mock = False
            def __init__(self, data):
                self.data = data
                self.user = None
            def complete_json(self, system, user):
                self.user = user
                return self.data
        data = {"stations": [
            {"name": "工位1", "workpiece": {"shape": "矩形", "label": "工件"},
             "cameras": [{"label": "相机", "x": 0, "y": 4.2}],
             "lights": [{"label": "光源", "x": -1.2, "y": 1.9, "angle": 45, "kind": "环形"}]}]}
        llm = _CaptureLLM(data)
        reason_station_layout("需求", llm, case_text="历史案例文本", station_ref="历史工位图参考")
        self.assertIn("历史案例文本", llm.user)
        self.assertIn("历史工位图参考", llm.user)

    def test_side_camera_faces_workpiece(self):
        self.assertEqual(diagram._camera_direction(StationCamera(x=1.4)), -1)
        self.assertEqual(diagram._camera_direction(StationCamera(x=-1.4)), 1)

    def test_light_specs_copied_from_station_hit(self):
        class _FakeStationLib:
            def __init__(self, hits):
                self.hits = hits
            def search(self, query, top_k=1):
                return self.hits

        hit = {
            "id": "hit_slide1", "project": "历史项目", "score": 0.8,
            "data": {
                "drawing_type": "打光示意图",
                "component_list": [{"name": "条形光源", "position": "左上方倾斜"}],
                "connection_list": [],
                "note": "光源需45°±15°角度可调",
                "camera_working_distance": "300±10mm",
                "light_spec_list": [{
                    "name": "条形光源", "type": "条形", "angle": "45°±15°",
                    "distance_to_object": "30±10mm", "direction": "right", "adjustable": True,
                }],
            },
        }
        data = {"stations": [{
            "name": "工位1", "detection": "检测",
            "workpiece": {"shape": "矩形", "label": "工件"},
            "cameras": [{"label": "相机", "x": 0, "y": 4.2}],
            "lights": [{"label": "条形光源", "x": -1.2, "y": 1.9, "angle": 45, "kind": "条形"}],
        }]}
        agent = RequirementAgent(Config(), _FakeLLM(data), kb=None, image_lib=None,
                                 template_lib=None, station_lib=_FakeStationLib([hit]))
        plan = TaskPlan(project_name="测试", requirement_summary="检测", detection_target="检测",
                        case_constraints={"working_distance": "178±5mm"})
        plan = agent._attach_station_layout(plan, "检测", case_ref=[])
        light = plan.diagrams[0].station_spec.stations[0].lights[0]
        self.assertEqual(light.distance, "30±10mm")
        self.assertEqual(light.angle_label, "45°±15°")
        self.assertEqual(light.direction, "right")
        self.assertEqual(plan.case_constraints["working_distance"], "300±10mm")

    def test_light_direction_rotation(self):
        from src.mv_proposal.diagram import _light_rotation
        self.assertEqual(_light_rotation(StationLight(x=-1.2, angle=45, direction="right")), 45.0)
        self.assertEqual(_light_rotation(StationLight(x=1.2, angle=45, direction="left")), -45.0)
        self.assertEqual(_light_rotation(StationLight(x=0, angle=90, direction="down")), 0.0)

    def test_light_direction_parsed(self):
        from src.mv_proposal.station import _light_from_dict
        self.assertEqual(_light_from_dict({"direction": "right"}).direction, "right")
        self.assertEqual(_light_from_dict({"direction": "斜向左下"}).direction, "left")
        self.assertEqual(_light_from_dict({"direction": "垂直向下"}).direction, "down")
        self.assertEqual(_light_from_dict({"x": -1.2, "kind": "条形"}).direction, "right")
        self.assertEqual(_light_from_dict({"x": 1.2, "kind": "条形"}).direction, "left")
        self.assertEqual(_light_from_dict({"x": -1.2, "kind": "条形", "direction": "down"}).direction, "right")
        self.assertEqual(_light_from_dict({"x": 1.2, "kind": "条形", "direction": "down"}).direction, "left")
        self.assertEqual(_light_from_dict({"x": 0, "kind": "同轴"}).direction, "down")

    def test_light_direction_away_warns(self):
        unit = StationUnit(
            name="工位1", detection="检测", workpiece_shape="矩形", workpiece_label="工件",
            cameras=[StationCamera(label="相机", x=0, y=4.2)],
            lights=[StationLight(label="右光源", x=1.2, y=1.9, direction="right", kind="条形")],
        )
        spec = StationLayoutSpec(stations=[unit])
        plan = TaskPlan(
            project_name="朝向测试",
            diagrams=[DiagramSpec(id="station-1", kind="station", title="工位图", station_spec=spec)],
        )
        report = VerificationAgent(None, None).run(plan, [], [])
        self.assertTrue(any(i.code == "LIGHT_DIRECTION" for i in report.issues))

    def test_light_spec_fields_parsed(self):
        from src.mv_proposal.station import _light_from_dict
        lt = _light_from_dict({"angle": 45, "angle_range": "30-60°", "distance": "40±5mm"})
        self.assertEqual(lt.angle_label, "30-60°")
        self.assertEqual(lt.distance, "40±5mm")

    def test_light_spec_labels_rendered(self):
        unit = StationUnit(
            name="工位1", detection="检测牙套孔", accuracy="0.008mm/pixel",
            working_distance="130±20mm", fov="40×27mm",
            workpiece_shape="矩形", workpiece_label="金属加工件", workpiece_size="156×94mm",
            cameras=[StationCamera(label="MV-CS200-10GM", x=0, y=4.2, lens="50mm FA")],
            lights=[StationLight(label="条形光源", x=-1.2, y=1.9, angle=45,
                                 angle_label="45°±15°", distance="30±10mm", kind="条形")],
        )
        spec = StationLayoutSpec(stations=[unit])
        with tempfile.TemporaryDirectory() as td:
            _, svg = diagram.render_station_layout(spec, pathlib.Path(td), dpi=60, name="light_spec_test")
            text = (pathlib.Path(td) / svg).read_text(encoding="utf-8")
            self.assertIn("角度 45°±15°", text)
            self.assertIn("距工件 30±10mm", text)

    def test_photos_attached_to_every_station(self):
        class _Entry:
            def __init__(self, name, rel_path):
                self.name = name
                self.rel_path = rel_path
        class _FakeTL:
            entries = [
                _Entry("相机加fa镜头", "camera/相机加fa镜头.png"),
                _Entry("圆顶光源", "light_source/圆顶光源.png"),
            ]
            def best(self, *args, **kwargs):
                return None
        agent = DrawingAgent(None, None, template_lib=_FakeTL())
        spec = StationLayoutSpec(stations=[_unit("工位1"), _unit("工位2")])
        agent._attach_station_photos(spec)
        for st in spec.stations:
            self.assertEqual(st.cameras[0].photo, "camera/相机加fa镜头.png")
            self.assertEqual(st.lights[0].photo, "light_source/圆顶光源.png")

    def test_render_uses_kb_photos(self):
        cam = StationCamera(label="MV-CS200-10GM", x=1.4, y=2.8, orientation="side",
                            lens="50mm FA", photo="camera/相机加fa镜头.png")
        light = StationLight(label="白色圆顶光源", x=-1.2, y=1.9, angle=45,
                             kind="圆顶", photo="light_source/圆顶光源.png")
        unit = StationUnit(
            name="工位2", detection="检测4处牙套孔漏装", accuracy="0.008mm/pixel",
            working_distance="130±20mm", fov="40×27mm",
            workpiece_shape="矩形", workpiece_label="金属加工件", workpiece_size="156×94mm",
            cameras=[cam], lights=[light],
        )
        spec = StationLayoutSpec(stations=[unit])
        with tempfile.TemporaryDirectory() as td:
            png, svg = diagram.render_station_layout(
                spec, pathlib.Path(td), image_root=ROOT / "data" / "image_templates",
                dpi=60, name="photo_test")
            self.assertTrue((pathlib.Path(td) / png).exists())
            text = (pathlib.Path(td) / svg).read_text(encoding="utf-8")
            self.assertIn("data:image/png;base64", text)

    def test_render_multi_station(self):
        spec = StationLayoutSpec(stations=[_unit("工位1"), _unit("工位2")], notes="两工位相同配置")
        with tempfile.TemporaryDirectory() as td:
            png, svg = diagram.render_station_layout(spec, pathlib.Path(td), dpi=60, name="station_test")
            self.assertTrue((pathlib.Path(td) / png).exists())
            text = (pathlib.Path(td) / svg).read_text(encoding="utf-8")
            self.assertIn("工位1 / 工位2", text)
            self.assertIn("遮光罩", text)


if __name__ == "__main__":
    unittest.main()
