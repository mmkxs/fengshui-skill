#!/usr/bin/env python3
"""Bind a complete-space analysis request to the active VR and user authorization."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
from urllib.parse import urlsplit, urlunsplit

from analyze import analyze, evidence_summary, write_output
from contracts import normalize_context
from consultation import readiness
from scene import fingerprint, validate
from scene import annotate, from_analysis, load

SCOPE = "full-space-fengshui-html-pdf"


def scheme_options():
    return [
        {'id': 'recommended', 'recommended': True, 'label': '推荐方案：完整空间解析',
         'description': '先分析三维空间的物品与格局，再可视化确认关键事实并给出改善建议；缺数据通过 API 补齐，计费提交单独确认。'},
        {'id': 'simple', 'recommended': False, 'label': '简版方案：户型图与朝向',
         'description': '提供户型图、朝向和房间用途等资料，得到常规布局建议；说明未基于完整三维空间解析。'},
    ]


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def atomic_json(path, value):
    write_output(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        [],
    )


def read_context(path):
    value, _ = load(path)
    value = normalize_context(value)
    if (
        not isinstance(value, dict)
        or value.get("schema") != "spatial-fengshui.active-vr"
        or value.get("version") != 1
    ):
        raise ValueError("需要从当前已连接浏览器读取 spatial-fengshui.active-vr 上下文")
    code = value.get("resourceCode")
    if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", code):
        raise ValueError("当前 VR 资源码无效")
    if (
        value.get("ready") is not True
        or not isinstance(value.get("generation"), str)
        or not value["generation"]
    ):
        raise ValueError("当前 VR 尚未就绪或缺少页面会话身份")
    url = urlsplit(value.get("pageUrl", ""))
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username
        or url.password
    ):
        raise ValueError("当前应用地址无效")
    return {
        "schema": "spatial-fengshui.active-vr",
        "version": 1,
        "resourceCode": code,
        "displayName": str(value.get("displayName", code))[:256],
        "generation": value["generation"],
        "pageUrl": urlunsplit((url.scheme, url.netloc, url.path, "", "")),
        "ready": True,
        "panoIndex": value.get("panoIndex"),
        "mode": value.get("mode"),
        "longitude": value.get("longitude"),
        "latitude": value.get("latitude"),
        "fov": value.get("fov"),
        "distance": value.get("distance"),
        "offset": value.get("offset"),
    }


def begin(project, context):
    project = Path(project).resolve()
    if not (project / ".vr-cli.json").is_file():
        raise ValueError("当前目录不是可识别的 Viewer 工程（缺少工程标识文件）")
    directory = (
        project
        / "analysis-output"
        / context["resourceCode"]
        / "fengshui"
        / uuid.uuid4().hex[:16]
    )
    directory.mkdir(parents=True, mode=0o700)
    question = (
        "你可以选推荐方案或简版方案。推荐方案先完整解析空间的物品、格局、"
        "朝向、层高、门窗与遮挡，确认关键事实后给出改善建议；本地没有准备好的数据时，"
        "通过 API 补齐（计费提交前确认）。简版方案请提供户型图、朝向和房间用途，"
        "给出常规布局建议。你选择哪种方案？"
    )
    request = {
        "scope": SCOPE,
        "requestId": directory.name,
        "context": context,
        "project": str(project),
        "question": question,
        "options": scheme_options(),
        "inputs": "full",
        "normalDownloads": True,
        "localScreenshots": True,
        "html": True,
        "pdf": True,
        "paidSubmission": False,
        "thirdPartyUpload": False,
    }
    state = {
        "schema": "spatial-fengshui.session",
        "version": 1,
        "createdAt": now(),
        "request": request,
        "requestSha256": digest(request),
        "status": "awaiting_scheme_choice",
    }
    path = directory / "session.json"
    atomic_json(path, state)
    return path, state


def checked_session(path, context=None, approved=True):
    state, _ = load(path)
    if (
        not isinstance(state, dict)
        or state.get("schema") != "spatial-fengshui.session"
        or state.get("version") != 1
    ):
        raise ValueError("会话记录无效")
    if state.get("requestSha256") != digest(state.get("request")) or state[
        "request"
    ].get("scope") not in {
        SCOPE,
        "full-space-fengshui-html",
        "full-space-fengshui-pdf",
    }:
        raise ValueError("授权范围已变化，请重新发起请求")
    bound = state["request"]["context"]
    if context is not None and any(
        context.get(key) != bound.get(key) for key in ["resourceCode", "pageUrl"]
    ):
        raise ValueError("当前 VR 或页面会话已变化，请重新确认本次任务")
    if context is not None:
        state["activeContext"] = context
    approval = state.get("authorization", {})
    if approved and (
        approval.get("decision") != "approved"
        or approval.get("requestSha256") != state["requestSha256"]
        or approval.get("actor") != "user"
    ):
        raise ValueError("尚未取得本次完整分析的用户授权")
    return state


def authorize(path, context, request_sha, reply, granted, scheme='recommended'):
    state = checked_session(path, context, approved=False)
    if request_sha != state["requestSha256"] or not reply.strip():
        raise ValueError("需要本次授权请求哈希与用户的明确回复原文")
    if scheme not in {'recommended', 'simple'}:
        raise ValueError('请选择 recommended 或 simple')
    state["authorization"] = {
        "actor": "user",
        "decision": ('approved' if scheme == 'recommended' else 'simple-selected') if granted else 'denied',
        "requestSha256": request_sha,
        "userReply": reply,
        "recordedAt": now(),
    }
    state["status"] = "authorized" if granted else "denied"
    if granted:
        state['selectedScheme'] = scheme
        state.pop('simpleInputsRequired', None)
        if scheme == 'simple':
            state['status'] = 'awaiting_simple_inputs'
            state['simpleInputsRequired'] = ['户型图', '朝向及其依据', '房间用途', '关心的问题或希望改善的位置']
    atomic_json(path, state)
    return state


def optional_download_lock(session_path):
    """Sibling analysis kit owns the lock when present; otherwise lock locally.

    Captures, HTML and PDF only need the file lock, so standalone skill use must
    not fail when the sibling analysis kit is absent.
    """
    from contextlib import contextmanager

    try:
        scripts = companion()
        sys.path.insert(0, str(scripts))
        from download_center import download_lock

        return download_lock(Path(session_path))
    except (ValueError, ImportError):
        @contextmanager
        def local_lock():
            path = Path(session_path).resolve().parent / ".download.lock"
            handle = open(path, "a+")
            try:
                try:
                    import fcntl

                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except ImportError:
                    pass
                except OSError as error:
                    raise ValueError("另一项任务正在写入本次会话") from error
                yield
            finally:
                handle.close()

        return local_lock()


def companion(project=None):
    if project is not None:
        installed = Path(project) / '.agents/skills/realsee-spatial-analysis/scripts'
        if (Path(project) / '.vr-cli.json').is_file() and (installed / 'pipeline.py').is_file():
            return installed
    directory = Path(__file__).resolve().parents[2] / "realsee-spatial-analysis/scripts"
    if not (directory / "pipeline.py").is_file():
        raise ValueError(
            "缺少同级空间解析适配模块；"
            "纯独立使用可跳过此入口，直接运行 analyze.py"
        )
    return directory


def run_command(command, cwd, logfile):
    with Path(logfile).open("w", encoding="utf-8") as output:
        result = subprocess.run(
            command,
            cwd=cwd,
            stdout=output,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
    lines = Path(logfile).read_text(errors="replace").splitlines()
    payload = {}
    for line in reversed(lines):
        try:
            candidate = json.loads(line)
            if isinstance(candidate, dict):
                payload = candidate
                break
        except ValueError:
            continue
    return result.returncode, payload


def spatial_pause_status(payload):
    if (payload.get('billingConfirmation') or {}).get('required'):
        return 'awaiting_billing_confirmation'
    if payload.get('error') == 'API_DOWNLOAD_UNAVAILABLE':
        return 'needs_environment'
    if payload.get('awaitingConfirmation'):
        return 'awaiting_download_confirmation'
    return 'needs_data'


def run_spatial(path, context, python, browser_work=None, confirm_billing=False, base_url=None):
    state = checked_session(path, context)
    project = Path(state["request"]["project"])
    code = context["resourceCode"]
    scripts = companion(project)
    workspace = project / "analysis-output" / code
    work = Path(path).resolve().parent / "inputs" / "work.json"
    directory = Path(path).resolve().parent
    # Retain files for history, but revoke every proof from the preceding attempt
    # before any operation which can fail, stop for data, or return a plan.
    for key in [
        "fullAnalysisExecuted",
        "analysisPath",
        "analysisSha256",
        "scenePath",
        "reportPath",
        "capturePlanPath",
        "consultationPath",
        "questions",
        "evidencePath",
        "htmlPath",
        "htmlVisualReviewPath",
        "pdfPath",
        "pdfVisualReviewPath",
        "reportConfirmation",
        "pdfAuthorization",
    ]:
        state.pop(key, None)
    state["analysisAttemptId"] = uuid.uuid4().hex
    state["status"] = "spatial_running"
    atomic_json(path, state)
    if browser_work:
        snapshot, _ = load(browser_work)
        if (
            snapshot.get("schema") != "spatial-fengshui.browser-snapshot"
            or snapshot.get("requestSha256") != state["requestSha256"]
        ):
            raise ValueError("浏览器 Work 快照未绑定本次授权")
        if any(
            snapshot.get("context", {}).get(key) != context.get(key)
            for key in ["resourceCode", "generation", "pageUrl"]
        ):
            raise ValueError("浏览器 Work 快照属于其他空间或页面")
        envelope = snapshot.get("envelope", {})
        if envelope.get("workCode") != code or not isinstance(
            envelope.get("work"), dict
        ):
            raise ValueError("浏览器返回的 Work 身份无效")
        atomic_json(work, {**envelope, "inputOrigin": "authorized-browser-bff"})
    else:
        source = urlsplit(context["pageUrl"])
        base_url = urlunsplit((source.scheme, source.netloc, "", "", ""))
        command = [
            python,
            str(scripts / "materialize_work_inputs.py"),
            "--resource-code",
            code,
            "--app",
            str(project),
            "--base-url",
            base_url,
            "--out",
            str(work.parent),
            "--force",
        ]
        if source.hostname not in {"127.0.0.1", "localhost", "::1"}:
            command.append("--allow-remote")
        exit_code, payload = run_command(
            command, project, directory / "materialize.log"
        )
        if exit_code:
            state.update(
                status="needs_data",
                blocked={
                    "stage": "materialize",
                    "exitCode": exit_code,
                    "result": payload,
                },
            )
            atomic_json(path, state)
            return state
    from viewer_confirm import requirements
    if not (scripts / 'analysis_request.py').is_file():
        raise ValueError('空间 skill 缺少外部需求契约，请更新后再运行完整分析')
    requirements_path = directory / 'spatial-requirements.json'
    if not requirements_path.exists():
        atomic_json(requirements_path, requirements(code))
    command = [
        python,
        str(scripts / "pipeline.py"),
        "all",
        "--analysis-request",
        str(requirements_path),
        "--resource-code",
        code,
        "--inputs",
        "full",
        "--resources-root",
        str(project / "resources"),
        "--work-json",
        str(work),
        "--workspace",
        str(workspace),
        "--no-apply",
        "--yes",
    ]
    origin = urlsplit(context['pageUrl'])
    if base_url:
        command += ['--base-url', base_url]
    elif origin.hostname in {'127.0.0.1', 'localhost', '::1'}:
        command += ['--base-url', urlunsplit((origin.scheme, origin.netloc, '', '', ''))]
    if confirm_billing:
        command.append('--confirm-billing')
    exit_code, payload = run_command(command, project, directory / "spatial.log")
    if (
        exit_code
        or payload.get("mode") != "run"
        or payload.get("ok") is not True
        or payload.get("awaitingChoice")
        or payload.get("awaitingConfirmation")
        or payload.get("billingConfirmation")
    ):
        state.update(
            status=spatial_pause_status(payload),
            blocked={"stage": "spatial", "exitCode": exit_code, "result": payload},
        )
        atomic_json(path, state)
        return state
    analysis_path = workspace / "data" / code / "spatial-analysis.v2.json"
    if not analysis_path.is_file():
        state.update(
            status="needs_data",
            blocked={"stage": "spatial", "reason": "本次未导出完整空间结果"},
        )
        atomic_json(path, state)
        return state
    document, analysis_sha = load(analysis_path)
    if document.get("resourceCode") != code or document.get("generator", {}).get(
        "params", {}
    ).get("pipeline.tier") not in {"full", "reduced", "horizon"}:
        state.update(
            status="needs_data",
            blocked={
                "stage": "spatial",
                "reason": "结果身份或物品推理档位未通过完整解析核对",
            },
        )
        atomic_json(path, state)
        return state
    state.update(
        status="awaiting_evidence",
        analysisPath=str(analysis_path),
        analysisSha256=analysis_sha,
        fullAnalysisExecuted=True,
    )
    state.pop("blocked", None)
    atomic_json(path, state)
    return assess(path, context)


def analyze_entire_space(prepared):
    validate(prepared)
    results = []
    seen = set()
    for room in prepared["rooms"]:
        selected = copy_scene_for_room(prepared, room)
        current = analyze(selected)
        for finding in current["findings"]:
            signature = (
                finding["ruleId"],
                tuple(sorted(finding["objectIds"])),
                finding["status"],
            )
            if signature not in seen:
                results.append(finding)
                seen.add(signature)
    if not prepared["rooms"]:
        result = analyze(prepared)
        result["consultation"] = readiness(prepared, result)
        result["evidence"]["questions"] = result["consultation"]["questions"]
        return result
    # Analyze per room for pair limits, then build whole-space metadata separately.
    seed = analyze(copy_scene_for_room(prepared, prepared["rooms"][0]))
    seed.update(
        sceneFingerprint=fingerprint(prepared),
        roomIds=[room["id"] for room in prepared["rooms"]],
        findings=results,
        rooms=[
            {
                "id": room["id"],
                "name": room.get("name"),
                "function": room.get("function", "unknown"),
            }
            for room in prepared["rooms"]
        ],
        evidence=evidence_summary(prepared),
    )
    seed["summary"] = {
        status: sum(item["status"] == status for item in results)
        for status in seed["summary"]
    }
    seed["notAssessed"] = [
        {
            "objectId": item["id"],
            "type": item["type"],
            "reason": "房间归属或专用规则待补",
        }
        for item in prepared["objects"]
        if not item.get("roomIds")
        or item["type"] in {"stove", "sink", "toilet", "column", "other"}
    ]
    seed["consultation"] = readiness(prepared, seed)
    seed["evidence"]["questions"] = seed["consultation"]["questions"]
    return seed


def copy_scene_for_room(prepared, room):
    import copy

    selected = copy.deepcopy(prepared)
    selected["rooms"] = [copy.deepcopy(room)]
    selected["objects"] = [
        item for item in selected["objects"] if room["id"] in item.get("roomIds", [])
    ]
    for item in selected["objects"]:
        item["roomIds"] = [room["id"]]
    return selected


def capture_plan(document, report, prepared):
    from visuals import KEY_TYPES

    rooms = document["overview"]["rooms"]
    views = []
    for room in rooms:
        subjects = [
            item
            for item in document["objects"]
            if item.get("roomId") == room["id"]
            and item.get("source") == "detector"
            and any(
                obj["id"] == item["id"] and obj["type"] in KEY_TYPES
                for obj in prepared["objects"]
            )
        ]
        by_pano = {}
        for item in subjects:
            by_pano.setdefault(item["bestPanoIndex"], []).append(item)
        if not by_pano:
            by_pano[room["entryPanoIndex"]] = []
        for pano, items in by_pano.items():
            views.append(
                {
                    "roomId": room["id"],
                    "panoIndex": pano,
                    "points": [
                        {
                            "id": item["id"],
                            "position": next(
                                (
                                    view["anchor"]
                                    for view in item.get("views", [])
                                    if view.get("panoIndex") == pano
                                ),
                                (item.get("obb") or {}).get("center", item["center"]),
                            ),
                        }
                        for item in items
                    ],
                    "suggestedLongitudeRadians": [
                        0,
                        1.5707963267948966,
                        3.141592653589793,
                        -1.5707963267948966,
                    ],
                    "coverage": "在画面内核对投影点，必要时补俯仰或换点位。截图以实际可见对象登记。",
                }
            )
    original_ids = {item["id"] for item in document["objects"]}
    for room in rooms:
        extra = [
            item
            for item in prepared["objects"]
            if item["id"] not in original_ids and room["id"] in item.get("roomIds", [])
        ]
        points = []
        for item in extra:
            position = (item.get("surface") or item.get("box") or {}).get("center")
            if position is not None:
                points.append({"id": item["id"], "position": position})
        if points:
            views.append(
                {
                    "roomId": room["id"],
                    "panoIndex": room["entryPanoIndex"],
                    "points": points,
                    "suggestedLongitudeRadians": [
                        0,
                        1.5707963267948966,
                        3.141592653589793,
                        -1.5707963267948966,
                    ],
                    "coverage": "补充标注物品，按实际可见表面选择标注点并复核图像。",
                }
            )
    model_views = []
    for room in prepared["rooms"]:
        corners = room.get("polygonXZ", [])
        if not corners:
            continue
        xs, zs = zip(*corners)
        model_views.append(
            {
                "roomId": room["id"],
                "mode": "Mapview",
                "state": {
                    "offset": [
                        (min(xs) + max(xs)) / 2,
                        (room.get("floorY") or 0)
                        + (room.get("ceilingHeightM") or 2.8) / 2,
                        (min(zs) + max(zs)) / 2,
                    ],
                    "distance": max(
                        max(xs) - min(xs),
                        max(zs) - min(zs),
                        room.get("ceilingHeightM") or 2.8,
                    )
                    * 1.8,
                    "longitude": 0.7853981633974483,
                    "latitude": 0.6,
                },
                "points": [
                    {
                        "id": obj["id"],
                        "position": (obj.get("box") or obj.get("surface") or {}).get(
                            "center"
                        ),
                    }
                    for obj in prepared["objects"]
                    if room["id"] in obj.get("roomIds", [])
                    and obj["type"] in KEY_TYPES
                    and (obj.get("box") or obj.get("surface"))
                ],
                "purpose": "模型态截图与空间关系图共用真实相机矩阵；解读完成后只标注结论涉及的物品和关键环境对象。",
            }
        )
    return {
        "resourceCode": document["resourceCode"],
        "views": views,
        "modelViews": model_views,
        "analysisSha256": report.get("sourceAnalysisSha256"),
        "observers": [
            observer["position"] for observer in document["frame"]["observers"]
        ],
        "reviewObjectIds": sorted(
            {
                identity
                for row in report["findings"]
                if row["status"] == "candidate"
                for identity in row["objectIds"]
            }
        ),
        "additionalAnnotations": [
            row for row in report["findings"] if row["status"] == "unknown"
        ],
    }


def require_current_analysis(state):
    if state.get("fullAnalysisExecuted") is not True or state.get("status") in {
        "spatial_running",
        "needs_data",
        "needs_environment",
        "awaiting_billing_confirmation",
        "awaiting_download_confirmation",
    }:
        raise ValueError("尚未完成本次完整空间解析；失败或待补数据的任务不能复用旧结果")


def assess(path, context, annotations_path=None):
    state = checked_session(path, context)
    require_current_analysis(state)
    source = state.get("analysisPath")
    if not source or not state.get("fullAnalysisExecuted"):
        raise ValueError("尚未完成本次完整空间解析")
    document, source_sha = load(source)
    if source_sha != state["analysisSha256"]:
        raise ValueError("空间分析结果已变化，请重新核对本次结果")
    prepared = from_analysis(source)
    if annotations_path:
        extra, extra_sha = load(annotations_path)
        prepared = annotate(prepared, extra)
        prepared["annotationsSha256"] = extra_sha
    report = analyze_entire_space(prepared)
    report["inputHashes"] = {"sourceAnalysisSha256": source_sha}
    if prepared.get("annotationsSha256"):
        report["inputHashes"]["annotationsSha256"] = prepared["annotationsSha256"]
    directory = Path(path).resolve().parent
    atomic_json(directory / "scene.json", prepared)
    atomic_json(directory / "fengshui-analysis.json", report)
    atomic_json(directory / "consultation.json", report.get("consultation", {}))
    atomic_json(
        directory / "capture-plan.json", capture_plan(document, report, prepared)
    )
    state.update(
        status="awaiting_user_input"
        if not report.get("consultation", {}).get("ready", False)
        else "awaiting_evidence",
        scenePath=str(directory / "scene.json"),
        reportPath=str(directory / "fengshui-analysis.json"),
        capturePlanPath=str(directory / "capture-plan.json"),
        questions=report.get("consultation", {}).get("questions", []),
        consultationPath=str(directory / "consultation.json"),
    )
    state.pop("reportConfirmation", None)
    atomic_json(path, state)
    return state


def finalize(path, context, review_path):
    state = checked_session(path, context)
    directory = Path(path).resolve().parent
    manifest_path = directory / "report-manifest.json"
    manifest, _ = load(manifest_path)
    if manifest.get("format") == "html":
        review, _ = load(review_path)
        if review.get("schema") == "spatial-fengshui.pdf-visual-review":
            from pdf_export import finalize_pdf

            return finalize_pdf(path, context, review_path, state, manifest)
        return finalize_html(path, context, review_path, state, manifest)
    if manifest.get("requestSha256") != state["requestSha256"]:
        raise ValueError("PDF 清单与本次任务不一致")
    pdf = Path(manifest["pdf"])
    actual_sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    review, _ = load(review_path)
    if (
        review.get("schema") != "spatial-fengshui.pdf-visual-review"
        or review.get("pdfSha256") != actual_sha
        or actual_sha != manifest["pdfSha256"]
    ):
        raise ValueError("PDF 或视觉复核记录属于旧版本")
    if (
        review.get("textCheckPassed") is not True
        or review.get("layoutPassed") is not True
    ):
        raise ValueError("中文或排版复核尚未通过")
    pages = review.get("pages", [])
    if sorted(item.get("page") for item in pages) != list(
        range(1, manifest["pageCount"] + 1)
    ):
        raise ValueError("需要逐页渲染并复核全部页面")
    for item in pages:
        image = (directory / item["path"]).resolve()
        if (
            not image.is_relative_to(directory)
            or not image.is_file()
            or hashlib.sha256(image.read_bytes()).hexdigest() != item.get("sha256")
        ):
            raise ValueError("页面渲染文件缺失或已变化")
    atomic_json(directory / "pdf-visual-review.json", review)
    manifest["visualReviewStatus"] = "accepted"
    manifest["visualReviewSha256"] = digest(review)
    atomic_json(manifest_path, manifest)
    state["status"] = (
        "report_draft"
        if manifest["status"] == "draft"
        else "delivered_with_limitations"
        if manifest["contentLimitations"]
        else "delivered"
    )
    state["pdfVisualReviewPath"] = str(directory / "pdf-visual-review.json")
    atomic_json(path, state)
    return state


def checked_html(state, manifest, directory):
    require_current_analysis(state)
    if (
        manifest.get("format") != "html"
        or manifest.get("requestSha256") != state["requestSha256"]
    ):
        raise ValueError("HTML 清单与本次任务不一致")
    html = Path(manifest["html"]).resolve()
    if not html.is_relative_to(directory) or hashlib.sha256(
        html.read_bytes()
    ).hexdigest() != manifest.get("htmlSha256"):
        raise ValueError("HTML 已变化，请重新生成与复核")
    prepared, _ = load(state["scenePath"])
    source, source_sha = load(state["analysisPath"])
    _, report_sha = load(state["reportPath"])
    if (
        fingerprint(prepared) != manifest.get("sceneFingerprint")
        or source_sha != manifest.get("analysisSha256")
        or report_sha != manifest.get("reportSha256")
    ):
        raise ValueError("HTML 对应的场景或分析已变化，请重新生成")
    if state.get("analysisAttemptId") != manifest.get("analysisAttemptId"):
        raise ValueError("HTML 属于之前的解析任务，请重新生成并复核")
    if manifest.get("interpretationSha256") is not None:
        interpretation = manifest.get("interpretationPath")
        if (
            not interpretation
            or not Path(interpretation).is_file()
            or hashlib.sha256(Path(interpretation).read_bytes()).hexdigest()
            != manifest["interpretationSha256"]
        ):
            raise ValueError("解读内容已变化或缺少来源绑定，请重新生成并复核 HTML")
    elif manifest.get("status") != "draft":
        raise ValueError("正式 HTML 缺少解读来源绑定，请重新生成")
    return html


def finalize_html(path, context, review_path, state, manifest):
    directory = Path(path).resolve().parent
    checked_html(state, manifest, directory)
    review, _ = load(review_path)
    if (
        review.get("schema") != "spatial-fengshui.html-visual-review"
        or review.get("htmlSha256") != manifest["htmlSha256"]
    ):
        raise ValueError("HTML 视觉复核记录属于旧版本")
    if (
        review.get("textCheckPassed") is not True
        or review.get("layoutPassed") is not True
    ):
        raise ValueError("HTML 内容或排版复核尚未通过")
    screenshots = review.get("screenshots", [])
    if not screenshots:
        raise ValueError("请保存桌面与手机宽度的页面复核截图")
    if not {"desktop", "mobile"}.issubset(
        {item.get("viewport") for item in screenshots}
    ):
        raise ValueError("需要桌面与手机宽度的页面复核记录")
    for item in screenshots:
        image = (directory / item["path"]).resolve()
        if (
            not image.is_relative_to(directory)
            or not image.is_file()
            or hashlib.sha256(image.read_bytes()).hexdigest() != item.get("sha256")
        ):
            raise ValueError("页面复核截图已变化")
    atomic_json(directory / "html-visual-review.json", review)
    manifest.update(visualReviewStatus="accepted", visualReviewSha256=digest(review))
    atomic_json(directory / "report-manifest.json", manifest)
    state.update(
        status="report_draft"
        if manifest["status"] == "draft"
        else "awaiting_report_confirmation",
        htmlVisualReviewPath=str(directory / "html-visual-review.json"),
    )
    atomic_json(path, state)
    return state


def confirm_report(path, context, html_sha, reply):
    state = checked_session(path, context)
    directory = Path(path).resolve().parent
    manifest, _ = load(directory / "report-manifest.json")
    checked_html(state, manifest, directory)
    if (
        manifest.get("status") == "draft"
        or manifest.get("visualReviewStatus") != "accepted"
    ):
        raise ValueError("请先完成正式 HTML 报告的视觉复核")
    if (
        html_sha != manifest["htmlSha256"]
        or not isinstance(reply, str)
        or not reply.strip()
    ):
        raise ValueError("需要用户针对当前 HTML 的明确确认与文件哈希")
    state.update(
        status="html_confirmed",
        reportConfirmation={
            "actor": "user",
            "htmlSha256": html_sha,
            "userReply": reply,
            "at": now(),
        },
    )
    manifest["userConfirmationStatus"] = "confirmed"
    atomic_json(directory / "report-manifest.json", manifest)
    atomic_json(path, state)
    return state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--project", default=".")
    plan.add_argument("--context", required=True)
    approval = sub.add_parser("authorize")
    approval.add_argument("--session", required=True)
    approval.add_argument("--context", required=True)
    approval.add_argument("--request-sha256", required=True)
    approval.add_argument("--user-reply", required=True)
    approval.add_argument("--decision", choices=["approve", "deny"], required=True)
    approval.add_argument('--scheme', choices=['recommended', 'simple'], default='recommended')
    for name in ["run", "assess"]:
        command = sub.add_parser(name)
        command.add_argument("--session", required=True)
        command.add_argument("--context", required=True)
        if name == "run":
            command.add_argument("--python", default=sys.executable)
            command.add_argument('--base-url', help='本机下载 BFF 地址；默认使用当前页面同源入口')
            command.add_argument('--confirm-billing', action='store_true', help='用户明确确认本次下载计划的计费后使用')
            command.add_argument(
                "--browser-work", help="当前浏览器从同源 BFF 获取并绑定授权的 Work 快照"
            )
        else:
            command.add_argument("--annotations")
    finish = sub.add_parser("finalize")
    finish.add_argument("--session", required=True)
    finish.add_argument("--context", required=True)
    finish.add_argument("--review", required=True)
    confirm = sub.add_parser("confirm-report")
    confirm.add_argument("--session", required=True)
    confirm.add_argument("--context", required=True)
    confirm.add_argument("--html-sha256", required=True)
    confirm.add_argument("--user-reply", required=True)
    pdf = sub.add_parser("export-pdf")
    pdf.add_argument("--session", required=True)
    pdf.add_argument("--context", required=True)
    pdf.add_argument("--output", required=True)
    pdf.add_argument("--browser-executable")
    pdf.add_argument(
        "--user-reply", help="旧的仅 HTML 授权需保留用户同意 PDF 的原始回复"
    )
    pdf.add_argument("--draft", action="store_true")
    args = parser.parse_args(argv)
    try:
        context = read_context(args.context)
        if args.command == "plan":
            path, state = begin(args.project, context)
            print(
                json.dumps(
                    {
                        "mode": "choose-scheme",
                        "awaitingChoice": True,
                        "options": state['request']['options'],
                        "session": str(path),
                        "question": state["request"]["question"],
                        "requestSha256": state["requestSha256"],
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        with optional_download_lock(args.session):
            if args.command == "authorize":
                state = authorize(
                    args.session,
                    context,
                    args.request_sha256,
                    args.user_reply,
                    args.decision == "approve",
                    args.scheme,
                )
            elif args.command == "run":
                state = run_spatial(
                    args.session, context, args.python, args.browser_work,
                    args.confirm_billing, args.base_url
                )
            elif args.command == "assess":
                state = assess(args.session, context, args.annotations)
            elif args.command == "confirm-report":
                state = confirm_report(
                    args.session, context, args.html_sha256, args.user_reply
                )
            elif args.command == "export-pdf":
                from pdf_export import export_pdf

                state = export_pdf(
                    args.session,
                    context,
                    args.output,
                    args.browser_executable,
                    args.user_reply,
                    args.draft,
                )
            else:
                state = finalize(args.session, context, args.review)
        print(json.dumps(state, ensure_ascii=False))
        return 6 if state["status"] in {"needs_data", "awaiting_user_input"} else 0
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
        print(
            json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
