"""Build a self-contained, reader-facing HTML report after consultation."""

import base64
from datetime import datetime
import hashlib
import io
from html import escape
import math
from pathlib import Path
import re

from consultation import display_names, excluded_rules, readiness, RULE_NAMES
from geometry import add, cross, scale, unit, world
from scene import fingerprint, load, validate
from workflow import atomic_json, checked_session, require_current_analysis
from visuals import (
    focus_objects,
    matching_model_image,
    camera_projector,
    note_rooms,
    paired_crop,
)

DISCLAIMER = "本系统基于传统风水文化及 VR 空间数据生成报告，仅用于空间格局分析、传统文化研究与娱乐参考，不构成现实人生、投资、商业选址等决策建议"

COLORS = {
    "bed": "#b3cdbf",
    "desk": "#c7d9c5",
    "sofa": "#b3cdbf",
    "door": "#87b1c2",
    "mirror": "#c5b3d7",
    "beam": "#d9b27b",
    "window": "#b0d6dc",
    "wall": "#d4d7cf",
    "partition": "#d4d7cf",
}
CSS = """:root{color-scheme:light;--ink:#233b34;--green:#2b654d;--paper:#f6f5f0;--muted:#5c6b65;--line:#dce3db}
*{box-sizing:border-box}html{scroll-padding-top:2rem}body{margin:0;background:var(--paper);color:var(--ink);font:1rem/1.85 system-ui,-apple-system,'PingFang SC','Microsoft YaHei',sans-serif}
a{color:inherit;text-underline-offset:.25em}a:focus-visible{outline:3px solid #b06929;outline-offset:5px}.skip{position:absolute;left:1rem;top:-5rem}.skip:focus{top:1rem;background:white;padding:1rem;z-index:5}
.wrap{max-width:1180px;margin:auto;padding:0 2rem}.masthead{display:flex;justify-content:space-between;align-items:center;gap:1rem;padding:1.6rem 0;border-bottom:1px solid var(--line)}.brand{font-weight:650;letter-spacing:.12em}.meta,.muted,figcaption{color:var(--muted);font-size:.875rem}
.hero{padding:4rem 0 2.7rem;max-width:850px}.eyebrow{font-size:.8rem;letter-spacing:.17em;color:var(--green);font-weight:700}h1{font-size:clamp(2rem,1.4rem + 2.8vw,3.7rem);line-height:1.27;font-weight:600;letter-spacing:-.035em;margin:.8rem 0 1.4rem}h2{font-size:clamp(1.35rem,1.1rem + .8vw,1.8rem);line-height:1.4;margin:0 0 1.2rem}h3{font-size:1.15rem;line-height:1.5;margin:0 0 .7rem}p{margin:.5rem 0 1rem;overflow-wrap:anywhere}.lead{font-size:1.16rem;max-width:70ch}
.layout{display:grid;grid-template-columns:160px minmax(0,1fr);gap:2.8rem;padding-bottom:4rem}.toc{position:sticky;top:2rem;align-self:start;border-top:2px solid var(--green);padding-top:1rem}.toc a{display:block;text-decoration:none;padding:.45rem 0;font-size:.9rem}.toc a:hover{text-decoration:underline}main{min-width:0}.section{margin-bottom:2rem;padding:2rem;background:white;border:1px solid var(--line);border-radius:12px;container-type:inline-size}.section>p:last-child{margin-bottom:0}
.priorities{padding-left:1.4rem}.priorities li{padding-left:.4rem;margin:0 0 1.2rem}.priorities .more{font-size:.86rem;color:var(--green);text-decoration:underline;white-space:nowrap}.section h2+.lead{color:var(--muted);margin-top:-.4rem}.tag{display:inline-block;background:#edf2eb;border-radius:4px;padding:.1rem .55rem;font-size:.76rem;color:var(--green);font-weight:650}.high{background:#f7ede2;color:#875123}.location{font-size:.9rem;color:var(--muted);margin-bottom:1.1rem}.finding-title{margin:-.2rem 0 .5rem;font-size:1.02rem;color:#33413b}.analysis{border-left:3px solid #b5c9b5;padding-left:1.1rem;margin:1.5rem 0}.actions{padding-left:1.3rem}.actions li{margin-bottom:.55rem}.note{border-top:1px solid var(--line);padding-top:1rem;font-size:.86rem;color:var(--muted)}
figure{margin:1rem 0 1.5rem}svg{display:block;width:100%;height:auto;border-radius:8px;background:#f1f4ed}svg text{font-family:system-ui,'PingFang SC',sans-serif}figcaption{padding-top:.6rem;line-height:1.7}.visuals{display:grid;grid-template-columns:1fr;gap:1.2rem}.legend{display:flex;flex-wrap:wrap;gap:.25rem 1rem;list-style:none;padding:0;margin:.7rem 0;font-size:.8rem;color:var(--muted)}.photo{display:block;width:100%;height:auto;border-radius:8px;object-fit:contain}.refs{font-size:.85rem}.preview{padding:.8rem 1rem;background:#f5e8d9;color:#744818;border-radius:6px;margin:1rem 0}.footer{padding:1.5rem 0 3rem;color:var(--muted);font-size:.85rem;border-top:1px solid var(--line)}
@container(min-width:600px){.visuals{grid-template-columns:1fr 1fr}}@media(max-width:760px){.wrap{padding:0 1rem}.masthead{align-items:start;flex-direction:column;gap:.1rem}.hero{padding:2.5rem 0 1.5rem}.layout{grid-template-columns:1fr;gap:1.3rem}.toc{position:static;display:flex;flex-wrap:wrap;gap:.15rem 1rem;padding-top:.6rem}.section{padding:1.3rem}.toc a{padding:.3rem 0}}
.model-pair{display:grid;grid-template-columns:minmax(0,1fr);gap:1rem}.model-pair:has(.model-photo){grid-template-columns:repeat(2,minmax(0,1fr))}.model-pair figure{min-width:0}.model-photo{width:100%;height:auto;display:block;border-radius:8px}.disclaimer{font-size:.85rem;color:var(--muted);border-top:1px solid var(--line);padding-top:1rem}
@supports not selector(:has(*)){.model-pair.has-model{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:760px){.model-pair:has(.model-photo),.model-pair.has-model{grid-template-columns:1fr}}
@page{size:A4;margin:16mm 17mm}
@media print{
html{font-size:10pt}body{background:#fff;line-height:1.6;print-color-adjust:exact;-webkit-print-color-adjust:exact}
.wrap{max-width:none;padding:0}.toc,.skip{display:none}.layout{display:block;padding:0}.masthead{padding:0 0 3mm}.meta{display:none}.hero{padding:8mm 0 5mm}.hero h1{font-size:27pt}.hero .lead{font-size:11pt}
.section{border:0;border-radius:0;padding:0;margin:0 0 7mm;container-type:normal}h2{font-size:17pt}h3{font-size:12pt}h2,h3{break-after:avoid}p,li{orphans:3;widows:3}
#space{break-before:page}section[id^="finding-"]{break-before:auto;break-inside:auto}.visuals{display:grid;grid-template-columns:1fr 1fr;gap:4mm}.visuals figure{margin:2mm 0}.visuals svg{max-height:52mm}
figure{break-inside:avoid;margin:3mm 0}.photo{max-height:40mm;object-fit:contain;width:100%}section[id^="finding-"]>figure svg{max-height:56mm}
.model-pair,.model-comparison,.finding-intro{break-inside:avoid}.model-pair:has(.model-photo),.model-pair.has-model{grid-template-columns:1fr 1fr}.model-pair svg,.model-photo{max-height:56mm;object-fit:contain}.actions,.disclaimer{break-inside:avoid}
.legend{font-size:8pt;margin:2mm 0;gap:1mm 3mm}figcaption,.note,.refs{font-size:8pt}.analysis{margin:4mm 0}.actions li{break-inside:avoid}.footer{padding:3mm 0 0;margin-top:4mm}a{text-decoration:none}
}
"""


