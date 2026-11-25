"""Collect user questions before authoring a reader-facing report."""

from collections import Counter

TYPE_NAMES = {
    "bed": "床",
    "desk": "书桌",
    "sofa": "沙发",
    "door": "门",
    "window": "窗",
    "mirror": "镜子",
    "beam": "横梁",
    "wall": "墙体",
    "partition": "隔断",
    "column": "柱",
    "cabinet": "柜子",
    "stove": "灶台",
    "sink": "水槽",
    "toilet": "坐便器",
    "other": "物品",
}
RULE_NAMES = {
    "FS-BEAM": "横梁与家具布局",
    "FS-DOOR": "门与家具布局",
    "FS-MIRROR": "镜面与家具布局",
    "FS-REFLECTION": "入口经镜面看向床位",
    "FS-BACKING": "床头与座椅背靠",
    "ENV-VOLUME": "层高与换气",
    "ENV-OPENINGS": "门窗与通风路径",
}
LAYOUT_RULES = ["FS-BEAM", "FS-DOOR", "FS-MIRROR", "FS-REFLECTION", "FS-BACKING"]


GENERIC_ROOM_PREFIXES = ("区域", "Region", "Area", "房间", "Room")
ROOM_FUNCTION_NAMES = {
    "office": "办公室",
    "bedroom": "卧室",
    "living": "起居区",
    "kitchen": "厨房",
    "bath": "卫生间",
    "corridor": "走廊",
}
SPACE_TYPE_NAMES = {
    "office": "办公室",
    "residential": "居室",
    "retail": "商铺",
    "factory": "厂房",
}


def room_label(scene, room, index):
    """Prefer a real room name; replace generic detector labels with the confirmed use."""
    name = (room.get("name") or "").strip()
    if name and not name.startswith(GENERIC_ROOM_PREFIXES):
        return name
    function = room.get("function")
    if function in ROOM_FUNCTION_NAMES:
        return ROOM_FUNCTION_NAMES[function]
    if len(scene["rooms"]) == 1:
        space_type = scene.get("spaceType")
        if space_type in SPACE_TYPE_NAMES:
            return SPACE_TYPE_NAMES[space_type]
    return f"房间{index + 1}"


def display_names(scene):
    names = {
        room["id"]: room_label(scene, room, i)
        for i, room in enumerate(scene["rooms"])
    }
    counts = Counter()
    for item in scene["objects"]:
        room = next(iter(item.get("roomIds", [])), None)
        counts[(room, item["type"])] += 1
        prefix = names.get(room, "空间")
        names[item["id"]] = (
            item.get("name")
            or f"{prefix}的{TYPE_NAMES[item['type']]}{counts[(room, item['type'])]}"
        )
    return names


def excluded_rules(scene):
    return {
        entry["ruleId"]
        for entry in scene.get("reportScope", {}).get("excludedRules", [])
    }


def infer_space_type(scene):
    """从检测到的物品推断整个空间的候选类型，供提问时先给结论再确认。"""
    kinds = Counter(item["type"] for item in scene["objects"])
    if kinds["bed"]:
        return "住宅"
    if kinds["stove"] or kinds["sink"]:
        return "住宅"
    if kinds["desk"]:
        return "办公"
    return None


def infer_room_function(scene, room_id):
    """从房间内的物品推断候选用途，供提问时先给结论再确认。"""
    kinds = Counter(
        item["type"] for item in scene["objects"] if room_id in item.get("roomIds", [])
    )
    if kinds["bed"]:
        return "卧室"
    if kinds["stove"]:
        return "厨房"
    if kinds["toilet"]:
        return "卫生间"
    if kinds["sofa"]:
        return "客厅"
    if kinds["desk"]:
        return "书房或办公"
    return None


