# 风水分析 Skill

把户型、物品和现场信息用于传统风水布局讨论的 Agent Skill。按用户关心的空间与流派逐项分析，结论绑定可复核的几何证据，缺项明确说明，不凭空补数据。

## 能力范围

- 几何核查：梁体与床、桌、沙发的水平投影与竖向净距；门洞对向关系；镜面反射路径；床头与座椅背靠距离；净层高与开口通风面积。
- 流派计算：八宅游年、玄空飞星下卦排盘（运/山/向三盘）、罗盘与二十四山、三元九运、命卦。
- 环境判断：层高与体积、对外开口、通风路径；有实测或模拟风量时可算 ACH。
- 输出形式：优先基于完整空间解析，交付带实景截图与空间关系图的 HTML 阅读版与 PDF 存档版；结构化 JSON 与 Markdown 作为分析核对产物，也可在用户选择轻量分析时单独交付。
- 缺项处理：数据能算的自己算，算不出的逐项向用户确认，未评估范围在报告中单独标明。
- 输入优先级：没有完整空间结果时，重点推荐并请求完整解析；用户选择轻量路径时可使用户型图/照片/描述，并在报告中标注依据等级。

## 明确不做

- 不输出灾祸、疾病、财运等必然性判断。
- 不构成投资、商业选址、医疗或法律建议。
- 不替代结构安全、燃气、消防、通风系统的专业测量与评估。

## 安装

这是一个 Agent Skill，入口为 [SKILL.md](SKILL.md)。把整个仓库放到 Agent 的 skills 目录下，目录名保持 `spatial-fengshui`：

```bash
git clone https://github.com/mmkxs/fengshui-skill.git \
  .agents/skills/spatial-fengshui
```

运行环境：Python 3.10+，仅使用标准库；玄空与八宅脚本附带 vendored lunar-python（MIT）。

## 关于空间信息

风水结论的准确性取决于对空间了解多深：只凭一句话或一张照片，只能得到方向性意见；拿到完整的房间划分、主要物品位置、层高、朝向和门窗条件，结论才能落到具体位置。

因此本 Skill 重点推荐先做**完整空间解析**，再出结论。收到分析请求时，如果还没有完整空间结果，Skill 会先说明完整解析能多得出哪些判断，并询问是否开始；用户选择轻量分析或环境不具备时，可按户型图/照片/描述继续，并在交付物中标注未基于空间解析。

可用输入按完整度从高到低：

1. 本 Skill 的场景 JSON（`spatial-fengshui.scene`）：房间、物品、开口与朝向齐全，结论最具体。字段见 [references/spatial-input.md](references/spatial-input.md)，`assets/example-scene.json` 是完整示例。
2. 外部空间解析结果：用 `--analysis` 导入，适配器做最小结构校验后转换为场景，完整约束仍由本 Skill 的校验器承担。
3. 户型图、照片或文字描述：在用户选择轻量分析或无法获取上述数据时使用，由 Agent 边问边补，报告中标注依据等级。

缺少某一层级的数据时，Skill 不会静默假装完整：缺失项会列出来逐项询问，未评估的范围在报告中单独标明。完整解析的接入、授权与计费遵循所用空间应用自己的规则，流程见 [references/current-vr-workflow.md](references/current-vr-workflow.md)。

## 快速开始

用示例场景跑一次分析：

```bash
python scripts/analyze.py --scene assets/example-scene.json --format markdown
```

导入外部空间解析结果：

```bash
python scripts/analyze.py \
  --analysis "path/to/external-space-analysis.json" \
  --annotations "path/to/annotations.json" \
  --format markdown \
  --output "path/to/fengshui-report.zh-CN.md"
```

独立的流派计算：

```bash
python scripts/xuankong.py --sit 子 --yun 8
python scripts/xuankong.py --facing 175 --date 2026-07-12
python scripts/bazhai.py --sit 子 --birth 1988 --gender 男
```

在本地 Viewer 工程内确认与取证的做法、以及已知的坑（后台标签页不渲染、标签默认只在全景可见、解读与排除规则的约束）见 [references/vr-confirmation.md](references/vr-confirmation.md)。

坐标约定、标注格式与输入分工见 [references/spatial-input.md](references/spatial-input.md)，缺失数据如何补见 [references/evidence-requirements.md](references/evidence-requirements.md)。

## 目录结构

```
SKILL.md                      Skill 入口与使用约束
references/                   流派、通风、输入格式、证据要求、古籍原文
scripts/analyze.py            主分析入口
scripts/workflow.py           完整空间解析的会话、授权与解析编排（需配套空间数据适配）
scripts/vr_capture.mjs        工程内无头取证（自动扫角，直接产出可导入截图）
scripts/project_context.py    判断工程内数据能否复用，默认建议完整档解析
scripts/labels.py             生成 VR 内编号确认标签
scripts/viewer_confirm.py     一条命令准备标签、入口与编号确认清单
scripts/agent_browser_shim.mjs 未装 agent-browser 时的 PDF 打印兜底
scripts/contracts.py          统一旧版与中立数据契约
scripts/report.py             HTML/PDF 图文报告
scripts/xuankong.py           玄空飞星下卦排盘
scripts/bazhai.py             八宅游年
scripts/luopan.py             罗盘与二十四山
scripts/flying_stars.py       洛书飞布
scripts/minggua.py            命卦
scripts/periods.py            三元九运
scripts/vendor/               vendored lunar-python（MIT）
assets/example-scene.json     合成示例场景
```

## 版权与出处

本项目以 MIT 许可证发布，完整条款见 [LICENSE](LICENSE)。版权归属：

- 新增的空间关系计算、空间数据适配与通风证据：FengShui Master contributors。
- 玄空飞星、八宅游年、命卦、三元九运算法：Feng Tang 与 命数天问（Mingshu Tianwen）contributors。
- `scripts/vendor/lunar_python`：6tail，MIT，许可见 [scripts/vendor/LICENSE-lunar-python](scripts/vendor/LICENSE-lunar-python)。

方法组织方式改编自 [FengShui Master](https://github.com/JackieL233/fengshui-master)，算法另参考 [Know-your-fate](https://github.com/tf1993614/Know-your-fate)。复用版本、文件清单与 SHA256 校验值见 [references/upstream.md](references/upstream.md)。《阳宅三要》为公有领域古籍转录，来源说明见该文件头部。

再分发时请保留 [LICENSE](LICENSE) 与本节的版权说明；修改后的版本请在 README 或 CHANGELOG 中注明。

## 免责声明

> 本系统基于传统风水文化及 VR 空间数据生成报告，仅用于空间格局分析、传统文化研究与娱乐参考，不构成现实人生、投资、商业选址等决策建议。

补充说明：

- 风水属于传统文化范畴，分析结论不具有科学必然性，不应作为居住、交易、装修或经营的唯一依据。
- 分析依赖输入数据的完整性。缺少实测朝向、层高、遮挡与开闭状态时，相关结论会标注为未评估或候选，请以现场核对为准。
- 涉及承重结构、燃气、电气、消防、通风系统的改动，须由具备资质的专业人员测量与施工。
- 使用者对依据本 Skill 输出做出的任何决定自行负责，作者与贡献者不承担由此产生的责任。

请勿在仓库或 Issue 中提交真实住宅的完整空间数据、门牌、联系方式等个人信息。分析产物默认写入 `analysis-output/`，已加入 `.gitignore`。
