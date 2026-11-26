# 在本地 Viewer 工程内确认与取证

本页记录在本地 Viewer 工程里做确认与截图时验证过的做法和坑。所有内容都来自真实运行；
其中“无头取证”和“VR 内标签”可以在没有可见浏览器窗口时独立工作。

## 1. 用 VR 内标签确认，不用文字和平面图

用户判断门、窗、桌的方位时，需要在场景里看，而不是读坐标或看平面图。一条命令即可准备好全部物料：

```bash
python scripts/viewer_confirm.py --project . --resource-code <RC> \
  --scene analysis-output/<RC>/fengshui/<id>/scene.json \
  --all --install
```

`--all` 为门、窗、桌、床、沙发、镜子、隔断与梁体生成确认事实；需要子集时用 `--door/--windows/--desks/--types`。输出 `request` 交给空间 skill 的 `window.__VR_SPATIAL_CONFIRM__.open(request)`，用户在场景旁表单提交后读取 `read().result`。只有 `answered` 才能回填；所有分析信息均在可视化界面中确认，坐向使用起终点明确的 GuideLine。`--install` 委托空间侧 wire_host.py，不注入 overlay。

1. 分析前导出目标和待确认事实：

   ```bash
   python scripts/viewer_confirm.py --resource-code <RC> --requirements-out <需求.json>
   ```

   按本次任务补充 facts，交给空间侧 `pipeline.py all --analysis-request <需求.json> ...`。消费方声明需求，空间侧执行适用分析并绑定真实候选。

2. 通过空间 skill 绑定候选并打开统一确认入口。缺候选、缺入口或定位失败时明确阻塞，先补分析或接线。物品临时标签、方向线以及会话清理由空间侧统一管理，完成、取消、刷新或异常都清理，不复用持久标签列表。

3. 用 `viewer_confirm.py --scene <scene.json> --resource-code <RC> --answers <result.json> --out <annotations.json>` 回填对象标注。脚本核对会话、作品、用户来源和完整答案；未知或否认的身份保留 unresolved。精确方位、房间用途等其他 facts 由消费方按 fact id 映射到当前 annotations，禁止猜测。不要再使用 `AgentTagOverlay`、`__VR_AGENT_TAGS__` 或 `agentLabels` URL。

### 会踩的坑

- 全景标签默认只在全景模式可见；不放开可见模式，切到模型态标签就消失（标签项配置里设 `visibleFiveMode: 'all'`）。
- 标签点落在墙外或墙体内部时不会渲染。`labels.py` 会把它拉进房间；手写位置时同样要保证在房间内。
- 标签是页面叠加层，不会进入底层画布像素，取证图仍然干净。
- 自动化浏览器标签页常常是 `document.visibilityState === 'hidden'`（窗口被遮挡、最小化或
  在别的桌面），此时动画帧暂停，瓦片就绪等待和截图前的两帧回调都会一直等。
  不要靠“请用户切到前台”解决，改用下面的无头取证。

## 2. 无头取证

```bash
node scripts/vr_capture.mjs \
  --url http://127.0.0.1:8087/<RC> \
  --scene analysis-output/<RC>/fengshui/<id>/scene.json \
  --capture-plan analysis-output/<RC>/fengshui/<id>/capture-plan.json \
  --views views.json --model model.json \
  --request-sha256 <本次授权哈希> \
  --out analysis-output/<RC>/fengshui/<id>/captures
```

- 自带无头浏览器（`--chrome` 或 `FENGSHUI_CHROME` 可覆盖路径），页面在该进程里始终可见。
- 每个视角自动扫 24 个经度，按“落入画面的点数 + 居中程度”选最优角度后再截最终图。
- `targets` 只接受**场景里真实存在的物品 ID**（或显式 `{id, position}`）。自定义名称会被
  `evidence.py` 判为无效标注点。
- 锚点默认抬到物品顶面：点在物品内部或被遮挡时，投影返回空，截图里就没有该点。
- 目标分散在两面墙时拆成多个视角；一个视角里全塞进去会只框住一部分。
- 产物直接是中立契约的截图，带内嵌 PNG、相机矩阵和 context，可直接交给
  `evidence.py`，不需要手工改 schema 或补 `imageDataUrl`。

## 3. 契约兼容

部分 Viewer 仍发布旧版厂商前缀的上下文与截图契约。`scripts/contracts.py`
在读取时统一转换成中立名，因此上下文文件、截图 JSON 都可以原样传入。
`read_context`、`evidence.py`、`visuals.validate_camera` 都已接入。

## 4. 解读与证据的硬约束

- 每条 note 必须对应本次 `findings` 里的 `(ruleId, objectIds)`，且同一项只能写一次。
- `reportScope.excludedRules` 中的规则不会出现在报告 findings 里，给它们写 note 会报
  “解读条目没有对应的本次几何核查项”。排除原因只保留在 `reportScope` 等内部记录中，
  不写进面向读者的 `summary` 或报告正文。
- 非 draft 报告里，note 引用的截图必须覆盖 note 的全部 `objectIds`（房间可代替房间内物品）。
- 候选（status=`candidate`）必须都有 note；`not_observed`、`limited` 只保留在内部结果中，
  不写进面向读者的 `summary` 或报告正文。

## 5. 开口与标注的最小集

- `exterior` 与 `openFraction` 必须同时给出，否则 `consultation` 会一直追问门窗状态；
  开合状态未确认时给保守值，并在 `evidenceRefs` 写明“未实测，按关闭/半开取值”。
- 只标门窗时 `FS-BACKING` 只能给出方向性结论；需要距离时要补墙体的几何盒。
- 梁体不是检测常项，需要用户指认后作为 `beam` 物品补进去，否则 `FS-BEAM` 只会是 unknown。
- 同一房间的多段窗检测（窗框、窗下设施）要按用户确认合并，避免把设施当外窗计入通风。
