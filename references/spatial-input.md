# 空间输入与补充标注

## 入口

`--scene` 是本 Skill 的输入契约，字段由本 Skill 校验。`assets/example-scene.json` 是可运行合成示例。

`--analysis` 可选，用于导入外部空间解析结果。适配器做最小结构校验并转换为场景，完整约束仍由本 Skill 的场景校验承担；缺少 `resourceCode`、`frame`、`overview.rooms`、`overview.doors` 或 `objects` 时会指出具体字段。

坐标采用米制局部坐标系，+Y 向上，平面为 XZ。OBB 用 yaw 表示绕 Y 轴的旋转，不能直接传入 Z-up 点云坐标。场景 frame 固定为下面的声明。

```json
{"name": "y-up-meters", "unit": "m", "up": "Y"}
```

## 场景字段

根字段包括 `schema: spatial-fengshui.scene`、`version: 1`、`resourceCode`、`frame`、`rooms`、`objects`。可选 `compass`、`settings`、`occlusionCoverage`、`spaceType` 、`reportScope` 和 `assumptions`。`spaceType` 取 residential/office/retail/factory/other/unknown，默认 unknown（未确认整个空间的类型），是比房间用途更上层的先决问题。

- 房间包含 `id`、`areaM2`，可选 `name`、`function`、`floorY`、`ceilingHeightM`、`confidence`、`evidenceRefs` 和 `ventilation`。`function` 取 bedroom/living/office/kitchen/bath/corridor/other/unknown，默认 unknown（未确认用途）。
- 物品包含 `id`、`type`、`roomIds`。支持 bed、desk、door、window、mirror、beam、column、wall、partition、cabinet、stove、sink、toilet、sofa、other。
- `box` 为 `center: [x,y,z]`、`size: [width,height,depth]`、`yawRad`，尺寸必须为正。缺少 OBB 时，上游 AABB 不自动升级为精确有向几何。
- `surface` 为 `center`、`normal`、`up`、`widthM`、`heightM`。镜面 normal 指向反射侧，门窗讨论室外气流时 normal 指向室外。平面支持倾斜法向，up 必须与 normal 非平行。
- `reviewPoint` 表示对应目标的审查点或门口眼位。缺省且有 box 时使用顶面中心代理点，结果显式标注。真实床上眼位和床垫顶面应分别核对。
- `headPoint` 与 `backDirection` 定义床头/靠背位置和朝后方向，不能直接用对称 OBB 的 yaw 猜测头尾。
- `exterior` 和 `openFraction` 描述开口的对外角色和可通几何面积比例，范围为 0–1。门洞连接到 null 房间时仍需确认是否对外。
- `occludes: true` 的物品才参与遮挡计算。把墙、隔断与遮挡家具按实际几何标注，保留门窗开口。当前遮挡查询只对这些几何盒生效。
- 物品可提供 `name`（自然语言位置名称）、`identityConfirmed`（布尔）与 `identityEvidenceRef`（用户确认来源）；身份确认独立于质量等级，true 时必须记录来源。
- `confidence` 为 high、medium、low 或 unknown。`evidenceRefs` 记录照片、点位、网格、测量或人工确认的引用。缺少引用时输出可信度保持 unknown。

床、桌、沙发等「停留区」结论不把检测标签当事实：先确认整个空间 `spaceType`（住宅/办公/商业/工厂），再确认其房间 `function` 已匹配（bed→bedroom，sofa→living/office，desk→office/bedroom）、且物品 identityConfirmed 为 true、identityEvidenceRef 已记录、confidence 不低于 medium 时，才作为布局候选计算；否则该条返回 unknown，并要求先确认空间类型、房间用途与物品身份。门、镜、梁、墙等几何不因用途门控。

`occlusionCoverage` 为 partial、reviewed 或 unknown，说明本次标注覆盖范围。即使标为 reviewed，查询仍受盒模型和输入误差限制。

## 补充现有空间结果

`--annotations` 使用下面的结构，资源码与哈希必须匹配本次文件。可用 Python 标准库 hashlib 或系统 SHA256 工具计算输入文件哈希。

```json
{
  "schema": "spatial-fengshui.annotations",
  "version": 1,
  "resourceCode": "YOUR_RESOURCE_CODE",
  "analysisSha256": "空间结果文件的实际 SHA256",
  "objectUpdates": [
    {
      "id": "已有镜子的 ID",
      "surface": {
        "center": [2, 1.2, 3.89],
        "normal": [0, 0, -1],
        "up": [0, 1, 0],
        "widthM": 1,
        "heightM": 1.4
      },
      "confidence": "medium",
      "evidenceRefs": ["对应全景与网格中的镜面人工复核"]
    }
  ],
  "roomUpdates": [],
  "objects": []
}
```