def xuan_kong_missing(scene):
    """玄空还缺什么：None 表示可算或已有排盘，无需提问；year / chart 表示缺失项。"""
    import _common as C
    from scene import validate_xuan_kong

    xuan = scene.get("xuanKong") or {}
    validate_xuan_kong(xuan)
    if xuan.get("chart") is not None:
        return None
    if xuan.get("year") is None and xuan.get("yun") is None:
        return "year"
    compass = scene.get("compass", {})
    if compass.get("facingDegrees") is None or compass.get("northBasis") not in {
        "magnetic",
        "true",
        "grid",
    }:
        return None  # 坐向缺失，由坐向问题覆盖
    sit = C.mountain_of_bearing((compass["facingDegrees"] + 180) % 360)
    if abs(sit["offset_deg"]) > C.JIANXIANG_THRESHOLD_DEG:
        return "chart"
    return None


def collect_questions(scene, report=None):
    """Questions are working records, never content for the delivered report.

    Geometry that can be recovered from the source must be recovered first. The
    agent asks these questions only after inspecting the available VR evidence.
    """
    names = display_names(scene)
    excluded = excluded_rules(scene)
    questions = []

    def ask(key, basis, question, rules, identities=()):
        active = [rule for rule in rules if rule not in excluded]
        if active and not any(row["id"] == key for row in questions):
            questions.append(
                {
                    "id": key,
                    "basis": basis,
                    "question": question,
                    "rules": active,
                    "objectIds": list(identities),
                }
            )

    if scene.get("spaceType", "unknown") == "unknown":
        candidate = infer_space_type(scene)
        ask(
            "space-type",
            "空间类型",
            (
                f"看这个空间的布置，这里应该是{candidate}吧？如果不是，实际是住宅、办公、商业还是工厂？"
                if candidate
                else "这个空间是做什么用的？住宅、办公、商业还是工厂？"
            ),
            list(RULE_NAMES),
        )
    for room in scene["rooms"]:
        rid = room["id"]
        if room.get("function", "unknown") == "unknown":
            candidate = infer_room_function(scene, rid)
            ask(
                "function:" + rid,
                "房间用途",
                (
                    f"{names[rid]}看起来是{candidate}，对吗？"
                    if candidate
                    else f"{names[rid]}是做什么用的？"
                ),
                LAYOUT_RULES,
                [rid],
            )
        if room.get("ceilingHeightM") is None:
            ask(
                "height:" + rid,
                "层高",
                f"{names[rid]}的层高大概多少？普通住宅一般 2.6 到 2.8 米。",
                ["ENV-VOLUME"],
                [rid],
            )
        scope = scene.get("reportScope", {})
        if not scope.get("airflowMode"):
            ask(
                "airflow-mode",
                "通风分析范围",
                "有实测或模拟的通风数据吗？没有的话，我就按门窗布局和通风路径来分析，可以吗？",
                ["ENV-VOLUME", "ENV-OPENINGS"],
            )
        if scope.get("airflowMode") in {"measured", "simulated"} and not room.get(
            "ventilation", {}
        ).get("flowM3h"):
            ask(
                "flow:" + rid,
                "通风量",
                f"麻烦提供一下{names[rid]}的通风量（实测或模拟），以及平时开窗的情况。",
                ["ENV-VOLUME"],
                [rid],
            )
    for item in scene["objects"]:
        oid, kind = item["id"], item["type"]
        label = names[oid]
        type_name = TYPE_NAMES.get(kind, "物品")
        if kind in {"bed", "desk", "sofa"}:
            if item.get("identityConfirmed") is not True:
                ask(
                    "identity:" + oid,
                    "物品身份",
                    f"图里这个识别出来是{type_name}，对吗？它平时怎么用、放在哪？",
                    LAYOUT_RULES,
                    [oid],
                )
            if item.get("reviewPoint") is None:
                ask(
                    "review-point:" + oid,
                    "实际使用位置",
                    f"你平时在{label}上坐或躺的时候，人大概在哪个位置、多高？",
                    ["FS-DOOR", "FS-MIRROR", "FS-REFLECTION"],
                    [oid],
                )
            if not item.get("headPoint") or not item.get("backDirection"):
                ask(
                    "backing:" + oid,
                    "背靠方向",
                    f"{label}的床头（或靠背）是靠哪面墙的？",
                    ["FS-BACKING"],
                    [oid],
                )
        if kind == "mirror" and (
            not item.get("surface")
            or item["surface"].get("normalBasis") in {"unknown", "two-sided"}
        ):
            ask(
                "mirror:" + oid,
                "镜面",
                "图里这块镜子，镜面朝哪边、大概多大范围？",
                ["FS-MIRROR", "FS-REFLECTION"],
                [oid],
            )
        if kind in {"door", "window"}:
            if "exterior" not in item or item.get("openFraction") is None:
                ask(
                    "opening:" + oid,
                    "门窗状态",
                    f"{label}是通户外的吗？平时开着还是关着？",
                    ["ENV-OPENINGS"],
                    [oid],
                )
            if not item.get("surface"):
                ask(
                    "surface:" + oid,
                    "门窗平面",
                    f"请在截图中指出{label}的实际开口位置和范围。",
                    ["ENV-OPENINGS"] + (["FS-DOOR"] if kind == "door" else []),
                    [oid],
                )
            elif item.get("exterior") is True and item["surface"].get(
                "normalBasis"
            ) in {"two-sided", "unknown"}:
                ask(
                    "surface:" + oid,
                    "门洞朝向",
                    f"{label}朝哪边开？哪一侧是通室外的？",
                    ["ENV-OPENINGS"],
                    [oid],
                )
    compass = scene.get("compass", {})
    schools = scene.get("reportScope", {}).get("schools", ["form", "luopan"])
    if any(school in schools for school in ["luopan", "eightMansions", "xuanKong"]):
        if (
            compass.get("facingDegrees") is None
            or compass.get("northBasis") not in {"magnetic", "true", "grid"}
            or compass.get("uncertaintyDegrees") is None
        ):
            ask(
                "compass",
                "坐向",
                "房子整体朝哪个方向？比如坐北朝南。参考磁北还是真北？入户门又朝哪边？",
                ["luopan", "eightMansions", "xuanKong"],
            )
    if "eightMansions" in schools and compass.get("houseKua") is None:
        ask("house-kua", "八宅", "八宅按宅卦看，还是按你的命卦看？", ["eightMansions"])
    if "xuanKong" in schools:
        missing = xuan_kong_missing(scene)
        if missing == "year":
            ask(
                "xuan-kong-year",
                "玄空",
                "玄空排盘需要建成或大修的年份，或直接说几运。你这边是？",
                ["xuanKong"],
            )
        elif missing == "chart":
            ask(
                "xuan-kong-chart",
                "玄空",
                "坐山偏得比较多（兼向），下卦排盘不适用；请提供可信的替卦宅盘。",
                ["xuanKong"],
            )
    if report:
        if scene.get("occlusionCoverage") != "reviewed" and any(
            f["status"] == "candidate"
            and f["ruleId"] in {"FS-DOOR", "FS-MIRROR", "FS-REFLECTION"}
            and f["ruleId"] not in excluded
            for f in report["findings"]
        ):
            ask(
                "occlusion",
                "现场遮挡",
                "从截图看，门、镜子和床（或座位）之间，有没有屏风、柜子之类的挡着？",
                ["FS-DOOR", "FS-MIRROR", "FS-REFLECTION"],
            )
        for finding in report["findings"]:
            rule = finding["ruleId"]
            if finding["status"] != "unknown" or rule in excluded:
                continue
            if any(rule in row["rules"] for row in questions):
                continue
            labels = "、".join(names.get(oid, "本空间") for oid in finding["objectIds"])
            ask(
                "rule:" + rule,
                RULE_NAMES.get(rule, "空间布局"),
                f"关于{labels or '本空间'}，还需要你补充：{'、'.join(finding['missing'])}。如果现场确实没有这个，就跳过这项，可以吗？",
                [rule],
                finding["objectIds"],
            )
    return questions


def readiness(scene, report):
    questions = collect_questions(scene, report)
    return {"ready": not questions, "questions": questions}
