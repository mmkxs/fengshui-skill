# 完整空间解析与双版本交付

这是本 Skill 重点推荐的交付路径：读取当前实景空间、完整解析、逐项确认、截图取证，最后生成带实景截图与空间关系图的 HTML + PDF。用户提出风水或格局分析请求而未提供完整空间结果时，先向用户说明这条路径的增益并询问是否开始；用户选择轻量分析时再按降级路径继续。

本文件描述的桥接、BFF 与截图流程适用于已接入相应实景空间应用的环境。没有可访问空间、或用户选择暂不做完整解析时，可通过 `analyze.py --scene` 或 `--analysis` 走降级路径；降级结果须在报告标题或摘要中注明「未基于完整空间解析」。

## 用户入口与确认

典型请求为“分析这个空间的格局风水，看看有什么需要改善的”。使用 Agent 已连接浏览器的当前页面，读取 `window.__VR_SPATIAL_CONTEXT__.read()`。其中资源码、页面会话与就绪状态是本次目标。没有已连接的目标页时，先请用户打开该空间的 VR 页面或提供页面 URL；用户暂不便提供时，可按现有户型图/描述继续并标注依据等级。多个候选页面时先确认目标页面，不能从新建空白浏览器猜测用户正在看的 VR。

旧工程可通过新版 CLI 的 `upgrade` 获取桥接模块。已登记的原版 App 会备份迁移，定制 App 需按现有运行时接入 `publishAgentContext` 并保留生命周期清理。桥接不可用时，先从当前页 URL 与已就绪的 Work 标识确认空间，再处理截图接入，不能根据服务端最后访问记录选择其他用户的空间。

读取当前页元数据后，把上下文 JSON 保存到任务工作区。此时只创建授权请求，尚未执行素材获取、解析或截图。

部分 Viewer 仍返回旧版前缀的上下文；读取时会自动转换成中立契约，不需要手工改 schema。

工程内先判断数据来源：`python scripts/project_context.py --project . --resource-code <RC>` 返回 `reuse-full`、`rerun-full` 或 `run-full`。除 `reuse-full` 外都按完整档执行，不降档；复用前仍要确认近期是否改动过家具或装修。

```bash
python "<skill-dir>/scripts/workflow.py" plan \
  --project "<当前工程>" --context "<当前浏览器上下文.json>"
```

用户提出风水、堪舆或同类格局分析诉求时，向用户展示返回的 `question`，默认文案如下。

> 可以。为了结合实际空间分析风水格局，需要先完整解析当前 VR，了解朝向、房间布局、主要物品的位置和通风条件，再给出图解结论与改善建议。是否授权开始完整解析？

等待用户明确回复。原始分析请求只触发该确认，不能自行替用户批准。用户同意这条明确的完整档请求后，本次已同时确认 full 档，无需重复发起精简/完整选档问题。完整档缺数据时报告缺项，继续沿用空间 Skill 的补数据与单独计费授权规则。

将用户回复原文和本次 requestSha256 记录在同一会话。

```bash
python "<skill-dir>/scripts/workflow.py" authorize \
  --session "<返回的session.json>" --context "<最新浏览器上下文.json>" \
  --request-sha256 "<返回的请求哈希>" \
  --decision approve --user-reply "<用户明确同意的原文>"
```

拒绝时使用 `--decision deny` 并停止后续步骤。切换到其他 VR 或授权范围变化后重新确认。当前任务的同一 VR 重载页面时，读取新 generation 并重新绑定点位，沿用已取得的本次授权。

## 调用空间理解 Skill

授权后调用完整链路。工作区、资源码和文件路径由助手从会话与项目推导，用户只需确认授权和实际缺失信息。

```bash
python "<skill-dir>/scripts/workflow.py" run \
  --session "<session.json>" --context "<最新浏览器上下文.json>" \
  --python "<已发现的 Python 3.12 解释器>"
```

该入口调用同级空间 Skill，经项目 BFF 获取当前 Work 快照，保存到本次任务 inputs 中，随后使用 `pipeline.py all --inputs full --no-apply --yes`。初次明确授权已覆盖本机必要素材、依赖和权重下载，付费 API 提交另行确认。仅为报告解析数据时使用 no-apply，保留当前应用的开发范围。

当前应用使用浏览器登录态或访问 Cookie、导致本机脚本无法直接请求 BFF 时，授权后可在同一页面通过同源 fetch 获取 Work。前后核对资源码与 generation，保存 `spatial-fengshui.browser-snapshot`，字段包括 context、requestSha256 与 envelope，再用 `workflow.py run --browser-work <快照文件>`。URL 固定为该页面同源 `/api/work/<当前资源码>`，保留原有服务端鉴权。不能导出浏览器凭据或改请求到其他空间。

