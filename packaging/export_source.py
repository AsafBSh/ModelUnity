"""Export one committed public source tree; never include workspace data."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = {'.git', '.runtime', '.cursor', '.github', '.venv', 'venv', 'env',
           'projects', 'outputs', 'bms_export', 'pretrained_weights', 'models_cache',
           '.cache', 'dist', 'build', 'tests', 'benchmarks', '__pycache__'}
WEIGHTS = {'.safetensors', '.ckpt', '.pth', '.pt', '.onnx', '.bin', '.whl',
           '.dll', '.pyd', '.so', '.lib', '.pdb', '.pem', '.key'}
GUIDES = {'OPERATING_GUIDE.md', 'ModelUnify_Operating_Guide.docx', 'MODEL_WEIGHTS.md',
          'INSTALLATION.md', 'COMFYUI.md', 'BMS_WORKFLOW.md', 'BUILD_PORTABLE.md',
          'CONTRIBUTING.md'}


def git(*arguments):
    return subprocess.check_output(['git', *arguments], cwd=ROOT)


def public_path(name):
    path = PurePosixPath(name)
    parts = path.parts
    if not parts or path.is_absolute() or '..' in parts or '\\' in name or ':' in name:
        return False
    if any(part in PRIVATE or part.startswith('.venv') for part in parts):
        return False
    if any(part == '.env' or part.startswith('.env.') for part in parts):
        return False
    if parts[0] == 'docs' and (len(parts) != 2 or parts[1] not in GUIDES):
        return False
    if parts[0] == 'inputs' and name != 'inputs/.gitkeep':
        return False
    if name == 'AGENTS.md' or name in {'scripts/benchmark.py', 'scripts/benchmark_suite.py',
            'scripts/validate_workbench.py', 'scripts/validate_optimization.py', 'tools/check_source_tree.py'}:
        return False
    if parts[:3] in (('tools', 'instalod', 'inbox'), ('tools', 'instalod', 'outbox')):
        return parts[-1] == '.gitkeep'
    if any(part in ('checkpoints', 'ckpt') for part in parts):
        return False
    return path.suffix.lower() not in WEIGHTS


def version_at(commit):
    tree = ast.parse(git('show', commit + ':scripts/_version.py').decode('utf-8'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'MODELUNIFY_VERSION' for t in node.targets):
            value = ast.literal_eval(node.value)
            if isinstance(value, str) and re.fullmatch(r'\d+\.\d+\.\d+', value):
                return value
    raise ValueError('The selected commit has no valid application version.')


def export(revision='HEAD', output=None):
    commit = git('rev-parse', '--verify', '--end-of-options', revision + '^{commit}').decode().strip()
    if not re.fullmatch(r'[0-9a-f]{40,64}', commit):
        raise ValueError('Expected an immutable Git commit.')
    version = version_at(commit)
    paths = []
    for row in git('ls-tree', '-r', '-z', commit).split(b'\0'):
        if not row:
            continue
        metadata, raw_name = row.split(b'\t', 1)
        name = raw_name.decode('utf-8')
        if metadata.split()[0] not in (b'100644', b'100755') or not public_path(name):
            raise ValueError('Refused non-public or linked source entry: ' + name)
        paths.append(name)
    destination = Path(output) if output else ROOT / 'dist' / f'ModelUnify-{version}-source.zip'
    destination = destination.resolve()
    if not destination.is_relative_to((ROOT / 'dist').resolve()) or destination.suffix.lower() != '.zip':
        raise ValueError('Choose a new ZIP inside this workspace dist/ directory.')
    checksum = destination.with_name(destination.name + '.sha256')
    manifest = destination.with_name(destination.stem + '.manifest.json')
    if any(p.exists() for p in (destination, checksum, manifest)):
        raise FileExistsError('Export output exists and is preserved; select a fresh name.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    prefix = f'ModelUnify-{version}-source/'
    info = {'application': 'ModelUnify', 'version': version, 'package_type': 'source',
            'source_commit': commit, 'source_date': git('show', '-s', '--format=%cI', commit).decode().strip(),
            'repository': 'https://github.com/AsafBSh/ModelUnity',
            'files': len(paths), 'runtime_included': False, 'model_weights_included': False,
            'setup_guide': 'docs/INSTALLATION.md',
            'inference_validation': 'Not performed by the source exporter'}
    # Build in a unique temporary file, then create the final output exclusively.
    with tempfile.TemporaryDirectory(prefix='source-export-', dir=destination.parent) as temporary:
        archive = Path(temporary) / 'source.zip'
        subprocess.run(['git', 'archive', '--format=zip', '--prefix=' + prefix,
                        '--output=' + str(archive), commit], cwd=ROOT, check=True)
        with ZipFile(archive, 'a', compression=ZIP_DEFLATED, compresslevel=9) as bundle:
            actual = {f.filename[len(prefix):] for f in bundle.infolist() if not f.is_dir()}
            if actual != set(paths):
                raise ValueError('Archive entries differ from the reviewed committed source tree.')
            hashes = ''.join(hashlib.sha256(bundle.read(prefix + name)).hexdigest() + '  ' + name + '\n' for name in sorted(paths))
            timestamp = bundle.infolist()[0].date_time
            for name, data in {'EXPORT_INFO.json': json.dumps(info, indent=2) + '\n',
                               'FILES.sha256': hashes}.items():
                member = ZipInfo(prefix + name, date_time=timestamp)
                member.compress_type = ZIP_DEFLATED
                member.external_attr = 0o100644 << 16
                bundle.writestr(member, data.encode('utf-8'))
        with ZipFile(archive) as bundle:
            if bundle.testzip():
                raise ValueError('Source export failed its ZIP integrity check.')
            for line in bundle.read(prefix + 'FILES.sha256').decode().splitlines():
                digest, name = line.split('  ', 1)
                if hashlib.sha256(bundle.read(prefix + name)).hexdigest() != digest:
                    raise ValueError('Source file checksum mismatch: ' + name)
        with destination.open('xb') as target, archive.open('rb') as source:
            import shutil
            shutil.copyfileobj(source, target)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    with checksum.open('x', encoding='ascii') as target:
        target.write(digest + '  ' + destination.name + '\n')
    with manifest.open('x', encoding='utf-8') as target:
        target.write(json.dumps({**info, 'archive': destination.name,
                                'bytes': destination.stat().st_size, 'sha256': digest}, indent=2) + '\n')
    return {'archive': str(destination), 'checksum': str(checksum), 'manifest': str(manifest),
            'source_commit': commit, 'files': len(paths), 'sha256': digest}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', default='HEAD', help='Committed Git revision to export')
    parser.add_argument('--output', help='Fresh ZIP path under dist/')
    args = parser.parse_args()
    print(json.dumps(export(args.revision, args.output), indent=2))


if __name__ == '__main__':
    main()