def human_text(value, names):
    value = str(value)
    for identity in sorted(names, key=len, reverse=True):
        value = re.sub(
            r"(?<![A-Za-z0-9_:@-])" + re.escape(identity) + r"(?![A-Za-z0-9_:@-])",
            lambda _: names[identity],
            value,
        )
    return escape(value).replace("\n", "<br>")


def diagram(
    scene,
    room=None,
    highlights=(),
    paths=(),
    mode="top",
    object_ids=None,
    numbering=None,
    camera=None,
    size=None,
    show_legend=True,
    crop=None,
):
    """SVG uses source geometry; numerals resolve to a nearby human-readable legend."""
    names = display_names(scene)
    objects = [
        item
        for item in scene["objects"]
        if (room is None or room["id"] in item.get("roomIds", []))
        and (object_ids is None or item["id"] in object_ids)
    ]
    numbering = numbering or {item["id"]: i for i, item in enumerate(objects, 1)}
    polygons = []
    for current in scene["rooms"]:
        if room and current["id"] != room["id"]:
            continue
        if current.get("polygonXZ") and current.get("floorY") is not None:
            bottom = [[x, current["floorY"], z] for x, z in current["polygonXZ"]]
            polygons.append((bottom, "#e0e7da", None))
    for item in objects:
        index = numbering[item["id"]]
        box = item.get("box")
        if box:
            top = [
                world(
                    box,
                    [
                        x * box["size"][0] / 2,
                        box["size"][1] / 2,
                        z * box["size"][2] / 2,
                    ],
                )
                for x, z in [(-1, -1), (1, -1), (1, 1), (-1, 1)]
            ]
            if mode == "iso":
                bottom = [[x, y - box["size"][1], z] for x, y, z in top]
                for i, j in [(0, 1), (1, 2)]:
                    polygons.append(
                        (
                            [bottom[i], bottom[j], top[j], top[i]],
                            COLORS.get(item["type"], "#d4d7cf"),
                            None,
                        )
                    )
            polygons.append(
                (top, COLORS.get(item["type"], "#d4d7cf"), (index, item["id"]))
            )
        surface = item.get("surface")
        if surface:
            n = unit(surface["normal"])
            u = unit(cross(surface["up"], n))
            v = cross(n, u)
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
                (corners, COLORS.get(item["type"], "#d4d7cf"), (index, item["id"]))
            )

    def project(p):
        x, y, z = p
        return (
            (x, -z)
            if mode == "top"
            else ((x - z) * 0.7071, -y * 0.9 - (x + z) * 0.3536)
        )

    coordinates = [project(p) for polygon, _, _ in polygons for p in polygon] + [
        project(p) for start, end, _ in paths for p in [start, end]
    ]
    if not coordinates:
        return ""
    xs, ys = zip(*coordinates)
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    factor = min(540 / max(maxx - minx, 0.1), 285 / max(maxy - miny, 0.1))

    def point(p):
        x, y = project(p)
        return (
            (x - (minx + maxx) / 2) * factor + 310,
            (y - (miny + maxy) / 2) * factor + 185,
        )

    width, height = size if camera else (620, 370)
    project_polygon = lambda polygon: [point(p) for p in polygon]
    if camera:
        project_polygon, point = camera_projector(camera, width, height)

    parts = []
    labels = []
    labeled = set()
    for polygon, color, identity in polygons:
        pts = project_polygon(polygon)
        if len(pts) < 3:
            continue
        coords = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
        active = identity and identity[1] in highlights
        parts.append(
            f'<polygon points="{coords}" fill="{color}" stroke="{"#a45536" if active else "#7e9587"}" stroke-width="{2.5 if active else 1}" fill-opacity=".8"/>'
        )
        if identity and identity[1] not in labeled:
            labeled.add(identity[1])
            x = sum(p[0] for p in pts) / len(pts)
            y = sum(p[1] for p in pts) / len(pts)
            labels.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{width * 12 / 620:.2f}" fill="#fff" stroke="#516f5e"/><text x="{x:.2f}" y="{y + width * 4 / 620:.2f}" text-anchor="middle" font-size="{width * 12 / 620:.2f}" fill="#233b34">{identity[0]}</text>'
            )
    for start, end, kind in paths:
        a, b = point(start), point(end)
        if a is None or b is None:
            continue
        dash = ' stroke-dasharray="7 5"' if kind == "geometry" else ""
        parts.append(
            f'<path d="M{a[0]:.2f},{a[1]:.2f} L{b[0]:.2f},{b[1]:.2f}" fill="none" stroke="{"#a36130" if kind == "geometry" else "#2a7398"}" stroke-width="2.5"{dash}/>'
        )
        if kind != "geometry":
            angle = math.atan2(b[1] - a[1], b[0] - a[0])
            for delta in [-0.45, 0.45]:
                endx, endy = (
                    b[0] - 9 * math.cos(angle + delta),
                    b[1] - 9 * math.sin(angle + delta),
                )
                parts.append(
                    f'<path d="M{b[0]:.2f},{b[1]:.2f} L{endx:.2f},{endy:.2f}" stroke="#2a7398" stroke-width="2.5"/>'
                )
    title = (names[room["id"]] + " · " if room else "") + (
        "平面位置" if mode == "top" else "空间关系"
    )
    legend = "".join(
        f"<li>{numbering[item['id']]} · {escape(names[item['id']])}</li>"
        for item in objects
        if item.get("box") or item.get("surface")
    )
    legend_html = f'<ul class="legend">{legend}</ul>' if show_legend else ""
    view_box = (
        f"{crop[0]} {crop[1]} {crop[2] - crop[0]} {crop[3] - crop[1]}"
        if crop
        else f"0 0 {width} {height}"
    )
    return f'<figure><svg xmlns="http://www.w3.org/2000/svg" viewBox="{view_box}" role="img" aria-label="{escape(title, quote=True)}"><title>{escape(title)}</title>{"".join(parts + labels)}</svg><figcaption>{escape(title)}</figcaption>{legend_html}</figure>'


