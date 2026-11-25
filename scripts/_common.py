#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_common.py —— fengshui-kanyu（风水堪舆）脚本共用底座 · 确定性计算的**唯一权威来源**。

本模块把风水中所有「可机算、不容目测」的常量与算法固化于此，供各 CLI 脚本调用：
  · 后天八卦 / 洛书九宫 方位表
  · 二十四山：度数分界、所属卦宫、三元龙（地/天/人元）、玄空阴阳（阳顺阴逆）
  · 玄空飞星引擎 fly()（洛书顺飞/逆飞）与 flying_stars()（运/山/向三盘 + 到山到向判定）
  · 三元九运：公历日期 → 运（以**立春**为年界，借 vendored lunar-python）
  · 八宅游年：由宅卦（或命卦）翻卦 → 八方九星（生气/天医/延年/伏位/祸害/六煞/五鬼/绝命）
  · 命卦：出生年 + 性别 → 命卦（立春调整；下卦法，兼向替卦不在此实现）

设计约束（对齐 .claude/rules/common/coding-style.md 与 python/coding-style.md）：
  · 纯函数、返回新对象、不原地修改入参；无 I/O 副作用（fail() 主动退出除外）。
  · 显式失败、不静默吞错。统一退出码与 stdout error JSON 契约（见下）。

错误约定（与 zhanshi-jixiong/bazi 脚本一致，便于 LLM 调用方解析）：
  退出码 0 成功 · 2 参数格式错 · 3 超出支持范围 · 4 依赖缺失 · 5 运行期失败(网络等)
  失败时 stdout 打印 {"error": "..."}，stderr 打印人读信息。

风水非科学预测。本模块只产出**可核验的术数事实**（何山何向、几运、飞星盘、游年方位），
不下吉凶结论——吉凶研判由 SKILL.md 结合 references 完成。
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import date
from typing import NoReturn

# ---------------------------------------------------------------- vendor 注入

_VENDOR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")

EXIT_OK = 0
EXIT_BAD_ARGS = 2
EXIT_OUT_OF_RANGE = 3
EXIT_MISSING_DEP = 4
EXIT_RUNTIME = 5

# lunar-python 覆盖区间（用于立春年界）。三元九运本身可外推，但立春日期依赖此表。
MIN_YEAR = 1901
MAX_YEAR = 2099


def fail(message: str, code: int) -> NoReturn:
    """显式失败：stdout 出结构化 error JSON，stderr 出人读信息，非 0 退出。绝不静默。"""
    print(json.dumps({"error": message}, ensure_ascii=False))
    print(message, file=sys.stderr)
    sys.exit(code)


def load_solar():
    """导入 vendored lunar-python 的 Solar。缺失即显式失败，不静默降级。"""
    if _VENDOR_DIR not in sys.path:
        sys.path.insert(0, _VENDOR_DIR)
    try:
        from lunar_python import Solar  # noqa: WPS433 (vendor 注入需运行时导入)
    except ImportError as exc:
        fail(
            f"vendored lunar-python 缺失或损坏（{exc}）。应存在于 {_VENDOR_DIR}/lunar_python/",
            EXIT_MISSING_DEP,
        )
    return Solar


# ---------------------------------------------------------------- 五行 / 生克

# 五行生克：SHENG[a]=a 所生；KE[a]=a 所克
WUXING_SHENG = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
WUXING_KE = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}
WUXING_COLOR = {"木": "青绿", "火": "赤红", "土": "黄褐", "金": "白/金", "水": "黑蓝"}


def wuxing_relation(subject: str, obj: str) -> str:
    """subject 对 obj 的五行关系：比和/生/被生/克/被克/无关。纯函数。"""
    if subject == obj:
        return "比和"
    if WUXING_SHENG.get(subject) == obj:
        return "生"
    if WUXING_SHENG.get(obj) == subject:
        return "被生"
    if WUXING_KE.get(subject) == obj:
        return "克"
    if WUXING_KE.get(obj) == subject:
        return "被克"
    return "无关"


# ---------------------------------------------------------------- 后天八卦 / 洛书九宫

