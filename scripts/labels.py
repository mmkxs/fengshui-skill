#!/usr/bin/env python3
"""Generate numbered in-VR labels so the user confirms openings and furniture.

Why: asking users to describe orientations in text is error-prone, and a floor
plan clashes with how they actually inspect a running viewer. Pin short labels at
the detected objects instead and ask by number while they look at the scene.

Output: a JSON array of spatial label items that the dev-only overlay documented
in references/vr-confirmation.md loads via ``?agentLabels=<path>``.

    python scripts/labels.py --scene scene.json --out labels.json
    python scripts/labels.py --scene scene.json --out labels.json \
        --door obj-mirror003 --windows obj-window002,obj-window003 \
        --desks obj-desk003 --types window,door,desk,mirror
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

TYPE_NAMES = {
    "door": "门",
    "window": "窗洞",
    "mirror": "疑似镜面",
    "desk": "疑似桌",
    "beam": "横梁",
    "partition": "隔断",
}
PREFIX = {
    "door": "D",
    "window": "W",
    "mirror": "P",
    "desk": "T",
    "beam": "B",
    "partition": "G",
}
SAFE_INSET_M = 0.25


def inside_polygon(x, z, polygon):
    """Ray casting on the XZ polygon."""
    inside = False
    count = len(polygon)
    for index in range(count):
        x1, z1 = polygon[index]
        x2, z2 = polygon[(index + 1) % count]
        if (z1 > z) != (z2 > z):
            cross = (x2 - x1) * (z - z1) / (z2 - z1) + x1
            if x < cross:
                inside = not inside
    return inside


def centroid(polygon):
    xs = [point[0] for point in polygon]
    zs = [point[1] for point in polygon]
    return sum(xs) / len(xs), sum(zs) / len(zs)


def clamp_into_room(point, polygon):
    """A label pinned outside the room (or inside a wall) is never rendered."""
    x, y, z = point
    if not polygon or inside_polygon(x, z, polygon):
        return [round(x, 3), round(y, 3), round(z, 3)]
    cx, cz = centroid(polygon)
    for step in range(1, 13):
        ratio = step / 12
        nx, nz = x + (cx - x) * ratio, z + (cz - z) * ratio
        if inside_polygon(nx, nz, polygon):
            return [round(nx, 3), round(y, 3), round(nz, 3)]
    return [round(cx, 3), round(y, 3), round(cz, 3)]


def tag_style(title):
    return {
        "id": None,
        "contentType": "Text",
        "stickType": "2DPoint",
        "position": None,
        "data": {"title": title},
        "config": {
            "visibleConfig": {
                "keep": "visible",
                # Without `all` the preset hides labels outside Panorama mode.
                "visibleFiveMode": "all",
                "entryFromModel": True,
            },
            "unfoldedConfig": {"keep": "unfolded"},
            "initialState": {"visible": True, "unfolded": True},
        },
        "fiveState": {"mode": "Panorama"},
    }


def split_ids(value):
    if not value:
        return set()
    return {item.strip() for item in value.split(",") if item.strip()}


def generate(
    scene,
    door_ids=None,
    window_ids=None,
    desk_ids=None,
    extra_types=None,
    room=None,
):
    rooms = {item["id"]: item for item in scene.get("rooms", [])}
    polygon = None
    if room and room in rooms:
        polygon = rooms[room].get("polygonXZ")
    elif len(rooms) == 1:
        polygon = next(iter(rooms.values())).get("polygonXZ")

    wanted = {}
    if door_ids:
        wanted.update({item: "door" for item in door_ids})
    if window_ids:
        wanted.update({item: "window" for item in window_ids})
    if desk_ids:
        wanted.update({item: "desk" for item in desk_ids})

    ordered = []
    counts = {}
    for item in scene.get("objects", []):
        kind = wanted.get(item["id"]) or (
            item.get("type") if item.get("type") in (extra_types or set()) else None
        )
        if not kind:
            continue
        position = None
        if item.get("box"):
            position = item["box"].get("center")
        elif item.get("surface"):
            position = item["surface"].get("center")
        elif item.get("reviewPoint"):
            position = item["reviewPoint"]
        if not position:
            continue
        counts[kind] = counts.get(kind, 0) + 1
        prefix = PREFIX.get(kind, kind[:1].upper())
        label = f"{prefix}{counts[kind]}"
        title = f"{label} {TYPE_NAMES.get(kind, kind)}"
        entry = tag_style(title)
        entry["id"] = label
        entry["position"] = clamp_into_room(position, polygon)
        entry["sceneObjectId"] = item["id"]
        ordered.append(entry)
    return ordered


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--door", help="逗号分隔的物品 ID")
    parser.add_argument("--windows")
    parser.add_argument("--desks")
    parser.add_argument("--types", help="额外整类型标注，如 beam,partition")
    parser.add_argument("--room")
    args = parser.parse_args(argv)

    scene = json.loads(Path(args.scene).read_text())
    labels = generate(
        scene,
        split_ids(args.door),
        split_ids(args.windows),
        split_ids(args.desks),
        split_ids(args.types),
        args.room,
    )
    if not labels:
        raise SystemExit("没有可标注的对象，请检查 --door/--windows/--desks/--types")
    Path(args.out).write_text(json.dumps(labels, ensure_ascii=False, indent=1) + "\n")
    print(
        json.dumps(
            {
                "ok": True,
                "count": len(labels),
                "out": str(Path(args.out).resolve()),
                "labels": [
                    {"id": item["id"], "title": item["data"]["title"], "object": item["sceneObjectId"]}
                    for item in labels
                ],
                "next": "此命令只导出锚点候选；确认请用 viewer_confirm.py 委托空间 skill 的统一临时确认入口。",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
