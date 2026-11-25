#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bazhai.py —— 八宅游年：宅坐 → 宅卦 + 八方九星；可选生年性别 → 命卦 + 命宅相配。

用法：
    python3 bazhai.py --sit 子                              # 坐北→坎宅，出八方游年
    python3 bazhai.py --facing 175 --json                   # 朝向反推坐→宅卦
    python3 bazhai.py --sit 子 --birth 1988 --gender 男     # 加命卦与命宅相配
    python3 bazhai.py --birth 1990-05-01 --gender 女        # 只算命卦（无宅坐）

宅卦以坐山所属后天卦定（坐北=坎宅、坐南=离宅…）。游年八星：
  四吉 生气(贪狼)·天医(巨门)·延年(武曲)·伏位(辅弼)；四凶 祸害·六煞·五鬼·绝命。
命卦以立春为年界（生于立春前按上一年）。八宅属传统文化参考，非科学预测。
"""
import sys

import _common as C

# 游年各星的现代空间用法建议（供判读，不下绝对吉凶）
STAR_USE = {
    "生气": "旺气位：宜大门、主卧、客厅、常用出入口",
    "天医": "健康位：宜主卧、病人房、厨房",
    "延年": "和谐位：宜主卧、办公位、餐厅",
    "伏位": "稳定位：宜书房、财位、静室",
    "祸害": "宜次要空间：储物、走道",
    "六煞": "宜卫浴、储物（泄其气）",
    "五鬼": "宜卫浴、储物、锅炉（镇之）",
    "绝命": "宜卫浴、储物、车库（避作主卧/灶）",
}


# 后天八卦宫的分界度数（每 45°，自 22.5° 起）。度数落在分界附近 → 东西四命敏感，宜复核。
_PALACE_BOUNDARIES = tuple(22.5 + 45 * i for i in range(8))   # 22.5,67.5,…,337.5
BAZHAI_BOUNDARY_WARN_DEG = 3.0


def _boundary_note(bearing):
    """坐山度数临近卦宫分界 → 复核提示；否则 None。纯函数。八宅东西四命随卦宫翻转，边界处测量极敏感。"""
    d = C.normalize_deg(bearing)
    gap = min(abs(((d - b + 180) % 360) - 180) for b in _PALACE_BOUNDARIES)
    if gap <= BAZHAI_BOUNDARY_WARN_DEG:
        return (f"⚠ 坐向 {d:.1f}° 距卦宫分界仅 {gap:.1f}°：极小的测量误差即会翻转宅卦东四/西四归属"
                f"（连带命宅相配与八方游年全变）——请用罗盘/指南针复核坐向后再断。")
    return None


def _resolve_zhai(sit_name, facing_deg, sitting_deg):
    """定宅卦（坐山所属后天卦）。返回 (宅卦, 坐山, note|None)；无坐向则 (None,None,None)。"""
    if sit_name is not None:
        if sit_name not in C.MOUNTAIN_CENTER:
            C.fail(f"未知坐山：{sit_name!r}", C.EXIT_BAD_ARGS)
        return C.MOUNTAIN_PALACE[sit_name], sit_name, None   # 明确给山名，无测量歧义
    if facing_deg is not None:
        sit_bearing = C.normalize_deg(facing_deg + 180)
    elif sitting_deg is not None:
        sit_bearing = C.normalize_deg(sitting_deg)
    else:
        return None, None, None
    node = C.mountain_of_bearing(sit_bearing)
    return node["palace"], node["mountain"], _boundary_note(sit_bearing)


def compute(zhai_gua, sit_mountain, birth, gender) -> dict:
    out = {"zhai_gua": None, "youxing": None, "ming": None, "match": None}
    if zhai_gua is not None:
        yx = C.younian(zhai_gua)
        out["zhai_gua"] = {
            "gua": zhai_gua, "sit_mountain": sit_mountain,
            "sit_direction": C.PALACE_DIR[zhai_gua], "group": C.gua_group(zhai_gua),
        }
        out["youxing"] = {
            direction: {**info, "use": STAR_USE[info["star"]]}
            for direction, info in yx.items()
        }
    if birth is not None:
        d = None
        year = birth
        if isinstance(birth, tuple):   # (year, date_obj)
            year, d = birth
        ming = C.ming_gua(year, gender, d)
        out["ming"] = ming
        if zhai_gua is not None:
            same = C.gua_group(zhai_gua) == ming["group"]
            out["match"] = {
                "compatible": same,
                "verdict": "命宅相配（同属" + ming["group"] + "）" if same
                           else f"命宅不配（命属{ming['group']}、宅属{C.gua_group(zhai_gua)}）",
                "note": "相配则以宅之四吉方为用；不配则重个人命卦吉方布局，或以化解、择吉方为主。",
            }
    return out


def human(o: dict) -> str:
    lines = []
    if o.get("zhai_note"):
        lines.append(o["zhai_note"])
    z = o["zhai_gua"]
    if z:
        lines.append(f"宅卦: {z['gua']}宅（坐{z['sit_direction']}"
                     + (f"·坐山{z['sit_mountain']}" if z["sit_mountain"] else "") + f"，{z['group']}宅）")
        lines.append("八方游年（方位 → 星·吉凶 → 现代用法）：")
        # 按吉凶排序展示
        order = ["生气", "天医", "延年", "伏位", "祸害", "六煞", "五鬼", "绝命"]
        by_star = {info["star"]: (d, info) for d, info in o["youxing"].items()}
        for star in order:
            if star in by_star:
                d, info = by_star[star]
                lines.append(f"  {d:<3}{info['gua']}宫  {info['star']}({info['jiuxing']}·{info['nature']})"
                             f"  {info['use']}")
    m = o["ming"]
    if m:
        lines.append(f"命卦: {m['gua']}命（洛书{m['luoshu']}，{m['group']}命，立春年{m['lichun_year']}）"
                     + (f"　[5{('男寄坤' if m['gender']=='男' else '女寄艮')}]" if m["substituted_from_5"] else ""))
        if not m.get("lichun_adjusted"):
            lines.append(m["note"])   # note 已自带「⚠」前缀，勿再叠加
    if o["match"]:
        lines.append(f"命宅相配: {o['match']['verdict']}——{o['match']['note']}")
    lines.append("　八宅为传统文化参考；现代应用重在“把主要活动放在采光通风好的空间、"
                 "把次要功能放到边角”，与游年吉凶多有暗合，勿因凶位而焦虑。")
    return "\n".join(lines)


def _parse_birth(token):
    """'1988' → 1988；'1988-05-01' → (1988, date)。"""
    if "-" in token:
        d = C.parse_date_arg(token)
        return (d.year, d)
    try:
        y = int(token)
    except ValueError:
        C.fail(f"--birth 须为年份或 YYYY-MM-DD，收到 {token!r}", C.EXIT_BAD_ARGS)
    if not (C.MIN_YEAR <= y <= C.MAX_YEAR):
        C.fail(f"生年仅支持 {C.MIN_YEAR}–{C.MAX_YEAR}，收到 {y}", C.EXIT_OUT_OF_RANGE)
    return y


def main(argv) -> int:
    want_json = "--json" in argv
    sit_name = facing = sitting = birth = gender = None
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
        elif a == "--birth":
            birth = _parse_birth(C.need_val(rest, i, "--birth")); i += 2
        elif a == "--gender":
            gender = C.need_val(rest, i, "--gender"); i += 2
        else:
            i += 1

    zhai_gua, sit_mountain, zhai_note = _resolve_zhai(sit_name, facing, sitting)
    if birth is not None and gender not in ("男", "女"):
        C.fail("给了 --birth 就须给 --gender 男/女（命卦男女异式）", C.EXIT_BAD_ARGS)
    if zhai_gua is None and birth is None:
        C.fail("至少须给 宅坐（--sit/--facing/--sitting）或 生年（--birth --gender）之一", C.EXIT_BAD_ARGS)

    o = compute(zhai_gua, sit_mountain, birth, gender)
    if zhai_note:
        o = {**o, "zhai_note": zhai_note}
    C.emit(o, human(o), want_json)
    return C.EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv))