# 后天（文王）八卦方位与洛书数。中五无方位。
PALACE_LUOSHU = {"坎": 1, "坤": 2, "震": 3, "巽": 4, "中": 5, "乾": 6, "兑": 7, "艮": 8, "离": 9}
LUOSHU_PALACE = {v: k for k, v in PALACE_LUOSHU.items()}
PALACE_DIR = {
    "坎": "北", "坤": "西南", "震": "东", "巽": "东南", "中": "中",
    "乾": "西北", "兑": "西", "艮": "东北", "离": "南",
}
DIR_PALACE = {v: k for k, v in PALACE_DIR.items()}
PALACE_WUXING = {
    "坎": "水", "坤": "土", "震": "木", "巽": "木", "中": "土",
    "乾": "金", "兑": "金", "艮": "土", "离": "火",
}
# 八卦三爻（下,中,上），1=阳 0=阴。翻卦用。
TRIGRAM_LINES = {
    "乾": (1, 1, 1), "兑": (1, 1, 0), "离": (1, 0, 1), "震": (1, 0, 0),
    "巽": (0, 1, 1), "坎": (0, 1, 0), "艮": (0, 0, 1), "坤": (0, 0, 0),
}
LINES_TRIGRAM = {v: k for k, v in TRIGRAM_LINES.items()}
TRIGRAM_SYMBOL = {
    "乾": "☰", "兑": "☱", "离": "☲", "震": "☳",
    "巽": "☴", "坎": "☵", "艮": "☶", "坤": "☷",
}

# 八卦洛书数（同 PALACE_LUOSHU，去中五），供命卦/宅卦与飞星互查
GUA_LUOSHU = {k: v for k, v in PALACE_LUOSHU.items() if k != "中"}

# 东西四宅/命：东四（坎离震巽），西四（乾坤艮兑）
EAST_GROUP = frozenset({"坎", "离", "震", "巽"})
WEST_GROUP = frozenset({"乾", "坤", "艮", "兑"})


def gua_group(gua: str) -> str:
    """卦属东四/西四。"""
    if gua in EAST_GROUP:
        return "东四"
    if gua in WEST_GROUP:
        return "西四"
    return "未知"


# ---------------------------------------------------------------- 二十四山

# 每山中心度数（正北=0/360，顺时针）。每山占 15°，界为中心±7.5°。
# 按卦宫成组，组内按度数升序即「地元→天元→人元」。
MOUNTAIN_CENTER = {
    "壬": 345, "子": 0, "癸": 15,          # 坎宫（北）
    "丑": 30, "艮": 45, "寅": 60,          # 艮宫（东北）
    "甲": 75, "卯": 90, "乙": 105,         # 震宫（东）
    "辰": 120, "巽": 135, "巳": 150,       # 巽宫（东南）
    "丙": 165, "午": 180, "丁": 195,       # 离宫（南）
    "未": 210, "坤": 225, "申": 240,       # 坤宫（西南）
    "庚": 255, "酉": 270, "辛": 285,       # 兑宫（西）
    "戌": 300, "乾": 315, "亥": 330,       # 乾宫（西北）
}
MOUNTAIN_PALACE = {
    "壬": "坎", "子": "坎", "癸": "坎",
    "丑": "艮", "艮": "艮", "寅": "艮",
    "甲": "震", "卯": "震", "乙": "震",
    "辰": "巽", "巽": "巽", "巳": "巽",
    "丙": "离", "午": "离", "丁": "离",
    "未": "坤", "坤": "坤", "申": "坤",
    "庚": "兑", "酉": "兑", "辛": "兑",
    "戌": "乾", "乾": "乾", "亥": "乾",
}
# 三元龙：天元龙（子午卯酉·乾坤艮巽），人元龙（寅申巳亥·乙辛丁癸），地元龙（辰戌丑未·甲庚丙壬）
MOUNTAIN_YUAN = {
    "壬": "地元", "子": "天元", "癸": "人元",
    "丑": "地元", "艮": "天元", "寅": "人元",
    "甲": "地元", "卯": "天元", "乙": "人元",
    "辰": "地元", "巽": "天元", "巳": "人元",
    "丙": "地元", "午": "天元", "丁": "人元",
    "未": "地元", "坤": "天元", "申": "人元",
    "庚": "地元", "酉": "天元", "辛": "人元",
    "戌": "地元", "乾": "天元", "亥": "人元",
}
# 玄空二十四山阴阳（阳顺阴逆之据）。自洽校验：阳12阴12。
# 阳：地元四阳干(甲庚丙壬) + 天元四阳卦(乾坤艮巽) + 人元四阳支(寅申巳亥)
# 阴：天元四正支(子午卯酉) + 人元四阴干(乙辛丁癸) + 地元四库支(辰戌丑未)
_YANG_MOUNTAINS = frozenset("甲庚丙壬乾坤艮巽寅申巳亥")
MOUNTAIN_YINYANG = {m: ("阳" if m in _YANG_MOUNTAINS else "阴") for m in MOUNTAIN_CENTER}

