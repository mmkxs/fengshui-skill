#!/usr/bin/env python3
"""Create a reader-facing HTML report for user review."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from html import escape
import json
import math
import os
from pathlib import Path
import sys
import tempfile

from geometry import add, cross, scale, unit, world
from scene import fingerprint, load, validate, vector
from workflow import (
    atomic_json,
    checked_session,
    read_context,
    require_current_analysis,
)

FONT = "FengshuiReport"
INK = "#20372e"
GREEN = "#216346"
MUTED = "#58665f"
PALETTE = {
    "bed": "#7eae90",
    "desk": "#7eae90",
    "sofa": "#7eae90",
    "beam": "#d1a158",
    "mirror": "#a68abb",
    "door": "#699ab1",
    "window": "#91bfc7",
    "wall": "#b8bdb8",
    "partition": "#b8bdb8",
}
STATUS = {
    "candidate": "需要核对的布局候选",
    "observed": "在输入模型中算得",
    "not_observed": "指定关系未出现",
    "occluded": "标注几何产生遮挡",
    "unknown": "输入待补齐",
    "limited": "有限条件分析",
}


METRIC_LABELS = {
    "horizontalFootprintsOverlap": "水平投影是否重叠",
    "beamBottomY": "梁底标高（m）",
    "targetTopY": "目标顶面标高（m）",
    "verticalClearanceM": "竖向净距（m）",
    "reviewPoint": "目标审查点坐标（m）",
    "pointBasis": "审查点依据",
    "projectsInsideOpening": "是否投影到门洞内",
    "normalDistanceM": "离门洞平面的距离（m）",
    "reviewDistanceLimitM": "几何核查搜索范围（m）",
    "reflectionPoint": "镜面反射点坐标（m）",
    "distanceM": "至镜面的距离（m）",
    "observerPoint": "观察眼位坐标（m）",
    "targetPoint": "目标点坐标（m）",
    "targetBasis": "目标点依据",
    "distanceToAnnotatedWallM": "至标注墙体的距离（m）",
    "searchLimitM": "背靠搜索范围（m）",
    "areaM2": "房间面积（m²）",
    "ceilingHeightM": "净层高（m）",
    "volumeM3": "几何体积（m³）",
    "volumeModel": "体积计算模型",
    "ach": "换气次数（次/小时）",
    "flowM3h": "室外通风量（m³/h）",
    "flowBasis": "风量依据",
    "flowEvidenceRef": "风量来源",
}
VALUE_LABELS = {
    "annotated-review-point": "已标注的审查点",
    "box-top-center-proxy": "物品盒顶面中心代理点",
    "floor-area-times-uniform-clear-height": "房间面积 × 均匀净层高",
    "measured": "实测工况",
    "simulated": "模拟工况",
    "scenario": "设定工况",
}


def metric_value(value):
    if value is None:
        return "未知或本次未算得"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, str):
        return VALUE_LABELS.get(value, value)
    return json.dumps(value, ensure_ascii=False)


def register_font(requested=None):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    choices = (
        [requested]
        if requested
        else [
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simsun.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansSC-Regular.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        ]
    )
    for candidate in choices:
        if not candidate or not Path(candidate).is_file():
            continue
        try:
            font = TTFont(FONT, candidate, subfontIndex=0)
            if not all(
                ord(char) in font.face.charToGlyph
                for char in "空间风水解析报告镜梁门通风"
            ):
                continue
            pdfmetrics.registerFont(font)
            return
        except Exception as error:
            # Font collections with CFF outlines may be unsupported by ReportLab.
            if requested:
                raise ValueError(
                    "指定中文字体无法嵌入，请提供支持中文的 TrueType 字体"
                ) from error
    raise ValueError(
        "未发现可嵌入中文字体，请通过 --font 提供 Noto Sans SC、微软雅黑等 TrueType 字体"
    )


def confined(root, relative):
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()) or not target.is_file():
        raise ValueError("截图文件缺失或超出本次任务目录")
    return target


def read_images(directory, state, prepared, draft):
    from PIL import Image

    manifest_path = directory / "evidence-manifest.json"
    if not manifest_path.is_file():
        if draft:
            return [], ["尚无当前 VR 的截图证据"]
        raise ValueError("缺少截图清单，先完成当前 VR 截图后再生成正式报告")
    evidence, _ = load(manifest_path)
    if any(
        evidence.get(key) != value
        for key, value in [
            ("resourceCode", state["request"]["context"]["resourceCode"]),
            ("requestSha256", state["requestSha256"]),
            ("analysisSha256", state.get("analysisSha256")),
        ]
    ):
        raise ValueError("截图清单与本次授权或分析结果不一致")
    images = evidence.get("images", [])
    if not isinstance(images, list) or len(images) > 128:
        raise ValueError("截图清单数量无效")
    result, gaps = [], []
    known = {item["id"] for item in prepared["objects"]}
    for i, entry in enumerate(images):
        path = confined(directory, entry["path"])
        original = confined(directory, entry["originalPath"])
        for file, key in [(path, "sha256"), (original, "originalSha256")]:
            if hashlib.sha256(file.read_bytes()).hexdigest() != entry.get(key):
                raise ValueError("截图被修改，需重新核对并登记")
        metadata_path = confined(directory, entry["metadataPath"])
        if hashlib.sha256(metadata_path.read_bytes()).hexdigest() != entry.get(
            "metadataSha256"
        ):
            raise ValueError("截图相机记录已被修改")
        metadata, _ = load(metadata_path)
        if (
            metadata.get("kind") != entry.get("kind")
            or metadata.get("requestSha256") != state["requestSha256"]
            or metadata.get("context") != entry.get("context")
            or metadata.get("binding") != entry.get("binding")
        ):
            raise ValueError("截图相机元数据与清单不一致")
        camera = metadata.get("camera")
        if camera is not None:
            from visuals import validate_camera

            validate_camera(camera)
            if metadata.get("roomIds") != entry.get("roomIds"):
                raise ValueError("截图房间记录与相机元数据不一致")
        if entry.get("kind") != "vr-screenshot":
            gaps.append("含合成或非 VR 实景截图")
        if entry.get("binding", {}).get("analysisSha256") != state.get(
            "analysisSha256"
        ):
            raise ValueError("截图绑定了其他分析结果")
        bound = state["request"]["context"]
        if any(
            entry.get("context", {}).get(key) != bound.get(key)
            for key in ["resourceCode", "pageUrl"]
        ):
            raise ValueError("截图属于其他 VR 或页面会话")
        if not set(entry.get("objectIds", [])).issubset(known):
            raise ValueError("截图引用了未知物品")
        with Image.open(path) as image:
            width, height = image.size
            if image.width > 4096 or image.height > 4096:
                raise ValueError("截图像素尺寸过大")
            image.verify()
        result.append(
            {
                **entry,
                "file": path,
                "originalFile": original,
                "camera": camera,
                "width": width,
                "height": height,
                "projections": metadata.get("projections", []),
                "figureId": entry.get("figureId", f"E{i + 1}"),
            }
        )
    if len({image["figureId"] for image in result}) != len(result):
        raise ValueError("截图编号重复，需重新核对清单")
    if not result:
        gaps.append("缺少可用截图")
    if gaps and not draft:
        raise ValueError("正式报告截图证据尚未齐全，合成演示请使用 --draft")
    return result, gaps


def airflow_field(path, prepared):
    if not path:
        return None
    value, _ = load(path)
    if (
        value.get("schema") != "spatial-fengshui.airflow-field"
        or value.get("version") != 1
        or value.get("resourceCode") != prepared["resourceCode"]
    ):
        raise ValueError("气流矢量数据格式或资源身份无效")
    if value.get("sceneFingerprint") != fingerprint(prepared) or value.get(
        "basis"
    ) not in {"measured", "simulated"}:
        raise ValueError("气流矢量未绑定本次场景或未说明实测/模拟来源")
    if (
        not value.get("method")
        or not value.get("evidenceRef")
        or not isinstance(value.get("boundaryConditions"), dict)
        or not value["boundaryConditions"]
    ):
        raise ValueError("气流数据须说明方法、来源及工况边界")
    points = value.get("vectors", [])
    if not isinstance(points, list) or not 1 <= len(points) <= 4096:
        raise ValueError("气流矢量数量无效")
    room_ids = {room["id"] for room in prepared["rooms"]}
    for point in points:
        if point.get("roomId") not in room_ids:
            raise ValueError("气流矢量房间无效")
        vector(point.get("position"), "airflow.position")
        vector(point.get("velocityMps"), "airflow.velocityMps")
    return value


def interpretation(path, prepared, report, images, draft):
    if not path:
        if draft:
            return {
                "summary": "合成或不完整证据的流程示例，传统解读与改善建议待复核。",
                "methods": [],
                "notes": [],
            }
        raise ValueError(
            "请先依据空间与截图证据形成传统分析及改善建议，再传 --interpretation"
        )
    value, _ = load(path)
    if (
        not isinstance(value, dict)
        or value.get("schema") != "spatial-fengshui.interpretation"
        or value.get("version") != 1
    ):
        raise ValueError("解读内容格式无效")
    if value.get("resourceCode") != prepared["resourceCode"] or value.get(
        "sceneFingerprint"
    ) != fingerprint(prepared):
        raise ValueError("解读内容属于其他空间或旧场景")
    if (
        not isinstance(value.get("summary"), str)
        or not value["summary"].strip()
        or len(value["summary"]) > 8000
    ):
        raise ValueError("需要本次分析结论摘要")
    methods = value.get("methods", [])
    notes = value.get("notes", [])
    if (
        not isinstance(methods, list)
        or not methods
        or not all(isinstance(item, str) and 0 < len(item) <= 512 for item in methods)
    ):
        raise ValueError("需要说明本次采用的传统流派与方法")
    if not isinstance(notes, list) or len(notes) > 1000:
        raise ValueError("解读条目数量无效")
    focus = value.get("focusObjectIds", [])
    objects = {obj["id"] for obj in prepared["objects"]}
    if (
        not isinstance(focus, list)
        or len(focus) != len(set(focus))
        or any(oid not in objects for oid in focus)
    ):
        raise ValueError("重点物品引用无效")
    known = {
        (row["ruleId"], tuple(sorted(row["objectIds"]))) for row in report["findings"]
    }
    image_ids = {image["figureId"] for image in images}
    geometry_refs = {ref for row in report["findings"] for ref in row["evidenceRefs"]}
    actual = set()
    for note in notes:
        for field in ["title", "group"]:
            if field in note and (
                not isinstance(note[field], str) or not 0 < len(note[field]) <= 160
            ):
                raise ValueError("解读标题与分组须为非空短文本")
        key = (note.get("ruleId"), tuple(sorted(note.get("objectIds", []))))
        if key not in known or key in actual:
            raise ValueError("解读条目没有对应的本次几何核查项或重复")
        actual.add(key)
        for name in ["analysis", "practicalImpact"]:
            if not isinstance(note.get(name), str) or not 0 < len(note[name]) <= 4000:
                raise ValueError("解读需要传统分析及实际空间影响")
        for name in ["improvements", "evidenceRefs"]:
            values = note.get(name)
            if (
                not isinstance(values, list)
                or not values
                or not all(
                    isinstance(item, str) and 0 < len(item) <= 1500 for item in values
                )
            ):
                raise ValueError("解读需要改善建议及可核对的证据引用")
        if not any(
            ref in image_ids or ref in geometry_refs for ref in note["evidenceRefs"]
        ):
            raise ValueError("解读必须引用本次截图或几何证据")
        cited_objects = {
            identity
            for image in images
            if image["figureId"] in note["evidenceRefs"]
            for identity in [*image.get("objectIds", []), *image.get("roomIds", [])]
        }
        if not draft and set(note["objectIds"]) - cited_objects:
            raise ValueError("解读所引用截图尚未覆盖该项对象")
        if note.get("priority") not in ["high", "medium", "low"]:
            raise ValueError("改善建议优先级无效")
    required = {
        (row["ruleId"], tuple(sorted(row["objectIds"])))
        for row in report["findings"]
        if row["status"] == "candidate"
    }
    if required - actual and not draft:
        raise ValueError("部分布局候选尚无对应解读和改善建议")
    validate_school_advice(value, prepared, image_ids, geometry_refs)
    return value


SCHOOL_ADVICE_KEYS = {"luopan", "eightMansions", "xuanKong"}


def validate_school_advice(value, prepared, image_ids, geometry_refs):
    """方位与宅卦建议是可选段落，但一旦提供就要求有依据可查。"""
    items = value.get("schoolAdvice")
    if items is None:
        return
    scope = prepared.get("reportScope", {}).get("schools", ["form", "luopan"])
    if not isinstance(items, list) or len(items) > 20:
        raise ValueError("方位建议条目数量无效")
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("方位建议条目格式无效")
        school = item.get("school")
        if school not in SCHOOL_ADVICE_KEYS or school not in scope:
            raise ValueError("方位建议引用了未选择或未知的流派")
        for name in ["title", "analysis"]:
            text_value = item.get(name)
            if not isinstance(text_value, str) or not 0 < len(text_value) <= 4000:
                raise ValueError("方位建议需要标题与说明")
        if len(item["title"]) > 160:
            raise ValueError("方位建议标题过长")
        impact = item.get("practicalImpact")
        if impact is not None and (
            not isinstance(impact, str) or len(impact) > 4000
        ):
            raise ValueError("方位建议的实际影响说明无效")
        improvements = item.get("improvements")
        if (
            not isinstance(improvements, list)
            or not improvements
            or len(improvements) > 8
            or not all(
                isinstance(entry, str) and 0 < len(entry) <= 1500
                for entry in improvements
            )
        ):
            raise ValueError("方位建议需要可执行条目")
        if item.get("priority") not in (None, "high", "medium", "low"):
            raise ValueError("方位建议优先级无效")
        refs = item.get("evidenceRefs")
        if (
            not isinstance(refs, list)
            or not refs
            or not all(isinstance(ref, str) and 0 < len(ref) <= 200 for ref in refs)
            or not any(
                ref in image_ids or ref in geometry_refs or ref == "compass"
                for ref in refs
            )
        ):
            raise ValueError("方位建议必须引用本次截图、几何证据或罗盘记录")


def diagram_class():
    from reportlab.platypus import Flowable
    from reportlab.lib.colors import HexColor

    class SpatialDiagram(Flowable):
        def __init__(
            self,
            prepared,
            room=None,
            highlights=(),
            paths=(),
            mode="iso",
            width=510,
            height=240,
        ):
            super().__init__()
            self.width, self.height = width, height
            self.prepared, self.room = prepared, room
            self.highlights, self.paths, self.mode = set(highlights), paths, mode
            self.objects = [
                item
                for item in prepared["objects"]
                if room is None or room["id"] in item.get("roomIds", [])
            ]

        def project(self, point):
            x, y, z = point
            return (
                (x, -z)
                if self.mode == "top"
                else ((x - z) * 0.7071, y * 0.9 + (x + z) * 0.3536)
            )

        def draw(self):
            canvas = self.canv
            canvas.setFillColor(HexColor("#f4f7f2"))
            canvas.roundRect(0, 0, self.width, self.height, 8, fill=1, stroke=0)
            polygons = []
            for room in self.prepared["rooms"]:
                if self.room and room["id"] != self.room["id"]:
                    continue
                floor = room.get("floorY")
                if room.get("polygonXZ") and floor is not None:
                    polygon = [[p[0], floor, p[1]] for p in room["polygonXZ"]]
                    polygons.append((polygon, "#d5e1d3", room["id"], False))
                    if self.mode == "iso" and room.get("ceilingHeightM"):
                        polygons.append(
                            (
                                [
                                    [p[0], floor + room["ceilingHeightM"], p[1]]
                                    for p in room["polygonXZ"]
                                ],
                                "#d5e1d3",
                                "",
                                True,
                            )
                        )
            for item in self.objects:
                box = item.get("box")
                if box:
                    bottom = [
                        world(
                            box,
                            [
                                x * box["size"][0] / 2,
                                -box["size"][1] / 2,
                                z * box["size"][2] / 2,
                            ],
                        )
                        for x, z in [(-1, -1), (1, -1), (1, 1), (-1, 1)]
                    ]
                    top = [[p[0], p[1] + box["size"][1], p[2]] for p in bottom]
                    color = PALETTE.get(item["type"], "#b0b9ad")
                    polygons.append((top, color, item["id"], False))
                    if self.mode == "iso":
                        polygons.append(
                            ([bottom[0], bottom[1], top[1], top[0]], color, "", False)
                        )
                        polygons.append(
                            ([bottom[1], bottom[2], top[2], top[1]], color, "", False)
                        )
                surface = item.get("surface")
                if surface:
                    normal = unit(surface["normal"])
                    u = unit(cross(surface["up"], normal))
                    v = cross(normal, u)
                    corners = [
                        add(
                            surface["center"],
                            add(
                                scale(u, x * surface["widthM"] / 2),
                                scale(v, y * surface["heightM"] / 2),
                            ),
                        )
                        for x, y in [(-1, -1), (1, -1), (1, 1), (-1, 1)]
                    ]
                    polygons.append(
                        (
                            corners,
                            PALETTE.get(item["type"], "#b0b9ad"),
                            item["id"],
                            False,
                        )
                    )
            coordinates = [
                self.project(point)
                for polygon, _, _, _ in polygons
                for point in polygon
            ]
            coordinates += [
                self.project(point)
                for start, end, _ in self.paths
                for point in [start, end]
            ]
            if not coordinates:
                canvas.setFont(FONT, 10)
                canvas.setFillColor(HexColor(MUTED))
                canvas.drawCentredString(
                    self.width / 2,
                    self.height / 2,
                    "本区域缺少可绘制几何，需补充空间证据",
                )
                return
            xs, ys = zip(*coordinates)
            lo_x, lo_y, hi_x, hi_y = min(xs), min(ys), max(xs), max(ys)
            factor = min(
                (self.width - 64) / max(hi_x - lo_x, 0.1),
                (self.height - 60) / max(hi_y - lo_y, 0.1),
            )

            def point(p):
                x, y = self.project(p)
                return (
                    (x - (lo_x + hi_x) / 2) * factor + self.width / 2,
                    (y - (lo_y + hi_y) / 2) * factor + self.height / 2,
                )

            for polygon, color, identity, dashed in polygons:
                converted = [point(p) for p in polygon]
                path = canvas.beginPath()
                path.moveTo(*converted[0])
                for p in converted[1:]:
                    path.lineTo(*p)
                path.close()
                canvas.setStrokeColor(
                    HexColor("#b34532" if identity in self.highlights else color)
                )
                canvas.setFillColor(HexColor(color))
                canvas.setLineWidth(1.8 if identity in self.highlights else 0.7)
                canvas.setDash(3, 3) if dashed else canvas.setDash()
                canvas.drawPath(
                    path, fill=0 if dashed or color == PALETTE["wall"] else 1, stroke=1
                )
                if identity:
                    x, y = converted[0]
                    canvas.setFillColor(HexColor(INK))
                    canvas.setFont(FONT, 7)
                    canvas.drawString(
                        max(4, min(x, self.width - 100)),
                        max(5, min(y - 10, self.height - 12)),
                        identity[:24],
                    )
            for start, end, style in self.paths:
                x1, y1 = point(start)
                x2, y2 = point(end)
                canvas.setStrokeColor(
                    HexColor("#246ca0" if style == "velocity" else "#a45d28")
                )
                canvas.setLineWidth(1.8)
                canvas.setDash() if style == "velocity" else canvas.setDash(4, 3)
                canvas.line(x1, y1, x2, y2)
                if style == "velocity":
                    angle = math.atan2(y2 - y1, x2 - x1)
                    for delta in [-0.45, 0.45]:
                        canvas.line(
                            x2,
                            y2,
                            x2 - 7 * math.cos(angle + delta),
                            y2 - 7 * math.sin(angle + delta),
                        )
            canvas.setDash()
            canvas.setFont(FONT, 8)
            canvas.setFillColor(HexColor(MUTED))
            canvas.drawString(
                10,
                self.height - 15,
                "轴测示意 · 米制 Y-up" if self.mode == "iso" else "平面定位 · XZ",
            )

    return SpatialDiagram


def create_pdf(
    session_path,
    context,
    output,
    draft=False,
    font=None,
    airflow=None,
    interpretation_path=None,
):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        PageBreak,
        Table,
        TableStyle,
        Image as PdfImage,
    )

    state = checked_session(session_path, context)
    require_current_analysis(state)
    directory = Path(session_path).resolve().parent
    prepared, _ = load(state["scenePath"])
    report, report_sha = load(state["reportPath"])
    validate(prepared)
    if report.get("resourceCode") != prepared["resourceCode"] or report.get(
        "sceneFingerprint"
    ) != fingerprint(prepared):
        raise ValueError("风水分析与用于绘图的场景不一致，请重新评估")
    actual_analysis, actual_sha = load(state["analysisPath"])
    if (
        actual_sha != state.get("analysisSha256")
        or actual_analysis.get("resourceCode") != prepared["resourceCode"]
    ):
        raise ValueError("原始空间解析结果已变化")
    images, gaps = read_images(directory, state, prepared, draft)
    required = {
        identity
        for row in report["findings"]
        if row["status"] == "candidate"
        for identity in row["objectIds"]
    }
    covered = {identity for image in images for identity in image.get("objectIds", [])}
    missing_images = sorted(required - covered)
    if missing_images:
        gaps.append("需要对应截图的对象 " + "、".join(missing_images))
    if gaps and not draft:
        raise ValueError("关键结论缺少对应截图，请按 capture-plan 补齐后生成正式 PDF")
    field = airflow_field(airflow, prepared)
    narrative = interpretation(interpretation_path, prepared, report, images, draft)
    register_font(font)
    destination = Path(output).resolve()
    protected = [
        Path(session_path).resolve(),
        Path(state["scenePath"]).resolve(),
        Path(state["reportPath"]).resolve(),
        Path(state["analysisPath"]).resolve(),
    ]
    if not draft and not destination.is_relative_to(directory):
        raise ValueError("正式 PDF 请保存到本次任务目录，避免覆盖其他会话的报告")
    if destination in protected or destination.suffix.lower() != ".pdf":
        raise ValueError("PDF 输出不能覆盖输入原件，且须使用 .pdf 扩展名")
    destination.parent.mkdir(parents=True, exist_ok=True)
    styles = {
        "title": ParagraphStyle(
            "title",
            fontName=FONT,
            fontSize=25,
            leading=34,
            textColor=colors.HexColor(INK),
            spaceAfter=18,
        ),
        "h1": ParagraphStyle(
            "h1",
            fontName=FONT,
            fontSize=17,
            leading=25,
            textColor=colors.HexColor(GREEN),
            spaceAfter=13,
        ),
        "h2": ParagraphStyle(
            "h2",
            fontName=FONT,
            fontSize=12,
            leading=18,
            textColor=colors.HexColor(INK),
            spaceBefore=8,
            spaceAfter=7,
        ),
        "body": ParagraphStyle(
            "body",
            fontName=FONT,
            fontSize=9.2,
            leading=15.5,
            wordWrap="CJK",
            textColor=colors.HexColor(INK),
            spaceAfter=9,
        ),
        "small": ParagraphStyle(
            "small",
            fontName=FONT,
            fontSize=7.6,
            leading=12,
            wordWrap="CJK",
            textColor=colors.HexColor(MUTED),
            spaceAfter=8,
        ),
    }
    story = []

    def para(value, style="body"):
        return Paragraph(escape(str(value)).replace("\n", "<br/>"), styles[style])

    def table(rows, widths=None):
        result = Table(
            [[para(cell, "small") for cell in row] for row in rows],
            colWidths=widths or [130, 381],
            hAlign="LEFT",
        )
        result.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8efe5")),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#d7dfd3")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        return result

    Diagram = diagram_class()

    def screenshot(image, max_height=210, max_width=511):
        from PIL import Image

        with Image.open(image["file"]) as source:
            width, height = source.size
        ratio = min(max_width / width, max_height / height)
        return PdfImage(
            str(image["file"]),
            width=width * ratio,
            height=height * ratio,
            hAlign="LEFT",
        )

    def caption(image):
        kind = "VR 实景截图" if image["kind"] == "vr-screenshot" else "合成示例截图"
        return para(
            f"{image['figureId']} · {kind} · 点位 {image['context'].get('panoIndex')} · {image['capturedAt']}\n对象 {'、'.join(f'{i + 1} {identity}' for i, identity in enumerate(image.get('objectIds', []))) or '空间总览'}",
            "small",
        )

    story += [
        Spacer(1, 55),
        para("空间格局与风水\n图解分析报告", "title"),
        para(state["request"]["context"]["displayName"], "h1"),
        para(f"资源 {prepared['resourceCode']} · 规则 {report['ruleset']}"),
        para(
            "草稿 / 合成或不完整证据"
            if draft or gaps
            else "截图证据已核对，结论按各项输入条件说明",
            "h2",
        ),
        para(
            "分析覆盖空间布局、主要物品、梁与停留区域、门洞对向、镜面反射、背靠及通风条件。几何事实、传统解释和待核实事项分别说明。"
        ),
        table(
            [
                ["核查项", "本次记录"],
                ["授权范围", "完整空间解析、必要本机下载、截图与 PDF"],
                ["用户授权", state["authorization"]["userReply"]],
                ["数据绑定", "本次资源码、空间结果哈希及页面会话"],
                [
                    "通风图依据",
                    f"{field['basis']} · {field['method']}"
                    if field
                    else "开口与遮挡的几何示意，真实风速/流量未计算",
                ],
                ["截图状态", f"{len(images)} 张，待补 {len(missing_images)} 个对象"],
            ]
        ),
        Spacer(1, 18),
        para("报告时间 " + datetime.now(timezone.utc).isoformat(), "small"),
        PageBreak(),
    ]
    story += [para("结论概览与改善重点", "h1")]
    story += [
        para(narrative["summary"]),
        para("采用方法 " + "、".join(narrative["methods"]), "small"),
    ]
    counts = report["summary"]
    story += [
        para(
            f"发现 {counts.get('candidate', 0)} 个布局核查候选，{counts.get('unknown', 0)} 项需要补充输入。候选以对应的空间关系和截图为依据，待结合实际使用姿态复核。"
        )
    ]
    rows = [["核查内容", "本次结果"]]
    for item in report["findings"]:
        rows.append(
            [
                item["title"],
                STATUS[item["status"]] + " · " + "、".join(item["objectIds"]),
            ]
        )
    story += [table(rows), Spacer(1, 12)]
    priorities = {"high": "优先核查", "medium": "随后改善", "low": "可选优化"}
    for note in sorted(
        narrative["notes"],
        key=lambda note: ["high", "medium", "low"].index(note["priority"]),
    )[:3]:
        story += [
            para(
                priorities[note["priority"]] + " · " + "、".join(note["objectIds"]),
                "h2",
            )
        ]
        for improvement in note["improvements"][:1]:
            story += [para(improvement)]
    for item in report["findings"]:
        if item["status"] == "candidate" and not narrative["notes"]:
            story += [para(item["title"], "h2"), para(item["reviewAction"])]
    if gaps:
        story += [para("截图与证据待补齐", "h2"), para("\n".join(gaps))]
    for room in prepared["rooms"]:
        story += [
            PageBreak(),
            para(room.get("name", room["id"]) + " · 空间解析", "h1"),
            table(
                [
                    ["房间 ID", room["id"]],
                    [
                        "面积与净层高",
                        f"{room['areaM2']} m² / {room.get('ceilingHeightM')} m",
                    ],
                    [
                        "轮廓依据",
                        "来自本次空间结果或已登记标注"
                        if room.get("polygonXZ")
                        else "轮廓缺失，图中只显示已提供对象",
                    ],
                ]
            ),
            Spacer(1, 10),
            Diagram(prepared, room, mode="top", height=215),
            para(
                "平面定位图。房间轮廓与物品投影用于定位，尺寸与未知状态以空间结果为准。",
                "small",
            ),
            Diagram(prepared, room, mode="iso", height=230),
            para(
                "几何盒与平面示意。显示物品高度和相对关系，图示的几何近似程度沿用输入可信度。",
                "small",
            ),
        ]
    groups = {}
    for item in report["findings"]:
        if not item["ruleId"].startswith("ENV-"):
            groups[f"{item['ruleId']}:{len(groups)}"] = [item]
    for code, items in groups.items():
        story += [PageBreak(), para(items[0]["title"], "h1")]
        identities = {identity for item in items for identity in item["objectIds"]}
        relevant = sorted(
            images,
            key=lambda image: len(set(image.get("objectIds", [])) & identities),
            reverse=True,
        )
        relevant = [
            image for image in relevant if identities & set(image.get("objectIds", []))
        ]
        paths = []
        for item in items:
            metrics = item["measurements"]
            if metrics.get("reflectionPoint"):
                start = metrics.get("observerPoint") or metrics.get("reviewPoint")
                end = metrics.get("targetPoint") or metrics.get("reviewPoint")
                paths += [
                    (start, metrics["reflectionPoint"], "geometry"),
                    (metrics["reflectionPoint"], end, "geometry"),
                ]
        if relevant:
            visuals = Table(
                [
                    [
                        screenshot(relevant[0], 180, 245),
                        Diagram(
                            prepared,
                            highlights=identities,
                            paths=paths,
                            width=245,
                            height=185,
                        ),
                    ]
                ],
                colWidths=[255, 256],
            )
            visuals.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ]
                )
            )
            story += [visuals, caption(relevant[0])]
        else:
            story += [
                para("本项对应实景截图待补齐。", "small"),
                Diagram(prepared, highlights=identities, paths=paths, height=195),
            ]
        story += [
            para(
                "右图为本项空间关系示意，虚线为给定点与平面产生的几何路径。实景大图和相机记录见截图证据索引。",
                "small",
            )
        ]
        for item in items:
            story += [
                para(
                    STATUS[item["status"]] + " · " + "、".join(item["objectIds"]), "h2"
                )
            ]
            metrics = item["measurements"]
            selected = {
                key: value
                for key, value in metrics.items()
                if key not in ["blockers", "occlusionCoverage"]
            }
            if selected:
                story += [
                    table(
                        [["测量 / 条件", "本次值"]]
                        + [
                            [METRIC_LABELS.get(key, key), metric_value(value)]
                            for key, value in selected.items()
                        ]
                    )
                ]
            if metrics.get("blockers"):
                story += [
                    para(
                        "标注遮挡物 "
                        + "、".join(hit["objectId"] for hit in metrics["blockers"])
                    )
                ]
            note = next(
                (
                    note
                    for note in narrative["notes"]
                    if note["ruleId"] == item["ruleId"]
                    and set(note["objectIds"]) == set(item["objectIds"])
                ),
                None,
            )
            if note:
                story += [
                    para("传统分析", "h2"),
                    para(note["analysis"]),
                    para("实际空间影响", "h2"),
                    para(note["practicalImpact"]),
                    para("改善建议", "h2"),
                ]
                for index, improvement in enumerate(note["improvements"], start=1):
                    story += [para(f"{index}. {improvement}")]
                story += [para("解读证据 " + "、".join(note["evidenceRefs"]), "small")]
            if item["traditionalInterpretation"]:
                story += [para(item["traditionalInterpretation"])]
            story += [para(item["reviewAction"])]
            if item["missing"]:
                story += [para("待核实 " + "、".join(item["missing"]), "small")]
            story += [para("证据 " + "、".join(item["evidenceRefs"]), "small")]
    story += [PageBreak(), para("层高、开口与空气流动", "h1")]
    object_map = {item["id"]: item for item in prepared["objects"]}
    for room in prepared["rooms"]:
        paths = []
        opening_result = next(
            (
                item
                for item in report["findings"]
                if item["ruleId"] == "ENV-OPENINGS" and room["id"] in item["objectIds"]
            ),
            None,
        )
        if field:
            vectors = [
                item for item in field["vectors"] if item["roomId"] == room["id"]
            ]
            step = max(1, math.ceil(len(vectors) / 80))
            for item in vectors[::step]:
                paths.append(
                    (
                        item["position"],
                        add(item["position"], scale(item["velocityMps"], 0.4)),
                        "velocity",
                    )
                )
        elif opening_result:
            for pair in opening_result["measurements"]["openingPairs"]:
                a, b = [
                    object_map[identity]["surface"]["center"]
                    for identity in pair["openingIds"]
                ]
                paths.append((a, b, "geometry"))
        story += [
            para(room.get("name", room["id"]), "h2"),
            Diagram(prepared, room, paths=paths, height=240),
        ]
        if field:
            story += [
                para(
                    f"气流矢量 · {field['basis']} · {field['method']}。箭头为输入速度矢量的缩放展示，长度按 0.4 s 位移绘制，最多抽样显示 80 个。",
                    "small",
                ),
                para("来源 " + field["evidenceRef"]),
                table(
                    [
                        [
                            "工况边界",
                            json.dumps(field["boundaryConditions"], ensure_ascii=False),
                        ]
                    ]
                ),
            ]
        else:
            story += [
                para(
                    "通风路径几何示意。虚线无流速与实际流向含义，尚未求解真实空气流场。",
                    "small",
                )
            ]
        volume = next(
            (
                item
                for item in report["findings"]
                if item["ruleId"] == "ENV-VOLUME" and room["id"] in item["objectIds"]
            ),
            None,
        )
        if volume:
            story += [
                table(
                    [["体积 / 换气条件", "本次值"]]
                    + [
                        [METRIC_LABELS.get(key, key), metric_value(value)]
                        for key, value in volume["measurements"].items()
                    ]
                ),
                para(
                    "在相同室外通风量下，层高增大使体积增大，Q/V 对应换气次数降低。实际通风还需要开口有效面积、风压、温差、阻力和设备状态。"
                ),
            ]
        if opening_result:
            story += [
                para(
                    f"已确认开启的对外开口 {opening_result['measurements']['activeExteriorOpeningIds']}。其他开口状态 {opening_result['measurements']['unknownOpeningIds']}。",
                    "small",
                )
            ]
    for image in images:
        story += [
            PageBreak(),
            para("截图证据 " + image["figureId"], "h1"),
            screenshot(image, 560),
            caption(image),
        ]
    story += [
        PageBreak(),
        para("流派依据、缺项与溯源", "h1"),
        para(
            "形势侧重门、床、镜、梁和围合关系。八宅需要确认宅卦与方位，玄空需要年份、可靠坐向和相应流派排盘。三合外局需要室外地形与水系。下表说明本次覆盖状态。"
        ),
    ]
    story += [
        table(
            [["流派 / 模块", "输入与适用状态"]]
            + [
                [METRIC_LABELS.get(key, key), metric_value(value)]
                for key, value in report["schools"].items()
            ]
        )
    ]
    for item in report.get("notAssessed", []):
        story += [
            para(
                f"{item['objectId']}（{item['type']}）的专用规则待补，需结合参考资料核查。",
                "small",
            )
        ]
    story += [
        para("传统资料与物理定义", "h2"),
        para(
            "FengShui Master 传统流派资料、二十四山与基础洛书工具。MIT 授权来源和固定版本见随包 references/upstream.md。"
        ),
        para(
            "《宅经》《葬书》用于传统术语与形势概念溯源。现代室内几何筛查参数按本报告记录解释。"
        ),
        para(
            "通风定义参考 ASHRAE Fundamentals 2025 第 16 章，以及 WHO Natural Ventilation for Infection Control in Health-Care Settings 的风量/体积定义。住宅分析保留各自适用条件。"
        ),
        para("空间结果 SHA256 " + str(state.get("analysisSha256")), "small"),
        para("风水结果 SHA256 " + report_sha, "small"),
        para("场景指纹 " + fingerprint(prepared), "small"),
    ]
    fd, temporary = tempfile.mkstemp(
        suffix=".pdf", prefix=".fengshui-", dir=destination.parent
    )
    os.close(fd)

    def page_header(canvas, doc):
        canvas.saveState()
        canvas.setFont(FONT, 8)
        canvas.setFillColor(colors.HexColor(MUTED))
        canvas.drawString(
            42, A4[1] - 25, "空间格局与风水图解报告 · " + prepared["resourceCode"]
        )
        canvas.drawRightString(A4[0] - 42, 22, str(doc.page))
        if draft or gaps:
            canvas.drawString(42, 22, "草稿 / 合成或不完整证据")
        canvas.restoreState()

    try:
        document = SimpleDocTemplate(
            temporary,
            pagesize=A4,
            rightMargin=42,
            leftMargin=42,
            topMargin=47,
            bottomMargin=42,
            title="空间格局与风水图解分析报告",
            author="Realsee spatial fengshui",
        )
        document.build(story, onFirstPage=page_header, onLaterPages=page_header)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    manifest = {
        "schema": "spatial-fengshui.report",
        "version": 1,
        "resourceCode": prepared["resourceCode"],
        "requestSha256": state["requestSha256"],
        "analysisSha256": state.get("analysisSha256"),
        "sceneFingerprint": fingerprint(prepared),
        "pdf": str(destination),
        "pdfSha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "status": "draft" if draft or gaps else "evidence-complete",
        "evidenceGaps": gaps,
        "contentLimitations": [
            item
            for item in report["findings"]
            if item["status"] in {"unknown", "limited"}
        ],
        "airflowBasis": field["basis"] if field else "geometric-only",
        "screenshots": len(images),
        "pageCount": document.page,
        "visualReviewStatus": "pending",
        "interpretationSha256": hashlib.sha256(
            Path(interpretation_path).read_bytes()
        ).hexdigest()
        if interpretation_path
        else None,
        "figureAssets": [
            {
                "figureId": image["figureId"],
                "sha256": image["sha256"],
                "objectIds": image.get("objectIds", []),
            }
            for image in images
        ],
    }
    atomic_json(directory / "report-manifest.json", manifest)
    state.update(
        status="report_draft" if draft or gaps else "pdf_generated",
        pdfPath=str(destination),
    )
    atomic_json(session_path, state)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--airflow-field")
    parser.add_argument("--interpretation")
    parser.add_argument("--draft", action="store_true")
    args = parser.parse_args(argv)
    try:
        from workflow import optional_download_lock

        with optional_download_lock(args.session):
            from html_report import create_html

            result = create_html(
                args.session,
                read_context(args.context),
                args.output,
                args.draft,
                args.airflow_field,
                args.interpretation,
            )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        RuntimeError,
        ImportError,
    ) as error:
        print(
            json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
