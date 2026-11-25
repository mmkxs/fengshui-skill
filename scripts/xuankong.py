#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
xuankong.py —— 玄空飞星下卦排盘：运 + 坐山 → 运盘/山盘/向盘三盘 + 到山到向格局。

用法（运可直接给，或由日期推）：
    python3 xuankong.py --sit 子 --yun 8
    python3 xuankong.py --sit 子 --date 2026-07-12          # 由建造/入住立向之运推当运
    python3 xuankong.py --facing 175 --yun 8 --json         # 由朝向反推坐山
    python3 xuankong.py --sitting 0 --yun 8

坐山可给二十四山名（--sit 子）或度数（--facing 向度 / --sitting 坐度，自动落山）。
输出「山运向」三星逐宫图（南上北下·洛书布局）与旺山旺向/上山下水/双星到向到坐判定。

限制：只做**下卦**。坐向入兼向（偏山中心 >4.5°）时输出仍为下卦盘，但标注"宜出替卦，此为近似"。
玄空非科学预测；本脚本只排盘出事实，吉凶化解由 SKILL.md 结合 references/liqi-xuankong.md 判读。
"""
import sys

import _common as C

# 南上北下·洛书布局（传统玄空盘）
_LAYOUT = [["巽", "离", "坤"], ["震", "中", "兑"], ["艮", "坎", "乾"]]


def _resolve_sit(sit_name, facing_deg, sitting_deg):
    """定坐山（二十四山名）。返回 (山名, jianxiang_note|None)。"""
    if sit_name is not None:
        if sit_name not in C.MOUNTAIN_CENTER:
            C.fail(f"未知坐山：{sit_name!r}（应为二十四山之一，如 子/壬/乾）", C.EXIT_BAD_ARGS)
        return sit_name, None
    if facing_deg is not None:
        node = C.mountain_of_bearing(facing_deg + 180)
    elif sitting_deg is not None:
        node = C.mountain_of_bearing(sitting_deg)
    else:
        C.fail("须给 --sit <山> 或 --facing <向度> 或 --sitting <坐度>", C.EXIT_BAD_ARGS)
    note = None
    if abs(node["offset_deg"]) > C.JIANXIANG_THRESHOLD_DEG:
        note = (f"坐山落{node['mountain']}但偏中心 {node['offset_deg']}°，入兼向；"
                f"下列为下卦盘，兼向传统宜出替卦，仅供近似参考。")
    return node["mountain"], note


def _cell(grid, palace):
    g = grid[palace]
    if palace == "中":
        return f" 中宫 {g['shan']}·{g['yun']}·{g['xiang']} "
    return f"{g['direction']}({palace}) {g['shan']}·{g['yun']}·{g['xiang']}"


def human(o: dict) -> str:
    fs = o["flying"]
    grid = fs["grid"]
    lines = [
        f"排盘: {fs['yun']}运 {fs['sit']['mountain']}山{fs['facing']['mountain']}向"
        f"（坐{fs['sit']['direction']} 向{fs['facing']['direction']}）",
        f"山星入中 {fs['shan_center']}（{fs['shan_sense']['sense']}飞 · {fs['shan_sense']['basis']}）；"
        f"向星入中 {fs['xiang_center']}（{fs['xiang_sense']['sense']}飞 · {fs['xiang_sense']['basis']}）",
        "",
        "三星逐宫（每格 山星·运星·向星，南上北下）：",
    ]
    for row in _LAYOUT:
        lines.append("   " + " | ".join(f"{_cell(grid, p):<20}" for p in row))
    lines += [
        "",
        f"格局: {fs['pattern']['name']}　当运山星到{fs['pattern']['wang_shan_at']}、"
        f"当运向星到{fs['pattern']['wang_xiang_at']}",
        f"　{fs['pattern']['note']}",
    ]
    if o.get("jianxiang_note"):
        lines.append(f"⚠ {o['jianxiang_note']}")
    if o.get("yun_source") == "date":
        lines.append(f"（运由日期 {o['date']} 推得：{o['yun_detail']['yuan']}{fs['yun']}运；"
                     f"若你知立向/建造之元运，请直接 --yun 指定。）")
    lines.append("　山管人丁向管财，然一切理气须以峦头（真实山水形势）为体、理气为用，勿舍形言理。")
    return "\n".join(lines)


def main(argv) -> int:
    want_json = "--json" in argv
    sit_name = facing = sitting = yun = date_str = None
    rest = argv[1:]
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--json":
            i += 1
        elif a == "--sit":
            sit_name = C.need_val(rest, i, "--sit"); i += 2
        elif a == "--facing":
            facing = C.parse_bearing_arg(C.need_val(rest, i, "--facing")); i += 2
        elif a == "--sitting":
            sitting = C.parse_bearing_arg(C.need_val(rest, i, "--sitting")); i += 2
        elif a == "--yun":
            tok = C.need_val(rest, i, "--yun")
            try:
                yun = int(tok)
            except ValueError:
                C.fail(f"--yun 须为 1–9 的整数，收到 {tok!r}", C.EXIT_BAD_ARGS)
            i += 2
        elif a == "--date":
            date_str = C.need_val(rest, i, "--date"); i += 2
        else:
            i += 1

    sit_mountain, jian_note = _resolve_sit(sit_name, facing, sitting)

    yun_source = "explicit"
    yun_detail = None
    if yun is None:
        if date_str is None:
            C.fail("须给 --yun <1-9> 或 --date <YYYY-MM-DD>（由日期推当运）", C.EXIT_BAD_ARGS)
        yun_detail = C.sanyuan_yun(C.parse_date_arg(date_str))
        yun = yun_detail["yun"]
        yun_source = "date"
    if yun not in range(1, 10):
        C.fail(f"运须为 1–9，收到 {yun}", C.EXIT_OUT_OF_RANGE)

    fs = C.flying_stars(yun, sit_mountain)
    o = {
        "yun_source": yun_source,
        "date": date_str,
        "yun_detail": yun_detail,
        "jianxiang_note": jian_note,
        "flying": fs,
    }
    C.emit(o, human(o), want_json)
    return C.EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv))