# (卦宫, 三元龙) → 该宫内对应元龙之山。玄空定向盘/山盘阴阳时用。
PALACE_YUAN_MOUNTAIN = {(MOUNTAIN_PALACE[m], MOUNTAIN_YUAN[m]): m for m in MOUNTAIN_CENTER}

MOUNTAIN_ORDER = sorted(MOUNTAIN_CENTER, key=lambda m: (MOUNTAIN_CENTER[m] % 360))


def normalize_deg(deg: float) -> float:
    """度数归一到 [0, 360)。纯函数。"""
    return deg % 360.0


def mountain_of_bearing(deg: float):
    """
    方位角（度）→ 所在山。返回 (山, 卦宫, 三元龙, 阴阳, 距山中心的偏差度)。纯函数。
    子山跨 352.5–360 与 0–7.5，用中心距处理环绕，无需特判。
    非有限度数（nan/inf）会使全部角差比较失败而返回 best=None，故在此显式拒绝（防御性，防未来调用路径绕过 parse_bearing_arg）。
    """
    if not math.isfinite(deg):
        raise ValueError(f"方位角须为有限数字，收到 {deg}")
    d = normalize_deg(deg)
    best, best_gap = None, 999.0
    for m, c in MOUNTAIN_CENTER.items():
        gap = abs(((d - c + 180) % 360) - 180)   # 环绕最小角差
        if gap < best_gap:
            best, best_gap = m, gap
    return {
        "mountain": best,
        "palace": MOUNTAIN_PALACE[best],
        "direction": PALACE_DIR[MOUNTAIN_PALACE[best]],
        "yuan": MOUNTAIN_YUAN[best],
        "yinyang": MOUNTAIN_YINYANG[best],
        "center_deg": MOUNTAIN_CENTER[best],
        "offset_deg": round(((d - MOUNTAIN_CENTER[best] + 180) % 360) - 180, 2),
    }


# 兼向阈值：偏离山中心 >阈值 即入「兼向」，传统改用替卦（本模块只做下卦，超阈显式告警）
JIANXIANG_THRESHOLD_DEG = 4.5


# ---------------------------------------------------------------- 玄空飞星引擎

def fly(center: int, sense: str) -> dict:
    """
    洛书飞星：给定入中之数与顺/逆，返回 {卦宫: 数}。纯函数。

    顺飞（阳）：中→乾→兑→艮→离→坎→坤→震→巽，数递增（9 后回 1）。
    逆飞（阴）：同一宫序，数递减。
    以「宫的洛书数 p 与中五之差」为步长实现，等价于沿洛书轨迹逐宫 ±1。
    """
    if center not in range(1, 10):
        raise ValueError(f"入中之数须为 1–9，收到 {center}")
    if sense not in ("顺", "逆"):
        raise ValueError(f"sense 须为 顺/逆，收到 {sense!r}")
    out = {}
    for palace, p in PALACE_LUOSHU.items():
        step = (p - 5) % 9
        if sense == "顺":
            v = (center - 1 + step) % 9 + 1
        else:
            v = (center - 1 - step) % 9 + 1
        out[palace] = v
    return out


def _sense_for(center_num: int, ref_yuan: str, ref_mountain: str) -> dict:
    """
    定山盘/向盘的顺逆。返回 {sense, basis}。纯函数。
    规则：入中之数 N 所对应「本宫」（洛书数=N 之宫）内、与坐/向同三元龙之山，其阴阳定顺逆。
    N==5 无本宫，从坐/向本山之阴阳（下卦法通用处理）。
    """
    if center_num == 5:
        yy = MOUNTAIN_YINYANG[ref_mountain]
        return {"sense": "顺" if yy == "阳" else "逆",
                "basis": f"入中为5（无本宫），从本山{ref_mountain}({yy})",
                "ref_mountain": ref_mountain, "yinyang": yy}
    origin_palace = LUOSHU_PALACE[center_num]
    m = PALACE_YUAN_MOUNTAIN[(origin_palace, ref_yuan)]
    yy = MOUNTAIN_YINYANG[m]
    return {"sense": "顺" if yy == "阳" else "逆",
            "basis": f"入中{center_num}居{origin_palace}宫，取{ref_yuan}之{m}({yy})",
            "ref_mountain": m, "yinyang": yy}


