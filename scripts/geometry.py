"""Deterministic geometry in metres, local Y-up coordinates.

Yaw transforms follow the standard local Y-up convention.
"""

from __future__ import annotations

import math

EPSILON = 1e-8


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def sub(a, b):
    return [x - y for x, y in zip(a, b)]


def add(a, b):
    return [x + y for x, y in zip(a, b)]


def scale(a, k):
    return [x * k for x in a]


def unit(a):
    length = math.sqrt(dot(a, a))
    if length < EPSILON:
        raise ValueError("方向向量长度必须大于零")
    return scale(a, 1 / length)


def cross(a, b):
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def world(box, point):
    c, s = math.cos(box["yawRad"]), math.sin(box["yawRad"])
    return add(
        box["center"],
        [c * point[0] + s * point[2], point[1], -s * point[0] + c * point[2]],
    )


def local(box, point):
    p = sub(point, box["center"])
    c, s = math.cos(box["yawRad"]), math.sin(box["yawRad"])
    return [c * p[0] - s * p[2], p[1], s * p[0] + c * p[2]]


def footprint(box):
    points = []
    for x, z in [(-1, -1), (1, -1), (1, 1), (-1, 1)]:
        corner = [x * box["size"][0] / 2, 0, z * box["size"][2] / 2]
        position = world(box, corner)
        points.append([position[0], position[2]])
    return points


def polygons_overlap(a, b):
    for polygon in (a, b):
        for i, p in enumerate(polygon):
            q = polygon[(i + 1) % len(polygon)]
            axis = [-(q[1] - p[1]), q[0] - p[0]]
            left = [dot(v, axis) for v in a]
            right = [dot(v, axis) for v in b]
            if max(left) <= min(right) + EPSILON or max(right) <= min(left) + EPSILON:
                return False
    return True


def ray_box(origin, direction, box, maximum):
    start = local(box, origin)
    end = local(box, add(origin, direction))
    delta = sub(end, start)
    near, far = 0.0, maximum
    for axis in range(3):
        half = box["size"][axis] / 2
        if abs(delta[axis]) < EPSILON:
            if abs(start[axis]) > half:
                return None
            continue
        a = (-half - start[axis]) / delta[axis]
        b = (half - start[axis]) / delta[axis]
        near, far = max(near, min(a, b)), min(far, max(a, b))
        if near > far:
            return None
    return near


def blockers(start, end, objects, exclude=()):
    distance = math.dist(start, end)
    if distance < EPSILON:
        return []
    direction = scale(sub(end, start), 1 / distance)
    hits = []
    for item in objects:
        if (
            item["id"] in exclude
            or item.get("occludes") is not True
            or item.get("box") is None
        ):
            continue
        hit = ray_box(start, direction, item["box"], distance)
        if hit is not None and hit < distance - EPSILON:
            hits.append({"objectId": item["id"], "distanceM": round(hit, 6)})
    return sorted(hits, key=lambda item: (item["distanceM"], item["objectId"]))


def surface_coordinates(surface, point):
    normal = unit(surface["normal"])
    horizontal = unit(cross(surface["up"], normal))
    vertical = cross(normal, horizontal)
    offset = sub(point, surface["center"])
    depth = dot(offset, normal)
    hit = sub(point, scale(normal, depth))
    return hit, dot(offset, horizontal), dot(offset, vertical), depth


def within_surface(surface, point):
    hit, horizontal, vertical, depth = surface_coordinates(surface, point)
    inside = (
        abs(horizontal) <= surface["widthM"] / 2 + EPSILON
        and abs(vertical) <= surface["heightM"] / 2 + EPSILON
    )
    return inside, hit, depth


def reflection_point(surface, eye, target):
    """Specular point between two points on the reflective side of a rectangle."""
    normal = unit(surface["normal"])
    eye_depth = dot(sub(eye, surface["center"]), normal)
    target_depth = dot(sub(target, surface["center"]), normal)
    if eye_depth <= EPSILON or target_depth <= EPSILON:
        return None
    virtual_eye = sub(eye, scale(normal, 2 * eye_depth))
    direction = sub(target, virtual_eye)
    denominator = dot(direction, normal)
    if abs(denominator) < EPSILON:
        return None
    fraction = dot(sub(surface["center"], virtual_eye), normal) / denominator
    if not 0 <= fraction <= 1:
        return None
    hit = add(virtual_eye, scale(direction, fraction))
    return hit if within_surface(surface, hit)[0] else None
