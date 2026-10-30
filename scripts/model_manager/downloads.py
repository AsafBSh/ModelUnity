"""Bounded, resumable HTTP transfers with cancellation and integrity checks."""
from __future__ import annotations
from pathlib import Path, PurePosixPath
from urllib import request, error, parse
import hashlib
import http.client
import json
import os
import stat
import time


class Cancelled(Exception):
    pass


class SafeRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new and parse.urlsplit(newurl).hostname != parse.urlsplit(req.full_url).hostname:
            new.remove_header('Authorization')
        if parse.urlsplit(newurl).scheme != 'https' and parse.urlsplit(req.full_url).scheme == 'https':
            raise ValueError('Refused an insecure download redirect.')
        return new


def headers(url, token=None):
    result = {'User-Agent': 'ModelUnify-model-manager', 'Accept-Encoding': 'identity'}
    if token and parse.urlsplit(url).hostname == 'huggingface.co':
        result['Authorization'] = 'Bearer ' + token
    return result


def open_url(url, token=None, extra=None):
    req = request.Request(url, headers={**headers(url, token), **(extra or {})})
    return request.build_opener(SafeRedirect()).open(req, timeout=15)


def read_json(url, token=None):
    try:
        with open_url(url, token) as response:
            data = response.read(8 * 1024 * 1024 + 1)
    except error.HTTPError as exc:
        if exc.code in (401,403):raise ValueError('Model access denied. Review the model source/license page and enter a Hugging Face token in Models if access is required.') from None
        if exc.code==429:raise ValueError('Model source rate limit reached. Wait, then use Retry.') from None
        raise
    if len(data) > 8 * 1024 * 1024:
        raise ValueError('Model metadata exceeds the supported size.')
    return json.loads(data)


def safe_relative(name):
    p = PurePosixPath(name)
    if not name or p.is_absolute() or '..' in p.parts or any(c in name for c in '\\:<>"|?*\0') or any(x.endswith((' ', '.')) for x in p.parts):
        raise ValueError('Unsafe model file path.')
    # Windows device names remain special even when they have an extension.
    reserved = {'con', 'prn', 'aux', 'nul', *(f'com{i}' for i in range(1,10)), *(f'lpt{i}' for i in range(1,10))}
    if any(x.split('.')[0].lower() in reserved for x in p.parts):
        raise ValueError('Reserved model filename.')
    return p


def target_path(root, relative):
    relative = safe_relative(relative)
    base = Path(root).resolve()
    target = base.joinpath(*relative.parts)
    if not target.resolve().is_relative_to(base):
        raise ValueError('Model file escapes its installation directory.')
    # Do not publish through symlinks/junctions supplied inside an installation.
    for p in [target, *target.parents]:
        if p == base: break
        reparse = bool(p.exists() and getattr(p.lstat(),'st_file_attributes',0) & getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024))
        if p.is_symlink() or reparse or (hasattr(p, 'is_junction') and p.is_junction()):
            raise ValueError('Model installation contains a link; choose an ordinary folder.')
    return target


def hash_file(path, cancelled=lambda: False, progress=lambda count: None):
    path = Path(path)
    size = path.stat().st_size
    sha256, md5, git = hashlib.sha256(), hashlib.md5(), hashlib.sha1()
    git.update(f'blob {size}\0'.encode())
    done = 0
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            if cancelled(): raise Cancelled('Verification cancelled.')
            for h in (sha256, md5, git): h.update(chunk)
            done += len(chunk)
            progress(done)
    return {'size': size, 'sha256': sha256.hexdigest(), 'md5': md5.hexdigest(), 'git_sha1': git.hexdigest()}


def valid(actual, expected):
    if expected.get('size') is not None and actual['size'] != expected['size']: return False
    return all(not expected.get(key) or actual[key] == expected[key] for key in ('sha256','md5','git_sha1'))