def flying_stars(yun: int, sit_mountain: str) -> dict:
    """
    玄空飞星下卦排盘。返回运盘/山盘/向盘三盘、各宫三星、及到山到向判定。纯函数。

    sit_mountain：坐山（二十四山之一）。向 = 坐 +180°。
    """
    if yun not in range(1, 10):
        raise ValueError(f"运须为 1–9，收到 {yun}")
    if sit_mountain not in MOUNTAIN_CENTER:
        raise ValueError(f"未知坐山：{sit_mountain}")

    face_deg = normalize_deg(MOUNTAIN_CENTER[sit_mountain] + 180)
    face = mountain_of_bearing(face_deg)
    face_mountain = face["mountain"]
    sit_palace = MOUNTAIN_PALACE[sit_mountain]
    face_palace = MOUNTAIN_PALACE[face_mountain]

    base = fly(yun, "顺")                       # 运盘：运星入中顺飞
    shan_center = base[sit_palace]              # 山星入中之数 = 运盘坐宫数
    xiang_center = base[face_palace]            # 向星入中之数 = 运盘向宫数

    shan_sense = _sense_for(shan_center, MOUNTAIN_YUAN[sit_mountain], sit_mountain)
    xiang_sense = _sense_for(xiang_center, MOUNTAIN_YUAN[face_mountain], face_mountain)

    shan = fly(shan_center, shan_sense["sense"])
    xiang = fly(xiang_center, xiang_sense["sense"])

    grid = {
        palace: {
            "yun": base[palace], "shan": shan[palace], "xiang": xiang[palace],
            "direction": PALACE_DIR[palace],
        }
        for palace in PALACE_LUOSHU
    }

    # 到山到向判定：当运星(=yun) 在山盘/向盘各落何宫
    def where(chart):
        return [p for p, v in chart.items() if v == yun]
    shan_wang = where(shan)[0]
    xiang_wang = where(xiang)[0]
    verdict = _daoshan_daoxiang(shan_wang, xiang_wang, sit_palace, face_palace)

    return {
        "yun": yun,
        "sit": {"mountain": sit_mountain, "palace": sit_palace,
                "direction": PALACE_DIR[sit_palace], "yuan": MOUNTAIN_YUAN[sit_mountain],
                "yinyang": MOUNTAIN_YINYANG[sit_mountain]},
        "facing": {"mountain": face_mountain, "palace": face_palace,
                   "direction": PALACE_DIR[face_palace], "yuan": MOUNTAIN_YUAN[face_mountain],
                   "yinyang": MOUNTAIN_YINYANG[face_mountain]},
        "shan_center": shan_center, "shan_sense": shan_sense,
        "xiang_center": xiang_center, "xiang_sense": xiang_sense,
        "yun_chart": base, "shan_chart": shan, "xiang_chart": xiang,
        "grid": grid,
        "wang_shan_palace": shan_wang, "wang_xiang_palace": xiang_wang,
        "pattern": verdict,
    }


def _daoshan_daoxiang(shan_wang: str, xiang_wang: str, sit_palace: str, face_palace: str) -> dict:
    """当运山星、向星落宫 → 旺山旺向/上山下水/双星到向/到坐 判定。纯函数。"""
    shan_at_sit = shan_wang == sit_palace
    shan_at_face = shan_wang == face_palace
    xiang_at_sit = xiang_wang == sit_palace
    xiang_at_face = xiang_wang == face_palace
    if shan_at_sit and xiang_at_face:
        name, note = "旺山旺向（到山到向）", "山管人丁向管财，丁财两旺之局；然仍需峦头山水配合。"
    elif shan_at_face and xiang_at_sit:
        name, note = "上山下水", "山星下水、向星上山，损丁破财之嫌；须坐后有水、向前有山方可扭转。"
    elif shan_at_face and xiang_at_face:
        name, note = "双星到向", "山向当运星俱到向方，旺财；向首宜见水，坐后见山则丁星另需城门/水照。"
    elif shan_at_sit and xiang_at_sit:
        name, note = "双星到坐", "山向当运星俱到坐方，旺丁；坐后宜见水，向前见山则财星另需布置。"
    else:
        name, note = "其他格局", "非四大标准格局，须逐宫细断（如反伏吟、令星入囚等）。"
    return {"name": name, "note": note,
            "wang_shan_at": PALACE_DIR[shan_wang], "wang_xiang_at": PALACE_DIR[xiang_wang]}


