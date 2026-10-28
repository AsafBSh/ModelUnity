"""Persistent single-worker queue with cooperative cancellation and restart recovery."""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from threading import Event, Thread
import time
import traceback
import uuid
from contextlib import contextmanager
import os
import subprocess
import sys
from scripts.gpu_lifecycle import operation
from .projects import now,atomic_json

class Cancelled(Exception):
    pass

class JobQueue:
    def __init__(self, path, store, executor=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.store, self.executor = store, executor
        self.wake = Event()
        self.thread = None
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, project TEXT, stage TEXT, state TEXT, request TEXT, created TEXT, updated TEXT, progress REAL, message TEXT, result TEXT, cancel INTEGER DEFAULT 0)")
            # Migrate legacy absolute locations, including a moved portable bundle.
            # A matching owned manifest ID is required before adopting the new path.
            for row in db.execute("SELECT id,project,result FROM jobs").fetchall():
                old = Path(row["project"])
                if not old.is_absolute():
                    continue
                candidate = self.store.root / old.name
                manifest = candidate / "project.json"
                if not manifest.is_file() or json.loads(manifest.read_text(encoding="utf-8")).get("id") != old.name:
                    continue
                result = row["result"]
                if result and Path(result).is_absolute():
                    try:
                        result = Path(result).relative_to(old).as_posix()
                    except ValueError:
                        continue  # Never relocate an artifact outside its owned project.
                db.execute("UPDATE jobs SET project=?,result=? WHERE id=?",(old.name,result,row["id"]))

    def decode_row(self, row):
        if row is None:
            return None
        result = dict(row)
        location = Path(result["project"])
        folder = self.store.folder(location if location.is_absolute() else self.store.root / location)
        result["project"] = str(folder)
        if result["result"]:
            result["result"] = str(self.store.resolve(folder,result["result"],require=False))
        return result

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def start(self):
        if self.thread is not None:
            return
        # Hold an OS lock until process exit; a second server must not recover live jobs.
        self.owner = self.path.with_suffix(".lock").open("a+b")
        self.owner.seek(0)
        self.owner.write(b"0")
        self.owner.flush()
        self.owner.seek(0)
        try:
            import os
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.owner.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.owner.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:
            self.owner.close()
            raise RuntimeError("Another ModelUnify workbench owns this job queue.") from exc
        with self.connect() as db:
            db.execute("UPDATE jobs SET state='interrupted',message='Server stopped before completion; rerun explicitly.' WHERE state IN ('running','cancel_pending')")
        self.thread = Thread(target=self._loop, daemon=True, name="ModelUnifyJobs")
        self.thread.start()

    def submit(self, project, stage, request):
        self.store.load(project)
        # Store project-owned inputs as relative references so saved projects are relocatable.
        request = json.loads(json.dumps(request))
        if "configuration" not in request:
            from .runtime import CFG
            request["configuration"]=json.loads(json.dumps(CFG))
        folder = self.store.folder(project)
        for key,value in request.get("images",{}).items():
            path = Path(value)
            if path.is_absolute():
                request["images"][key] = path.resolve().relative_to(folder).as_posix()
        if request.get("mesh") and Path(request["mesh"]).is_absolute():
            request["mesh"] = Path(request["mesh"]).resolve().relative_to(folder).as_posix()
        job_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (job_id,folder.name,stage,"queued",json.dumps(request),now(),now(),0,"Queued",None,0))
        self.wake.set()
        return job_id

    def rows(self, project=None):
        with self.connect() as db:
            if project:
                folder = self.store.folder(project)
                rows = db.execute("SELECT * FROM jobs WHERE project IN (?,?) ORDER BY CASE WHEN state IN ('running','cancel_pending') THEN 0 ELSE 1 END,rowid DESC LIMIT 40", (folder.name,str(folder))).fetchall()
            else:
                rows = db.execute("SELECT * FROM jobs ORDER BY CASE WHEN state IN ('running','cancel_pending') THEN 0 ELSE 1 END,rowid DESC LIMIT 40").fetchall()
        return [self.decode_row(row) for row in rows]

    def get(self, job_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone()
        return self.decode_row(row)

    def update(self, job_id, **values):
        if values.get("result") and Path(values["result"]).is_absolute():
            folder = self.store.folder(self.get(job_id)["project"])
            values["result"] = Path(values["result"]).resolve().relative_to(folder).as_posix()
        values["updated"] = now()
        with self.connect() as db:
            db.execute("UPDATE jobs SET " + ",".join(k+"=?" for k in values) + " WHERE id=?", (*values.values(),job_id))

    def cancel(self, job_id):
        with self.connect() as db:
            row = db.execute("SELECT state FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise ValueError("Choose a job first.")
            if row["state"] == "queued":
                db.execute("UPDATE jobs SET state='cancelled',cancel=1,message='Cancelled before execution' WHERE id=?",(job_id,))
            elif row["state"] in ("running","cancel_pending"):
                db.execute("UPDATE jobs SET state='cancel_pending',cancel=1,message='Cancellation requested; waiting for safe boundary' WHERE id=?",(job_id,))

    def checkpoint(self, job_id, message, progress, memory=None):
        with self.connect() as db:
            row = db.execute("SELECT cancel FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row["cancel"]:
            raise Cancelled("Cancelled at a safe boundary; no preview was published.")
        self.update(job_id, message=message, progress=progress)
        row = self.get(job_id)
        log = self.store.folder(row["project"]) / "logs" / f"{job_id}.jsonl"
        log.parent.mkdir(parents=True,exist_ok=True)
        sample = {"time":now(),"stage":message,"progress":progress}
        try:
            import torch
            if memory is not None:
                sample["gpu"] = memory
                sample["memory_source"] = "inference worker"
            elif torch.cuda.is_available():
                free,total = torch.cuda.mem_get_info()
                sample["gpu"] = {"device_free_bytes":free,"device_total_bytes":total,
                                 "torch_allocated_bytes":torch.cuda.memory_allocated(),"torch_reserved_bytes":torch.cuda.memory_reserved()}
                sample["memory_source"] = "UI process / global device free memory"
        except Exception as exc:
            sample["telemetry_error"] = str(exc)
        with log.open("a",encoding="utf-8") as stream:
            stream.write(json.dumps(sample)+"\n")

    def _loop(self):
        while True:
            with self.connect() as db:
                row = db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY rowid LIMIT 1").fetchone()
                if row:
                    db.execute("UPDATE jobs SET state='running' WHERE id=?",(row["id"],))
            if not row:
                self.wake.wait(2)
                self.wake.clear()
                continue
            self.run(self.decode_row(row))

    def child_execute(self,row,request,private):
        folder=self.store.folder(row["project"])
        logdir=folder/"logs"
        logdir.mkdir(exist_ok=True)
        prefix=logdir/row["id"]
        request_path=prefix.with_suffix(".request.json")
        status_path=prefix.with_suffix(".progress.json")
        result_path=prefix.with_suffix(".result.json")
        cancel_path=prefix.with_suffix(".cancel")
        stdout_path=prefix.with_suffix(".log")
        atomic_json(request_path,request)
        script=Path(__file__).with_name("worker.py")
        options={"creationflags":subprocess.CREATE_NO_WINDOW} if os.name=="nt" else {}
        environment={**os.environ,"PYTHONUTF8":"1","PYTHONIOENCODING":"utf-8","PYTHONFAULTHANDLER":"1"}
        last=None
        with stdout_path.open("wb") as log:
            process=subprocess.Popen([sys.executable,"-u",str(script),str(request_path),row["stage"],str(private),
                str(status_path),str(cancel_path),str(result_path)],cwd=script.parents[2],env=environment,
                stdout=log,stderr=subprocess.STDOUT,**options)
            while process.poll() is None:
                current=self.get(row["id"])
                if current["cancel"]:cancel_path.touch(exist_ok=True)
                if status_path.exists():
                    try:
                        sample=json.loads(status_path.read_text(encoding="utf-8"))
                        if sample!=last:
                            # Preserve cancel_pending until the worker acknowledges at its next boundary.
                            if not current["cancel"]:
                                self.checkpoint(row["id"],sample["message"],sample["progress"],sample.get("gpu"))
                            last=sample
                    except (OSError,ValueError):pass
                time.sleep(.3)
        result=json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else None
        if result and result["state"]=="cancelled":raise Cancelled(result["message"])
        if process.returncode!=0 or not result or result["state"]!="completed":
            message=result.get("message") if result else f"Native worker exited with code {process.returncode}; no result was published."
            raise RuntimeError(f"{message} Log: {stdout_path}")
        return Path(result["output"]),result["report"]

    @operation()
    def run(self, row):
        job_id = row["id"]
        try:
            request = json.loads(row["request"])
            folder = self.store.folder(row["project"])
            runtime_request = json.loads(json.dumps(request))
            runtime_request["images"] = {k:str(self.store.resolve(folder,v)) for k,v in request.get("images",{}).items()}
            if request.get("mesh"):
                runtime_request["mesh"] = str(self.store.resolve(folder,request["mesh"]))
            if request.get('high_mesh'):
                runtime_request['high_mesh']=str(self.store.resolve(folder,request['high_mesh']))
            private = folder / "jobs" / (job_id + ".working")
            published = folder / "jobs" / job_id
            if self.executor is None:
                result,report=self.child_execute(row,runtime_request,private)
            else:
                executor = self.executor
                result, report = executor(row["stage"],runtime_request,private,
                                      lambda message,progress:self.checkpoint(job_id,message,progress))
            self.checkpoint(job_id,"Publishing validated preview", .99)
            relative = Path(result).relative_to(private)
            private.rename(published)
            result = published / relative
            self.store.add_version(folder,result,row["stage"],job_id,request,
                                   report.get("warnings",()),[str(p.relative_to(folder)) for p in published.rglob("*") if p.is_file()])
            if row["stage"] == "Generate":
                with self.store.edit(folder) as manifest:
                    for direction,info in report.get("preparation",{}).items():
                        entry = manifest["inputs"].get(direction)
                        # A running request can finish after the user changed inputs.
                        if entry and str(self.store.resolve(folder,entry["original"])) == runtime_request["images"].get(direction):
                            entry.update(prepared=str((published/f"{direction}_prepared.png").relative_to(folder)),
                                         mask=str((published/f"{direction}_mask.png").relative_to(folder)),preparation=info)
            message="Preview ready; inspect and accept/checkpoint."
            if report.get("warnings"):
                message+=" Warnings: "+" ".join(report["warnings"])
            self.update(job_id,state="completed",progress=1,result=str(result),message=message)
        except Cancelled as exc:
            self.update(job_id,state="cancelled",message=str(exc))
        except Exception as exc:
            traceback.print_exc()
            self.update(job_id,state="failed",message=f"{type(exc).__name__}: {exc}")