`objects` 是新增对象，不能复用已有 ID。`objectUpdates` 可补充几何、审查点、朝后方向、开口状态、房间归属、类型、name 与身份确认状态。`roomUpdates` 可补净高、地板高度、通风工况与房间用途 function。更新须有证据引用，原记录保存在对象的 baseline 中供核对。

空间结果的 door.position 是门洞地面位置，适配时会加上半高，优先采用已关联门洞 OBB 的中心。宽、高或 yaw 未知时不生成精确开口平面。推导的门洞法向标记 `normalBasis: two-sided`，确认其对外法向时请更新 surface。镜面、窗户的反射侧/对外法向，以及真实门窗状态继续由标注提供。

## 方位与流派上下文

```json
{
  "compass": {
    "facingDegrees": 180,
    "northBasis": "magnetic",
    "uncertaintyDegrees": 2,
    "houseKua": 1,
    "evidenceRef": "用户确认的坐向测量与宅卦口径"
  }
}
```

`northBasis` 支持 magnetic、true、grid、user-relative、unknown。前三种有可靠坐向输入时可做二十四山查询，测量误差与分界状态保留。上游 `frame.orientation` 的用户相对朝向不会自动填入房屋坐向。

选玄空时，`xuanKong` 保存建成/大修年份或运数、定运口径与排盘结果。给了 `year`（或 `yun`）且有可靠坐向时，脚本用 `xuankong.py` 的算法直接排下卦，不再重复问；坐山入兼向（偏山中心超 4.5°）时下卦不适用，需外部可信替卦结果，保存在 `chart`。

```json
{
  "xuanKong": {
    "basis": "build",
    "year": 2020,
    "yun": 8,
    "chartSource": "xuankong.py",
    "chart": {},
    "evidenceRef": "用户确认：2020 年建成"
  }
}
```

`basis` 取 build / renovation / moveIn / explicit。`year` 为 1901–2099 的整数年份，`yun` 为 1–9，`chartSource` 取 xuankong.py 或 external。填齐年份（或运数）与坐向后 `consultation.ready` 不再卡在玄空问题上。

`year: 2004.0` 等整数值年份按整数解释；`yun` 必须为真正的 1–9 整数，不接受布尔值或浮点数。现成宅盘 `chart` 须使用 xuankong.py 输出的完整格式：`yun` 为运数，`grid` 包含中、乾、兑、艮、离、坎、坤、震、巽九宫，每宫含 yun、shan、xiang 三个星数，各盘均为完整的 1–9 星序，中宫运星须与宅运一致。另须填写 chartSource 和 evidenceRef。空对象、残缺宅盘或无来源宅盘不会被标为已排盘。

已确认通向室内的门窗不要求室外法向，双面门洞可用于门与家具的几何关系判断。缺少平面范围时仍须补齐；已确认对外的开口需另行确认朝向室外的一侧，才能讨论对外通风路径。

## 输出与解释状态

输出 `spatial-fengshui.analysis` version 1。每条 finding 包括 ruleId、objectIds、measurements、evidenceRefs、confidence、missing、traditionalInterpretation 和 reviewAction。

- candidate 为待复核的布局关注点。
- observed 为在给定输入模型中算得的量或关系。
- not_observed 为本次指定几何关系未出现。
- occluded 为已标注几何盒遮挡指定线段。
- unknown 为缺少必要输入。
- limited 为有限工况或覆盖范围下的结果。

仅在提供有效流量时计算 ACH，单位为 h⁻¹，并保存 measured/simulated/scenario 来源。没有风量时保持 null。

对象较多时可添加 `--room <房间ID>`，按房间复核。跨房间遮挡与通风关系继续保留待评估。`notAssessed` 列出当前脚本尚未实现专用规则的物品，按传统参考与现场证据继续分析。

## 报告范围与生成前问答

可通过 annotations.reportScope 回填用户明确同意的范围。schools 默认 ["form", "luopan"]；airflowMode 可为 geometry / measured / simulated。geometry 表示用户同意只分析开口布局与路径。measured/simulated 必须提供对应风量与绑定的气流场。reportScope.evidenceRef 记录原始用户确认，不得由助手自行设定。

用户明确同意排除某项时，excludedRules 可包含 {"ruleId":"FS-REFLECTION","reason":"用户确认此房间没有床，不分析入口经镜面看向床位","evidenceRef":"用户原始回复引用"}。仅支持现有七项几何规则；未知数据不能作为自动排除理由。

assess 输出 consultation.ready 和 questions，并同步 evidence.questions。问题按整个空间及具体对象汇总；还有问题时会话为 awaiting_user_input。每条问题带 `channel`：`viewer` 表示可在画面里指认的事实（物品身份、门窗对外/开合、开口平面、镜面法向、床头方向），本地 Viewer 工程内须用编号标签在 VR 确认；`chat` 表示只能在对话里回答的信息（空间类型、房间用途、层高、坐向、年份等）。HTML 生成入口也会重新检查；最终报告不呈现内部问答清单。
