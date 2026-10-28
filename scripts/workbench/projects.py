"""Versioned asset projects with owned files, provenance and atomic manifests."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
from threading import RLock
import uuid

from .schema import SHAPE_KEYS, PAINT_KEYS

_LOCK = RLock()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False, default=str)
            stream.flush()
            os.fsync(stream.fileno())
        # Windows may briefly deny replacement while a reader/antivirus holds the
        # destination open. Keep the old complete document until replacement succeeds.
        for attempt in range(20):
            try:
                os.replace(temp,path)
                break
            except PermissionError:
                if attempt==19:raise
                time.sleep(.025*(attempt+1))
    finally:
        temp.unlink(missing_ok=True)


def settings_fingerprints(settings):
    shape = {k:settings.get(k) for k in SHAPE_KEYS if k != "m_paint"}
    shape["backend"] = settings.get("backend")
    shape["m_box"] = settings.get("m_box",1.01)
    return {"Inputs": fingerprint(settings.get("preparation", {})), "Generate": fingerprint(shape),
            "Texture": fingerprint({k:settings.get(k) for k in PAINT_KEYS}),
            "Surface": fingerprint(settings.get("surface",{})),
            "Scale": fingerprint(settings.get("scale",{})),
            "Optimize": fingerprint(settings.get("optimization", {})),
            "Export": fingerprint(settings.get("export", {})),
            "Rebake": fingerprint(settings.get('rebake',{}))}


class ProjectStore:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def create(self, name):
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", (name or "asset")).strip("_")[:70] or "asset"
        folder = self.root / f"{slug}_{uuid.uuid4().hex[:10]}"
        folder.mkdir(parents=True)
        manifest = dict(schema_version=2, id=folder.name, name=name or "asset", created=now(), updated=now(),
                        source=None, accepted=None, preview=None, inputs={}, settings={}, versions=[], runs=[],
                        stage_states={}, branches=[], profile="general")
        atomic_json(folder / "project.json", manifest)
        return folder

    def folder(self, value):
        folder = Path(value).resolve()
        if folder.parent != self.root:
            raise ValueError("Select a project from this workbench's project directory.")
        return folder

    def load(self, folder):
        folder = self.folder(folder)
        manifest = json.loads((folder / "project.json").read_text(encoding="utf-8"))
        if manifest.get("schema_version") != 2:
            raise ValueError("Unsupported project schema; import the legacy snapshot into a new project.")
        for entry in manifest.get("inputs", {}).values():
            for key in ("original", "prepared", "mask"):
                if entry.get(key):
                    self.resolve(folder, entry[key])
        for key in ("source", "accepted", "preview"):
            if manifest.get(key):
                self.resolve(folder, manifest[key])
        return manifest

    def resolve(self, folder, relative, *, require=True):
        folder = self.folder(folder)
        path = (folder / relative).resolve()
        if not path.is_relative_to(folder):
            raise ValueError("Project artifact path escapes the project.")
        if require and not path.is_file():
            raise FileNotFoundError(f"Project artifact is missing: {relative}")
        return path

    @contextmanager
    def edit(self, folder):
        with _LOCK:
            manifest = self.load(folder)
            yield manifest
            manifest["updated"] = now()
            atomic_json(self.folder(folder) / "project.json", manifest)

    def choices(self):
        result = []
        for path in sorted(self.root.glob("*/project.json"), reverse=True):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
                result.append((f"{manifest['name']} · {path.parent.name[-10:]}", str(path.parent)))
            except (OSError, ValueError, KeyError):
                continue
        return result

    def own_file(self, folder, source, category="sources"):
        source = Path(source).resolve()
        sha = digest(source)
        suffix = source.suffix.lower()
        dest = self.folder(folder) / category / f"{sha}{suffix}"
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            # Copy to a private filename, then publish. Input files are never modified.
            temp = dest.with_name(dest.name + "." + uuid.uuid4().hex + ".tmp")
            shutil.copy2(source, temp)
            os.replace(temp, dest)
        return dest.relative_to(folder).as_posix()

    def store_image(self, folder, image, category):
        from io import BytesIO
        image = image.convert("RGBA")
        stream = BytesIO()
        image.save(stream, format="PNG")
        data = stream.getvalue()
        sha = hashlib.sha256(data).hexdigest()
        dest = self.folder(folder) / category / f"{sha}.png"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            temp = dest.with_name(dest.name + "." + uuid.uuid4().hex + ".tmp")
            temp.write_bytes(data)
            os.replace(temp, dest)
        return dest.relative_to(folder).as_posix()

    def snapshot(self, folder, settings, images, source=None):
        owned = {}
        for direction, image in images.items():
            if image is not None:
                owned[direction] = self.store_image(folder, image, "inputs/original")
        source_owned = self.own_file(folder, source) if source else None
        with self.edit(folder) as m:
            old = settings_fingerprints(m["settings"])
            changed = {k for k,v in settings_fingerprints(settings).items() if old.get(k) != v}
            # Invalidation is metadata; no generated geometry or old files are removed.
            dependencies = {"Inputs":["Generate","Texture","Surface","Optimize","Export","Rebake"],
                            "Generate":["Texture","Surface","Optimize","Export","Rebake"],
                            "Texture":["Surface","Optimize","Export","Rebake"],"Surface":["Optimize","Export","Rebake"],
                            "Optimize":["Export"], "Scale":["Optimize","Export"], "Export":[],
                            'Rebake':['Surface','Optimize','Export']}
            for stage in changed:
                for affected in (stage, *dependencies[stage]):
                    m["stage_states"][affected] = "settings changed / stale"
            for direction, relative in owned.items():
                entry = m["inputs"].get(direction, {})
                if entry.get("original") != relative:
                    entry = {"original":relative, "sha256":Path(relative).stem}
                    for stage in (("Texture","Surface","Optimize","Export","Rebake") if direction=="reference" else ("Generate","Texture","Surface","Optimize","Export","Rebake")):
                        m["stage_states"][stage] = "input changed / stale"
                m["inputs"][direction] = entry
            # Clearing a view is intentional and must survive reopening.
            for direction in list(m["inputs"]):
                if direction in images and images[direction] is None:
                    del m["inputs"][direction]
                    for stage in (("Texture","Surface","Optimize","Export","Rebake") if direction=="reference" else ("Generate","Texture","Surface","Optimize","Export","Rebake")):
                        m["stage_states"][stage] = "input changed / stale"
            if source_owned and not m["source"]:
                m["source"] = m["accepted"] = source_owned
            m["settings"] = settings
            m["profile"] = settings.get("profile", "general")
        return self.load(folder)

    def add_version(self, folder, path, stage, job_id, requested, warnings=(), artifacts=()):
        folder = self.folder(folder)
        path = Path(path).resolve()
        if not path.is_relative_to(folder):
            raise ValueError("Derived files must live inside their asset project.")
        relative = path.relative_to(folder).as_posix()
        with self.edit(folder) as m:
            actual_parent = requested.get("mesh") if isinstance(requested,dict) else None
            if actual_parent:
                actual_parent = self.resolve(folder,actual_parent).relative_to(folder).as_posix()
                recorded=requested.get("mesh_version")
                if recorded:
                    if not any(v["path"]==recorded for v in m["versions"]):raise ValueError("Input version is not in this project.")
                    if digest(self.resolve(folder,recorded))!=digest(self.resolve(folder,actual_parent)):raise ValueError("Input version does not match frozen mesh bytes.")
                    actual_parent=recorded
            version = dict(id=uuid.uuid4().hex[:12], stage=stage, path=relative, created=now(),
                           parent=actual_parent or m["accepted"], job_id=job_id, requested=requested, status="preview",
                           sha256=digest(path), warnings=list(warnings), artifacts=list(artifacts))
            m["versions"].append(version)
            m["preview"] = relative
            m["stage_states"][stage] = "preview ready"
            m["runs"].append(job_id)
        return version

    def accept(self, folder, label="Checkpoint"):
        with self.edit(folder) as m:
            if not m["preview"]:
                raise ValueError("There is no preview to accept.")
            m["accepted"] = m["preview"]
            if not m["source"]:
                m["source"] = m["accepted"]
            for v in m["versions"]:
                if v["path"] == m["accepted"]:
                    v.update(status="accepted", label=label or "Checkpoint")
                    m["stage_states"][v["stage"]] = "accepted"
            m["preview"] = None
        return self.resolve(folder, self.load(folder)["accepted"])

    def discard(self, folder):
        with self.edit(folder) as m:
            m["preview"] = None
        return self.resolve(folder, self.load(folder)["accepted"]) if self.load(folder)["accepted"] else None

    def select_version(self, folder, relative, branch=False):
        with self.edit(folder) as m:
            if relative not in {m["source"], m["accepted"], *[v["path"] for v in m["versions"]]}:
                raise ValueError("Select a version belonging to this project.")
            self.resolve(folder, relative)
            if branch:
                m["branches"].append(dict(created=now(), source=relative, previous=m["accepted"]))
                m["accepted"], m["preview"] = relative, None
            else:
                m["preview"] = relative
        return self.resolve(folder, relative)
