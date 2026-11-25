# 在本地 Viewer 工程内确认与取证

本页记录在本地 Viewer 工程里做确认与截图时验证过的做法和坑。所有内容都来自真实运行；
其中“无头取证”和“VR 内标签”可以在没有可见浏览器窗口时独立工作。

## 1. 用 VR 内标签确认，不用文字和平面图

用户判断门、窗、桌的方位时，需要在场景里看，而不是读坐标或看平面图。一条命令即可准备好全部物料：

```bash
python scripts/viewer_confirm.py --project . --resource-code <RC> \
  --scene analysis-output/<RC>/fengshui/<id>/scene.json \
  --door <门ID> --windows <窗ID列表> --desks <桌ID列表> --types mirror --install
```

输出里的 `openUrl` 直接发给用户，`questions` 是按编号组织的问题，`overlay` 给出 dev-only 入口的位置和 App 侧调用片段。需要了解底层物料时，再按下面的分步流程生成标签：

1. 生成编号标签：

   ```bash
   python scripts/labels.py --scene analysis-output/<RC>/fengshui/<id>/scene.json \
     --out public/agent-labels/<RC>.json \
     --door <门物品ID> --windows <窗ID列表> --desks <桌ID列表> --types mirror
   ```

   标签按 `D/W/P/T` 编号，位置自动收进房间多边形；`visibleFiveMode` 已设为 `all`。

2. 在项目里加一个仅开发构建生效的加载入口。`viewer_confirm.py --install` 会写入
   `src/features/tags/AgentTagOverlay.ts`：它只依赖传入的 `loader.load(list)`，不绑定具体
   空间 SDK。在空间与标签实例就绪后调用 `installAgentTagOverlay({ load: (list) => tags.load(list) })`，
   清理时调用返回值的 `dispose()`。

3. 让用户打开 `http://<host>/<RC>?agentLabels=/agent-labels/<RC>.json`，按画面里的编号回答：
   “D 是不是入户门”“哪些 W 通户外”“门朝哪边”。**不要**要求用户描述坐标轴或方位角换算。

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
  “解读条目没有对应的本次几何核查项”。把排除原因写进 `summary`。
- 非 draft 报告里，note 引用的截图必须覆盖 note 的全部 `objectIds`（房间可代替房间内物品）。
- 候选（status=`candidate`）必须都有 note；`not_observed`、`limited` 可以只在 summary 里说明。

## 5. 开口与标注的最小集

- `exterior` 与 `openFraction` 必须同时给出，否则 `consultation` 会一直追问门窗状态；
  开合状态未确认时给保守值，并在 `evidenceRefs` 写明“未实测，按关闭/半开取值”。
- 只标门窗时 `FS-BACKING` 只能给出方向性结论；需要距离时要补墙体的几何盒。
- 梁体不是检测常项，需要用户指认后作为 `beam` 物品补进去，否则 `FS-BEAM` 只会是 unknown。
- 同一房间的多段窗检测（窗框、窗下设施）要按用户确认合并，避免把设施当外窗计入通风。
