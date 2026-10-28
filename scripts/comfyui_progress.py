"""Prompt-scoped native WebSocket progress; history remains the completion authority."""
import json
import math
import time


class LiveProgress:
    def __init__(self,url,client_id,graph):
        self.url=url;self.client_id=client_id;self.graph=graph;self.socket=None
        self.prompt_id=None;self.completed=set();self.node=None;self.step=None;self.total=None
        self.memory={};self.peak_allocated=0;self.available=False;self.error=None

    def connect(self):
        try:
            from websockets.sync.client import connect
            self.socket=connect(self.url.replace("http://","ws://",1)+"/ws?clientId="+self.client_id,
                open_timeout=2,close_timeout=.2,max_size=16*1024**2)
            self.available=True
        except Exception as exc:self.error=str(exc)
        return self

    def ingest(self,event):
        data=event.get("data",{});kind=event.get("type")
        if not isinstance(data,dict) or not self.prompt_id or data.get("prompt_id")!=self.prompt_id:return
        if kind=="execution_cached":self.completed.update(n for n in data.get("nodes",[]) if n in self.graph)
        elif kind=="executing":
            if self.node:self.completed.add(self.node)
            self.node=data.get("node");self.step=self.total=None
        elif kind=="progress" and data.get("node") in self.graph:
            self.node=data["node"]
            value,total=data.get("value"),data.get("max")
            if isinstance(value,(int,float)) and isinstance(total,(int,float)) and math.isfinite(value) and math.isfinite(total) and total>0:
                self.step=max(0,min(value,total));self.total=total

    def poll(self):
        if self.socket:
            for _ in range(100):
                try:
                    frame=self.socket.recv(timeout=.001)
                    if isinstance(frame,str):self.ingest(json.loads(frame))
                except TimeoutError:break
                except Exception as exc:
                    self.error=str(exc);self.available=False;self.close();break
        fraction=(len(self.completed)+(self.step/self.total if self.total else 0))/max(1,len(self.graph))
        label="ComfyUI · "+(self.graph.get(self.node,{}).get("class_type",self.node) or "queued / preparing")
        if self.node:label+=" ["+self.node+"]"
        if self.total:label+=f" · step {self.step:g}/{self.total:g}"
        if not self.available:label+=" · live events unavailable; polling completion"
        return label,.2+.6*min(1,fraction)

    def sample_memory(self,stats):
        self.memory=stats
        self.peak_allocated=max(self.peak_allocated,sum(d.get("torch_vram_total",0)-d.get("torch_vram_free",0) for d in stats.get("devices",[])))

    def snapshot(self):
        return {"time_unix":time.time(),"prompt_id":self.prompt_id,"node":self.node,"step":self.step,"total_steps":self.total,
            "completed_nodes":len(self.completed),"workflow_nodes":len(self.graph),"websocket_available":self.available,
            "host_stats":self.memory,"sampled_peak_host_torch_allocated_bytes":self.peak_allocated,"event_error":self.error,
            "progress_basis":"Completed graph nodes and active sampler steps; not a remaining-time estimate."}

    def close(self):
        if self.socket:
            try:self.socket.close()
            except Exception:pass
            self.socket=None
