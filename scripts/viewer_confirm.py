#!/usr/bin/env python3
"""Package the in-viewer confirmation step: overlay + numbered labels + questions.

Users confirm doors, windows and furniture by looking at the scene, not by
describing orientations in chat. This command prepares everything needed for
that single interaction:

1. optionally installs a dev-only overlay module (`?agentLabels=` loader);
2. writes numbered labels into `public/agent-labels/<RC>.json`;
3. emits a question sheet bound to those labels and the URL to open.

    python scripts/viewer_confirm.py --project . --resource-code <RC> \
        --scene analysis-output/<RC>/fengshui/<id>/scene.json \
        --door obj-mirror003 \
        --windows obj-window002,obj-window003,obj-window006,obj-window007 \
        --desks obj-desk001,obj-desk002,obj-desk003 --install
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from labels import generate, split_ids

OVERLAY_PATH = "src/features/tags/AgentTagOverlay.ts"
OVERLAY_SOURCE = '''export type AgentTagList = unknown[]

export interface AgentTagLoader {
  load(list: AgentTagList): Promise<unknown>
}

declare global {
  interface Window {
    __VR_AGENT_TAGS__?: { load(list: AgentTagList): Promise<unknown> }
  }
}

/**
 * Dev-only overlay. Loads `?agentLabels=/agent-labels/<file>.json` into the
 * running scene so a reviewer can confirm numbered anchors in place.
 *
 * `loader` comes from the app's own spatial tag feature, so this module stays
 * independent of any particular viewer SDK.
 */
export function installAgentTagOverlay(loader: AgentTagLoader) {
  const handle = { load: (list: AgentTagList) => loader.load(list) }
  window.__VR_AGENT_TAGS__ = handle
  const source = new URLSearchParams(window.location.search).get('agentLabels')
  if (source?.startsWith('/')) {
    void fetch(source)
      .then((response) => response.json())
      .then((list: AgentTagList) => handle.load(list))
      .catch((error: unknown) => console.warn('Agent 标签加载失败', error))
  }
  return {
    load: handle.load,
    dispose() {
      if (window.__VR_AGENT_TAGS__ === handle) delete window.__VR_AGENT_TAGS__
    },
  }
}
'''

APP_SNIPPET = """// 仅在开发构建启用；空间标签实例已就绪后调用
import { installAgentTagOverlay } from './features/tags/AgentTagOverlay'
const overlay = enable ? installAgentTagOverlay({ load: (list) => tags.load(list) }) : undefined
// 清理时调用 overlay?.dispose()"""


def questions_for(labels):
    by_prefix = {}
    for item in labels:
        prefix = item["id"][0]
        by_prefix.setdefault(prefix, []).append(item["id"])
    questions = []
    if by_prefix.get("D"):
        questions.append(
            {
                "id": "door-identity",
                "labelIds": by_prefix["D"],
                "question": "画面里哪个编号是入户门？",
                "field": "door",
            }
        )
    if by_prefix.get("W"):
        questions.append(
            {
                "id": "exterior-windows",
                "labelIds": by_prefix["W"],
                "question": "哪几个编号真正通向室外？（可多选）",
                "field": "windows",
            }
        )
    if by_prefix.get("T"):
        questions.append(
            {
                "id": "desk-identity",
                "labelIds": by_prefix["T"],
                "question": "哪几个编号是平时使用的桌子，其余是什么？",
                "field": "desks",
            }
        )
    if by_prefix.get("P") or by_prefix.get("G"):
        questions.append(
            {
                "id": "mirror-identity",
                "labelIds": by_prefix.get("P", []) + by_prefix.get("G", []),
                "question": "这些编号是镜子还是玻璃隔断？",
                "field": "mirrors",
            }
        )
    questions.append(
        {
            "id": "opening-state",
            "labelIds": by_prefix.get("W", []),
            "question": "外窗平时开着还是关着？",
            "field": "openFraction",
        }
    )
    questions.append(
        {
            "id": "compass",
            "labelIds": by_prefix.get("D", []),
            "question": "站在门口面向门外，门朝哪个方向？（可读手机指南针）",
            "field": "compass",
        }
    )
    return questions


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=".")
    parser.add_argument("--resource-code", required=True)
    parser.add_argument("--scene", required=True)
    parser.add_argument("--door")
    parser.add_argument("--windows")
    parser.add_argument("--desks")
    parser.add_argument("--types", help="额外整类型，如 mirror,beam,partition")
    parser.add_argument("--room")
    parser.add_argument("--install", action="store_true", help="写入 dev-only 标签入口")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--viewer", default="http://127.0.0.1:8087", help="Viewer 根地址")
    parser.add_argument("--out", help="确认清单输出路径")
    args = parser.parse_args(argv)

    project = Path(args.project).resolve()
    scene = json.loads(Path(args.scene).read_text())
    labels = generate(
        scene,
        split_ids(args.door),
        split_ids(args.windows),
        split_ids(args.desks),
        split_ids(args.types),
        args.room,
    )
    if not labels:
        raise SystemExit("没有可标注的对象，请检查 --door/--windows/--desks/--types")

    installed = False
    note = None
    overlay = project / OVERLAY_PATH
    if args.install:
        if overlay.exists() and not args.force:
            note = f"标签入口已存在，未覆盖：{overlay}；需要替换时加 --force"
        else:
            overlay.parent.mkdir(parents=True, exist_ok=True)
            overlay.write_text(OVERLAY_SOURCE)
            installed = True

    label_dir = project / "public/agent-labels"
    label_dir.mkdir(parents=True, exist_ok=True)
    label_path = label_dir / f"{args.resource_code}.json"
    label_path.write_text(json.dumps(labels, ensure_ascii=False, indent=1) + "\n")

    open_url = f"{args.viewer.rstrip('/')}/{args.resource_code}?agentLabels=/agent-labels/{args.resource_code}.json"
    questions = questions_for(labels)
    result = {
        "schema": "spatial-fengshui.viewer-confirmation",
        "version": 1,
        "resourceCode": args.resource_code,
        "openUrl": open_url,
        "labels": [
            {"id": item["id"], "title": item["data"]["title"], "object": item["sceneObjectId"]}
            for item in labels
        ],
        "questions": questions,
        "overlay": {
            "path": OVERLAY_PATH,
            "installed": installed,
            "appSnippet": APP_SNIPPET,
            **({"note": note} if note else {}),
        },
        "next": "让用户打开 openUrl，按编号回答 questions；答案回填 annotations 后运行 assess。",
    }
    out = Path(args.out) if args.out else project / f"analysis-output/{args.resource_code}/viewer-confirmation.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({"ok": True, "out": str(out), **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
