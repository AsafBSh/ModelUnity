"""Dependency-free source publication checks, not inference validation."""
import ast
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode('utf-8').split('\0')
    forbidden = {'.safetensors', '.ckpt', '.pth', '.pt', '.onnx', '.bin',
                 '.dll', '.pyd', '.whl', '.7z', '.exe', '.pdb'}
    blocked = {'.venv', '.runtime', 'pretrained_weights', 'models_cache',
               'outputs', 'projects', 'bms_export', 'dist'}
    failures, checked = [], 0
    for name in filter(None, tracked):
        path = Path(name)
        if path.parts[0] in blocked or path.suffix.lower() in forbidden:
            failures.append(f'Generated/model/runtime file tracked: {name}')
        if name.startswith('inputs/') and path.name != '.gitkeep':
            failures.append(f'Private input tracked: {name}')
        if path.name == '.env' or (path.name.startswith('.env.') and path.name != '.env.example'):
            failures.append(f'Environment secret file tracked: {name}')
        if path.suffix == '.py' and path.parts[0] in {'scripts', 'tools', 'tests'}:
            ast.parse((ROOT / path).read_text(encoding='utf-8-sig'), filename=name)
            checked += 1
    if failures:
        raise SystemExit('\n'.join(failures))
    print(f'Source checks passed: {checked} Python files; no tracked model/runtime assets.')


if __name__ == '__main__':
    main()