def group_notes(notes):
    """Keep related machine findings behind one authored conclusion and diagram."""
    groups = {}
    for index, (note, item) in enumerate(notes):
        key = note.get("group") or ("individual", index)
        if key not in groups:
            groups[key] = (dict(note), {**item, "relatedFindings": [item]})
            continue
        merged, finding = groups[key]
        finding["relatedFindings"].append(item)
        for field in ["objectIds", "evidenceRefs", "improvements"]:
            merged[field] = list(dict.fromkeys([*merged[field], *note[field]]))
        for field in ["analysis", "practicalImpact"]:
            merged[field] = "\n".join(dict.fromkeys([merged[field], note[field]]))
        if ["high", "medium", "low"].index(note["priority"]) < [
            "high",
            "medium",
            "low",
        ].index(merged["priority"]):
            merged["priority"] = note["priority"]
    return list(groups.values())


def photo(image, names, selected, numbering, title, model=False, crop=None):
    from PIL import Image, ImageDraw, ImageFont

    with Image.open(image.get("originalFile", image["file"])) as original:
        picture = original.convert("RGB")
    if crop:
        picture = picture.crop(crop)
    width, height = picture.size
    draw = ImageDraw.Draw(picture)
    visible = []
    font = ImageFont.load_default(size=max(14, round(width / 50)))
    for point in image.get("projections", []):
        oid = point.get("id")
        if oid not in selected or oid not in numbering:
            continue
        x, y = (
            point["x"] - (crop[0] if crop else 0),
            point["y"] - (crop[1] if crop else 0),
        )
        if not 0 <= x < width or not 0 <= y < height:
            continue
        radius = max(10, width / 70)
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            fill="#20372e",
            outline="white",
            width=2,
        )
        draw.text((x, y), str(numbering[oid]), font=font, fill="white", anchor="mm")
        visible.append(oid)
    buffer = io.BytesIO()
    picture.save(buffer, format="PNG")
    data = base64.b64encode(buffer.getvalue()).decode()
    caption = "同视角 VR 模型态截图" if model else "对应空间实景截图"
    labels = "；".join(
        f"{numbering[oid]}：{names[oid]}" for oid in dict.fromkeys(visible)
    )
    if model:
        labels = ""
    anchor = "" if model else f' id="photo-{escape(image["figureId"], quote=True)}"'
    return f'<figure{anchor}><img class="{"model-photo" if model else "photo"}" width="{width}" height="{height}" src="data:image/png;base64,{data}" alt="{escape(title, quote=True)}"><figcaption>{escape(image["figureId"])} · {caption}{" · " + escape(labels) if labels else ""}</figcaption></figure>'


