"""Validate standalone scenes and adapt external spatial-analysis results."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path

from geometry import cross, dot

FRAME = {"name": "y-up-meters", "unit": "m", "up": "Y"}
CONFIDENCES = {"high", "medium", "low", "unknown"}
TYPES = {
    "bed",
    "desk",
    "door",
    "window",
    "mirror",
    "beam",
    "column",
    "wall",
    "partition",
    "cabinet",
    "stove",
    "sink",
    "toilet",
    "sofa",
    "other",
}
ALIASES = {
    "床": "bed",
    "书桌": "desk",
    "桌子": "desk",
    "门": "door",
    "doorway": "door",
    "镜子": "mirror",
    "窗户": "window",
    "横梁": "beam",
    "柱子": "column",
    "柜子": "cabinet",
    "沙发": "sofa",
    "灶台": "stove",
}
FUNCTIONS = {
    "bedroom",
    "living",
    "office",
    "kitchen",
    "bath",
    "corridor",
    "other",
    "unknown",
}
SPACE_TYPES = {
    "residential",
    "office",
    "retail",
    "factory",
    "other",
    "unknown",
}


def number(value, path, positive=False):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"{path} 必须为有限数值")
    if abs(value) > 10000 or (positive and value <= 0):
        raise ValueError(f"{path} 超出支持范围（绝对值至多 10000，尺寸须为正）")
    return value


def text(value, path):
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError(f"{path} 必须是非空短文本")
    return value


def vector(value, path):
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{path} 必须是三个数值的坐标")
    return [number(v, f"{path}[{i}]") for i, v in enumerate(value)]


def unique(items, path, limit=512):
    if not isinstance(items, list) or len(items) > limit:
        raise ValueError(f"{path} 必须是至多 {limit} 个条目的列表")
    ids = set()
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"{path}[{i}] 必须是对象")
        identity = text(item.get("id"), f"{path}[{i}].id")
        if not re.fullmatch(r"[A-Za-z0-9_.:@-]{1,128}", identity):
            raise ValueError(f"{path}[{i}].id 格式无效")
        if identity in ids:
            raise ValueError(f"{path} 存在重复 id {identity}")
        ids.add(identity)
    return ids


def evidence(item, path):
    refs = item.get("evidenceRefs", [])
    if not isinstance(refs, list) or len(refs) > 64:
        raise ValueError(f"{path}.evidenceRefs 必须是至多 64 个引用的列表")
    for ref in refs:
        text(ref, f"{path}.evidenceRefs")
    if item.get("confidence", "unknown") not in CONFIDENCES:
        raise ValueError(f"{path}.confidence 无效")


def validate_surface(surface, path):
    if not isinstance(surface, dict):
        raise ValueError(f"{path} 必须是对象")
    vector(surface.get("center"), path + ".center")
    normal = vector(surface.get("normal"), path + ".normal")
    up = vector(surface.get("up"), path + ".up")
    if dot(cross(normal, up), cross(normal, up)) < 1e-8:
        raise ValueError(f"{path} 的 normal 与 up 必须非零且不平行")
    number(surface.get("widthM"), path + ".widthM", positive=True)
    number(surface.get("heightM"), path + ".heightM", positive=True)
    if surface.get("normalBasis") not in {
        None,
        "two-sided",
        "outward",
        "reflective",
        "unknown",
    }:
        raise ValueError("surface.normalBasis 无效")


def validate_xuan_kong(xuan):
    if not isinstance(xuan, dict):
        raise ValueError("xuanKong 必须是对象")
    if xuan.get("basis") not in {None, "build", "renovation", "moveIn", "explicit"}:
        raise ValueError("xuanKong.basis 无效")
    if xuan.get("year") is not None:
        year = number(xuan["year"], "xuanKong.year")
        if int(year) != year or not 1901 <= year <= 2099:
            raise ValueError("xuanKong.year 必须是 1901–2099 的整数年份")
    if xuan.get("yun") is not None and (
        type(xuan["yun"]) is not int or not 1 <= xuan["yun"] <= 9
    ):
        raise ValueError("xuanKong.yun 必须是 1–9 的整数，不能是布尔值")
    if xuan.get("chartSource") not in {None, "xuankong.py", "external"}:
        raise ValueError("xuanKong.chartSource 无效")
    if xuan.get("evidenceRef") is not None:
        text(xuan["evidenceRef"], "xuanKong.evidenceRef")
    chart = xuan.get("chart")
    if chart is None:
        return
    if (
        not isinstance(chart, dict)
        or type(chart.get("yun")) is not int
        or not 1 <= chart["yun"] <= 9
    ):
        raise ValueError("玄空宅盘须包含有效运数与完整九宫运/山/向三盘")
    palaces = {"中", "乾", "兑", "艮", "离", "坎", "坤", "震", "巽"}
    grid = chart.get("grid")
    if not isinstance(grid, dict) or set(grid) != palaces:
        raise ValueError("玄空宅盘须包含完整九宫 grid")
    for key in ["yun", "shan", "xiang"]:
        values = [
            grid[p].get(key) if isinstance(grid[p], dict) else None for p in palaces
        ]
        if any(
            type(value) is not int or not 1 <= value <= 9 for value in values
        ) or set(values) != set(range(1, 10)):
            raise ValueError("玄空宅盘每一盘须为完整的 1–9 星序")
    if grid["中"]["yun"] != chart["yun"] or (
        xuan.get("yun") is not None and xuan["yun"] != chart["yun"]
    ):
        raise ValueError("玄空宅盘运数与输入或中宫不一致")
    if xuan.get("chartSource") not in {"xuankong.py", "external"}:
        raise ValueError("玄空宅盘必须说明 chartSource")
    text(xuan.get("evidenceRef"), "xuanKong.evidenceRef")


def validate(scene):
    if (
        not isinstance(scene, dict)
        or scene.get("schema") != "spatial-fengshui.scene"
        or (type(scene.get("version")) is not int or scene.get("version") != 1)
    ):
        raise ValueError("需要 spatial-fengshui.scene version 1")
    if scene.get("frame") != FRAME:
        raise ValueError("frame 必须为 y-up-meters / m / Y，须先转换坐标")
    identity = text(scene.get("resourceCode"), "resourceCode")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identity):
        raise ValueError("resourceCode 格式无效")
    assumptions = scene.get("assumptions", [])
    if not isinstance(assumptions, list) or len(assumptions) > 64:
        raise ValueError("assumptions 必须是至多 64 个说明的列表")
    for assumption in assumptions:
        text(assumption, "assumptions")
    rooms = scene.get("rooms", [])
    room_ids = unique(rooms, "rooms", limit=64)
    for room in rooms:
        evidence(room, "room " + room["id"])
        if room.get("function", "unknown") not in FUNCTIONS:
            raise ValueError("room.function 无效")
        number(room.get("areaM2"), "room.areaM2", positive=True)
        for key in ["floorY", "ceilingHeightM"]:
            if room.get(key) is not None:
                number(room[key], "room." + key, positive=key == "ceilingHeightM")
        if room.get("polygonXZ") is not None:
            polygon = room["polygonXZ"]
            if not isinstance(polygon, list) or not 3 <= len(polygon) <= 256:
                raise ValueError("polygonXZ 必须是 3–256 个平面点")
            for point in polygon:
                if not isinstance(point, list) or len(point) != 2:
                    raise ValueError("polygonXZ 的点必须是 [x,z]")
                for coordinate in point:
                    number(coordinate, "polygonXZ")
        ventilation = room.get("ventilation", {})
        if not isinstance(ventilation, dict):
            raise ValueError("ventilation 必须是对象")
        if ventilation.get("flowM3h") is not None:
            number(ventilation["flowM3h"], "flowM3h", positive=True)
            if ventilation.get("basis") not in {"measured", "simulated", "scenario"}:
                raise ValueError("通风量须标明 measured / simulated / scenario")
            text(ventilation.get("evidenceRef"), "ventilation.evidenceRef")
    objects = scene.get("objects", [])
    unique(objects, "objects", limit=1024)
    for item in objects:
        path = "object " + item["id"]
        evidence(item, path)
        if "name" in item:
            text(item["name"], path + ".name")
        if "identityConfirmed" in item and type(item["identityConfirmed"]) is not bool:
            raise ValueError("identityConfirmed 必须是布尔值")
        if item.get("identityConfirmed"):
            text(item.get("identityEvidenceRef"), path + ".identityEvidenceRef")
        if item.get("type") not in TYPES:
            raise ValueError(f"{path}.type 无效")
        refs = item.get("roomIds", [])
        if (
            not isinstance(refs, list)
            or any(r not in room_ids for r in refs)
            or len(refs) != len(set(refs))
        ):
            raise ValueError(f"{path}.roomIds 引用了未知或重复房间")
        box = item.get("box")
        if box is not None:
            if not isinstance(box, dict):
                raise ValueError(f"{path}.box 必须是对象")
            vector(box.get("center"), path + ".box.center")
            size = vector(box.get("size"), path + ".box.size")
            if min(size) <= 0:
                raise ValueError(f"{path}.box.size 必须为正")
            number(box.get("yawRad"), path + ".box.yawRad")
        if item.get("surface") is not None:
            validate_surface(item["surface"], path + ".surface")
        for key in ["reviewPoint", "headPoint", "backDirection"]:
            if item.get(key) is not None:
                v = vector(item[key], path + "." + key)
                if key == "backDirection" and dot(v, v) < 1e-8:
                    raise ValueError("backDirection 必须非零")
        for key in ["occludes", "exterior"]:
            if key in item and not isinstance(item[key], bool):
                raise ValueError(f"{path}.{key} 必须是布尔值")
        if item.get("openFraction") is not None:
            value = number(item["openFraction"], path + ".openFraction")
            if not 0 <= value <= 1:
                raise ValueError("openFraction 必须在 [0, 1] 内")
    context = scene.get("compass", {})
    if not isinstance(context, dict):
        raise ValueError("compass 必须是对象")
    if context.get("facingDegrees") is not None:
        degree = number(context["facingDegrees"], "compass.facingDegrees")
        if not 0 <= degree < 360:
            raise ValueError("facingDegrees 必须在 [0, 360) 内")
        text(context.get("evidenceRef"), "compass.evidenceRef")
    if context.get("northBasis") not in {
        None,
        "magnetic",
        "true",
        "grid",
        "user-relative",
        "unknown",
    }:
        raise ValueError("compass.northBasis 无效")
    if context.get("uncertaintyDegrees") is not None:
        if number(context["uncertaintyDegrees"], "uncertaintyDegrees") < 0:
            raise ValueError("方位误差必须非负")
    if context.get("houseKua") is not None and (
        isinstance(context["houseKua"], bool)
        or context["houseKua"] not in [1, 2, 3, 4, 6, 7, 8, 9]
    ):
        raise ValueError("houseKua 必须是已确认的八宅卦数")
    if scene.get("occlusionCoverage", "unknown") not in {
        "partial",
        "reviewed",
        "unknown",
    }:
        raise ValueError("occlusionCoverage 无效")
    if scene.get("spaceType", "unknown") not in SPACE_TYPES:
        raise ValueError("spaceType 无效")
    xuan = scene.get("xuanKong")
    if xuan is not None:
        validate_xuan_kong(xuan)
    scope = scene.get("reportScope", {})
    if not isinstance(scope, dict) or set(scope) - {
        "excludedRules",
        "airflowMode",
        "schools",
        "evidenceRef",
    }:
        raise ValueError("reportScope 字段无效")
    if scope:
        text(scope.get("evidenceRef"), "reportScope.evidenceRef")
    if scope.get("airflowMode") not in {None, "geometry", "measured", "simulated"}:
        raise ValueError("reportScope.airflowMode 无效")
    schools = scope.get("schools", ["form", "luopan"])
    if (
        not isinstance(schools, list)
        or not schools
        or any(
            s not in {"form", "luopan", "eightMansions", "xuanKong"} for s in schools
        )
    ):
        raise ValueError("reportScope.schools 无效")
    exclusions = scope.get("excludedRules", [])
    if not isinstance(exclusions, list) or len(exclusions) > 7:
        raise ValueError("reportScope.excludedRules 无效")
    seen_rules = set()
    for entry in exclusions:
        if (
            not isinstance(entry, dict)
            or entry.get("ruleId")
            not in {
                "FS-BEAM",
                "FS-DOOR",
                "FS-MIRROR",
                "FS-REFLECTION",
                "FS-BACKING",
                "ENV-VOLUME",
                "ENV-OPENINGS",
            }
            or entry["ruleId"] in seen_rules
        ):
            raise ValueError("排除项必须引用有效且唯一的规则")
        seen_rules.add(entry["ruleId"])
        text(entry.get("reason"), "excludedRules.reason")
        text(entry.get("evidenceRef"), "excludedRules.evidenceRef")
    return scene


def load(path, max_bytes=8 * 1024 * 1024):
    raw = Path(path).read_bytes()
    if len(raw) > max_bytes:
        raise ValueError("输入文件超过允许的大小")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"JSON 重复键 {key}")
            result[key] = value
        return result

    def reject(value):
        raise ValueError(f"JSON 不允许 {value}")

    return json.loads(
        raw, object_pairs_hook=pairs, parse_constant=reject
    ), hashlib.sha256(raw).hexdigest()


def fingerprint(value):
    content = {key: item for key, item in value.items() if key != "sceneSha256"}
    encoded = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _validate_external(document):
    """外部空间解析结果的最小结构校验；完整约束由本 Skill 的 scene 校验承担。"""
    if not isinstance(document, dict):
        raise ValueError("外部空间解析结果必须是 JSON 对象")
    identity = document.get("resourceCode")
    text(identity, "resourceCode")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identity):
        raise ValueError("外部结果 resourceCode 格式无效")
    if not isinstance(document.get("frame"), dict):
        raise ValueError("外部结果缺少 frame，须先转换为米制、Y 轴向上坐标")
    overview = document.get("overview")
    if not isinstance(overview, dict):
        raise ValueError("外部结果缺少 overview")
    rooms = overview.get("rooms")
    doors = overview.get("doors", [])
    objects = document.get("objects")
    if not isinstance(rooms, list) or not rooms:
        raise ValueError("外部结果缺少 overview.rooms")
    if not isinstance(doors, list) or not isinstance(objects, list):
        raise ValueError("外部结果的 overview.doors 与 objects 必须是列表")
    for i, room in enumerate(rooms):
        required = {"id", "name", "areaM2", "polygon", "panoIndexes", "floorY"}
        if not isinstance(room, dict) or not required <= set(room):
            raise ValueError(f"外部结果 overview.rooms[{i}] 缺少必要字段")
    for i, item in enumerate(objects):
        if not isinstance(item, dict) or not {"id", "label", "roomId"} <= set(item):
            raise ValueError(f"外部结果 objects[{i}] 缺少必要字段")
    for i, door in enumerate(doors):
        if not isinstance(door, dict) or not {"id", "connects"} <= set(door):
            raise ValueError(f"外部结果 overview.doors[{i}] 缺少必要字段")
    return document


def from_analysis(path):
    document, digest = load(path)
    document = _validate_external(document)
    scene = {
        "schema": "spatial-fengshui.scene",
        "version": 1,
        "resourceCode": document["resourceCode"],
        "frame": dict(FRAME),
        "rooms": [],
        "objects": [],
        "occlusionCoverage": "unknown",
        "spaceType": "unknown",
        "sourceAnalysisSha256": digest,
        "compass": {},
        "assumptions": [],
    }
    for i, room in enumerate(document["overview"]["rooms"]):
        scene["rooms"].append(
            {
                "id": room["id"],
                "name": room["name"],
                "function": "unknown",
                "areaM2": room["areaM2"],
                "polygonXZ": room["polygon"],
                "panoIndexes": room["panoIndexes"],
                "floorY": room["floorY"],
                "ceilingHeightM": room.get("ceilingHeightM"),
                "confidence": (room.get("quality") or {}).get("tier", "unknown"),
                "evidenceRefs": [f"analysis:/overview/rooms/{i}"],
            }
        )
    linked = {
        door["objectId"]
        for door in document["overview"]["doors"]
        if door.get("objectId")
    }
    by_id = {item["id"]: item for item in document["objects"]}
    for i, item in enumerate(document["objects"]):
        if item["id"] in linked:
            continue
        label = ALIASES.get(item["label"], item["label"])
        scene["objects"].append(
            {
                "id": item["id"],
                "type": label if label in TYPES else "other",
                "sourceLabel": item["label"],
                "roomIds": [item["roomId"]] if item["roomId"] else [],
                "box": item.get("obb"),
                "confidence": (item.get("quality") or {}).get("tier", "unknown"),
                "evidenceRefs": [f"analysis:/objects/{i}"],
            }
        )
    for i, door in enumerate(document["overview"]["doors"]):
        linked_object = by_id.get(door.get("objectId"), {})
        surface = None
        if all(door.get(key) is not None for key in ["widthM", "heightM", "yawRad"]):
            x, floor, z = door["position"]
            center = (linked_object.get("obb") or {}).get(
                "center", [x, floor + door["heightM"] / 2, z]
            )
            surface = {
                "center": center,
                "normal": [math.sin(door["yawRad"]), 0, math.cos(door["yawRad"])],
                "up": [0, 1, 0],
                "widthM": door["widthM"],
                "heightM": door["heightM"],
                "normalBasis": "two-sided",
            }
        scene["objects"].append(
            {
                "id": door["id"],
                "type": "door",
                "roomIds": [r for r in door["connects"] if r],
                "box": linked_object.get("obb"),
                "surface": surface,
                "confidence": (linked_object.get("quality") or {}).get(
                    "tier", "unknown"
                ),
                "evidenceRefs": [f"analysis:/overview/doors/{i}"],
            }
        )
    if document["frame"].get("orientation"):
        scene["assumptions"].append(
            "上游方位由用户指定且未做地理北校准。房屋坐向和镜面法向需独立确认。"
        )
    return scene


def annotate(scene, annotations):
    if not isinstance(annotations, dict):
        raise ValueError("补充标注必须是对象")
    if annotations.get("schema") != "spatial-fengshui.annotations" or (
        type(annotations.get("version")) is not int or annotations.get("version") != 1
    ):
        raise ValueError("需要 spatial-fengshui.annotations version 1")
    if (
        annotations.get("analysisSha256") != scene["sourceAnalysisSha256"]
        or annotations.get("resourceCode") != scene["resourceCode"]
    ):
        raise ValueError("补充标注的资源身份或 analysisSha256 与本次结果不一致")
    scene = copy.deepcopy(scene)
    groups = [
        (
            "rooms",
            "roomUpdates",
            {
                "ceilingHeightM",
                "floorY",
                "ventilation",
                "confidence",
                "evidenceRefs",
                "function",
            },
        ),
        (
            "objects",
            "objectUpdates",
            {
                "box",
                "surface",
                "reviewPoint",
                "headPoint",
                "backDirection",
                "exterior",
                "openFraction",
                "occludes",
                "confidence",
                "evidenceRefs",
                "roomIds",
                "type",
                "name",
                "identityConfirmed",
                "identityEvidenceRef",
            },
        ),
    ]
    for collection, updates, allowed in groups:
        current = {item["id"]: item for item in scene[collection]}
        unique(annotations.get(updates, []), updates)
        for change in annotations.get(updates, []):
            if change["id"] not in current or set(change) - allowed - {"id"}:
                raise ValueError(f"{updates} 的对象或字段无效")
            if not change.get("evidenceRefs"):
                raise ValueError("补充标注必须保留 evidenceRefs")
            target = current[change["id"]]
            baseline = copy.deepcopy(target)
            target.update(change)
            target["baseline"] = baseline
    additions = annotations.get("objects", [])
    unique(additions, "annotations.objects")
    used = {item["id"] for item in scene["objects"]}
    if any(item["id"] in used for item in additions):
        raise ValueError("新增物品 id 已存在，请使用 objectUpdates")
    scene["objects"].extend(copy.deepcopy(additions))
    for field in [
        "compass",
        "occlusionCoverage",
        "spaceType",
        "xuanKong",
        "assumptions",
        "reportScope",
    ]:
        if field in annotations:
            scene[field] = copy.deepcopy(annotations[field])
    return scene
