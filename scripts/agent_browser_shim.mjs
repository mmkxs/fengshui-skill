#!/usr/bin/env node
/**
 * Minimal `agent-browser` compatible driver for PDF printing.
 *
 * Implements: open <url> | wait --fn <expr> | pdf <path> | close
 * Backed by a local headless Chrome over CDP. Used automatically when the
 * `agent-browser` CLI is not installed.
 */
import { spawn } from 'node:child_process'
import { mkdirSync, readFileSync, writeFileSync, existsSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

const CHROME =
  process.env.FENGSHUI_CHROME ||
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const DIR = join(tmpdir(), 'fengshui-agent-browser')
mkdirSync(DIR, { recursive: true })
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

const argv = process.argv.slice(2)
const si = argv.indexOf('--session')
const session = si >= 0 ? argv[si + 1] : 'default'
const rest = argv.filter((_, i) => i !== si && i !== si + 1)
const cmd = rest[0]
const statePath = join(DIR, session + '.json')

const fail = (message) => {
  console.error(message)
  process.exit(1)
}

async function connect() {
  const state = JSON.parse(readFileSync(statePath, 'utf8'))
  const ws = new WebSocket(state.wsUrl)
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
  const send = (method, params = {}, timeout = 60000) =>
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
  return { ws, send }
}

if (cmd === 'open') {
  const url = rest[1]
  if (!url) fail('open requires a URL')
  const port = 9400 + Math.floor(Math.random() * 400)
  const profile = join(DIR, 'profile-' + session)
  const child = spawn(
    CHROME,
    [
      '--headless=new',
      `--remote-debugging-port=${port}`,
      `--user-data-dir=${profile}`,
      '--window-size=1440,1000',
      '--hide-scrollbars',
      '--no-first-run',
      '--no-default-browser-check',
      '--disable-background-timer-throttling',
      '--allow-file-access-from-files',
      'about:blank',
    ],
    { detached: true, stdio: 'ignore' },
  )
  child.unref()
  let version = null
  for (let attempt = 0; attempt < 200; attempt += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/version`)
      if (response.ok) {
        version = await response.json()
        break
      }
    } catch {
      // Chrome not listening yet.
    }
    await sleep(150)
  }
  if (!version) fail('headless Chrome did not start')
  const target = await (
    await fetch(`http://127.0.0.1:${port}/json/new?${encodeURIComponent(url)}`, {
      method: 'PUT',
    })
  ).json()
  writeFileSync(statePath, JSON.stringify({ port, pid: child.pid, wsUrl: target.webSocketDebuggerUrl }))
  console.log('open ok')
  process.exit(0)
}

if (cmd === 'wait') {
  const fi = rest.indexOf('--fn')
  const expression = fi >= 0 ? rest[fi + 1] : null
  if (!expression) fail('wait requires --fn')
  const { ws, send } = await connect()
  await send('Runtime.enable')
  for (let attempt = 0; attempt < 150; attempt += 1) {
    try {
      const result = await send('Runtime.evaluate', {
        expression: `(() => { try { return !!(${expression}) } catch { return false } })()`,
        returnByValue: true,
      })
      if (result.result?.value === true) {
        console.log('wait ok')
        ws.close()
        process.exit(0)
      }
    } catch {
      // Page still navigating.
    }
    await sleep(400)
  }
  ws.close()
  fail('wait timeout: ' + expression)
}

if (cmd === 'pdf') {
  const output = rest[1]
  if (!output) fail('pdf requires a path')
  const { ws, send } = await connect()
  await send('Page.enable')
  const result = await send(
    'Page.printToPDF',
    {
      printBackground: true,
      preferCSSPageSize: true,
      marginTop: 0,
      marginBottom: 0,
      marginLeft: 0,
      marginRight: 0,
    },
    180000,
  )
  writeFileSync(output, Buffer.from(result.data, 'base64'))
  console.log('pdf ok')
  ws.close()
  process.exit(0)
}

if (cmd === 'close') {
  if (existsSync(statePath)) {
    try {
      process.kill(JSON.parse(readFileSync(statePath, 'utf8')).pid)
    } catch {
      // Already gone.
    }
    try {
      rmSync(statePath, { force: true })
    } catch {
      // Ignore cleanup failure.
    }
  }
  console.log('close ok')
  process.exit(0)
}

fail('unknown command ' + cmd)
