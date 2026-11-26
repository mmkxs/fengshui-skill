#!/usr/bin/env python3
"""Adapt fengshui facts to the spatial skill's temporary visual confirmation API."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from labels import generate, split_ids


def options(*values):
    return [{'value': value, 'label': label} for value, label in values]


def requirements(resource_code):
    kinds = {'door': '门', 'window': '窗', 'bed': '床', 'desk': '桌', 'sofa': '沙发', 'mirror': '镜子', 'beam': '梁', 'partition': '隔断'}
    return {
        'version': 1, 'id': 'fengshui:' + resource_code, 'workCode': resource_code,
        'goals': ['房间用途、关键物品身份与位置', '门窗开口、对外关系与开合状态', '床头靠背、镜面法向、梁体遮挡和通风路径', '绝对方位须有用户校准依据'],
        'facts': [{'id': 'identity:' + kind, 'kind': 'object', 'selector': kind,
                   'prompt': f'标记物品是{label}吗？',
                   'options': options(('yes', '是'), ('no', '不是'), ('unknown', '无法判断'))}
                  for kind, label in kinds.items()],
    }


def scene_request(scene, labels, resource_code):
    facts = []
    by_id = {item['id']: item for item in scene.get('objects', [])}
    for label in labels:
        object_id = label['sceneObjectId']
        item = by_id[object_id]
        base = {'kind': 'object', 'position': label['position'], 'objectId': object_id}
        facts.append({**base, 'id': 'identity:' + object_id, 'prompt': label['data']['title'] + '，识别正确吗？',
                      'options': options(('yes', '正确'), ('no', '不正确'), ('unknown', '无法判断'))})
        if item.get('type') in ('door', 'window'):
            facts.append({**base, 'id': 'exterior:' + object_id, 'prompt': label['data']['title'] + '是否通室外？',
                          'options': options(('yes', '通室外'), ('no', '通室内'), ('unknown', '无法判断'))})
            facts.append({**base, 'id': 'openFraction:' + object_id, 'prompt': label['data']['title'] + '平时的开合状态？',
                          'options': options(('0', '关闭'), ('0.5', '半开'), ('1', '全开'), ('unknown', '无法判断'))})
    request = {**requirements(resource_code), 'facts': facts, 'analysisSha256': scene.get('sourceAnalysisSha256')}
    digest = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    request['id'] += ':' + digest
    return request


def annotations(result, request):
    if result.get('status') != 'answered' or result.get('id') != request['id'] or result.get('workCode') != request['workCode']:
        raise ValueError('确认尚未完成清理，或会话/作品不匹配')
    expected = {fact['id']: fact for fact in request['facts']}
    rows = result.get('answers', [])
    if len(rows) != len(expected) or {row.get('id') for row in rows} != set(expected):
        raise ValueError('确认答案必须完整且无重复')
    objects, unresolved = {}, []
    for answer in rows:
        fact = expected[answer['id']]
        if answer.get('source') != 'user' or answer.get('value') not in {option['value'] for option in fact['options']}:
            raise ValueError('确认答案没有用户来源或取值无效')
        value = answer['value']
        object_id = fact.get('objectId')
        if value == 'unknown' or not object_id:
            unresolved.append(answer['id'])
            continue
        field = answer['id'].split(':', 1)[0]
        target = objects.setdefault(object_id, {'id': object_id})
        if field == 'identity':
            target.update(identityConfirmed=value == 'yes', identityEvidenceRef='viewer:' + request['id'])
            if value != 'yes':
                unresolved.append(answer['id'])
        elif field == 'exterior':
            target['exterior'] = value == 'yes'
        elif field == 'openFraction':
            target['openFraction'] = float(value)
        else:
            unresolved.append(answer['id'])
    if not request.get('analysisSha256'):
        raise ValueError('回填需要与当前 scene 绑定的 analysisSha256')
    for item in objects.values():
        item['evidenceRefs'] = ['viewer:' + request['id']]
    return {'schema': 'spatial-fengshui.annotations', 'version': 1,
            'analysisSha256': request['analysisSha256'], 'resourceCode': request['workCode'],
            'objectUpdates': list(objects.values()), 'unresolved': unresolved}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', default='.')
    parser.add_argument('--resource-code', required=True)
    parser.add_argument('--scene')
    parser.add_argument('--request', help='空间分析前或补确认时传入的通用需求 JSON')
    parser.add_argument('--requirements-out', help='仅导出分析前需求')
    parser.add_argument('--answers', help='统一确认入口 read().result 的 JSON')
    for flag in ('door', 'windows', 'desks', 'types', 'room', 'viewer', 'out'):
        parser.add_argument('--' + flag)
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--install', action='store_true', help='通过空间 skill 的 wire_host.py 接线')
    parser.add_argument('--force', action='store_true', help='兼容旧调用；不覆盖 Viewer 文件')
    args = parser.parse_args(argv)
    project = Path(args.project).resolve()
    output = Path(args.out) if args.out else project / 'analysis-output' / args.resource_code / 'viewer-confirmation.json'
    try:
        if args.requirements_out:
            target = Path(args.requirements_out)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(requirements(args.resource_code), ensure_ascii=False, indent=2) + '\n')
            print(json.dumps({'ok': True, 'request': str(target)}, ensure_ascii=False))
            return 0
        scripts = project / '.agents/skills/realsee-spatial-analysis/scripts'
        binder = scripts / 'analysis_request.py'
        if not binder.is_file():
            raise ValueError('空间确认能力未安装：更新项目内 realsee-spatial-analysis skill 后重试；本适配器不注入 overlay')
        output.parent.mkdir(parents=True, exist_ok=True)
        if args.request:
            request_path = Path(args.request)
            request = json.loads(request_path.read_text())
        elif args.scene:
            scene = json.loads(Path(args.scene).read_text())
            kinds = split_ids(args.types)
            if args.all:
                kinds |= {'door', 'window', 'desk', 'bed', 'sofa', 'mirror', 'partition', 'beam'}
            labels = generate(scene, split_ids(args.door), split_ids(args.windows), split_ids(args.desks), kinds, args.room)
            request = scene_request(scene, labels, args.resource_code)
            request_path = output.with_name('confirmation-requirements.json')
            request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2) + '\n')
        else:
            raise ValueError('需要 --scene 或 --request；分析前可用 --requirements-out 导出需求')
        if args.answers:
            result = annotations(json.loads(Path(args.answers).read_text()), request)
        else:
            if args.install:
                wire = subprocess.run([sys.executable, str(scripts / 'wire_host.py'), '--app', str(project)], capture_output=True, text=True)
                if wire.returncode:
                    raise ValueError('空间确认入口接线失败：' + (wire.stdout or wire.stderr))
            bound = subprocess.run([sys.executable, str(binder), '--request', str(request_path), '--resource-code', args.resource_code], capture_output=True, text=True)
            if bound.returncode:
                raise ValueError(bound.stdout or bound.stderr)
            result = json.loads(bound.stdout)
            result['entry'] = 'window.__VR_SPATIAL_CONFIRM__'
            result['next'] = '在已加载同作品的 Viewer 调用 entry.open(request)，用户提交后读取 entry.read().result；仅 answered 可回填。'
            if args.viewer:
                result['openUrl'] = args.viewer.rstrip('/') + '/' + args.resource_code
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({'ok': True, 'out': str(output), **result}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({'ok': False, 'error': 'SPATIAL_CONFIRMATION_BLOCKED', 'detail': str(error)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