def paired_diagram(
    scene, images, selected, numbering, room=None, highlights=(), paths=(), draft=False
):
    image = matching_model_image(images, room, selected)
    if image is None and not draft:
        raise ValueError(
            "请先补拍同视角的 Mapview 模型态截图并保存真实相机矩阵，再生成正式报告"
        )
    names = display_names(scene)
    crop = paired_crop(scene, room, selected, image) if image else None
    shot = (
        photo(
            image,
            names,
            selected,
            numbering,
            "与关系图相同视角的 VR 模型",
            model=True,
            crop=crop,
        )
        if image
        else ""
    )
    geometry = diagram(
        scene,
        room,
        highlights,
        paths,
        mode="iso",
        object_ids=selected,
        numbering=numbering,
        camera=image["camera"] if image else None,
        size=(image["width"], image["height"]) if image else None,
        show_legend=False,
        crop=crop,
    )
    listed = [
        o
        for o in scene["objects"]
        if o["id"] in selected
        and (room is None or room["id"] in o.get("roomIds", []))
        and (o.get("box") or o.get("surface"))
    ]
    legend = "".join(
        f"<li>{numbering[o['id']]} · {escape(names[o['id']])}</li>" for o in listed
    )
    return f'<div class="model-comparison"><div class="model-pair{" has-model" if image else ""}">{geometry}{shot}</div><ul class="legend">{legend}</ul></div>'


