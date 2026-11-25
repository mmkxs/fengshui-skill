#!/usr/bin/env python3
"""Import browser captures with active-Work, analysis and authorization bindings."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import math
from pathlib import Path
import sys

from contracts import normalize_capture
from scene import load
from visuals import validate_camera, camera_projector
from workflow import atomic_json, checked_session, optional_download_lock, read_context


def import_capture(
    session_path, context, capture_path, room_ids=(), kind="vr-screenshot"
):
    from PIL import Image, ImageDraw, ImageFont

    state = checked_session(session_path, context)
    if not state.get("analysisSha256"):
        raise ValueError("截图前需要完成并绑定本次空间解析")
    capture, _ = load(capture_path, max_bytes=40 * 1024 * 1024)
    if (
        isinstance(capture, dict)
        and capture.get("success") is True
        and isinstance(capture.get("data"), dict)
    ):
        capture = capture["data"].get("result")
    if not isinstance(capture, dict):
        raise ValueError("截图数据必须是对象")
    capture = normalize_capture(capture)
    if capture.get("schema") != "spatial-fengshui.vr-capture" or capture.get("version") != 1:
        raise ValueError("截图数据格式无效")
    captured = capture.get("context", {})
    for key in ["resourceCode", "generation", "pageUrl"]:
        if captured.get(key) != context.get(key):
            raise ValueError("截图属于其他 VR 或页面会话")
    if (
        capture.get("requestSha256") != state["requestSha256"]
        or captured.get("ready") is not True
    ):
        raise ValueError("截图授权或就绪状态无效")
    binding = capture.get("binding", {})
    if (
        binding.get("analysisSha256") != state["analysisSha256"]
        or not isinstance(binding.get("maxDeltaM"), (float, int))
        or not 0 <= binding["maxDeltaM"] <= 0.01
    ):
        raise ValueError("截图与本次空间分析的点位绑定未通过")
    document, actual_sha = load(state["analysisPath"])
    if actual_sha != state["analysisSha256"] or binding.get("observerCount") != len(
        document["frame"]["observers"]
    ):
        raise ValueError("空间结果或截图点位绑定已变化")
    scene, _ = load(state["scenePath"])
    known = {item["id"] for item in scene["objects"]}
    room_map = {room["id"]: room for room in scene["rooms"]}
    if any(identity not in room_map for identity in room_ids):
        raise ValueError("截图房间身份无效")
    data_url = capture.get("imageDataUrl", "")
    if (
        not data_url.startswith("data:image/png;base64,")
        or len(data_url) > 32 * 1024 * 1024
    ):
        raise ValueError("截图必须为大小受限的 PNG")
    raw = base64.b64decode(data_url.split(",", 1)[1], validate=True)
    with Image.open(io.BytesIO(raw)) as source:
        width, height = source.size
        if not 1 <= width <= 4096 or not 1 <= height <= 4096 or source.format != "PNG":
            raise ValueError("截图像素尺寸无效")
        if width != capture.get("width") or height != capture.get("height"):
            raise ValueError("截图尺寸与相机记录不一致")
        image = source.convert("RGB")
    points = capture.get("projections", [])
    if not isinstance(points, list) or len(points) > 128:
        raise ValueError("截图标注点过多")
    visible = []
    draw = ImageDraw.Draw(image)
    for point in points:
        identity, x, y = point.get("id"), point.get("x"), point.get("y")
        if (
            identity not in known
            or identity in visible
            or not all(
                isinstance(v, (float, int))
                and not isinstance(v, bool)
                and math.isfinite(v)
                for v in [x, y]
            )
        ):
            raise ValueError("截图标注点无效")
        if not 0 <= x < width or not 0 <= y < height:
            continue
        visible.append(identity)
        size = max(14, round(width / 50))
        font = ImageFont.load_default(size=size)
        radius = size * 0.7
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            fill="#20372e",
            outline="white",
            width=2,
        )
        draw.text((x, y), str(len(visible)), font=font, fill="white", anchor="mm")
    if captured.get("mode") == "Panorama":
        for identity in room_ids:
            if captured.get("panoIndex") not in room_map[identity].get(
                "panoIndexes", []
            ):
                raise ValueError("截图点位与所声明的房间不一致")
    elif captured.get("mode") == "Mapview":
        camera = validate_camera(capture.get("camera"))
        polygon, _ = camera_projector(camera, width, height)
        for identity in room_ids:
            room = room_map[identity]
            outline = [
                [x, room.get("floorY") or 0, z] for x, z in room.get("polygonXZ", [])
            ]
            if not outline or not polygon(outline):
                raise ValueError("模型截图视角没有覆盖所声明的房间")
    elif room_ids:
        raise ValueError("当前截图模式不能登记为房间证据")
    directory = Path(session_path).resolve().parent
    assets = directory / "evidence"
    assets.mkdir(exist_ok=True)
    image_sha = hashlib.sha256(raw).hexdigest()
    capture_id = hashlib.sha256(
        json.dumps(
            {
                "image": image_sha,
                "context": captured,
                "points": points,
                "capturedAt": capture["capturedAt"],
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    original = assets / f"{image_sha[:20]}.png"
    annotated = assets / f"{capture_id[:20]}-annotated.png"
    original.write_bytes(raw)
    image.save(annotated)
    metadata = {
        key: capture[key]
        for key in [
            "context",
            "binding",
            "capturedAt",
            "requestSha256",
            "width",
            "height",
        ]
    }
    metadata["projections"] = points
    if capture.get("camera") is not None:
        metadata["camera"] = validate_camera(capture["camera"])
        metadata["roomIds"] = list(room_ids)
    metadata["kind"] = kind
    atomic_json(assets / f"{capture_id[:20]}.json", metadata)
    manifest_path = directory / "evidence-manifest.json"
    if manifest_path.exists():
        manifest, _ = load(manifest_path)
        if manifest.get("requestSha256") != state["requestSha256"]:
            raise ValueError("已有截图清单属于其他授权请求")
    else:
        manifest = {
            "schema": "spatial-fengshui.evidence",
            "version": 1,
            "resourceCode": context["resourceCode"],
            "requestSha256": state["requestSha256"],
            "analysisSha256": state["analysisSha256"],
            "images": [],
        }
    record = {
        "kind": kind,
        "captureId": capture_id,
        "path": str(annotated.relative_to(directory)),
        "sha256": hashlib.sha256(annotated.read_bytes()).hexdigest(),
        "originalPath": str(original.relative_to(directory)),
        "originalSha256": image_sha,
        "metadataPath": str(
            (assets / f"{capture_id[:20]}.json").relative_to(directory)
        ),
        "metadataSha256": hashlib.sha256(
            (assets / f"{capture_id[:20]}.json").read_bytes()
        ).hexdigest(),
        "objectIds": visible,
        "roomIds": list(room_ids),
        "context": captured,
        "binding": binding,
        "capturedAt": capture["capturedAt"],
    }
    existing = next(
        (
            i
            for i, entry in enumerate(manifest["images"])
            if entry.get("captureId") == capture_id
        ),
        None,
    )
    if existing is None:
        used = [
            int(entry.get("figureId", f"E{i + 1}")[1:])
            for i, entry in enumerate(manifest["images"])
        ]
        record["figureId"] = f"E{max(used, default=0) + 1}"
        manifest["images"].append(record)
    else:
        record["figureId"] = manifest["images"][existing].get(
            "figureId", f"E{existing + 1}"
        )
        manifest["images"][existing] = record
    atomic_json(manifest_path, manifest)
    state["evidencePath"] = str(manifest_path)
    atomic_json(session_path, state)
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--capture", required=True)
    parser.add_argument("--room", action="append", default=[])
    parser.add_argument(
        "--synthetic", action="store_true", help="登记合成测试截图，报告只可作为草稿"
    )
    args = parser.parse_args(argv)
    try:
        context = read_context(args.context)
        with optional_download_lock(args.session):
            result = import_capture(
                args.session,
                context,
                args.capture,
                args.room,
                "synthetic-screenshot" if args.synthetic else "vr-screenshot",
            )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (
        ValueError,
        KeyError,
        OSError,
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