# ---------------------------------------------------------------- 三元九运

# 一运始于 1864（上元甲子）。每运 20 年，一元三运，三元九运共 180 年，循环往复。
SANYUAN_CYCLE_START = 1864
SANYUAN_CYCLE_LEN = 180
YUN_LEN = 20
YUAN_OF_YUN = {1: "上元", 2: "上元", 3: "上元", 4: "中元", 5: "中元", 6: "中元",
               7: "下元", 8: "下元", 9: "下元"}


def lichun_year(d: date) -> int:
    """
    d 所属「立春年」：早于当年立春者归上一年。借 vendored lunar-python 的节气表。纯读取，无副作用。
    三元九运/命卦均以立春为年界，故须此调整而非直接取公历年。
    """
    Solar = load_solar()
    lunar = Solar.fromYmd(d.year, d.month, d.day).getLunar()
    lichun_str = lunar.getJieQiTable().get("立春")   # 'YYYY-MM-DD'
    if not lichun_str:
        # 立春缺失是数据异常，不静默：退回公历年并留痕由调用方决定
        return d.year
    ly, lm, ld = (int(x) for x in str(lichun_str).split(" ")[0].split("-"))
    return d.year if d >= date(ly, lm, ld) else d.year - 1


def sanyuan_yun(d: date) -> dict:
    """公历日期 → 三元九运。以立春为年界。返回新 dict。纯函数（除读节气表）。"""
    y = lichun_year(d)
    offset = (y - SANYUAN_CYCLE_START) % SANYUAN_CYCLE_LEN
    yun = offset // YUN_LEN + 1
    cycle_base = y - offset
    yun_start = cycle_base + (yun - 1) * YUN_LEN
    return {
        "date": d.isoformat(),
        "lichun_year": y,
        "yun": yun,
        "yuan": YUAN_OF_YUN[yun],
        "yun_start_year": yun_start,
        "yun_end_year": yun_start + YUN_LEN - 1,
        "note": "运界以立春为准；生于公历年初、立春前者归上一年之运。",
    }


# ---------------------------------------------------------------- 八宅游年

# 游年翻卦：自伏位（宅/命卦）起，依次翻 上,中,下,中,上,中,下,中 爻，
# 得八卦分居八方，配九星（自洽：八翻后归伏位、八方各异）。1=阳 0=阴，(下,中,上)。
_YOUNIAN_FLIPS = (2, 1, 0, 1, 2, 1, 0, 1)   # 爻序号：0下 1中 2上
_YOUNIAN_STARS = ("生气", "五鬼", "延年", "六煞", "祸害", "天医", "绝命", "伏位")
STAR_NATURE = {
    "生气": ("吉", "贪狼", "木"), "天医": ("吉", "巨门", "土"),
    "延年": ("吉", "武曲", "金"), "伏位": ("小吉", "辅弼", "木"),
    "祸害": ("凶", "禄存", "土"), "六煞": ("凶", "文曲", "水"),
    "五鬼": ("大凶", "廉贞", "火"), "绝命": ("大凶", "破军", "金"),
}


def younian(gua: str) -> dict:
    """
    八宅游年：由宅卦或命卦（八卦之一）翻卦，得八方九星。返回 {方位: {star, nature, ...}}。纯函数。
    """
    if gua not in TRIGRAM_LINES:
        raise ValueError(f"未知卦：{gua}")
    lines = list(TRIGRAM_LINES[gua])
    result = {}
    for flip_idx, star in zip(_YOUNIAN_FLIPS, _YOUNIAN_STARS):
        lines[flip_idx] ^= 1                     # 累进翻爻
        cur = LINES_TRIGRAM[tuple(lines)]
        nature, jiuxing, wx = STAR_NATURE[star]
        result[PALACE_DIR[cur]] = {
            "gua": cur, "star": star, "nature": nature,
            "jiuxing": jiuxing, "wuxing": wx,
        }
    return result   # 伏位一翻回本卦，占据宅卦本方