CN_DIGITS = "零一二三四五六七八九"


def ordinal(index):
    """1 -> 一, 10 -> 十, 12 -> 十二, beyond 99 -> 阿拉伯数字。"""
    if index <= 0:
        return str(index)
    if index < 10:
        return CN_DIGITS[index]
    if index < 20:
        return "十" + (CN_DIGITS[index - 10] if index > 10 else "")
    if index < 100:
        return CN_DIGITS[index // 10] + "十" + (CN_DIGITS[index % 10] if index % 10 else "")
    return str(index)


def finding_label(index):
    return f"改进建议{ordinal(index)}"


def render_html(scene, findings, narrative, images, field, display_name, draft=False):
    names = display_names(scene)
    text = lambda value: human_text(value, names)
    excluded = excluded_rules(scene)
    known = {
        (item["ruleId"], tuple(sorted(item["objectIds"]))): item
        for item in findings["findings"]
    }
    notes = []
    for note in narrative["notes"]:
        item = known[(note["ruleId"], tuple(sorted(note["objectIds"])))]
        if item["ruleId"] in excluded or item["status"] == "unknown":
            if not draft:
                raise ValueError(
                    "解读包含未完成核实或已排除的项目，请先完成用户问答并重新整理结论"
                )
            continue
        notes.append((note, item))
    if not notes and not draft:
        raise ValueError("请先整理有依据的分析结果和建议；不能用空清单生成正式报告")
    for value in [narrative["summary"]] + [
        v
        for note, _ in notes
        for v in [note["analysis"], note["practicalImpact"], *note["improvements"]]
    ]:
        if not draft and any(
            term in value
            for term in ["输入待补", "缺少数据", "数据缺失", "待补齐", "无法判断"]
        ):
            raise ValueError("解读仍含未解决的缺项，请先询问用户或确认分析范围")
    priority = {"high": "优先改善", "medium": "建议调整", "low": "可选优化"}
    school_pairs = []
    for advice in narrative.get("schoolAdvice") or []:
        merged = {
            "ruleId": f"school-{advice['school']}",
            "objectIds": [],
            "title": advice["title"],
            "analysis": advice["analysis"],
            "practicalImpact": advice.get("practicalImpact", ""),
            "improvements": advice["improvements"],
            "evidenceRefs": advice["evidenceRefs"],
            "priority": advice.get("priority", "medium"),
            "school": advice["school"],
        }
        school_pairs.append(
            (
                merged,
                {
                    "ruleId": merged["ruleId"],
                    "objectIds": [],
                    "status": "limited",
                    "evidenceRefs": [],
                    "measurements": {},
                    "relatedFindings": [],
                },
            )
        )
    ordered = sorted(
        group_notes(notes) + school_pairs,
        key=lambda pair: ["high", "medium", "low"].index(pair[0]["priority"]),
    )
    focus = focus_objects(
        scene,
        [note for note, _ in notes],
        narrative.get("focusObjectIds", []),
        findings["findings"],
    )
    if not draft and any(
        obj["id"] in focus
        and obj["type"] == "other"
        and (
            not obj.get("name")
            or re.fullmatch(r".*(?:的物品|其他物品)\d*", obj["name"])
        )
        for obj in scene["objects"]
    ):
        raise ValueError(
            "影响结论的重点物品尚未明确命名，请先核对身份和位置，不要在报告中使用泛称物品"
        )
    numbering = {
        obj["id"]: i
        for i, obj in enumerate(
            [obj for obj in scene["objects"] if obj["id"] in focus], 1
        )
    }
    links = [
        '<a href="#overview">总览</a>',
        '<a href="#space">空间图解</a>',
    ]
    links += [
        f'<a href="#finding-{i}">{finding_label(i)}</a>'
        for i, (note, _) in enumerate(ordered, 1)
    ]
    hero_notice = (
        '<p class="preview">合成场景 · 版式预览，不是实际空间分析结论</p>'
        if draft
        else ""
    )
    parts = [
        f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; object-src 'none'"><meta name="referrer" content="no-referrer"><title>{text(display_name)} · 空间风水分析</title><style>{CSS}</style></head><body><a class="skip" href="#main">跳到分析正文</a><div class="wrap"><header class="masthead"><span class="brand">空间格局 · 风水分析</span><span class="meta">{datetime.now().strftime("%Y.%m.%d")} · HTML 审阅版</span></header><div class="hero"><div class="eyebrow">空间布局与改善建议</div><h1>{text(display_name)}</h1><p class="lead">从实际空间出发，看清布局关系，找到值得改善的位置。</p>{hero_notice}</div><div class="layout"><nav class="toc" aria-label="报告目录">{"".join(links)}</nav><main id="main"><section class="section" id="overview"><h2>总览</h2><p class="lead">{text(narrative["summary"])}</p><h3>改善重点</h3><ol class="priorities">"""
    ]
    for index, (note, _) in enumerate(ordered, 1):
        title = note.get("title") or "、".join(names[oid] for oid in note["objectIds"])
        parts.append(
            f'<li><a href="#finding-{index}"><strong>{text(title)}</strong></a> <span class="tag {"high" if note["priority"] == "high" else ""}">{priority[note["priority"]]}</span><p>{text(note["improvements"][0])} <a class="more" href="#finding-{index}">查看详情👇</a></p></li>'
        )
    parts.append(
        '</ol></section><section class="section" id="space"><h2>空间图解</h2><p class="lead">以下按房间列出空间关系图与同视角模型截图，编号与后文各条建议一一对应。</p>'
    )
    report_rooms = (
        set().union(*(note_rooms(scene, note) for note, _ in notes)) if notes else set()
    )
    for room in scene["rooms"]:
        if room["id"] not in report_rooms:
            continue
        selected = {
            oid
            for oid in focus
            if room["id"]
            in next(o for o in scene["objects"] if o["id"] == oid).get("roomIds", [])
        }
        if not selected:
            continue
        parts.append(
            f"<h3>{text(names[room['id']])}</h3>{diagram(scene, room, object_ids=selected, numbering=numbering, show_legend=False)}{paired_diagram(scene, images, selected, numbering, room=room, draft=draft)}"
        )
    parts.append("</section>")
    used_images = set()
    for i, (note, item) in enumerate(ordered, 1):
        ids = set(note["objectIds"])
        title = note.get("title") or RULE_NAMES.get(note["ruleId"], "布局分析")
        where = (
            '<p class="location">依据：确认的坐向与宅卦</p>'
            if note.get("school")
            else f'<p class="location">位置：{text("、".join(names[oid] for oid in note["objectIds"]))}</p>'
        )
        parts.append(
            f'<section class="section" id="finding-{i}"><div class="finding-intro"><span class="tag">{priority[note["priority"]]}</span><h2>{finding_label(i)}</h2><p class="finding-title"><strong>{text(title)}</strong></p>{where}<div class="analysis"><h3>分析结论</h3><p>{text(note["analysis"])}</p><h3>对日常使用的影响</h3><p>{text(note["practicalImpact"])}</p></div></div>'
        )
        refs = []
        for image in images:
            if image["context"].get("mode") == "Mapview":
                continue
            if image["figureId"] not in note["evidenceRefs"]:
                continue
            fig = image["figureId"]
            if fig not in used_images:
                parts.append(photo(image, names, focus, numbering, title))
                used_images.add(fig)
            else:
                refs.append(
                    f'<a href="#photo-{escape(fig, quote=True)}">查看对应实景图 {escape(fig)}</a>'
                )
        if refs:
            parts.append('<p class="refs">' + " · ".join(refs) + "</p>")
        paths = []
        for related in item["relatedFindings"]:
            metrics = related["measurements"]
            if metrics.get("reflectionPoint"):
                start = metrics.get("observerPoint") or metrics.get("reviewPoint")
                end = metrics.get("targetPoint") or metrics.get("reviewPoint")
                if start and end:
                    paths += [
                        (start, metrics["reflectionPoint"], "geometry"),
                        (metrics["reflectionPoint"], end, "geometry"),
                    ]
            if related["ruleId"] == "ENV-OPENINGS":
                by_id = {o["id"]: o for o in scene["objects"]}
                for pair in metrics.get("openingPairs", []):
                    a, b = [
                        by_id[oid]["surface"]["center"] for oid in pair["openingIds"]
                    ]
                    paths.append((a, b, "geometry"))
        if item["ruleId"].startswith("ENV-") and field:
            for vector in field["vectors"]:
                if vector["roomId"] in ids:
                    paths.append(
                        (
                            vector["position"],
                            add(vector["position"], scale(vector["velocityMps"], 0.4)),
                            "velocity",
                        )
                    )
        selected = (
            focus_objects(scene, [note], findings=item["relatedFindings"]) & focus
        )
        rooms = note_rooms(scene, note)
        room = (
            next((room for room in scene["rooms"] if room["id"] in rooms), None)
            if len(rooms) == 1
            else None
        )
        parts.append(
            paired_diagram(
                scene,
                images,
                selected,
                numbering,
                room=room,
                highlights=ids,
                paths=paths,
                draft=draft,
            )
        )
        if paths:
            parts.append(
                '<p class="note">蓝色箭头依据本次实测或模拟气流数据绘制。</p>'
                if field and item["ruleId"].startswith("ENV-")
                else '<p class="note">虚线表示几何关系'
                + (
                    "，用于解释门窗之间的空间路径。"
                    if item["ruleId"].startswith("ENV-")
                    else "。"
                )
                + "</p>"
            )
        parts.append(
            '<h3>改善建议</h3><ol class="actions">'
            + "".join(f"<li>{text(v)}</li>" for v in note["improvements"])
            + "</ol></section>"
        )
    scope_names = list(
        dict.fromkeys(RULE_NAMES.get(note["ruleId"], "空间布局") for note, _ in notes)
    )
    parts.append(
        f'<p class="note">本次分析范围：{text("、".join(scope_names))}。<br>分析方法：{text("、".join(narrative["methods"]))}。</p><aside class="disclaimer" aria-label="免责声明"><strong>免责声明</strong><p>{escape(DISCLAIMER)}</p></aside></main></div><footer class="footer">报告同时保留 HTML 阅读版与 PDF 存档版，内容以同一份分析结论为准。</footer></div></body></html>'
    )
    return "".join(parts)


def create_html(
    session_path, context, output, draft=False, airflow=None, interpretation_path=None
):
    from report import read_images, interpretation, airflow_field

    state = checked_session(session_path, context)
    require_current_analysis(state)
    directory = Path(session_path).resolve().parent
    scene, _ = load(state["scenePath"])
    findings, report_sha = load(state["reportPath"])
    validate(scene)
    actual, source_sha = load(state["analysisPath"])
    if (
        source_sha != state.get("analysisSha256")
        or actual.get("resourceCode") != scene["resourceCode"]
        or findings.get("sceneFingerprint") != fingerprint(scene)
        or findings.get("resourceCode") != scene["resourceCode"]
    ):
        raise ValueError("报告数据已变化或属于其他空间，请重新分析")
    ready = readiness(scene, findings)
    if not ready["ready"] and not draft:
        state.update(status="awaiting_user_input", questions=ready["questions"])
        atomic_json(session_path, state)
        atomic_json(directory / "consultation.json", ready)
        raise ValueError(
            "请先向用户询问 consultation.json 中的问题，回填后重跑 assess；暂不生成报告"
        )
    images, gaps = read_images(directory, state, scene, draft)
    filtered = {
        **findings,
        "findings": [
            item
            for item in findings["findings"]
            if item["ruleId"] not in excluded_rules(scene)
        ],
    }
    required = {
        oid
        for item in filtered["findings"]
        if item["status"] == "candidate"
        for oid in item["objectIds"]
    }
    if (
        required - {oid for image in images for oid in image.get("objectIds", [])}
        and not draft
    ):
        raise ValueError("请先补拍关键分析对象的实景截图")
    narrative = interpretation(interpretation_path, scene, filtered, images, draft)
    field = airflow_field(airflow, scene)
    mode = scene.get("reportScope", {}).get("airflowMode")
    if (
        mode in {"measured", "simulated"}
        and (not field or field["basis"] != mode)
        and not draft
    ):
        raise ValueError(
            "请先提供用户选择的实测或模拟气流场及工况，或请用户确认只做几何通风分析"
        )
    if field and mode == "geometry":
        raise ValueError("当前用户确认的是几何通风分析，请先确认范围再使用实际气流场")
    destination = Path(output).resolve()
    if destination.suffix.lower() not in {
        ".html",
        ".htm",
    } or not destination.is_relative_to(directory):
        raise ValueError("HTML 报告须保存在本次任务目录中，使用 .html 扩展名")
    content = render_html(
        scene,
        filtered,
        narrative,
        images,
        field,
        state["request"]["context"]["displayName"],
        draft,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    from analyze import write_output

    write_output(
        destination,
        content,
        [
            session_path,
            state["scenePath"],
            state["reportPath"],
            state["analysisPath"],
            *([interpretation_path] if interpretation_path else []),
        ],
    )
    manifest = {
        "schema": "spatial-fengshui.report",
        "version": 1,
        "format": "html",
        "requestSha256": state["requestSha256"],
        "analysisSha256": source_sha,
        "analysisAttemptId": state.get("analysisAttemptId"),
        "sceneFingerprint": fingerprint(scene),
        "reportSha256": report_sha,
        "html": str(destination),
        "htmlSha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "status": "draft" if draft else "ready_for_review",
        "visualReviewStatus": "pending",
        "userConfirmationStatus": "pending",
        "screenshots": len(images),
        "interpretationSha256": hashlib.sha256(
            Path(interpretation_path).read_bytes()
        ).hexdigest()
        if interpretation_path
        else None,
        "interpretationPath": str(Path(interpretation_path).resolve())
        if interpretation_path
        else None,
    }
    previous_path = directory / "report-manifest.json"
    if previous_path.is_file():
        previous, _ = load(previous_path)
        if previous.get("requestSha256") == state["requestSha256"]:
            registered = (
                {"pdf": previous["pdf"], "pdfSha256": previous.get("pdfSha256")}
                if previous.get("pdf")
                else previous.get("previousPdf")
            )
            if registered:
                manifest["previousPdf"] = registered
    atomic_json(previous_path, manifest)
    state.update(
        status="report_draft" if draft else "html_generated", htmlPath=str(destination)
    )
    state.pop("reportConfirmation", None)
    for field in ["pdfPath", "pdfAuthorization", "pdfVisualReviewPath"]:
        state.pop(field, None)
    atomic_json(session_path, state)
    return manifest