pipeline 的输入哈希、缓存键与决定记录继续生效。完整档失败、推理未执行或结果未导出时停在 needs_data，不能继续套用旧结果生成“完整空间报告”。需要付费补数据时，按空间 Skill 的计划、确认计费与任务续查流程完成素材获取，再重跑本入口。

同一会话重跑时会先撤销旧解析、截图与交付的有效标记，并生成新的 analysisAttemptId。历史文件不删除，但失败、待补数据或只返回计划的尝试不能继续 assess、确认旧 HTML 或导出 PDF；本次完整解析成功后才能恢复后续流程。

解析完成后生成本次 `scene.json`、`fengshui-analysis.json` 和 `capture-plan.json`。逐房间核查完整范围，镜面法向、梁体、门窗开合、真实朝向等缺项由助手依据全景、模型或用户的现场信息补标注，保留来源。

```bash
python "<skill-dir>/scripts/workflow.py" assess \
  --session "<session.json>" --context "<最新浏览器上下文.json>" \
  --annotations "<与本次analysisSha256绑定的标注.json>"
```

## 确认空间类型、房间用途与物品身份

生成 `scene.json` 后、下任何风水结论前，先按顺序把下面几类问清楚。检测标签（bed、sofa、desk 等）只是候选身份，不是事实；`spaceType` 与房间 `function` 默认 unknown。本地 Viewer 工程内先用 `python scripts/labels.py --scene scene.json --out labels.json` 生成编号标签，让用户在 VR 里对着编号回答，不要用坐标轴或平面图让人描述方位（接入方式与坑见 vr-confirmation.md）。其余情况逐条提问并等待明确回复：

1. 整个空间是什么类型？办公室 / 住宅 / 商场 / 工厂 / 其他（`spaceType`）。
2. 每个房间的用途：`room-1（示例卧室）` 实际是卧室 / 客厅 / 办公 / 厨房 / 卫浴 / 走廊 / 其他？
3. 每个停留区物品：`bed-1`（检测为床，可信度 high）实际是什么？
4. 依据缺失项：读取本次 `fengshui-analysis.json` 的 `consultation.questions`，合并同类问题后向用户提问并等待明确回复。其中坐向/朝向、入户门、层高、门窗开合等无法从模型直接推导的，直接请用户给出，不要只标记缺失。

把用户回复写成补充标注，绑定本次 analysisSha256，再重跑 assess：

```json
{
  "schema": "spatial-fengshui.annotations",
  "version": 1,
  "resourceCode": "<RC>",
  "analysisSha256": "<本次哈希>",
  "spaceType": "residential",
  "reportScope": {"schools": ["form", "luopan"], "airflowMode": "geometry", "evidenceRef": "用户确认：本次仅分析形势坐向和通风路径，不做实际风速判断"},
  "compass": {
    "facingDegrees": 180,
    "northBasis": "magnetic",
    "uncertaintyDegrees": 2,
    "evidenceRef": "用户确认：坐北朝南"
  },
  "roomUpdates": [
    {"id": "room-1", "function": "bedroom", "ceilingHeightM": 2.8, "evidenceRefs": ["用户确认：主卧，净高 2.8m"]}
  ],
  "objectUpdates": [
    {"id": "bed-1", "type": "bed", "name": "卧室靠墙双人床", "identityConfirmed": true, "identityEvidenceRef": "用户确认：双人床", "confidence": "high", "evidenceRefs": ["用户确认：双人床"]}
  ]
}
```

空间类型未确认或非住宅/办公时，床、桌、沙发等住宅式布局判断不套用；用户未确认的物品保持 unknown，不能把检测标签当已确认身份写进解读或建议。缺失依据在用户补充前保持缺失，不静默用默认值。

## 对应截图

每次截图前重新读取当前 VR 上下文，检查资源码与 generation。把本次授权 requestSha256 作为截图请求绑定信息。它是本地任务关联标识，浏览器桥接不替代应用本身的访问鉴权。

先用 capture-plan 中的分析文件哈希和全部点位位置绑定当前 Five Work。容差与空间结果消费层一致，为 1 cm。

自动化标签页被遮挡或最小化时 `document.visibilityState === 'hidden'`，`requestAnimationFrame` 暂停，`view`/`capture` 会一直等待。此时不要依赖用户切到前台，改用无头取证：`node scripts/vr_capture.mjs --url ... --scene ... --capture-plan ... --views ... --model ... --request-sha256 ... --out ...`，它会自动扫角、把锚点抬到物品顶面，并直接写出可导入的 `spatial-fengshui.vr-capture`。

```javascript
const bridge = window.__VR_SPATIAL_CONTEXT__;
const permit = {
  resourceCode: context.resourceCode,
  generation: context.generation,
  requestSha256: session.requestSha256
};
bridge.bind(permit, capturePlan.analysisSha256, capturePlan.observers);
```

