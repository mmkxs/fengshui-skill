"""Select reader-relevant geometry and project it with a captured Five camera."""

import math

from contracts import normalize_camera
from geometry import add, cross, scale, unit, world

KEY_TYPES = {"bed", "desk", "sofa", "door", "window", "mirror", "beam"}


def note_rooms(scene, note):
    rooms = {room["id"] for room in scene["rooms"]}
    explicit = rooms.intersection(note["objectIds"])
    if explicit:
        return explicit
    groups = [
        set(obj.get("roomIds", []))
        for obj in scene["objects"]
        if obj["id"] in note["objectIds"] and obj.get("roomIds")
    ]
    if not groups:
        return set()
    return set.intersection(*groups) or set.union(*groups)


def focus_objects(scene, notes, explicit=(), findings=()):
    known = {obj["id"]: obj for obj in scene["objects"]}
    selected = set(explicit)
    active_rooms = set()
    for note in notes:
        selected.update(oid for oid in note["objectIds"] if oid in known)
        active_rooms.update(note_rooms(scene, note))
        for finding in findings:
            if finding["ruleId"] == note["ruleId"] and set(finding["objectIds"]) == set(
                note["objectIds"]
            ):
                selected.update(
                    hit["objectId"]
                    for hit in finding.get("measurements", {}).get("blockers", [])
                )
    # Beds, openings and similar recognisable context are useful; unidentified
    # detector boxes and unrelated storage furniture are not a report inventory.
    selected.update(
        obj["id"]
        for obj in scene["objects"]
        if obj["type"] in KEY_TYPES
        and active_rooms.intersection(obj.get("roomIds", []))
    )
    return {oid for oid in selected if oid in known}


def object_corners(item):
    points = []
    if item.get("box"):
        box = item["box"]
        points += [
            world(
                box,
                [
                    x * box["size"][0] / 2,
                    y * box["size"][1] / 2,
                    z * box["size"][2] / 2,
                ],
            )
            for x in [-1, 1]
            for y in [-1, 1]
            for z in [-1, 1]
        ]
    if item.get("surface"):
        surface = item["surface"]
        normal = unit(surface["normal"])
        u = unit(cross(surface["up"], normal))
        v = cross(normal, u)
        points += [
            add(
                surface["center"],
                add(
                    scale(u, x * surface["widthM"] / 2),
                    scale(v, y * surface["heightM"] / 2),
                ),
            )
            for x, y in [(-1, -1), (1, -1), (1, 1), (-1, 1)]
        ]
    return points


def validate_camera(camera):
    camera = normalize_camera(camera)
    if (
        not isinstance(camera, dict)
        or camera.get("schema") != "spatial-fengshui.camera-projection"
        or camera.get("version") != 1
    ):
        raise ValueError("模型态截图缺少真实相机投影记录，请用新版桥接重新截图")
    for name in ["projectionMatrix", "viewMatrix"]:
        matrix = camera.get(name)
        if (
            not isinstance(matrix, list)
            or len(matrix) != 16
            or any(type(v) not in {int, float} or not math.isfinite(v) for v in matrix)
            or not any(matrix)
        ):
            raise ValueError("相机矩阵无效")
    return camera


def camera_projector(camera, width, height):
    validate_camera(camera)

    def multiply(matrix, point):
        return [
            sum(matrix[column * 4 + row] * point[column] for column in range(4))
            for row in range(4)
        ]

    def clip(point):
        return multiply(
            camera["projectionMatrix"], multiply(camera["viewMatrix"], [*point, 1])
        )

    def pixel(point):
        return (
            (point[0] / point[3] + 1) * width / 2,
            (1 - point[1] / point[3]) * height / 2,
        )

    def polygon(points):
        values = [clip(point) for point in points]
        # Clip in homogeneous space, including the near plane, before division.
        for axis, sign in [(0, 1), (0, -1), (1, 1), (1, -1), (2, 1), (2, -1)]:
            out = []
            for a, b in zip(values, values[1:] + values[:1]):
                da = a[3] + sign * a[axis]
                db = b[3] + sign * b[axis]
                if da >= 0:
                    out.append(a)
                if (da >= 0) != (db >= 0):
                    t = da / (da - db)
                    out.append([a[i] + t * (b[i] - a[i]) for i in range(4)])
            values = out
            if not values:
                return []
        return [pixel(point) for point in values if point[3] > 1e-9]

    def point(position):
        value = clip(position)
        if value[3] <= 1e-9 or any(abs(value[i]) > value[3] for i in range(3)):
            return None
        return pixel(value)

    return polygon, point


def matching_model_image(images, room, identities):
    choices = [
        image
        for image in images
        if image.get("camera")
        and image["context"].get("mode") == "Mapview"
        and (room is None or room["id"] in image.get("roomIds", []))
    ]
    return max(
        choices,
        key=lambda image: len(set(image.get("objectIds", [])) & set(identities)),
        default=None,
    )


def paired_crop(scene, room, identities, image):
    _, project = camera_projector(image["camera"], image["width"], image["height"])
    points = [
        p
        for obj in scene["objects"]
        if obj["id"] in identities
        for p in object_corners(obj)
    ]
    for current in scene["rooms"]:
        if room and current["id"] != room["id"]:
            continue
        for y in [
            current.get("floorY") or 0,
            (current.get("floorY") or 0) + (current.get("ceilingHeightM") or 0),
        ]:
            points.extend([x, y, z] for x, z in current.get("polygonXZ", []))
    pixels = [pixel for point in points if (pixel := project(point)) is not None]
    if not pixels:
        return (0, 0, image["width"], image["height"])
    xs, ys = zip(*pixels)
    pad = max(20, (max(xs) - min(xs)) * 0.08, (max(ys) - min(ys)) * 0.08)
    return (
        max(0, math.floor(min(xs) - pad)),
        max(0, math.floor(min(ys) - pad)),
        min(image["width"], math.ceil(max(xs) + pad)),
        min(image["height"], math.ceil(max(ys) + pad)),
    )
