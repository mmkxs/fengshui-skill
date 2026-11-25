#!/usr/bin/env node
/**
 * Headless evidence capture for local spatial viewers.
 *
 * Why this exists: a browser tab that is backgrounded (or occluded) reports
 * document.visibilityState === 'hidden', which pauses animation frames and
 * the viewer's tile readiness. view()/capture() then wait forever. This driver owns a
 * headless Chrome instance, waits for the live bridge to report ready, sweeps
 * candidate longitudes so every anchor projects inside the frame, and writes
 * self-contained capture files (neutral schema + embedded PNG) that
 * scripts/evidence.py can import without hand edits.
 *
 * Usage:
 *   node scripts/vr_capture.mjs \
 *     --url http://127.0.0.1:8087/<resourceCode> \
 *     --scene analysis-output/<RC>/fengshui/<id>/scene.json \
 *     --capture-plan analysis-output/<RC>/fengshui/<id>/capture-plan.json \
 *     --views views.json --out analysis-output/<RC>/fengshui/<id>/captures \
 *     [--model model.json] [--chrome "/Applications/Google Chrome.app/..." ] \
 *     [--timeout 240]
 *
 * views.json:
 *   [{"name":"door","panoIndex":0,"targets":["obj-door"],"latitude":0.2,
 *     "fov":100,"longitude":null}]
 *
 * model.json:
 *   {"offset":[-1.3,0.2,1.8],"distance":7.5,"longitude":0.78,"latitude":0.6,
 *    "targets":["obj-desk"]}
 */
import { spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const CHROME =
  process.env.FENGSHUI_CHROME ||
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

const args = process.argv.slice(2)
const flag = (name) => {
  const index = args.indexOf(name)
  return index >= 0 ? args[index + 1] : undefined
}
const url = flag('--url')
const scenePath = flag('--scene')
const planPath = flag('--capture-plan')
const viewsPath = flag('--views')
const outDir = flag('--out') || '.'
const modelPath = flag('--model')
const timeoutS = Number(flag('--timeout') || 240)
const anchor = flag('--anchor') || 'top'

if (!url || !scenePath || !planPath) {
  console.error('需要 --url、--scene 与 --capture-plan')
  process.exit(2)
}

const scene = JSON.parse(readFileSync(scenePath, 'utf8'))
const plan = JSON.parse(readFileSync(planPath, 'utf8'))
const views = viewsPath ? JSON.parse(readFileSync(viewsPath, 'utf8')) : null
const model = modelPath ? JSON.parse(readFileSync(modelPath, 'utf8')) : null
const analysisSha256 = flag('--analysis-sha256') || plan.analysisSha256
const requestSha256 = flag('--request-sha256')
const observers = plan.observers
if (!analysisSha256 || !/^[a-f0-9]{64}$/.test(analysisSha256)) {
  console.error('需要 64 位 analysisSha256（可来自 capture-plan）')
  process.exit(2)
}
if (!requestSha256 || !/^[a-f0-9]{64}$/.test(requestSha256)) {
  console.error('需要本次授权的 requestSha256')
  process.exit(2)
}
if (!Array.isArray(observers) || observers.length === 0) {
  console.error('capture-plan 缺少 observers')
  process.exit(2)
}

const byId = new Map(scene.objects.filter((item) => item.box).map((item) => [item.id, item]))
const resolveTarget = (entry) => {
  if (typeof entry === 'string') {
    const item = byId.get(entry)
    if (!item) throw new Error(`场景中找不到物体 ${entry}`)
    const [cx, cy, cz] = item.box.center
    const height = item.box.size[1]
    const y = anchor === 'center' ? cy : cy + height / 2 - 0.05
    return { id: entry, position: [cx, y, cz] }
  }
  if (entry && entry.id && Array.isArray(entry.position)) return entry
  throw new Error('targets 需要物体 ID 或 {id, position}')
}

mkdirSync(outDir, { recursive: true })
const port = 9500 + Math.floor(Math.random() * 400)
const profile = join(outDir, '.chrome-profile')
const chrome = spawn(
  CHROME,
  [
    '--headless=new',
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`,
    '--window-size=1280,900',
    '--hide-scrollbars',
    '--use-gl=angle',
    '--use-angle=swiftshader',
    '--enable-unsafe-swiftshader',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-background-timer-throttling',
    '--disable-renderer-backgrounding',
    '--disable-backgrounding-occluded-windows',
    'about:blank',
  ],
  { stdio: ['ignore', 'ignore', 'pipe'] },
)
chrome.stderr.on('data', () => {})

const shutdown = (code) => {
  try {
    chrome.kill('SIGTERM')
  } catch {
    // Already gone.
  }
  process.exit(code)
}

let version = null
for (let attempt = 0; attempt < 200; attempt += 1) {
  try {
    const response = await fetch(`http://127.0.0.1:${port}/json/version`)
    if (response.ok) {
      version = await response.json()
      break
    }
  } catch {
    // Not listening yet.
  }
  await sleep(150)
}
if (!version) {
  console.error('无头 Chrome 启动失败')
  shutdown(2)
}

const target = await (
  await fetch(`http://127.0.0.1:${port}/json/new?${encodeURIComponent(url)}`, {
    method: 'PUT',
  })
).json()
const ws = new WebSocket(target.webSocketDebuggerUrl)
await new Promise((resolve, reject) => {
  ws.onopen = resolve
  ws.onerror = reject
})
let id = 0
const pending = new Map()
ws.onmessage = (event) => {
  const message = JSON.parse(event.data)
  if (message.id && pending.has(message.id)) {
    const { resolve, reject } = pending.get(message.id)
    pending.delete(message.id)
    if (message.error) reject(new Error(JSON.stringify(message.error)))
    else resolve(message.result)
  }
}
const send = (method, params = {}, timeout = 120000) =>
  new Promise((resolve, reject) => {
    const mid = ++id
    pending.set(mid, { resolve, reject })
    ws.send(JSON.stringify({ id: mid, method, params }))
    setTimeout(() => {
      if (pending.has(mid)) {
        pending.delete(mid)
        reject(new Error('timeout ' + method))
      }
    }, timeout)
  })
const evaluate = async (expression, awaitPromise = false, timeout = 120000) => {
  const result = await send('Runtime.evaluate', { expression, awaitPromise, returnByValue: true }, timeout)
  if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails).slice(0, 400))
  return result.result?.value
}