按房间入口和物品 bestPanoIndex 切换视角。longitude、latitude 使用弧度，fov 使用角度。优先用对象的可见 anchor，按实际投影核对对象是否在画面内，必要时换角度或点位。手工添加的梁、镜面等可根据已核对的几何选择可见表面点。

```javascript
await bridge.view(permit, { panoIndex: view.panoIndex, longitude: 0, latitude: 0 });
const captured = await bridge.capture(permit, view.points);
```

截图采用 Five 原生 getPixels，保留当前画面与相机姿态。结果为 PNG data URL 和可见投影点，交由浏览器工具直接保存为 JSON，再导入本次任务。使用 agent-browser 时可将 `eval --json` 的输出重定向到文件，导入器支持其 success/data/result 包装。避免把大段图像 data URL 打印到对话中。截图计划中的物品不等于在当前截图中已经可见。

```bash
python "<skill-dir>/scripts/evidence.py" \
  --session "<session.json>" --context "<最新浏览器上下文.json>" \
  --capture "<浏览器导出的capture.json>" --room "<实际房间ID>"
```

导入时保存原图、带标注图与相机记录，核对资源、授权、分析哈希、点位绑定和图片哈希。全景实景需对应房间内点位；Mapview 模型态截图可登记其相机视锥实际覆盖的房间。已有叠加层与本次结果不符时，先隐藏无关层再截图。截图开始前保存 bridge.read()，结束时可用 bridge.restore(permit, originalSnapshot) 在同一 Work 和页面会话仍有效时恢复原视角。

## 模型态截图与同视角关系图

每个报告涉及的房间都补拍 Mapview 模型态。使用 capture-plan.modelViews 的建议姿态，再根据画面微调，确保重点区域完整可见。解读完成后只向 capture 传入关键物品点，避免对全部检测对象编号。

```javascript
const original = bridge.read();
await bridge.modelView(permit, modelView.state);
const modelCapture = await bridge.capture(permit, modelView.points);
```

将结果保存 JSON，继续用 evidence.py --capture ... --room ... 导入。相机 projectionMatrix 和 viewMatrix 由原生 Five 相机在截图时自动读取，不手工编造矩阵。导入器保存并校验相机元数据；HTML 用这些矩阵计算关系图，画幅、投影与模型截图相同。原图保留完整模型，只精简关系图中的无关检测框。截图后恢复 original。旧截图只有经纬角时不能证明同视角，需用新版桥接补拍。

正式报告遇到缺少相应模型截图会暂停生成，助手补拍后再继续；不把缺图提示写入交付正文。模型截图与关系图并排，移动端上下排列；共用一份编号和关键物品图例。

## 形成完整结论与改善建议

Agent 结合本次空间结果、逐项截图与传统参考，写出解释和可操作的改善建议，不能只复述几何检查清单。区分传统解释、日常使用影响、计算事实和待核实事项，注明采用的流派。

保存 `spatial-fengshui.interpretation` version 1，包含 resourceCode、sceneFingerprint、summary、methods 和 notes；可通过 focusObjectIds 显式补充正文涉及的关键物品。每条 note 对应现有 ruleId + objectIds，可提供 title（读者可懂的结论标题）和 group（同一改善主题的分组），包含 analysis（传统分析）、practicalImpact（实际空间影响）、improvements（建议列表）、priority（high/medium/low）与 evidenceRefs。证据引用使用本次截图 E1/E2 等编号或实际几何 evidenceRefs。每个布局候选须有对应解读及建议。同一镜子的多条反射关系等相关项目使用同一个 group，合并为一段结论、一组建议与一张关系图，不按机器对象对重复堆页。

缺少宅运、坐向、镜面方向或空气工况时，在生成前先向用户询问并等待答复，不能在最终报告里罗列缺项。用户确认不分析某项时，将 ruleId、reason 和 evidenceRef 写入 reportScope.excludedRules；仅分析明确约定的范围。流派选择记录在 reportScope.schools 中，不将未选择的流派写成“缺少输入”。涉及具体搬动位置时，用场景几何核对新位置的门扇、通道、梁体和镜面关系，方案图注明为改善设想。

## 生成 HTML 报告

最终交付 HTML 与 PDF 两个文件。`report.py` 先生成 HTML，复核通过后由浏览器打印同一份 HTML 生成 PDF，保留截图、图解与结论，不调用旧的逐项校验表 PDF 模板。

```bash
python "<skill-dir>/scripts/report.py" \
  --session "<session.json>" --context "<最新浏览器上下文.json>" \
  --interpretation "<Agent整理的本次解读.json>" \
  --output "<本次任务目录>/空间格局风水分析.html"
```

生成前重新检查 consultation。还有影响结论的未知项时，入口保存 consultation.json，状态为 awaiting_user_input，不生成正式 HTML。助手先从空间素材补齐能识别的数据，剩余信息用截图和自然语言位置向用户提问；回填后运行 assess。不得删除 unknown 结果或擅自改 reportScope 绕过缺项。

