# -*- coding: utf-8 -*-
"""생성물이 나갈 자리를 정합니다 — build.py · build_xlsx.py · tools/make_artifact.py 공용.

파일 이름은 YAML 의 `output`, 폴더는 `output_dir` 이 정합니다.
`output_dir` 이 없으면 DEFAULT_DIR 이고, `'.'` 이나 빈 값으로 두면 저장소 뿌리에 그대로 떨어집니다.

세 곳에 같은 계산을 복사해 두면 언젠가 갈라집니다. 그래서 여기 한 곳에만 둡니다.
"""
import os

DEFAULT_DIR = '결과물'


def resolve(doc, key='output', make=True):
    """YAML 딕셔너리에서 생성물 경로를 만들어 돌려줍니다. 이름이 없으면 None."""
    name = doc.get(key)
    if not name:
        return None
    folder = doc.get('output_dir', DEFAULT_DIR)
    if not folder or folder == '.':
        return name
    if make:
        os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, name)
