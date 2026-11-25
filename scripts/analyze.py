#!/usr/bin/env python3
"""Evidence-based 3D form review with separately labeled traditional interpretation."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import sys
import tempfile

from geometry import (
    EPSILON,
    blockers,
    dot,
    footprint,
    polygons_overlap,
    ray_box,
    reflection_point,
    unit,
    within_surface,
)
from scene import (
    annotate,
    fingerprint,
    from_analysis,
    load,
    number,
    validate,
    validate_xuan_kong,
)
from luopan import mountain_for_bearing
from minggua import DIRECTIONS
from consultation import collect_questions

RULESET = "spatial-fengshui-1"
REFERENCES = {
    "form": "references/traditional-frameworks.md#形势与门床梁镜",
    "compass": "references/traditional-frameworks.md#八宅与二十四山",
    "xuan-kong": "references/traditional-frameworks.md#三元玄空",
    "air": "references/ventilation.md",
}

# 先确认整个空间的类型（住宅/办公/商业/工厂），再谈房间用途与停留区对象。
# 空间类型 unknown 或非住宅/办公时，床、桌、沙发等住宅式布局判断一律不套用。
SPACE_TYPE_COMPAT = {
    "bed": {"residential"},
    "sofa": {"residential", "office"},
    "desk": {"residential", "office"},
}
SPACE_TYPE_LABELS = {
    "residential": "住宅",
    "office": "办公",
    "retail": "商业/店铺",
    "factory": "工厂/厂房",
    "other": "其他",
    "unknown": "未确认",
}
# 床/桌/沙发等停留区对象只有在其房间用途已确认且匹配时才按布局候选计算。
FUNCTION_COMPAT = {
    "bed": {"bedroom"},
    "sofa": {"living", "office"},
    "desk": {"office", "bedroom"},
}
FUNCTION_LABELS = {
    "bedroom": "卧室",
    "living": "客厅",
    "office": "办公/书房",
    "kitchen": "厨房",
    "bath": "卫浴",
    "corridor": "走廊",
    "other": "其他",
    "unknown": "未确认",
}


def room_functions(scene):
    return {room["id"]: room.get("function", "unknown") for room in scene["rooms"]}


def stay_target_note(target, scene):
    """停留区对象（床/桌/沙发）能否作为候选计算；不能时返回需核对的原因。"""
    compat = FUNCTION_COMPAT.get(target["type"])
    if compat is None:
        return None
    space_type = scene.get("spaceType", "unknown")
    if space_type == "unknown":
        return "先确认此空间类型（办公室/住宅/商场/工厂等）"
    if space_type not in SPACE_TYPE_COMPAT.get(target["type"], set()):
        return (
            f"当前空间类型（{SPACE_TYPE_LABELS.get(space_type, space_type)}）"
            f"不适用「{target['type']}」的住宅/办公式布局判断"
        )
    if target.get("confidence", "unknown") in {"low", "unknown"}:
        return "物品身份与几何低可信度，需现场确认后再判断"
    if not target.get("identityConfirmed"):
        return "请先让用户确认此物品的实际身份，检测可信度不能代替身份确认"
    functions = room_functions(scene)
    funcs = {functions.get(room_id, "unknown") for room_id in target.get("roomIds", [])}
    if not funcs or "unknown" in funcs:
        return "先确认此房间用途（卧室/客厅/办公等）与物品身份，再判断停留区布局"
    if funcs - compat:
        return f"物品标为 {target['type']} 但房间用途不符，需核对物品身份或房间用途"
    return None


def same_room(a, b):
    return bool(set(a.get("roomIds", [])) & set(b.get("roomIds", [])))


def confidence(items):
    levels = ["unknown", "low", "medium", "high"]
    return min(
        (
            item.get("confidence", "unknown") if item.get("evidenceRefs") else "unknown"
            for item in items
        ),
        key=levels.index,
        default="unknown",
    )


def finding(
    code,
    title,
    status,
    items=(),
    measurements=None,
    missing=(),
    interpretation="",
    action="",
    source="form",
):
    return {
        "ruleId": code,
        "title": title,
        "status": status,
        "objectIds": [item["id"] for item in items],
        "confidence": confidence(items),
        "evidenceRefs": sorted(
            {ref for item in items for ref in item.get("evidenceRefs", [])}
        ),
        "measurements": measurements or {},
        "missing": list(missing),
        "traditionalInterpretation": interpretation,
        "reviewAction": action,
        "reference": REFERENCES[source],
    }


def with_blockers(scene, subjects, hits):
    identities = {item["id"] for item in subjects}
    blocker_ids = {item["objectId"] for item in hits} - identities
    return list(subjects) + [
        item for item in scene["objects"] if item["id"] in blocker_ids
    ]


def review_point(item):
    if item.get("reviewPoint") is not None:
        return item["reviewPoint"], "annotated-review-point"
    if item.get("box") is not None:
        center = list(item["box"]["center"])
        center[1] += item["box"]["size"][1] / 2
        return center, "box-top-center-proxy"
    return None, "missing"


def beam_review(scene):
    beams = [item for item in scene["objects"] if item["type"] == "beam"]
    targets = [
        item for item in scene["objects"] if item["type"] in {"bed", "desk", "sofa"}
    ]
    if not beams or not targets:
        return [
            finding(
                "FS-BEAM",
                "梁体与停留区域",
                "unknown",
                missing=["梁体与床、桌或沙发的标注及房间归属"],
            )
        ]
    results = []
    reported = set()
    for beam in beams:
        for target in targets:
            if not same_room(beam, target):
                continue
            note = stay_target_note(target, scene)
            if note:
                if target["id"] not in reported:
                    reported.add(target["id"])
                    results.append(
                        finding(
                            "FS-BEAM",
                            "梁体与停留区域",
                            "unknown",
                            [target],
                            missing=[note],
                        )
                    )
                continue
            items = [beam, target]
            if beam.get("box") is None or target.get("box") is None:
                results.append(
                    finding(
                        "FS-BEAM",
                        "梁体与停留区域",
                        "unknown",
                        items,
                        missing=["双方的包围盒"],
                    )
                )
                continue
            beam_box, target_box = beam["box"], target["box"]
            overlaps = polygons_overlap(footprint(beam_box), footprint(target_box))
            beam_bottom = beam_box["center"][1] - beam_box["size"][1] / 2
            target_top = target_box["center"][1] + target_box["size"][1] / 2
            clearance = beam_bottom - target_top
            overhead = overlaps and clearance > 0
            results.append(
                finding(
                    "FS-BEAM",
                    "梁体与停留区域",
                    "candidate" if overhead else "not_observed",
                    items,
                    {
                        "horizontalFootprintsOverlap": overlaps,
                        "beamBottomY": beam_bottom,
                        "targetTopY": target_top,
                        "verticalClearanceM": round(clearance, 6),
                    },
                    interpretation="同室梁体在停留区域上方重叠时，列为形势派横梁压顶的布局核查候选。",
                    action="结合实际坐卧位置、视线、顶面照片和净高确认感受。调整摆放时保留通行空间。",
                )
            )
    return results or [
        finding("FS-BEAM", "梁体与停留区域", "unknown", missing=["同室对象关系"])
    ]


def opening_review(scene):
    results = []
    doors = [item for item in scene["objects"] if item["type"] == "door"]
    targets = [
        item for item in scene["objects"] if item["type"] in {"bed", "desk", "sofa"}
    ]
    maximum = scene.get("settings", {}).get("openingReviewDistanceM", 6.0)
    reported = set()
    for door in doors:
        for target in targets:
            if not same_room(door, target):
                continue
            note = stay_target_note(target, scene)
            if note:
                if target["id"] not in reported:
                    reported.add(target["id"])
                    results.append(
                        finding(
                            "FS-DOOR",
                            "门洞与停留位置对向",
                            "unknown",
                            [target],
                            missing=[note],
                        )
                    )
                continue
            items = [door, target]
            point, basis = review_point(target)
            if door.get("surface") is None or point is None:
                results.append(
                    finding(
                        "FS-DOOR",
                        "门洞与停留位置对向",
                        "unknown",
                        items,
                        missing=["门洞矩形平面与目标审查点"],
                    )
                )
                continue
            inside, projected, depth = within_surface(door["surface"], point)
            aligned = inside and EPSILON < abs(depth) <= maximum
            hits = (
                blockers(projected, point, scene["objects"], [door["id"], target["id"]])
                if aligned
                else []
            )
            status = (
                "candidate"
                if aligned and not hits
                else ("occluded" if aligned else "not_observed")
            )
            results.append(
                finding(
                    "FS-DOOR",
                    "门洞与停留位置对向",
                    status,
                    with_blockers(scene, items, hits),
                    {
                        "reviewPoint": point,
                        "pointBasis": basis,
                        "projectsInsideOpening": inside,
                        "normalDistanceM": round(abs(depth), 6),
                        "reviewDistanceLimitM": maximum,
                        "blockers": hits,
                        "occlusionCoverage": scene.get("occlusionCoverage", "unknown"),
                    },
                    missing=["核对未建模遮挡、实际视线与门的使用状态"]
                    if status == "candidate"
                    else [],
                    interpretation="门洞投影覆盖停留位置时，可核查传统门冲床、门冲座的布局关注点。",
                    action="确认目标审查点和日常活动状态。用顶面中心作代理点时补核对真实眼位。",
                )
            )
    return results or [
        finding(
            "FS-DOOR",
            "门洞与停留位置对向",
            "unknown",
            missing=["同室门洞与床、桌或沙发"],
        )
    ]


def mirror_review(scene):
    results = []
    mirrors = [item for item in scene["objects"] if item["type"] == "mirror"]
    targets = [
        item for item in scene["objects"] if item["type"] in {"bed", "desk", "door"}
    ]
    reported = set()
    for mirror in mirrors:
        for target in targets:
            if not same_room(mirror, target):
                continue
            note = stay_target_note(target, scene)
            if note:
                if target["id"] not in reported:
                    reported.add(target["id"])
                    results.append(
                        finding(
                            "FS-MIRROR",
                            "镜面与床、座位或门的关系",
                            "unknown",
                            [target],
                            missing=[note],
                        )
                    )
                continue
            items = [mirror, target]
            point, basis = review_point(target)
            if mirror.get("surface") is None or point is None:
                results.append(
                    finding(
                        "FS-MIRROR",
                        "镜面与床、座位或门的关系",
                        "unknown",
                        items,
                        missing=["镜面矩形、反射面法向与目标审查点"],
                        action="从可核对的全景、网格或现场补充镜面范围和朝向。镜子包围盒的长轴不能确定反射面正反。",
                    )
                )
                continue
            hit = reflection_point(mirror["surface"], point, point)
            hits = (
                blockers(point, hit, scene["objects"], [mirror["id"], target["id"]])
                if hit
                else []
            )
            status = (
                "candidate"
                if hit is not None and not hits
                else ("occluded" if hit is not None else "not_observed")
            )
            results.append(
                finding(
                    "FS-MIRROR",
                    "镜面与床、座位或门的关系",
                    status,
                    with_blockers(scene, items, hits),
                    {
                        "reviewPoint": point,
                        "pointBasis": basis,
                        "reflectionPoint": hit,
                        "distanceM": round(math.dist(point, hit), 6) if hit else None,
                        "blockers": hits,
                        "occlusionCoverage": scene.get("occlusionCoverage", "unknown"),
                    },
                    missing=["实际眼位与未建模遮挡"] if status == "candidate" else [],
                    interpretation="在给定审查点可形成自反射路径时，列为镜照床、镜照座或镜面正对门的传统布局核查候选。",
                    action="核对坐卧视角、镜面反射和夜间灯光。记录的是一个审查点，范围外的目标部位另行评估。",
                )
            )
    return results or [
        finding(
            "FS-MIRROR",
            "镜面与床、座位或门的关系",
            "unknown",
            missing=["同室镜面和目标对象"],
        )
    ]


def reflected_view_review(scene):
    results = []
    mirrors = [
        item
        for item in scene["objects"]
        if item["type"] == "mirror" and item.get("surface")
    ]
    doors = [
        item
        for item in scene["objects"]
        if item["type"] == "door" and item.get("reviewPoint")
    ]
    beds = [item for item in scene["objects"] if item["type"] == "bed"]
    reported = set()
    for mirror in mirrors:
        for door in doors:
            for bed in beds:
                if not same_room(mirror, door) or not same_room(mirror, bed):
                    continue
                note = stay_target_note(bed, scene)
                if note:
                    if bed["id"] not in reported:
                        reported.add(bed["id"])
                        results.append(
                            finding(
                                "FS-REFLECTION",
                                "经镜面形成的门到床反射路径",
                                "unknown",
                                [bed],
                                missing=[note],
                            )
                        )
                    continue
                target, basis = review_point(bed)
                if target is None:
                    continue
                hit = reflection_point(mirror["surface"], door["reviewPoint"], target)
                items = [mirror, door, bed]
                hits = []
                if hit is not None:
                    hits = blockers(
                        door["reviewPoint"],
                        hit,
                        scene["objects"],
                        [item["id"] for item in items],
                    )
                    hits += blockers(
                        hit, target, scene["objects"], [item["id"] for item in items]
                    )
                status = (
                    "candidate"
                    if hit is not None and not hits
                    else ("occluded" if hit is not None else "not_observed")
                )
                results.append(
                    finding(
                        "FS-REFLECTION",
                        "经镜面形成的门到床反射路径",
                        status,
                        with_blockers(scene, items, hits),
                        {
                            "observerPoint": door["reviewPoint"],
                            "targetPoint": target,
                            "targetBasis": basis,
                            "reflectionPoint": hit,
                            "blockers": hits,
                        },
                        missing=["实际眼位、开合状态和未建模遮挡"]
                        if status == "candidate"
                        else [],
                        interpretation="按照平面镜反射几何，核查给定门口眼位是否可能经镜面看到床位。",
                        action="在对应门口眼位现场复核。遮挡检查采用已标注几何盒。",
                    )
                )
    return results or [
        finding(
            "FS-REFLECTION",
            "经镜面形成的门到床反射路径",
            "unknown",
            missing=["门口眼位、镜面平面和同室床位"],
        )
    ]


def backing_review(scene):
    results = []
    maximum = scene.get("settings", {}).get("backingSearchDistanceM", 3.0)
    walls = [
        item
        for item in scene["objects"]
        if item["type"] in {"wall", "partition"} and item.get("box")
    ]
    for item in scene["objects"]:
        if item["type"] not in {"bed", "desk", "sofa"}:
            continue
        note = stay_target_note(item, scene)
        if note:
            results.append(
                finding(
                    "FS-BACKING",
                    "床头与座位背靠",
                    "unknown",
                    [item],
                    missing=[note],
                )
            )
            continue
        if item.get("headPoint") is None or item.get("backDirection") is None:
            results.append(
                finding(
                    "FS-BACKING",
                    "床头与座位背靠",
                    "unknown",
                    [item],
                    missing=["真实头部或靠背位置、朝后方向与墙体标注"],
                )
            )
            continue
        hits = []
        for wall in walls:
            if not same_room(item, wall):
                continue
            hit = ray_box(
                item["headPoint"], unit(item["backDirection"]), wall["box"], maximum
            )
            if hit is not None:
                hits.append((hit, wall))
        nearest = min(hits, key=lambda pair: (pair[0], pair[1]["id"])) if hits else None
        results.append(
            finding(
                "FS-BACKING",
                "床头与座位背靠",
                "observed" if nearest else "limited",
                [item, nearest[1]] if nearest else [item],
                {
                    "distanceToAnnotatedWallM": round(nearest[0], 6)
                    if nearest
                    else None,
                    "searchLimitM": maximum,
                },
                missing=[] if nearest else ["搜索范围内的墙体几何与覆盖完整性"],
                interpretation="把传统背后有靠的关注点落实为指定靠背方向上的墙体距离与高度核查。",
                action="核对真实床头、座椅靠背与墙体，优先兼顾使用舒适、门扇开启和通行。",
            )
        )
    return results or [
        finding("FS-BACKING", "床头与座位背靠", "unknown", missing=["床、桌或沙发标注"])
    ]


def ventilation_review(scene):
    results = []
    for room in scene["rooms"]:
        height = room.get("ceilingHeightM")
        if height is None:
            results.append(
                finding(
                    "ENV-VOLUME",
                    "层高、体积与换气条件",
                    "unknown",
                    [room],
                    missing=["净层高"],
                    source="air",
                )
            )
            continue
        volume = room["areaM2"] * height
        if not math.isfinite(volume) or volume <= 0:
            raise ValueError("房间体积超出可计算范围")
        metrics = {
            "areaM2": room["areaM2"],
            "ceilingHeightM": height,
            "volumeM3": round(volume, 6),
            "volumeModel": "floor-area-times-uniform-clear-height",
            "ach": None,
        }
        supply = room.get("ventilation", {})
        missing = ["实际通风量、开合状态、风与温差条件"]
        if supply.get("flowM3h") is not None:
            ach = supply["flowM3h"] / volume
            if not math.isfinite(ach):
                raise ValueError("换气次数超出可计算范围")
            metrics.update(
                {
                    "flowM3h": supply["flowM3h"],
                    "ach": round(ach, 6),
                    "flowBasis": supply["basis"],
                    "flowEvidenceRef": supply["evidenceRef"],
                }
            )
            missing = ["风量代表性、有效室外风量与混合条件复核"]
        results.append(
            finding(
                "ENV-VOLUME",
                "层高、体积与换气条件",
                "observed" if supply.get("basis") == "measured" else "limited",
                [room],
                metrics,
                missing,
                action="比较同一风量条件下的 Q/V。变层高、斜顶或大体积家具需补体积模型。采样点风速与设备铭牌风量须先确认其代表性。",
                source="air",
            )
        )
        openings = [
            item
            for item in scene["objects"]
            if item["type"] in {"door", "window"}
            and room["id"] in item.get("roomIds", [])
        ]
        active = [
            item
            for item in openings
            if item.get("exterior") is True
            and item.get("surface")
            and (item.get("openFraction") or 0) > 0
        ]
        unknown = [
            item["id"]
            for item in openings
            if "exterior" not in item
            or item.get("openFraction") is None
            or not item.get("surface")
        ]
        pairs = []
        for i, a in enumerate(active):
            for b in active[i + 1 :]:
                normals_confirmed = all(
                    item["surface"].get("normalBasis", "outward") == "outward"
                    for item in [a, b]
                )
                opposite = (
                    dot(unit(a["surface"]["normal"]), unit(b["surface"]["normal"]))
                    if normals_confirmed
                    else None
                )
                hits = blockers(
                    a["surface"]["center"],
                    b["surface"]["center"],
                    scene["objects"],
                    [a["id"], b["id"]],
                )
                pairs.append(
                    {
                        "openingIds": [a["id"], b["id"]],
                        "normalDot": round(opposite, 6)
                        if opposite is not None
                        else None,
                        "opposedNormalCandidate": opposite <= -0.5
                        if opposite is not None
                        else None,
                        "centerHeightSeparationM": round(
                            abs(a["surface"]["center"][1] - b["surface"]["center"][1]),
                            6,
                        ),
                        "centerSegmentBlockers": hits,
                    }
                )
        results.append(
            finding(
                "ENV-OPENINGS",
                "外部开口与通风路径线索",
                "limited",
                [room] + active,
                {
                    "knownOpenGeometricAreaM2": round(
                        sum(
                            item["surface"]["widthM"]
                            * item["surface"]["heightM"]
                            * item["openFraction"]
                            for item in active
                        ),
                        6,
                    ),
                    "activeExteriorOpeningIds": [item["id"] for item in active],
                    "unknownOpeningIds": unknown,
                    "openingPairs": pairs,
                    "actualFlowM3h": None,
                },
                missing=["实际开口有效面积、风压/温差、室内门状态与流动阻力"],
                interpretation="传统藏风聚气、穿堂风可作为布局讨论主题，开口线段和层高用于描述实测或标注几何。",
                action="对向开口阈值 normalDot ≤ -0.5 是几何筛查约定。结合天气、开窗状态、现场测量或经验证的流动模型确认真实通风。",
                source="air",
            )
        )
    return results or [
        finding(
            "ENV-VOLUME",
            "层高、体积与换气条件",
            "unknown",
            missing=["房间与净层高"],
            source="air",
        )
    ]


def xuan_kong_context(scene):
    """玄空状态：已有排盘结果、可算下卦、缺输入或需外部替卦。"""
    import _common as C
    from datetime import date

    compass = scene.get("compass", {})
    xuan = scene.get("xuanKong") or {}
    validate_xuan_kong(xuan)
    if xuan.get("chart") is not None:
        return {
            "status": "computed",
            "chartSource": xuan.get("chartSource", "unknown"),
            "chart": xuan["chart"],
        }
    facing = compass.get("facingDegrees")
    has_sitting = facing is not None and compass.get("northBasis") in {
        "magnetic",
        "true",
        "grid",
    }
    has_yun = xuan.get("yun") is not None
    has_year = xuan.get("year") is not None
    if has_sitting and (has_yun or has_year):
        try:
            yun = (
                xuan["yun"]
                if has_yun
                else C.sanyuan_yun(date(int(xuan["year"]), 7, 1))["yun"]
            )
            sit = C.mountain_of_bearing((facing + 180) % 360)
            if abs(sit["offset_deg"]) > C.JIANXIANG_THRESHOLD_DEG:
                return {
                    "status": "needs_external",
                    "required": ["坐山入兼向，下卦不适用，需外部可信替卦结果"],
                }
            return {
                "status": "computed",
                "chartSource": "xuankong.py",
                "yun": yun,
                "sitMountain": sit["mountain"],
                "chart": C.flying_stars(yun, sit["mountain"]),
            }
        except (ValueError, KeyError, TypeError):
            pass
    return {
        "status": "needs_input",
        "required": [
            "建成/大修年份（或运数）与可靠坐向；兼向替卦、年盘、月盘需外部可信结果"
        ],
        "helperScope": "xuankong.py 提供下卦排盘，兼向替卦、年盘、月盘未实现",
    }


def school_context(scene):
    compass = scene.get("compass", {})
    result = {
        "formSchool": {"status": "available", "basis": "本次形势候选与人工复核"},
        "eightMansions": {
            "status": "needs_input",
            "required": ["已确认宅卦、宅命适用口径和可靠方位"],
        },
        "xuanKong": xuan_kong_context(scene),
        "sanHe": {
            "status": "needs_input",
            "required": ["室外地形、来去水、实测方向和流派依据"],
        },
    }
    if compass.get("houseKua") is not None:
        result["eightMansions"] = {
            "status": "context_supplied",
            "houseKua": compass["houseKua"],
            "directions": DIRECTIONS[compass["houseKua"]],
            "required": ["对照实际空间方位、确认宅卦来源和流派口径"],
        }
    facing = compass.get("facingDegrees")
    if facing is not None and compass.get("northBasis") in {"magnetic", "true", "grid"}:
        result["luopan"] = asdict(
            mountain_for_bearing(
                facing, compass.get("uncertaintyDegrees"), compass["northBasis"]
            )
        )
    else:
        result["luopan"] = {
            "status": "needs_input",
            "required": ["房屋坐向度数、参考北及测量误差。当前相对朝向只作布局参考"],
        }
    return result


def evidence_summary(scene):
    """按空间类型汇总风水分析所需的依据，以及物品识别的覆盖情况。"""
    objects = scene["objects"]
    space_type = scene.get("spaceType", "unknown")
    all_types = {"residential", "office", "retail", "factory"}

    def ids(*types):
        return [
            item["id"]
            for item in objects
            if item["type"] in types and (item.get("box") or item.get("surface"))
        ]

    compass = scene.get("compass", {})
    rows = [
        {
            "basis": "物品摆放",
            "spaceTypes": {"residential", "office"},
            "rules": ["FS-BEAM", "FS-DOOR", "FS-MIRROR", "FS-BACKING", "FS-REFLECTION"],
            "needs": "床/桌/沙发的几何盒与审查点",
            "source": "物品识别 + 用户确认身份",
            "question": "床、桌、沙发等主要家具分别放在哪个房间、靠哪个位置？",
            "provided": ids("bed", "desk", "sofa"),
        },
        {
            "basis": "门洞朝向",
            "spaceTypes": all_types,
            "rules": ["FS-DOOR", "ENV-OPENINGS"],
            "needs": "门开口平面（位置/法向/宽高）与对外、开合状态",
            "source": "门识别 + 人工标注",
            "question": "哪一扇是入户门？入户门朝向（开向）哪个方向？室内其他门分别通向哪里？",
            "provided": ids("door"),
        },
        {
            "basis": "镜面",
            "spaceTypes": {"residential", "office"},
            "rules": ["FS-MIRROR", "FS-REFLECTION"],
            "needs": "镜面有限平面与反射面法向",
            "source": "物品识别 + 人工标注",
            "question": "房间里有镜子吗？镜子挂在哪面墙、反射面朝向哪？",
            "provided": ids("mirror"),
        },
        {
            "basis": "梁体",
            "spaceTypes": {"residential", "office"},
            "rules": ["FS-BEAM"],
            "needs": "梁体几何盒",
            "source": "物品识别 + 人工标注",
            "question": "房间顶上有横梁吗？横梁大致在哪个位置、压过哪些家具？",
            "provided": ids("beam"),
        },
        {
            "basis": "墙体遮挡",
            "spaceTypes": all_types,
            "rules": ["FS-BACKING", "FS-DOOR", "FS-MIRROR"],
            "needs": "墙/隔断几何盒",
            "source": "墙识别",
            "question": "主要的隔墙或遮挡物在什么位置？",
            "provided": ids("wall", "partition"),
        },
        {
            "basis": "层高",
            "spaceTypes": all_types,
            "rules": ["ENV-VOLUME"],
            "needs": "房间净层高",
            "source": "空间解析",
            "question": "各房间的净层高大约多少米？",
            "provided": [
                room["id"]
                for room in scene["rooms"]
                if room.get("ceilingHeightM") is not None
            ],
        },
        {
            "basis": "开口通风",
            "spaceTypes": all_types,
            "rules": ["ENV-OPENINGS", "ENV-VOLUME"],
            "needs": "门窗对外状态、开合比例与风量来源",
            "source": "门窗识别 + 人工标注 + 实测/模拟",
            "question": "门窗平时开还是关？房间是否有对流通风（如南北通透）？",
            "provided": ids("window", "door"),
        },
        {
            "basis": "坐向",
            "spaceTypes": all_types,
            "rules": ["luopan", "eightMansions", "xuanKong"],
            "needs": "房屋坐向度数、参考北与测量误差",
            "source": "用户确认坐向",
            "question": "这个空间的坐向/朝向是多少度或哪个方位（如坐北朝南）？参考北是磁北还是真北？",
            "provided": ["compass"] if compass.get("facingDegrees") is not None else [],
        },
    ]
    for row in rows:
        if space_type == "unknown":
            row["status"] = "pending"
        elif space_type not in row["spaceTypes"]:
            row["status"] = "not_applicable"
        else:
            row["status"] = "supplied" if row["provided"] else "missing"
        row["spaceTypes"] = sorted(row["spaceTypes"])
    questions = collect_questions(scene)
    for row in rows:
        row["status"] = (
            "missing"
            if any(set(question["rules"]) & set(row["rules"]) for question in questions)
            else row["status"]
        )
    return {
        "spaceType": space_type,
        "basis": rows,
        "questions": questions,
        "note": "依据覆盖由空间智能分析的物品识别与人工确认共同决定；检测到对象不等于身份已确认，缺失项应直接向用户提问补充。",
    }


def analyze(scene):
    validate(scene)
    settings = scene.get("settings", {})
    if not isinstance(settings, dict) or set(settings) - {
        "openingReviewDistanceM",
        "backingSearchDistanceM",
    }:
        raise ValueError(
            "settings 仅支持 openingReviewDistanceM / backingSearchDistanceM"
        )
    for key, value in settings.items():
        number(value, "settings." + key, positive=True)
    # Bound pair work and output size before evaluating the scene.
    if len(scene["objects"]) > 128:
        raise ValueError("单次最多分析 128 个物品，请按房间拆分")
    counts = Counter(item["type"] for item in scene["objects"])
    targets = counts["bed"] + counts["desk"] + counts["sofa"]
    estimated_pairs = counts["beam"] * targets + counts["door"] * targets
    estimated_pairs += counts["mirror"] * (targets + counts["door"])
    estimated_pairs += counts["mirror"] * counts["door"] * counts["bed"]
    if estimated_pairs > 10000:
        raise ValueError("候选关系超过 10000，请使用 --room 按房间分析")
    findings = []
    for rule in [
        beam_review,
        opening_review,
        mirror_review,
        reflected_view_review,
        backing_review,
        ventilation_review,
    ]:
        findings.extend(rule(scene))
    if len(findings) > 10000:
        raise ValueError("关系过多，请按房间拆分")
    return {
        "schema": "spatial-fengshui.analysis",
        "version": 1,
        "ruleset": RULESET,
        "sceneFingerprint": fingerprint(scene),
        "resourceCode": scene["resourceCode"],
        "frame": scene["frame"],
        "geometryModel": "annotated-yaw-OBBs-and-finite-3D-planes",
        "scope": "形势计算、传统流派解释上下文与通风条件核查",
        "spaceType": scene.get("spaceType", "unknown"),
        "roomIds": [room["id"] for room in scene["rooms"]],
        "rooms": [
            {
                "id": room["id"],
                "name": room.get("name"),
                "function": room.get("function", "unknown"),
            }
            for room in scene["rooms"]
        ],
        "sourceAnalysisSha256": scene.get("sourceAnalysisSha256"),
        "assumptions": scene.get("assumptions", []),
        "schools": school_context(scene),
        "evidence": evidence_summary(scene),
        "findings": findings,
        "notAssessed": [
            {
                "objectId": item["id"],
                "type": item["type"],
                "reason": "当前脚本尚未实现该对象的专用传统布局规则，按参考资料另行核对",
            }
            for item in scene["objects"]
            if item["type"] in {"stove", "sink", "toilet", "column", "other"}
        ],
        "summary": {
            status: sum(item["status"] == status for item in findings)
            for status in [
                "candidate",
                "observed",
                "not_observed",
                "occluded",
                "unknown",
                "limited",
            ]
        },
    }


def markdown_text(value):
    value = str(value).replace("\n", " ").replace("\r", " ")
    for character in ["\\", "`", "*", "_", "[", "]", "<", ">", "#", "|"]:
        value = value.replace(character, "\\" + character)
    return value


def markdown(report):
    lines = [
        "# 空间风水与环境核查报告",
        "",
        f"资源 `{report['resourceCode']}` · 规则 `{report['ruleset']}`",
        "",
        "本报告依据提供的几何盒、矩形平面和审查点计算。传统解释须结合相应流派、实际使用方式及现场复核。",
        "",
    ]
    for assumption in report["assumptions"]:
        lines.extend(["输入约定 " + markdown_text(assumption), ""])
    lines += ["## 空间类型", ""]
    space_type = report.get("spaceType", "unknown")
    lines.append(
        f"- {SPACE_TYPE_LABELS.get(space_type, space_type)}"
        + (
            "（请先确认：办公室 / 住宅 / 商场 / 工厂 等）"
            if space_type == "unknown"
            else ""
        )
    )
    if space_type == "unknown":
        lines += [
            "",
            "注意：空间类型未确认，涉及床、桌、沙发的住宅/办公式布局判断暂不套用，先确认空间类型再继续。",
        ]
    lines += ["", "## 空间用途", ""]
    for room in report.get("rooms", []):
        lines.append(
            f"- `{room['id']}` {markdown_text(room.get('name') or '')}："
            f"{FUNCTION_LABELS.get(room.get('function'), '未确认')}"
        )
    if any(
        room.get("function", "unknown") == "unknown" for room in report.get("rooms", [])
    ):
        lines += [
            "",
            "注意：存在用途未确认的房间，涉及床、桌、沙发的布局判断需先确认空间用途与物品身份；"
            "此类结果以「待补输入」呈现，不代表该物品确为床或该空间确为卧室。",
        ]
    questions = report.get("evidence", {}).get("questions", [])
    if questions:
        lines += ["", "## 需补充的依据（请向用户确认）", ""]
        for item in questions:
            lines.append(f"- {item['basis']}：{item['question']}")
        lines += [
            "",
            "以上信息无法从模型直接推导时（如朝向、入户门、层高），直接请用户给出，再把答复作为补充标注回填后重跑。",
        ]
    lines += ["", "## 分析结果", ""]
    statuses = {
        "candidate": "布局核查候选",
        "observed": "在输入模型中算得",
        "not_observed": "本次指定几何关系未出现",
        "occluded": "标注几何产生遮挡",
        "unknown": "待补输入",
        "limited": "有限条件分析",
    }
    for item in report["findings"]:
        lines += [
            f"### {item['ruleId']} · {item['title']}",
            "",
            f"状态为{statuses[item['status']]}，输入可信度为 `{item['confidence']}`。",
            "",
            "对象引用 " + "、".join(f"`{identity}`" for identity in item["objectIds"])
            if item["objectIds"]
            else "对象引用待补。",
            "",
        ]
        if item["measurements"]:
            lines += [
                "```json",
                json.dumps(item["measurements"], ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        if item["traditionalInterpretation"]:
            lines += [item["traditionalInterpretation"], ""]
        if item["missing"]:
            lines += ["待核对 " + "、".join(item["missing"]) + "。", ""]
        if item["reviewAction"]:
            lines += [item["reviewAction"], ""]
        lines += [
            "依据 " + "、".join(markdown_text(ref) for ref in item["evidenceRefs"])
            if item["evidenceRefs"]
            else "证据引用待补。",
            "",
        ]
    lines += [
        "## 流派与输入条件",
        "",
        "```json",
        json.dumps(report["schools"], ensure_ascii=False, indent=2),
        "```",
        "",
    ]
    if report["notAssessed"]:
        lines.extend(["## 待补专用规则的物品", ""])
        for item in report["notAssessed"]:
            lines.extend(
                [
                    f"- `{item['objectId']}`（{item['type']}）需按流派参考与实际几何继续核查。",
                    "",
                ]
            )
    if report.get("inputHashes"):
        lines.extend(
            [
                "## 输入哈希",
                "",
                "```json",
                json.dumps(report["inputHashes"], indent=2),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def write_output(path, content, input_paths):
    destination = Path(path).expanduser().resolve()
    if destination in {
        Path(source).expanduser().resolve() for source in input_paths if source
    }:
        raise ValueError("输出不能覆盖输入原件")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix="." + destination.name + "-", dir=destination.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--scene", help="独立的空间风水场景 JSON")
    inputs.add_argument("--analysis", help="空间理解导出的 spatial-analysis.v2.json")
    parser.add_argument("--annotations", help="与 analysisSha256 绑定的补充标注 JSON")
    parser.add_argument("--room", action="append", help="仅分析指定房间，可重复传入")
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    parser.add_argument("--output", help="独立输出文件，原子写入。省略则输出到终端")
    parser.add_argument(
        "--prepare", action="store_true", help="只转换并导出场景，供补充标注使用"
    )
    args = parser.parse_args(argv)
    try:
        if args.annotations and not args.analysis:
            raise ValueError("--annotations 需要 --analysis")
        if args.prepare and (not args.analysis or args.format != "json"):
            raise ValueError("--prepare 需要 --analysis 且使用 json 格式")
        if args.analysis:
            scene = from_analysis(args.analysis)
            if args.annotations:
                annotations, annotation_sha = load(args.annotations)
                scene = annotate(scene, annotations)
                scene["annotationsSha256"] = annotation_sha
        else:
            scene, scene_sha = load(args.scene)
            scene["sceneSha256"] = scene_sha
        if args.room:
            selected = set(args.room)
            available = {room["id"] for room in scene["rooms"]}
            if selected - available:
                raise ValueError("请求的房间不存在")
            scene["rooms"] = [room for room in scene["rooms"] if room["id"] in selected]
            scene["objects"] = [
                item
                for item in scene["objects"]
                if selected & set(item.get("roomIds", []))
            ]
            for item in scene["objects"]:
                item["roomIds"] = [
                    identity for identity in item["roomIds"] if identity in selected
                ]
            scene.setdefault("assumptions", []).append(
                "本次按指定房间分析，跨房间遮挡与流动关系另行核对。"
            )
        if args.prepare:
            validate(scene)
            result = scene
        else:
            result = analyze(scene)
            result["inputHashes"] = {
                key: scene[key]
                for key in ["sourceAnalysisSha256", "annotationsSha256", "sceneSha256"]
                if key in scene
            }
        content = (
            markdown(result)
            if args.format == "markdown"
            else json.dumps(result, ensure_ascii=False, indent=2)
        ) + "\n"
        if args.output:
            write_output(
                args.output, content, [args.scene, args.analysis, args.annotations]
            )
        else:
            print(content, end="")
        return 0
    except (ValueError, TypeError, KeyError, OSError, RecursionError) as error:
        print(
            json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
