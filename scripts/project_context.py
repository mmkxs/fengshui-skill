#!/usr/bin/env python3
"""Decide how a fengshui task should obtain spatial data inside a project.

Rule of thumb encoded here: inside a local viewer project the analysis always
starts from that viewer's own spatial data. Reuse a complete result when the current Work
snapshot still matches; otherwise run the full tier again. Never silently fall
back to a work-only downgrade.

    python scripts/project_context.py --project . --resource-code <RC>
    python scripts/project_context.py --project . --resource-code <RC> --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return None


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


GEOMETRY_KEYS = (
    "resource_code",
    "basic_code",
    "project_id",
    "device_type",
    "initial",
    "observers",
    "model",
    "panorama",
)


def geometry_signature(value):
    """Only geometry-bearing fields decide whether an old result can be reused.

    Signatures, expiry, cover pictures and the display name change per request
    and must not force a full re-parse by themselves.
    """
    if not isinstance(value, dict):
        return value
    work = value.get("work") if isinstance(value.get("work"), dict) else value
    return {key: work.get(key) for key in GEOMETRY_KEYS}


def find_analysis(project, resource_code):
    out = project / "analysis-output" / resource_code
    analysis = out / "data" / resource_code / "spatial-analysis.v2.json"
    scenes = list((out / "fengshui").glob("*/scene.json")) if (
        out / "fengshui"
    ).is_dir() else []
    scene = max(scenes, key=lambda path: path.stat().st_mtime, default=None)
    inputs = out / "inputs" / "work.json"
    snapshot = project / "resources" / resource_code / "work.json"
    return {
        "analysis": analysis if analysis.is_file() else None,
        "scene": scene,
        "inputs": inputs if inputs.is_file() else None,
        "snapshot": snapshot if snapshot.is_file() else None,
        "out": out,
    }


def detect(project, resource_code):
    project = Path(project).resolve()
    result = {
        "schema": "spatial-fengshui.project-context",
        "version": 1,
        "project": str(project),
        "resourceCode": resource_code,
        "mode": "standalone",
        "recommendation": "standalone",
        "inputs": None,
        "details": {},
        "next": [],
    }
    if not (project / ".vr-cli.json").is_file():
        result["next"].append(
            "未检测到工程标识：按独立使用处理。若该空间有可访问的实景空间或 VR，优先走完整解析并导入结果。"
        )
        result["next"].append(
            "用户选择轻量分析或没有完整解析来源时，再使用场景 JSON、外部解析结果或户型图；降级结果须标注依据等级。"
        )
        return result

    result["mode"] = "local-viewer"
    kit = project / ".agents/skills/realsee-spatial-analysis/scripts/pipeline.py"
    paired = (project / ".env.development").is_file()
    paths = find_analysis(project, resource_code)
    result["details"] = {
        "spatialKit": kit.is_file(),
        "bffPaired": paired,
        "analysisPath": str(paths["analysis"]) if paths["analysis"] else None,
        "scenePath": str(paths["scene"]) if paths["scene"] else None,
        "workSnapshot": str(paths["snapshot"]) if paths["snapshot"] else None,
    }

    if not paths["analysis"]:
        result["recommendation"] = "run-full"
        result["inputs"] = "full"
        result["next"] = [
            "工程内没有该空间解析结果：按完整档解析（inputs=full）后再做风水分析。",
            "只为报告解析数据时使用 --no-apply 交付路径，不改应用本身。",
        ]
        return result

    document = read_json(paths["analysis"]) or {}
    rooms = document.get("overview", {}).get("rooms") or []
    objects = document.get("objects") or []
    work_match = None
    if paths["snapshot"] and paths["inputs"]:
        current_raw = read_json(paths["snapshot"])
        delivered_raw = read_json(paths["inputs"])
        current = geometry_signature(current_raw)
        delivered = geometry_signature(delivered_raw)
        work_match = current is not None and delivered is not None and digest(current) == digest(delivered)
        names = {
            (current_raw or {}).get("work", {}).get("name"),
            (delivered_raw or {}).get("work", {}).get("name"),
        }
        result["details"]["renamed"] = len(names) > 1
    result["details"]["rooms"] = len(rooms)
    result["details"]["objects"] = len(objects)
    result["details"]["workMatch"] = work_match

    if work_match and rooms:
        result["recommendation"] = "reuse-full"
        result["inputs"] = "full"
        result["next"] = [
            "已有完整档空间结果且与当前空间快照一致：直接复用，不重复解析。",
            "复用前向用户确认近期是否改动过家具或装修；有改动则重跑完整档。",
        ]
    elif work_match is False:
        result["recommendation"] = "rerun-full"
        result["inputs"] = "full"
        result["next"] = [
            "现有空间结果与当前空间快照不一致：数据已更新，按完整档重新解析。",
            "不要沿用旧结果生成报告。",
        ]
    else:
        result["recommendation"] = "reuse-full"
        result["inputs"] = "full"
        result["next"] = [
            "已有空间结果但缺少空间快照或房间划分：先核对来源，缺失时重跑完整档。",
        ]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=".")
    parser.add_argument("--resource-code", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = detect(args.project, args.resource_code)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0
    print(f"模式：{result['mode']}　建议：{result['recommendation']}　档位：{result['inputs'] or '-'}")
    for key, value in result["details"].items():
        print(f"  {key}: {value}")
    for item in result["next"]:
        print(f"- {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