# ---------------------------------------------------------------- 命卦

def ming_gua(year: int, gender: str, d: date | None = None) -> dict:
    """
    出生年 + 性别 → 命卦（八宅东西四命）。返回新 dict。
    year 为公历年；若给 d（完整生日）则按立春调整年界。下卦法，男女各式，5 男寄坤、女寄艮。
    """
    if gender not in ("男", "女"):
        raise ValueError(f"gender 须为 男/女，收到 {gender!r}")
    y = lichun_year(d) if d is not None else year

    def digit_root(n: int) -> int:
        n = abs(n)
        while n > 9:
            n = sum(int(c) for c in str(n))
        return n or 9

    s = digit_root(y)
    if gender == "男":
        g = 11 - s
    else:
        g = 4 + s
    g = (g - 1) % 9 + 1          # 归入 1–9
    substituted = None
    if g == 5:
        g = 2 if gender == "男" else 8
        substituted = "坤" if gender == "男" else "艮"
    gua = LUOSHU_PALACE[g]
    # d 缺省时未做立春年界调整——须如实告警，否则立春前（约1月~2月初）出生者会得错误命卦
    note = ("命卦以立春为年界（生于立春前者按上一年）；5 男寄坤、女寄艮。" if d is not None else
            "⚠ 仅按公历年取命卦，未做立春年界调整；若生于 1 月~2 月初（立春前），"
            "请提供完整出生日期 YYYY-MM-DD 以校正。5 男寄坤、女寄艮。")
    return {
        "year": year, "lichun_year": y, "gender": gender,
        "gua": gua, "luoshu": g, "group": gua_group(gua),
        "substituted_from_5": substituted,
        "lichun_adjusted": d is not None,
        "note": note,
    }


# ---------------------------------------------------------------- CLI 帮助

def parse_date_arg(token: str) -> date:
    """'YYYY-MM-DD' → date。格式错或超范围即显式失败。"""
    try:
        parts = token.split("-")
        if len(parts) != 3:
            raise ValueError("需三段")
        y, m, dd = (int(p) for p in parts)
        parsed = date(y, m, dd)
    except (ValueError, TypeError) as exc:
        fail(f"日期格式应为 YYYY-MM-DD（例 2026-07-12），收到 {token!r}：{exc}", EXIT_BAD_ARGS)
    if not (MIN_YEAR <= parsed.year <= MAX_YEAR):
        fail(f"仅支持 {MIN_YEAR}–{MAX_YEAR} 年（立春年界依赖 vendored 节气表），收到 {parsed.year}",
             EXIT_OUT_OF_RANGE)
    return parsed


def parse_bearing_arg(token: str) -> float:
    """方位角字符串 → 度数 [0,360)。接受 '175' / '175.5'。格式错即显式失败。"""
    try:
        deg = float(token)
    except (ValueError, TypeError) as exc:
        fail(f"方位角应为 0–360 的数字（例 175），收到 {token!r}：{exc}", EXIT_BAD_ARGS)
    # inf/nan/1e400 能被 float() 接受，但 inf%360=nan 会让 mountain_of_bearing 全比较失败→KeyError:None。
    # 在边界拦下，兑现 EXIT_BAD_ARGS + error JSON 契约，不裸崩。
    if not math.isfinite(deg):
        fail(f"方位角须为有限数字（0–360），收到 {token!r}", EXIT_BAD_ARGS)
    return normalize_deg(deg)


def need_val(rest: list, i: int, flag: str) -> str:
    """
    取 rest[i+1]（flag 的参数值）；若 flag 为末位或其后无值，显式失败而非抛 IndexError。
    手写 argv 循环共用，保证「缺值的末位 flag」也走 EXIT_BAD_ARGS + error JSON 契约（不裸崩 rc=1）。
    """
    if i + 1 >= len(rest):
        fail(f"{flag} 需要一个参数值", EXIT_BAD_ARGS)
    return rest[i + 1]


def emit(payload: dict, human_text: str, want_json: bool) -> None:
    """统一输出：--json 只出 JSON；否则人读 + 末行 JSON。"""
    if want_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(human_text)
    print()
    print(json.dumps(payload, ensure_ascii=False))