await send('Runtime.enable')

const deadline = Date.now() + timeoutS * 1000
let ready = false
while (Date.now() < deadline) {
  try {
    ready = await evaluate(
      `(() => { const b = window.__VR_SPATIAL_CONTEXT__; return !!(b && b.read().ready); })()`,
      false,
      10000,
    )
  } catch {
    // Page not ready yet.
  }
  if (ready) break
  await sleep(500)
}
if (!ready) {
  console.error('VR 页面在限定时间内没有就绪（检查 BFF 与资源码）')
  shutdown(3)
}

const normalized = (capture) => {
  const copy = { ...capture }
  copy.schema = 'spatial-fengshui.vr-capture'
  copy.context = { ...capture.context, schema: 'spatial-fengshui.active-vr', version: 1 }
  if (capture.camera) copy.camera = { ...capture.camera, schema: 'spatial-fengshui.camera-projection' }
  return copy
}

const write = (name, capture) => {
  const body = normalized(capture)
  const file = join(outDir, `${name}.json`)
  writeFileSync(file, JSON.stringify(body))
  const sha = createHash('sha256').update(Buffer.from(capture.imageDataUrl.split(',')[1], 'base64')).digest('hex')
  return { name, file, pngSha256: sha, projections: body.projections?.length ?? 0 }
}

// Target positions are resolved in Node and passed into the page as plain
// {id, position} pairs, so the page script stays small and dependency-free.
const resolvedViews = (views || []).map((view) => ({
  ...view,
  targets: view.targets.map(resolveTarget),
}))
const resolvedModel = model
  ? {
      state: {
        offset: model.offset,
        distance: model.distance,
        longitude: model.longitude,
        latitude: model.latitude,
        ...(model.fov ? { fov: model.fov } : {}),
      },
      targets: (model.targets || []).map(resolveTarget),
    }
  : null

const pageJob = `(async () => {
  const bridge = window.__VR_SPATIAL_CONTEXT__;
  const permit = {
    resourceCode: bridge.read().resourceCode,
    generation: bridge.read().generation,
    requestSha256: REQUEST,
  };
  bridge.bind(permit, ANALYSIS, OBSERVERS);
  const original = bridge.read();
  const inside = (point, shot) =>
    point && point.x > 70 && point.x < shot.width - 70 && point.y > 40 && point.y < shot.height - 40;
  const results = [];
  for (const view of VIEWS) {
    const targets = view.targets;
    let longitude = view.longitude;
    if (longitude === null || longitude === undefined) {
      let best = null;
      for (let step = 0; step < 24; step += 1) {
        const candidate = -Math.PI + (step * Math.PI) / 12;
        await bridge.view(permit, {
          panoIndex: view.panoIndex,
          longitude: candidate,
          latitude: view.latitude === undefined ? 0.15 : view.latitude,
          fov: view.fov === undefined ? 100 : view.fov,
        });
        const sample = await bridge.capture(permit, targets);
        const visible = sample.projections.filter((point) => inside(point, sample));
        const meanX = visible.reduce((sum, point) => sum + point.x, 0) / (visible.length || 1);
        const score = visible.length * 1000 - Math.abs(meanX - sample.width / 2);
        if (!best || score > best.score) best = { longitude: candidate, score };
      }
      longitude = Number(best.longitude.toFixed(3));
    }
    await bridge.view(permit, {
      panoIndex: view.panoIndex,
      longitude,
      latitude: view.latitude === undefined ? 0.15 : view.latitude,
      fov: view.fov === undefined ? 100 : view.fov,
    });
    results.push({ name: view.name, chosen: longitude, shot: await bridge.capture(permit, targets) });
  }
  if (MODEL) {
    await bridge.modelView(permit, MODEL.state);
    results.push({
      name: 'model',
      chosen: MODEL.state.longitude,
      shot: await bridge.capture(permit, MODEL.targets),
    });
  }
  await bridge.restore(permit, original);
  return results;
})()`

const results = await evaluate(
  `(async () => {
     const VIEWS = ${JSON.stringify(resolvedViews)};
     const MODEL = ${JSON.stringify(resolvedModel)};
     const ANALYSIS = ${JSON.stringify(analysisSha256)};
     const OBSERVERS = ${JSON.stringify(observers)};
     const REQUEST = ${JSON.stringify(requestSha256)};
     return ${pageJob};
   })()`,
  true,
  Math.max(180000, timeoutS * 1000),
)

for (const item of results) {
  const written = write(item.name, item.shot)
  console.log(JSON.stringify({ ...written, chosen: item.chosen }))
}
ws.close()
shutdown(0)
