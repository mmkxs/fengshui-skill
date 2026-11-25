# 上游与来源

本 Skill 基于 [FengShui Master](https://github.com/JackieL233/fengshui-master) 的空间风水方法组织方式改造，增加空间关系计算、空间数据结果适配和通风证据。

复用版本为 `2666304c5cb4ac13091c8c1fcdd4e40c218b275a`。以下脚本保持上游原文，版权归 FengShui Master contributors，随附 [MIT 许可证](../LICENSE)。其他新增代码遵循同一许可证。

- `scripts/luopan.py`，SHA256 `bd3414b28a8ee2fba9f88573045d331c92a7132f0855c8a860f38c6f0bcd0cd0`。
- `scripts/minggua.py`，SHA256 `ffc23b2c7994d02642052f6402f0471e478697f59861153a5dbd6fd6ebcc3824`。
- `scripts/periods.py`，SHA256 `a2663bae66eeee5d8656b42cd6d620dd422cd29606bb510074298212a09234f9`。
- `scripts/flying_stars.py`，SHA256 `e426804ea08c6e2252fe7f825a37e47e43ba1a10733493bf828110eb16894bd9`。

参考资料按知识主题重写。上游知识框架涉及的流派范围广于现有计算脚本，实际实现状态以本 Skill 的计算输出和缺项记录为准。

## 玄空与八宅算法来源

玄空飞星下卦排盘与八宅游年等确定性算法复用自 [Know-your-fate / fengshui-kanyu](https://github.com/tf1993614/Know-your-fate/tree/main/.claude/skills/fengshui-kanyu)，复用版本 `1aa675597ee1405c9dea142bda0a3a9ed460ac99`，MIT 许可，版权归 Feng Tang 与命数天问 (Mingshu Tianwen) contributors。

- `scripts/_common.py`：二十四山、玄空飞星下卦排盘、三元九运（立春年界）、八宅游年、命卦的确定性算法底座。
- `scripts/xuankong.py`：玄空飞星下卦排盘 CLI，输出运/山/向三盘与旺山旺向、上山下水、双星到向/到坐格局；只做下卦，兼向显式告警。
- `scripts/bazhai.py`：八宅游年 CLI，由坐山定宅卦、翻卦得八方九星，可叠加命卦与命宅相配。

`scripts/vendor/lunar_python` 为 vendored [lunar-python](https://github.com/6tail/lunar-python)（MIT，Copyright (c) 2020 6tail），仅用于取立春节气日期作为三元九运与命卦的年界，覆盖 1901–2099 年。保持原文未改，许可见 `scripts/vendor/LICENSE-lunar-python`。

《阳宅三要》原文见 [references/classics/yangzhai-sanyao.md](classics/yangzhai-sanyao.md)，为公有领域古籍转录（provenance 见该文件头），用于门、主、灶与东四/西四宅、游年八宅的术语和规则溯源。本文本来源非善本，含转录者补充内容，已在该文件头逐条标注。

## 核验资料

- [《宅经》卷上](https://zh.wikisource.org/wiki/宅經/卷上)，传统宅法和方位术语的文本参照。
- [《葬书》](https://zh.wikisource.org/wiki/葬書)，形势、山水与围合概念的历史资料，应用到室内属于后续解释。
- [上游形势资料](https://github.com/JackieL233/fengshui-master/blob/2666304c5cb4ac13091c8c1fcdd4e40c218b275a/fengshui-master/references/forms-and-environment.md)，门、床、镜、梁等布局判断的改编参考。
- [上游玄空范围](https://github.com/JackieL233/fengshui-master/blob/2666304c5cb4ac13091c8c1fcdd4e40c218b275a/fengshui-master/references/xuan-kong-flying-stars.md)，明确基础洛书飞布与完整山向盘的区别。
- [ASHRAE Fundamentals 2025 第 16 章](https://handbook.ashrae.org/Handbooks/F25/SI/F25_Ch16/F25_Ch16_si.aspx)，风压、热浮力和开口阻力。
- [WHO 自然通风指南](https://iris.who.int/bitstream/handle/10665/44167/9789241547857_eng.pdf)，通风量、房间体积和换气次数的定义。本文仅引用定义，不把医疗建筑数值阈值迁移到住宅。
- [加拿大卫生部通风与室内环境](https://www.canada.ca/en/health-canada/services/publications/healthy-living/ventilation-indoor-environment.html)，室内外温差、风与开口条件对自然通风的影响。