def transfer(item, destination, *, token=None, cancelled=lambda: False,
             progress=lambda done,total,speed: None, verifying=lambda done,total:None,
             reserve=512 * 1024 * 1024, retries=3):
    """Publish only a fully checked file. Partial bytes survive cancellation/retry."""
    import shutil
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(destination.name + '.part')
    marker = part.with_name(part.name + '.json')
    for pending in (part,marker):
        if pending.is_symlink() or pending.exists() and getattr(pending.lstat(),'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024):
            raise ValueError('Refused a linked partial-download file.')
    identity = {key:item.get(key) for key in ('url','size','sha256','md5','git_sha1')}
    if marker.exists():
        try:previous=json.loads(marker.read_text(encoding='utf-8'))
        except (OSError,ValueError):previous=None
        if previous != identity:
            part.unlink(missing_ok=True)
    elif part.exists():
        part.unlink()
    marker.write_text(json.dumps(identity), encoding='utf-8')
    started, initial = time.monotonic(), part.stat().st_size if part.exists() else 0
    for attempt in range(retries):
        if cancelled(): raise Cancelled('Download cancelled; partial bytes retained for Retry.')
        offset = part.stat().st_size if part.exists() else 0
        total = item.get('size')
        if total is not None and offset > total:
            part.unlink(); offset = 0
        try:
            if total is None or offset != total:
                if shutil.disk_usage(destination.parent).free < max(0, (total or 0)-offset) + reserve:
                    raise OSError('Not enough free space on the model destination drive, including headroom.')
                extra = {'Range': f'bytes={offset}-'} if offset else {}
                with open_url(item['url'], token, extra) as response:
                    if response.status == 206:
                        value = response.headers.get('Content-Range', '')
                        expected_prefix = f'bytes {offset}-'
                        if not value.startswith(expected_prefix):
                            raise ValueError('Server returned an unexpected download range.')
                        range_total = value.rsplit('/',1)[-1]
                        if range_total.isdigit():
                            if total is not None and int(range_total) != total: raise ValueError('Remote file size changed.')
                            total = int(range_total)
                    elif response.status == 200:
                        if offset:
                            initial=0;started=time.monotonic()
                        offset = 0  # Range unsupported: restart honestly from byte zero.
                        length = response.headers.get('Content-Length')
                        if length and length.isdigit():
                            if total is not None and int(length) != total: raise ValueError('Remote file size changed.')
                            total = int(length)
                    else: raise ValueError('Unexpected download response.')
                    if item.get('max_size') and total and total > item['max_size']:
                        raise ValueError('Download exceeds the recipe size limit.')
                    done, last = offset, 0
                    with part.open('ab' if offset else 'wb') as stream:
                        while True:
                            if cancelled(): raise Cancelled('Download cancelled; partial bytes retained for Retry.')
                            chunk = response.read(256 * 1024)
                            if not chunk: break
                            done += len(chunk)
                            if item.get('max_size') and done > item['max_size']:raise ValueError('Download exceeds the recipe size limit.')
                            if total is not None and done > total: raise ValueError('Download exceeds its declared size.')
                            if shutil.disk_usage(destination.parent).free < len(chunk) + reserve:
                                raise OSError('Destination drive is full; partial download retained.')
                            stream.write(chunk)
                            current = time.monotonic()
                            if current-last >= .2:
                                progress(done,total,max(0,done-initial)/max(.01,current-started)); last=current
                        stream.flush(); os.fsync(stream.fileno())
                    if total is not None and done != total:
                        raise ConnectionError('Download ended before the declared size; partial bytes retained.')
            progress(part.stat().st_size,total,0)
            verifying(0,part.stat().st_size)
            result = hash_file(part, cancelled,lambda count:verifying(count,part.stat().st_size))
            if not valid(result, {**item, 'size': total}):
                part.unlink(missing_ok=True)
                raise ValueError('Checkpoint integrity check failed. Retry will download a fresh copy.')
            if item.get('format')=='zip':
                import zipfile
                try:
                    with zipfile.ZipFile(part) as bundle:
                        if sum(f.file_size for f in bundle.infolist())>512*1024*1024:raise ValueError('Source archive expands beyond its recipe limit.')
                        if bundle.testzip():raise ValueError('Source archive failed its CRC check.')
                except (zipfile.BadZipFile,ValueError):
                    part.unlink(missing_ok=True)
                    raise ValueError('Source archive is corrupt or exceeds its limit. Retry will download it again.') from None
            part.replace(destination)
            marker.unlink(missing_ok=True)
            return {'size':result['size'], 'sha256':result['sha256']}
        except error.HTTPError as exc:
            if exc.code in (401,403):
                raise ValueError('Model access denied. Review the model license/access page and set a Hugging Face token in Models if required.') from None
            if exc.code not in (408,429,500,502,503,504):
                raise ValueError(f'Model download returned HTTP {exc.code}. Check the selected revision and filenames.') from None
            if attempt == retries-1: raise ConnectionError(f'Download failed after {retries} attempts (HTTP {exc.code}).') from None
        except (error.URLError, TimeoutError, ConnectionError,http.client.IncompleteRead,http.client.RemoteDisconnected) as exc:
            if attempt == retries-1:
                raise ConnectionError('Download interrupted. Check the connection and use Retry; partial bytes are retained.') from None
        # Backoff is cancellable and never sleeps the GUI thread.
        deadline = time.monotonic() + 2**attempt
        while time.monotonic() < deadline:
            if cancelled(): raise Cancelled('Download cancelled during retry.')
            time.sleep(.1)