HTML 只包含总体判断、优先建议、空间图解、对应实景、各项分析结论与可执行改善建议。所有解读应指明房间和具体位置，解释为什么需要调整、怎么调整；没有问题的关系可简洁说明维持现状。使用 title 为建议命名，正文用“入口右侧镜子”“窗边书桌”等可辨识称呼。脚本将已知内部对象 ID 转为自然语言名称，但 Agent 仍须检查指代与截图对应。

对象编号、校验状态、候选计数、逐对关系矩阵、坐标、哈希、原始测量表、授权回执和缺项清单保留在内部 JSON，不展示给读者。只在理解结论所需时，直接用自然语言解释尺寸或距离，不堆数字。

截图或关键证据不足时正式生成拒绝通过。--draft 仅用于合成版式预览，不作为真实空间结论。解读只写已完成核实、且在约定范围内的项目；每个改善关注点须有对应截图与解读，重复截图通过图号互相引用。

## 空气流动的可视化

默认绘制开口、层高、障碍物和开口之间的几何路径。没有真实风速与流向数据时，以虚线和“几何示意”标识，保留真实气流未知状态。

已有可信测量或模拟结果时，通过 `--airflow-field` 提供 `spatial-fengshui.airflow-field` version 1。字段包括 resourceCode、sceneFingerprint、basis（measured/simulated）、method、evidenceRef、boundaryConditions，以及 vectors 中每项的 roomId、position 和 velocityMps。单位为米和 m/s，坐标与本次场景相同。

矢量图只显示提供的数据，注明实测/模拟、工况、算法与抽样。真实 CFD 需要相应求解器和经过验证的边界条件，本工具目前负责接收、绑定和展示其结果。层高或平面图本身不足以确定实际空气流动。

## HTML 视觉复核与用户确认

用浏览器打开生成的 HTML，检查桌面和手机宽度下的中文、截图、图例、导航与布局，保存对应截图。网页内容应能直接读懂，不能出现未知项清单或内部对象编号。

复核记录使用 spatial-fengshui.html-visual-review，包含 htmlSha256、textCheckPassed、layoutPassed 与 screenshots。每张截图记录 viewport（desktop/mobile）、相对任务目录的 path 和文件 sha256。使用 workflow.py finalize --session ... --context ... --review ... 核对，状态进入 awaiting_report_confirmation。

用户明确要求先审阅时，先交给用户并等待回复；已授权双版本交付时，完成复核后继续生成 PDF。用户确认 HTML 的原始回复可用 workflow.py confirm-report --session ... --context ... --html-sha256 ... --user-reply ... 记录。内容修改后重新生成和复核两个版本，旧确认和旧 PDF 不代表新版本通过。

报告清单同时绑定解析尝试、解读文件的绝对路径和 SHA256。解读内容修改后，原 HTML 的复核、确认和 PDF 导出均被拒绝，须重新生成并复核。升级前的旧清单若没有解读来源绑定，也需用原始 interpretation 文件重新生成 HTML；原报告文件仍可阅读，不会自动删除。

## 从同一 HTML 导出 PDF

使用已有 agent-browser（Chrome 打印）与 pypdf；未安装该 CLI 时会自动回退到自带的无头打印脚本（需要本机 Node.js 与 Chrome）。HTML 自带 A4 打印样式。PDF 不重新组织文字，也不从原始 JSON 再生成另一套内容。

```bash
python "<skill-dir>/scripts/workflow.py" export-pdf \
  --session "<session.json>" --context "<最新浏览器上下文.json>" \
  --output "<本次任务目录>/空间格局风水分析.pdf"
```

浏览器命令不在 PATH 时，用 --browser-executable 指定 agent-browser 或设置 AGENT_BROWSER_BIN。旧任务仅授权 HTML 时，附 --user-reply 记录用户本次要求保留 PDF 的原话；已授权双版本的任务不重复提问。合成预览仅可用 --draft 导出，并保留示例标记。

导出使用独立浏览器会话，等待字体和图片加载，打印后关闭自身会话。清单同时保留 html、htmlSha256、pdf、pdfSha256 和 pdfSourceHtmlSha256，HTML 原文件保持原样。

用 Poppler 或 PyMuPDF 将 PDF 每页渲染为图片，逐页检查中文、图片、页边距和断页，并用 pypdf 核对正文。复核记录使用 spatial-fengshui.pdf-visual-review，包含 pdfSha256、textCheckPassed、layoutPassed 与全部 pages（page、相对任务目录的 path、图片 sha256）。再调用 workflow.py finalize --session ... --context ... --review ...，双版本通过后交付两个文件。HTML 和 PDF 的视觉复核状态分别保留，合成草稿仍保持 report_draft。
