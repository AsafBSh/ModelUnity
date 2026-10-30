"""ModelUnify CAD Mesh Workbench using the real local backends.

Run: .venv/Scripts/python.exe -m scripts.workbench_preview --port 7861
The existing web_ui.py and port 7860 remain available.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0,str(_ROOT))
from scripts.workbench import viewer as view
from scripts.workbench import layout
from scripts.workbench import models_ui
from scripts.workbench.schema import VIEWS
from scripts.workbench.schema import PARAMETERS
from scripts.workbench.projects import atomic_json
from scripts._version import MODELUNIFY_VERSION
from scripts.app_identity import instance_marker

import gradio as gr
from gradio.themes.utils.fonts import LocalFont

from scripts import workbench_service as svc

app = svc.app

CSS = """
* { box-sizing:border-box; }
html, body { height:100%; margin:0; overflow:hidden !important; background:#09181d; }
.gradio-container { width:100% !important; max-width:none !important; height:100dvh !important;
    padding:10px 12px !important; overflow:hidden !important; }
.gradio-container > .main, .gradio-container > .main > .wrap,
.gradio-container main.contain, .gradio-container main.contain > .column {
    height:100%; min-height:0 !important; }
.gradio-container > .main, .gradio-container main.contain { padding:0 !important; }
.gradio-container main.contain > .column { gap:8px !important; }
.gradio-container .column { min-width:0 !important; }
#app-header { flex:0 0 auto; align-items:center; gap:12px; }
#app-header > .column:last-child { flex:0 0 112px !important; }
#app-header button { white-space:nowrap; font-size:12px; }
#masthead { display:flex; gap:12px; align-items:center; height:58px; }
#masthead img { width:54px; height:54px; object-fit:contain; border-radius:9px; margin:0; }
#masthead h1 { color:#c5fbf2; font-size:25px; font-weight:750; margin:0; letter-spacing:2px; line-height:1.1; }
#masthead p { color:#7ca6ae; margin:4px 0 0; font-size:11px; letter-spacing:1px; }
#telemetry { padding:7px 11px; border:1px solid #25574f; border-left:3px solid #5cdbb5;
    background:#102c2a; border-radius:6px; font-size:11px; max-height:54px; overflow:auto; }
#asset-toolbar { flex:0 0 auto; align-items:center; gap:8px; }
#asset-toolbar .form { border:0; background:transparent; gap:8px; }
#asset-toolbar .block { padding:5px 8px; }
#asset-toolbar textarea { min-height:30px !important; padding:5px 8px; }
#asset-toolbar label { font-size:11px; }
#workflow-nav { flex:0 0 auto; border:0; background:transparent; padding:0; }
#workflow-nav .wrap { gap:6px; }
#workflow-nav label { flex:1; justify-content:center; padding:7px 10px; font-size:12px; font-weight:600; }
#workflow-nav label.selected { background:#164a49; border-color:#4ce0cb; color:#bdfbef; }
#workspace { display:grid !important; grid-template-columns:340px minmax(200px,1fr) 310px;
    gap:10px !important; flex:1 1 0 !important; min-height:0 !important; overflow:hidden; }
#controls, #inspectors { height:100%; min-height:0 !important; overflow-y:scroll !important;
    overflow-x:hidden; scrollbar-gutter:stable; background:#10232b; border:1px solid #24434b;
    border-radius:8px; padding:10px; display:block !important; }
#controls > *, #inspectors > * { margin-bottom:8px; }
/* Native, persistent, deliberately wide scrollbars on Windows/Chromium. */
.gradio-container * { scrollbar-width:auto; }
.gradio-container *::-webkit-scrollbar { width:16px; height:16px; }
.gradio-container *::-webkit-scrollbar-track { background:#174247; border-radius:8px; }
.gradio-container *::-webkit-scrollbar-thumb { background:#75ebd2; border:2px solid #174247; border-radius:9px; min-height:48px; }
.gradio-container *::-webkit-scrollbar-thumb:hover { background:#85ead3; }
#stage-tabs > .tab-wrapper { display:none; }
#controls [role=tabpanel] { padding:0; }
#view-inputs { border:1px solid #2e625e; border-radius:6px; padding:6px; }
#view-inputs .row { gap:6px; }
#view-inputs .form { min-width:0 !important; }
#view-inputs [data-testid=block-label] { font-size:10px; }
#view-inputs .wrap { font-size:11px; }
#viewport { height:100%; min-height:0 !important; overflow:hidden; gap:8px; }
#viewport-tools { flex:0 0 auto; gap:6px; }
#viewport-tools .form { min-width:0 !important; }
#viewport-tools .block { padding:5px; }
#viewport-tools label { font-size:11px; padding:5px 7px; }
#workbench-viewer { flex:1 1 0 !important; height:0 !important; min-height:160px !important; }
#workbench-viewer > div, #workbench-viewer canvas { max-height:100%; }
#stage-status { flex:0 0 76px; height:76px; min-height:0; overflow:auto !important;
    border-left:3px solid #56d6aa; padding:7px 10px; background:#102b28; border-radius:5px; font-size:11px; }
#inspectors .tab-container button { padding:7px 8px; font-size:11px; }
#inspectors [role=tabpanel] { padding:8px 0 0; }
#inspectors .prose p, #inspectors .prose li { font-size:11px; }
#asset-summary h3 { margin:0 0 6px; font-size:16px; color:#9cebd8; }
#asset-summary p { font-size:11px; overflow-wrap:anywhere; }
.panel-title { color:#75dcca; font:600 10px monospace; letter-spacing:1.5px; margin:2px 0 4px; }
.capability { border-left:2px solid #4cbcae; padding:0 8px; margin:4px 0 8px; }
.capability p { font-size:11px; color:#a9c9cd; }
.gradio-container footer { display:none !important; }
@media(max-width:1250px) { #workspace { grid-template-columns:290px minmax(180px,1fr) 270px; } }
@media(max-height:760px) { #masthead {height:46px;} #masthead img {width:43px;height:43px;} }

/* Visual finish: locally served type, restrained depth and clear action hierarchy. */
.gradio-container {
    --mu-text:#e0edf2; --mu-muted:#8fa8b4; --mu-accent:#62e6ce;
    --mu-border:#293e4a; --mu-surface:#13212b;
    --mu-font-ui:"IBM Plex Sans","Segoe UI Variable Text","Segoe UI",sans-serif;
    --mu-font-display:"Montserrat","IBM Plex Sans","Segoe UI",sans-serif;
    --mu-font-mono:"IBM Plex Mono","Cascadia Code",monospace;
    --font:var(--mu-font-ui); --font-mono:var(--mu-font-mono);
    background:radial-gradient(ellipse at 5% 0%,#16333066,transparent 38%),#0b121c;
    color:var(--mu-text); -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility;
}
.gradio-container, .gradio-container :is(button,input,textarea,select,.prose) {
    font-family:var(--mu-font-ui) !important;
}
.gradio-container :is(button,input,textarea,select) { font-size:13px; }
.gradio-container :is(button,input,textarea,select):focus-visible {
    outline:2px solid #73e6d2 !important; outline-offset:2px;
}
#masthead { gap:13px; }
#masthead img { border:1px solid #5da99f66; box-shadow:0 0 0 4px #4fe1c708,0 6px 18px #0005; }
#masthead h1 {
    font-family:var(--mu-font-display) !important; font-size:23px;
    font-weight:700; letter-spacing:.65px; color:#e4faf5;
}
#masthead p { color:#7eaba9; font-size:10px; letter-spacing:1.65px; font-weight:600; }
#telemetry {
    background:linear-gradient(110deg,#15352eaa,#13242caa); border:1px solid #2d534b;
    border-left:3px solid #69d6ab; border-radius:10px; color:#a5c4bf; font-size:12px;
}
#telemetry strong { font-weight:600; color:#d7efe6; }
#asset-toolbar .block {
    border:1px solid #263d48 !important; border-radius:10px !important;
    background:linear-gradient(120deg,#14232e,#111c27) !important;
}
#asset-toolbar label { color:#8daab6; font-size:11px; font-weight:600; }
.gradio-container :is(input,textarea), .gradio-container [role=combobox] {
    border-radius:7px !important; color:#deebf1;
}
.gradio-container :is(input,textarea):focus { box-shadow:0 0 0 2px #44cbb52b; }
.gradio-container button.primary, .gradio-container button.secondary {
    border-radius:10px !important; border:1px solid transparent !important;
    font-size:13px; font-weight:600; letter-spacing:.1px;
    transition:background .15s ease,border-color .15s ease,box-shadow .15s ease,transform .15s ease;
}
.gradio-container button.secondary {
    color:#c8d9e1 !important; background:linear-gradient(180deg,#203440,#182832) !important;
    border-color:#35505f !important; box-shadow:inset 0 1px 0 #ffffff08,0 2px 5px #0002;
}
.gradio-container button.secondary:not(:disabled):hover {
    color:#edfffa !important; border-color:#5caa9f !important;
    background:linear-gradient(180deg,#294b51,#203c43) !important;
    box-shadow:0 0 0 2px #4edbc412,0 4px 12px #0003;
}
.gradio-container button.primary {
    color:#062d27 !important; background:linear-gradient(115deg,#75ead0,#39c8b6) !important;
    border-color:#92f1dd88 !important; box-shadow:inset 0 1px 0 #e9fff866,0 4px 15px #2ad1b522;
}
.gradio-container button.primary:not(:disabled):hover {
    background:linear-gradient(115deg,#a0f3dc,#63e3ce) !important;
    box-shadow:0 0 0 3px #54e0c918,0 5px 18px #2ad1b532;
}
.gradio-container button.primary:not(:disabled):active,
.gradio-container button.secondary:not(:disabled):active { transform:translateY(1px); }
.gradio-container button:disabled { opacity:.45; box-shadow:none !important; }
#workflow-nav .wrap {
    padding:4px; border:1px solid #263b48; border-radius:13px;
    background:linear-gradient(180deg,#15232f,#101b25); gap:5px;
}
#workflow-nav label {
    position:relative; border:1px solid transparent; background:transparent;
    color:#90a7b5; border-radius:9px; padding:8px 10px; font-size:13px;
    transition:color .15s ease,background .15s ease,border-color .15s ease;
}
#workflow-nav label:hover { color:#d3ebe7; background:#203841; }
#workflow-nav label.selected {
    color:#aeffea; background:linear-gradient(110deg,#205249,#1c3e47);
    border-color:#448f8266; box-shadow:inset 0 1px 0 #b9ffec14,0 2px 6px #0003;
}
/* The actual radio remains a full-size accessible click/keyboard target. */
#workflow-nav input[type=radio], #viewport-tools input[type=radio] {
    position:absolute !important; inset:0; width:100% !important; height:100% !important;
    opacity:0; margin:0; cursor:pointer; border-radius:inherit; z-index:1;
}
#workflow-nav label:focus-within, #viewport-tools label:focus-within {
    outline:2px solid #73e6d2; outline-offset:1px;
}
#controls, #inspectors {
    background:linear-gradient(160deg,#162733cc,#111e29e8);
    border:1px solid #2a414d; border-radius:13px;
    box-shadow:inset 0 1px 0 #ffffff04,0 8px 24px #0002;
}
.panel-title { color:#7bacb3; font-family:var(--mu-font-display); font-size:10px; letter-spacing:1.65px; font-weight:600; }
#view-inputs { background:#18322f55; border-color:#345d5777; border-radius:10px; padding:7px; }
/* Gradio retains nested Group shells when its children become hidden. */
#view-inputs:not(:has(#view-front)) { display:none !important; }
#view-inputs #view-inputs { border:0; padding:0; background:transparent; }
/* Keep uploaded values mounted while other workflow stages use the settings panel. */
body:has(#workflow-nav input[value="texture"]:checked) #view-inputs,
body:has(#workflow-nav input[value="optimize"]:checked) #view-inputs,
body:has(#workflow-nav input[value="export"]:checked) #view-inputs { display:none !important; }
#view-inputs .prose { font-size:12px; color:#b7d9ce; }
#view-inputs [data-testid=block-label] { background:#162b32; color:#bad8d9; border-radius:5px; }
#view-inputs [data-testid=image] { background:linear-gradient(145deg,#152e37,#111e2a); }
#view-inputs button[aria-dropeffect=copy]:hover { background:#47d5b80a; }
#controls .block:has(>button.label-wrap) {
    border:1px solid #304854 !important; border-radius:10px !important; box-shadow:none !important;
}
#controls button.label-wrap { font-size:13px; color:#c5dcdf; }
#controls .block { border-color:#2a414c; border-radius:9px; }
#controls label:has(input[type=radio]), #controls label:has(input[type=checkbox]) {
    border-radius:8px; background:#1b2f3b; border-color:#344c58; color:#aec3cd; font-size:12px;
}
#controls label.selected { background:#20473f; border-color:#408a79; color:#c7f8e9; }
#controls .prose { font-size:12px; }
.capability { border-color:#4caa9b; background:#0e20284d; border-radius:0 8px 8px 0; padding:4px 9px; }
.capability p { font-size:12px; line-height:1.5; color:#9fb9c5; }
.capability strong { color:#cbe6e7; font-weight:600; }
#viewport-tools .form { border:1px solid #2b424f; border-radius:10px; background:#14232d; }
#viewport-tools .block { border:0; background:transparent; padding:5px; }
#viewport-tools label { position:relative; border-radius:7px; background:transparent; color:#8da8b7; font-size:12px; }
#viewport-tools label:hover { background:#203a43; color:#d1eee9; }
#viewport-tools label.selected { background:#2a4b4d; color:#bdfff0; box-shadow:inset 0 1px 0 #a8f5dd12; }
#workbench-viewer { border:1px solid #2b4851; border-radius:12px; box-shadow:inset 0 0 32px #0004; }
#workbench-viewer [data-testid=block-label] { border-radius:0 0 8px 0; background:#152631dd; color:#8caebc; font-size:11px; }
#stage-status { background:linear-gradient(110deg,#13312b,#12272b); border:1px solid #2c5148; border-left:3px solid #60d7b0; border-radius:10px; font-size:12px; }
#inspectors .tab-wrapper { border-bottom:1px solid #2a414e; }
#inspectors .tab-container button { color:#8faab8; font-size:12px; font-weight:600; padding:8px; }
#inspectors .tab-container button.selected { color:#87edd3; border-color:#55d9bc; }
#inspectors .prose p, #inspectors .prose li { font-size:12px; color:#a7c0cd; line-height:1.5; }
#asset-summary h3 { font-size:17px; font-weight:600; letter-spacing:-.3px; }
#inspectors .block { border-radius:10px; border-color:#2e4754; }
@media(prefers-reduced-motion:reduce) { .gradio-container * { transition:none !important; } }

/* Precision CAD: compact drafting surfaces with semantic color and visible controls. */
.gradio-container {background:#0c1420;color:#deebf4;}
.gradio-container, .gradio-container :is(button,input,textarea,select,.prose,label,span) {
 font-family:var(--mu-font-ui)!important;}
.gradio-container :is(button,input,textarea,[role=combobox],.block),
#controls,#inspectors,#workbench-viewer,#stage-status,#telemetry,#asset-toolbar .block,
#controls label,#viewport-tools .form,#viewport-tools label,#workflow-nav label {
 border-radius:3px!important;box-shadow:none!important;}
#controls,#inspectors {background:#111e2d;border-color:#2b4359;}
#masthead h1 {font-size:24px;letter-spacing:2.1px;color:#e4f7fc;}
#masthead p {color:#55d5c4;}
#masthead img {border:0;box-shadow:none;}
#workflow-nav label {background:#152334;border:1px solid #30445c;color:#9db2c8;}
#workflow-nav label.selected {background:#124944;border-color:#45d9c1;color:#c2fff2;}
#controls .primary,#checkpoint-tools .primary {background:#43d3bb!important;border-color:#69e6d0!important;color:#08281f!important;font-weight:700;}
#controls .primary:hover,#checkpoint-tools .primary:hover {background:#71ead1!important;}
#controls input[type=range] {accent-color:#4cdac4;}
#inspectors .tab-container button {border-top:2px solid transparent;}
#inspectors .tab-container button.selected {color:#c7b8ff;border-color:#9c81e9;}
#telemetry,#stage-status {background:#112b2b;border:1px solid #29594d;border-left:3px solid #54d69c;}
#stage-status:has(.mu-warning){background:#332716;border-color:#78613c;border-left-color:#e3b35e;}
#stage-status:has(.mu-failed){background:#321e29;border-color:#784254;border-left-color:#ed879b;}
#material-tools,#checkpoint-tools {flex:0 0 auto;gap:5px;align-items:center;}
#material-tools .block,#checkpoint-tools .block {padding:4px 6px;min-width:0;}
#material-tools label {font-size:11px;}
#material-tools .form {min-width:0;}
#checkpoint-tools button {font-size:12px;padding:6px;}
#workbench-viewer {display:flex!important;flex-direction:column;overflow:hidden;background:#0b111a;}
#workbench-viewer > div {height:100%;min-height:0;flex:1;}
.gradio-container *::-webkit-scrollbar-track {background:#1b3047;border-radius:2px;}
.gradio-container *::-webkit-scrollbar-thumb {background:#54cfbd;border:3px solid #1b3047;border-radius:3px;}
#controls .capability {border-left-color:#4ddac4;background:#132b36;}
#controls .prose strong {color:#d0eee9;}
#inspectors .prose strong {color:#c0b4f5;}
@media(max-width:1050px){#workspace{grid-template-columns:270px minmax(170px,1fr) 240px;}}
@media(max-height:760px){#stage-status{flex-basis:56px;height:56px;}#masthead{height:40px;}#app-header{gap:6px;}}

/* Shared typography and alignment for the dense, single-window CAD workspace. */
.gradio-container {font-size:13px;line-height:1.45;font-weight:400;}
.gradio-container :is(code,pre,kbd), .gradio-container :is(code,pre,kbd) * {
    font-family:var(--mu-font-mono)!important;font-size:11px;font-variant-ligatures:none;
}
.gradio-container :is(input[type=number],.number), #telemetry {font-variant-numeric:tabular-nums;}
#masthead h1 {font-family:var(--mu-font-display)!important;font-size:24px;font-weight:700;letter-spacing:1.2px;}
#masthead p {font-size:10px;line-height:1.5;letter-spacing:1.6px;}
.panel-title {
    font-family:var(--mu-font-display)!important;font-weight:700;font-size:9px;
    line-height:1.6;letter-spacing:1.15px;text-align:center;padding:5px 0 7px;margin:0;
}
.gradio-container :is(button.primary,button.secondary) {
    display:flex;align-items:center;justify-content:center;text-align:center;
    font-size:13px;line-height:1.3;font-weight:600;letter-spacing:.1px;
}
#asset-toolbar {align-items:stretch;}
#asset-toolbar .block {padding:7px 10px;border-radius:12px!important;}
#asset-toolbar :is(textarea,input,[role=combobox],.input-container,.wrap.inner) {
    border-radius:8px!important;
}
#asset-toolbar [data-testid=block-info] {
    display:block;width:100%;text-align:center;font-size:11px;font-weight:600;
    line-height:1.4;letter-spacing:.25px;color:#a7bfce;margin-bottom:5px;
}
#asset-toolbar > button {
    align-self:stretch;height:auto;min-height:0;border-radius:12px!important;
}
#project-name textarea {text-align:center;line-height:20px;}
#workflow-nav label, #workflow-nav label span {
    font-family:var(--mu-font-display)!important;font-size:11px;font-weight:700;line-height:1.35;
}
#workflow-nav label, #viewport-tools label {
    display:flex;align-items:center;justify-content:center;text-align:center;min-height:34px;
}
#workflow-nav label {padding:8px;}
#workflow-nav label span, #viewport-tools label span {text-align:center;}
#view-hint {padding:7px 6px 9px!important;background:transparent!important;}
#view-hint .prose, #view-hint .prose p {
    text-align:center;font-size:12px;line-height:1.5;color:#a9c5d0;margin:0;
}
#view-hint .prose p + p {margin-top:5px;}
#view-hint .prose strong {font-size:13px;font-weight:600;color:#e0f5f0;}
#view-inputs {padding:8px;}
#view-inputs .row {gap:7px;}
#view-inputs [data-testid=block-label] {
    display:flex;align-items:center;justify-content:center;gap:6px;
    top:0;left:0;width:100%;height:25px;padding:4px 8px;margin:0;
    border:0;border-bottom:1px solid #2e4b56;border-radius:0;
    background:#1b333f;color:#c0e4e5;text-align:center;
    font-size:11px;font-weight:600;line-height:16px;letter-spacing:.25px;
}
#view-inputs [data-testid=block-label] > span {margin:0;}
#view-inputs [data-testid=image] {padding-top:25px;}
#view-inputs button[aria-dropeffect=copy] {padding:0 4px;}
#view-inputs button[aria-dropeffect=copy] .wrap {
    display:flex;flex-direction:column;align-items:center;justify-content:center;
    text-align:center;font-size:11px;font-weight:400;line-height:15px;gap:0;
    width:100%;height:100%;min-height:0;padding:5px 0;
}
#view-inputs button[aria-dropeffect=copy] .icon-wrap {width:21px;height:21px;margin:0 0 5px;color:#74dac9;}
#view-inputs button[aria-dropeffect=copy] .or {font-size:10px;line-height:14px;color:#7897a8;}
#controls button.label-wrap {font-size:12px;font-weight:600;line-height:1.4;}
#controls .prose :is(h3,h4), #asset-summary h3 {
    font-family:var(--mu-font-display)!important;font-weight:700;line-height:1.4;
}
#controls .prose :is(h3,h4) {font-size:12px;letter-spacing:.1px;}
#controls .prose, #inspectors .prose {line-height:1.55;}
#inspectors .tab-container button {font-size:12px;line-height:1.4;}
#stage-status {line-height:1.5;}
"""
CSS += layout.CSS

TRIPO_INFO = """**TripoSG 1.5B · single image → shape**

Uses the Front image. Outputs a GLB plus an editable OBJ companion. Optional
planar projection copies the photograph onto the mesh; PBR painting is a separate step.

**Background:** BRIA RMBG-1.4, rembg's default U²-Net, or none.
**Runtime:** NVIDIA CUDA supported; configurable CPU fallback is slow.
No text-to-3D or Turbo decoder is wired in this wrapper.
"""
MV_INFO = """**Hunyuan3D-2mv · 1–4 views → shape**

Accepts any nonempty subset of Front / Left / Back / Right. Inputs preparation is authoritative for every view. Existing alpha can be preserved; no hidden second background removal occurs.

Shape-only outputs GLB, with optional planar projection. Enable the real chained
PBR pipeline below, or paint later in Texture. NVIDIA CUDA supported; CPU shape
fallback is slow. Text-to-3D and FlashVDM/Turbo are not integrated.
"""
PAINT_INFO = """**Hunyuan3D-2.1 Paint · mesh + reference → PBR**

Paints the current asset using the Texture reference image. The current wrapper
exports textured GLB and editable OBJ/MTL companions. glTF packs **roughness in G,
metallic in B**. Normal baking is a separate post-paint operation below.

**Requires NVIDIA CUDA**, compiled custom_rasterizer and RealESRGAN weights.
Low-VRAM mode requests mmgp offload; the completion report states whether it
actually ran. Install and verify its checkpoints in Models before painting.
"""
NORMAL_INFO = """Off retains existing normals. Low uses the mesh-derived NumPy baker;
Medium uses StableNormal; High uses Marigold. AI normal bakers run after paint
has unloaded. Install their weights/code through Models first. Failures can fall back to Low;
the operation report records the actual baker when a map is produced."""

COMFY_INFO = """**Native ComfyUI 3D · isolated Windows / NVIDIA CUDA runtime**

TRELLIS.2 uses one Front image. Pixal3D supports one image or a dedicated
multiview checkpoint for 1–4 fixed-orbit directions. Multiview needs equal
framing and 90° camera intervals; it cannot calibrate arbitrary photographs.

Default Comfy-Org diffusion checkpoints use INT8 weights. Spatial resolutions
512 / 1024 / 1536 trade detail for memory and runtime; accuracy is not guaranteed.
Optional PBR exports base colour, metallic and roughness with UVs. The raw
decoded master is retained before explicitly configured working-mesh cleanup. Normals / AO are
separate Surface Lab operations. Scale is normalized, not measured.

Generation never installs packages or downloads checkpoints. Use Models for
runtime/checkpoint installation; check readiness below. AMD / Intel GPU support is unvalidated.
Use an isolated foreground on transparent or black background. For ordinary
photos, select a remover in Inputs; retaining a scene background can reconstruct
the background instead of the intended object.
"""


def build():
    from scripts.model_manager.service import get_manager
    model_manager = get_manager(app.ROOT,app.CFG)
    initial = svc.default_asset()
    summary, details, maps, _ = svc.inspect_asset(initial)
    params = {}
    prep = {}
    surface = {}

    def field(key, cls, *args, **kwargs):
        kwargs.setdefault("elem_id", key)
        if key in PARAMETERS:
            kwargs.setdefault("info",PARAMETERS[key][4])
        component = cls(*args, **kwargs)
        params[key] = component
        return component

    with gr.Blocks(title="ModelUnify · Mesh Workbench", analytics_enabled=False, fill_width=True) as demo:
        project = gr.State(None)
        last_job = gr.State(None)
        seen_preview = gr.State(None)
        job_stamp = gr.State(None)
        fit_count = gr.State(0)
        source = gr.State(initial)
        # A value component emits a frontend change after nonqueued timer updates;
        # State.change is not consistently dispatched by Gradio's timer transport.
        current = gr.Textbox(value=initial,visible=False)
        displayed = gr.Textbox(value=initial,visible=False)
        with gr.Row(elem_id="app-header"):
            with gr.Column(scale=4, min_width=260):
                logo = app._load_logo_data_url()
                gr.HTML('<div id="masthead">' + (f'<img src="{logo}" alt="ModelUnify logo">' if logo else '')
                        + f'<div><h1>MODELUNIFY</h1><p>MESH WORKBENCH · LOCAL / v{MODELUNIFY_VERSION}</p></div></div>')
            with gr.Column(scale=7, min_width=250):
                gpu = gr.Markdown(svc.telemetry(), elem_id="telemetry")
            with gr.Column(scale=1, min_width=120):
                refresh_gpu = gr.Button("Refresh GPU", min_width=120)
                gr.HTML(html_template=layout.RESET,elem_id="layout-reset-control",min_height=0)
        with gr.Row(equal_height=False, elem_id="asset-toolbar") as asset_toolbar:
            name = gr.Textbox(value="workbench_asset", label="Project / asset name", scale=2, elem_id="project-name")
            existing = gr.Dropdown(svc.assets(), value=initial, label="Project meshes on disk", scale=4)
            open_asset = gr.Button("Open asset", scale=1, min_width=100)
            new_asset = gr.Button("New asset",scale=1,min_width=85)
            models_button = gr.Button('Models',scale=1,min_width=100,elem_id='models-button')

        stage = gr.Radio([("01 Inputs", "inputs"), ("02 Generate", "generate"), ("03 Texture", "texture"),
                          ("04 Optimize", "optimize"), ("05 Export", "export")], value="inputs",
                         label="Workflow", show_label=False, elem_id="workflow-nav")

        with gr.Row(equal_height=False, elem_id="workspace") as mesh_workspace:
            with gr.Column(scale=4, min_width=380, elem_id="controls"):
                gr.HTML('<div class="panel-title">OPERATION SETTINGS · SCROLL FOR MORE</div>')
                model_readiness = gr.Markdown('Model files are checked before AI operations.',elem_id='mm-inline-readiness')
                manage_required = gr.Button('Manage required models',elem_id='mm-manage-required')
                with gr.Group(elem_id="view-inputs") as view_inputs:
                    view_hint = gr.Markdown("**Reference views · Hunyuan3D-2mv**\n\nUpload 1–4 directions: Front, Left, Back and Right.", elem_id="view-hint")
                    with gr.Row():
                        front = gr.Image(type="pil", image_mode='RGBA', format='png', label="Front", height=125, min_width=0, sources=["upload"], elem_id="view-front")
                        left = gr.Image(type="pil", image_mode='RGBA', format='png', label="Left", height=125, min_width=0, sources=["upload"], elem_id="view-left")
                    with gr.Row() as rear_views:
                        back = gr.Image(type="pil", image_mode='RGBA', format='png', label="Back", height=125, min_width=0, sources=["upload"], elem_id="view-back")
                        right = gr.Image(type="pil", image_mode='RGBA', format='png', label="Right", height=125, min_width=0, sources=["upload"], elem_id="view-right")
                    rig_confirm=field("input_confirm_rig",gr.Checkbox,value=False,visible=False,label="These are matched fixed-orbit views",
                        info="Pixal: named sides at 90° intervals, equal scale/framing, shared FOV; camera poses cannot be inferred by these checks.")
                    check_references=gr.Button("Check reference inputs",elem_id="check-references")
                    with gr.Accordion("Input readiness / framing findings",open=False):
                        input_report=gr.JSON(label="CPU checks · camera poses require visual verification",elem_id="input-readiness")
                with gr.Tabs(elem_id="stage-tabs") as workflow:
                    with gr.Tab("1 Inputs", id="inputs"):
                        with gr.Accordion("Import a GLB", open=False):
                            upload = gr.File(label="Upload GLB", file_types=[".glb"], type="filepath", height=150)
                        gr.Markdown("#### Background & image preparation")
                        prep_provider = gr.Radio([("Keep input / alpha", "none"), ("rembg", "rembg"), ("BRIA RMBG-1.4", "rmbg")], value="none", label="Background-removal provider")
                        prep_model = gr.Dropdown(["u2net", "u2netp", "isnet-general-use", "silueta"], value="u2net", label="rembg model", info="Used only by rembg. Install the selected model in Models before preparation.")
                        prep_view = gr.Radio(["Front", "Left", "Back", "Right"], value="Front", label="View to inspect preparation")
                        prep_size = gr.Slider(256, 2048, value=1024, step=64, label="Square output size (px)")
                        prep_crop = gr.Textbox(label="Optional crop: left,top,right,bottom")
                        prep["margin"] = gr.Slider(0, .4, value=.05, step=.01, label="Padding margin per side")
                        prep["background"] = gr.Radio(["transparent", "white", "black"], value="transparent", label="Preparation preview background", info="The alpha master is retained; TripoSG receives a white composite.")
                        prep["preserve_alpha"] = gr.Checkbox(value=True, label="Preserve existing alpha; skip remover")
                        with gr.Accordion("Advanced rembg mask settings", open=False):
                            prep["execution"] = gr.Radio(["CPUExecutionProvider", "CUDAExecutionProvider"], value="CPUExecutionProvider", label="ONNX provider", info="CUDA requires a CUDA-enabled ONNX Runtime. CPU works for preprocessing on any vendor.")
                            prep["alpha_matting"] = gr.Checkbox(value=False, label="Alpha matting · rembg only")
                            prep["foreground"] = gr.Slider(0,255,value=240,step=1,label="Foreground threshold")
                            prep["background_threshold"] = gr.Slider(0,255,value=10,step=1,label="Background threshold")
                            prep["erode"] = gr.Slider(0,100,value=10,step=1,label="Matting erosion size")
                            prep["postprocess"] = gr.Checkbox(value=False,label="Mask postprocessing · rembg only")
                        prep_go = gr.Button("Preview preparation & mask", variant="primary")
                        prepared_image = gr.Image(label="Prepared view · originals retained",interactive=False,height=180)
                        prepared_mask = gr.Image(label="Alpha mask",interactive=False,height=140)
                        prepared_overlay = gr.Image(label="Mask edges / framing guide",interactive=False,height=180)
                        with gr.Accordion('Manual mask correction',open=False):
                            gr.Markdown('Load the selected view, then use **Restore** (white) or **Remove** (black). Undo/Clear affect strokes only. Apply before generating; originals remain in project history. CPU editing works on every GPU vendor. Manual editing supports images up to 4096 pixels per side.')
                            mask_load=gr.Button('Load selected view into mask editor',elem_id='mask-load')
                            from scripts.workbench import mask_editor_ui
                            mask_editor=gr.HTML(value='{}',html_template=mask_editor_ui.TEMPLATE,css_template=mask_editor_ui.CSS,
                                js_on_load=mask_editor_ui.JS,elem_id='mask-editor')
                            mask_background=gr.State(None)
                            mask_strokes=gr.Textbox(value='',visible=False)
                            mask_apply=gr.Button('Apply corrected alpha to selected view',elem_id='mask-apply')
                            prep['manual_alpha_digests']=gr.JSON(value=[],visible=False)
                        gr.Markdown("Generate applies these settings once to each supplied view. Preview does not replace your originals.")

                    with gr.Tab("2 Generate", id="generate"):
                        from scripts.comfyui_workflows import BACKENDS as COMFY_BACKENDS
                        backend = gr.Radio(["TripoSG 1.5B", "Hunyuan3D-2mv", *COMFY_BACKENDS], value="Hunyuan3D-2mv", label="Shape model")
                        capabilities = gr.Markdown(MV_INFO, elem_classes="capability")
                        with gr.Accordion("Model identity & runtime configuration", open=False):
                            model_config = gr.JSON(value=app.model_config(), label="Current engine configuration · read only")
                            gr.Markdown("Loaded from config.yaml when this server starts. The controls below change run parameters; "
                                        "edit configuration and restart to change model paths, device or dtype.")
                        preset = gr.Radio(["Fast", "Balanced", "HQ"], value="Balanced", label="Apply shape preset",
                                          info="Copies the repository's actual preset values. Advanced fields remain editable.")
                        with gr.Group(visible=False) as tripo:
                            field("t_bg", gr.Radio, ["none"], value="none", label="Shared Inputs preparation", visible=False)
                            field("t_planar", gr.Checkbox, value=True, label="Planar texture projection")
                            with gr.Accordion("Advanced · TripoSG", open=True):
                                field("t_steps", gr.Slider, 15, 75, value=50, step=1, label="Diffusion steps",
                                      info="More denoising iterations increase runtime; they do not guarantee a better mesh.")
                                field("t_guidance", gr.Slider, 1, 15, value=7, step=.5, label="Guidance scale")
                                field("t_octree", gr.Slider, 7, 10, value=9, step=1, label="Octree depth",
                                      info="Higher spatial extraction detail costs memory and time.")
                                field("t_dense", gr.Slider, 6, 9, value=8, step=1, label="Dense octree depth",
                                      info="The engine clamps this to at most Octree depth.")
                                field("t_bounds", gr.Slider, .5, 2, value=1.25, step=.05, label="Extraction bounds")
                                field("t_seed", gr.Number, value=42, precision=0, label="Seed")
                                field("t_faces", gr.Number, value=25000, precision=0, label="Max faces",
                                      info="Decimation target; use -1 to retain extracted geometry.")
                            with gr.Accordion("TripoSG folder batch", open=False):
                                batch_folder = gr.Textbox(label="Image folder")
                                batch_pattern = gr.Textbox(value="*.png", label="File pattern")
                                batch_skip = gr.Checkbox(value=True, label="Skip existing outputs")
                                batch_go = gr.Button("Generate folder using TripoSG settings")
                        with gr.Group() as mv:
                            field("m_bake", gr.Radio, ["front", "left", "back", "right", "none"], value="front",
                                  label="Planar projection view", info="Shape-only placeholder texture; ignored when chained PBR is enabled.")
                            field("m_paint", gr.Checkbox, value=False, label="Run PBR paint after multi-view shape",
                                  info="Uses Texture stage settings and the front view (or first supplied view) as its reference.")
                            with gr.Accordion("Advanced · Hunyuan3D-2mv", open=True):
                                field("m_steps", gr.Slider, 15, 75, value=50, step=1, label="Diffusion steps")
                                field("m_octree", gr.Slider, 256, 512, value=380, step=4, label="Octree resolution",
                                      info="Higher volume resolution costs memory. This is a resolution, not TripoSG's depth parameter.")
                                field("m_guidance", gr.Slider, 1, 15, value=5, step=.5, label="Guidance scale")
                                field("m_chunks", gr.Number, value=20000, precision=0, label="Decoder chunks",
                                      info="Decoder work batch size; lower values trade speed for memory.")
                                field("m_level", gr.Slider, -.5, .5, value=0, step=.01, label="Marching-cubes level",
                                      info="Surface extraction isovalue. Changes the reconstructed surface.")
                                field("m_box",gr.Slider,.5,2,value=1.01,step=.01,label="Extraction bounding-box scale",info="Scale of the extraction cube. Values that are too small may clip the reconstructed object.")
                                field("m_seed", gr.Number, value=12345, precision=0, label="Seed")
                                field("m_faces", gr.Number, value=20000, precision=0, label="Max faces · shape-only",
                                      info="Ignored by the chained PBR path, which has its own remeshing.")
                        with gr.Group(visible=False) as comfy:
                            multi = field("c_multiview", gr.Checkbox, value=False, label="Pixal3D fixed-orbit multiview",
                                info="Separate multiview weights. Supply aligned Front / Left / Back / Right; 90° apart with shared FOV.")
                            field("c_resolution", gr.Radio, [512,1024,1536], value=1024, label="Shape spatial resolution",
                                info="512 skips the upsample stage. Higher resolution increases memory and runtime.")
                            field("c_seed", gr.Number, value=42, precision=0, label="Reproducible seed")
                            with gr.Accordion("Working mesh · raw master retained",open=False):
                                field("c_remesh",gr.Checkbox,value=True,label="Solid remesh working copy",
                                    info="Recommended for fragmented decoded surfaces. Changes topology and may close openings or merge thin parts. Raw master is retained.")
                                field("c_remesh_resolution",gr.Slider,32,2048,value=768,step=32,label="Remesh voxel resolution",
                                    info="Independent of diffusion resolution. Higher values retain smaller details at greater memory/runtime cost.")
                                field("c_remesh_qef",gr.Checkbox,value=False,label="Recover sharp edges · QEF",
                                    info="Solid remesh only. Can preserve hard-surface edges but introduce jagged creases.")
                                field("c_faces",gr.Number,value=700000,precision=0,label="Working mesh triangle budget · 0 disables",
                                    info="Explicit native midpoint decimation before UV baking. This alters geometry; inspect thin parts and achieved counts. BMS LOD reduction remains a later step.")
                                field("c_guard_bounds",gr.Slider,0,20,value=5,step=.1,label="Cleanup bounds-change limit (%)")
                                field("c_guard_surface",gr.Slider,0,20,value=2,step=.1,label="Cleanup sampled surface-error limit (%)",
                                    info="Sampled distances against raw geometry; does not prove all thin parts/openings are preserved.")
                                field("c_guard_strict",gr.Checkbox,value=False,label="Reject cleanup exceeding limits",
                                    info="Off keeps warnings for review. On publishes no preview when comparison fails; raw master stays retained.")
                            field("c_texture", gr.Checkbox, value=True, label="Generate PBR materials and UV atlas",
                                info="Dense raw geometry can take several minutes to unwrap and bake. Off returns shape only for early inspection.")
                            field("c_texture_size", gr.Radio, [1024,2048,4096,8192], value=2048, label="PBR atlas pixels",
                                info="Baking resolution, independent of shape resolution. Does not invent missing source detail.")
                            with gr.Accordion("Advanced · ComfyUI diffusion stages", open=False):
                                for key,label,value in (("structure","Sparse structure",12),("shape","Shape",20),("upsample","Shape upsample",12),("texture","Texture",12)):
                                    field("c_"+key+"_steps", gr.Slider, 1,100,value=value,step=1,label=label+" steps")
                                field("c_guidance", gr.Slider, 0,30,value=7.5,step=.1,label="Structure / shape guidance")
                                field("c_texture_guidance", gr.Slider, 0,30,value=1,step=.1,label="Texture guidance")
                                gr.Markdown("Upsample steps apply above 512. Texture controls apply only with PBR enabled. More steps do not guarantee accuracy.")
                            with gr.Group() as comfy_camera:
                                field("c_auto_fov", gr.Checkbox, value=True, label="Estimate single-image FOV with MoGe",
                                    info="Pixal3D single-image only; requires MoGe weights. Multiview always uses the supplied shared FOV.")
                                field("c_fov", gr.Slider, 1,170,value=20,step=.1,label="Horizontal FOV (degrees)",
                                    info="Pixal3D manual single-image or shared multiview FOV. Unused by TRELLIS.2.")
                            with gr.Accordion("Local ComfyUI host", open=False):
                                gr.Markdown("Install/verify this runtime and its checkpoints in Models. Endpoint and memory policy: `model.comfyui` in config.yaml. Check host readiness before generating.")
                                with gr.Row():
                                    comfy_start = gr.Button("Start host",min_width=80)
                                    comfy_check = gr.Button("Check model",min_width=80)
                                    comfy_stop = gr.Button("Stop host",min_width=80)
                                comfy_status = gr.JSON(label="Host / checkpoint readiness")
                                comfy_plan = gr.Button("Check setup requirements")
                        generate = gr.Button("Generate mesh", variant="primary", size="lg")
                        gr.Markdown("Reads images from Inputs and starts real inference with installed models. Missing checkpoints are reported; no download starts here.")
                        with gr.Accordion("Compare generators · reproducible benchmark",open=False):
                            gr.Markdown("Creates separate saved projects and queues real shape-only inference. Same input preparation, seed 42 and working triangle target; Hunyuan uses supplied directions, single-image models use Front. Quick settings measure draft behavior, not maximum model quality. Review silhouettes, symmetry and thin parts against your references.")
                            from scripts.workbench.benchmarking import MODELS
                            benchmark_models=gr.CheckboxGroup([(v,k) for k,v in MODELS.items()],value=list(MODELS),label="Models to compare")
                            benchmark_profile=gr.Radio(["quick","quality"],value="quick",label="Comparison profile")
                            benchmark_faces=gr.Number(value=20000,precision=0,label="Shared working triangle target")
                            benchmark_go=gr.Button("Queue generator comparison")
                            benchmark_report=gr.JSON(label="Queued projects / input checks")

                    with gr.Tab("3 Texture", id="texture"):
                        gr.Markdown(PAINT_INFO, elem_classes="capability")
                        reference = gr.Image(type="pil", image_mode='RGBA', format='png', label="Texture reference image", height=220)
                        copy_ref = gr.Button("Use Front image as paint reference")
                        paint_preset = gr.Radio(["Speed", "Balanced", "HQ"], value="Balanced", label="Apply paint preset")
                        field("p_low", gr.Checkbox, value=app.PAINT_LOW_VRAM_DEFAULT, label="Low-VRAM mode · mmgp offload",
                              info="Default comes from runtime VRAM detection and config.yaml; actual activation is reported after paint.")
                        field("p_remesh", gr.Checkbox, value=True, label="Remesh before texture painting")
                        field("p_maps", gr.Checkbox, value=False, label="Additional PNG map copies",info="Copies embedded map pixels to PNG: albedo, packed MR, scalar metallic/roughness and available normals. Native OBJ/JPG companions remain intact; PNG conversion cannot recover detail lost to JPEG.")
                        with gr.Accordion("Advanced · Hunyuan3D-2.1 Paint", open=True):
                            field("p_views", gr.Slider, 4, 8, value=6, step=1, label="Baking view budget",info="The view selector may add coverage views. Actual camera count is recorded in the operation report.")
                            field("p_resolution", gr.Slider, 256, 512, value=512, step=64, label="Diffusion resolution")
                            field("p_render", gr.Radio, ["512", "1024", "2048", "4096"], value="1024", label="Render size")
                            field("p_texture", gr.Radio, ["1024", "2048", "4096", "8192"], value="2048", label="Bake atlas size · export at half resolution",
                                  info="The upstream exporter downsamples by 2: a 2048 bake exports 1024 maps. Larger atlases cost memory/work; this does not change diffusion resolution.")
                            field("p_exponent", gr.Slider, 1, 8, value=4, step=1, label="Bake exponent")
                            field("p_merge", gr.Radio, ["fast", "max"], value="fast", label="Texture merge method")
                        field("normal", gr.Radio, [("Off", "off"), ("Low · mesh", "low"),
                                                   ("Medium · StableNormal", "medium"), ("High · Marigold", "high")],
                              value=app._normal_baker_default(), label="Post-paint normal baker")
                        gr.Markdown(NORMAL_INFO)
                        paint_go = gr.Button("Paint current asset", variant="primary", size="lg")

                    with gr.Tab("4 Optimize", id="optimize"):
                        gr.Markdown("### Reduce the current mesh\n**Existing pymeshlab decimator** · CPU processing\n\n"
                                    "Uses texture-aware decimation when the mesh has UVs, geometry decimation otherwise. "
                                    "Up to three passes retain the same safety settings. Winding repair works on a copy. "
                                    "A fresh output keeps the loaded master available for comparison.")
                        target = gr.Number(value=8000, precision=0, label="Target triangles")
                        opt_strict = gr.Checkbox(value=False, label="Require triangle budget", elem_id="opt-strict",
                            info="Reject an over-budget result instead of publishing a best-effort preview.")
                        with gr.Accordion("Optimization safeguards", open=False):
                            opt_passes = gr.Slider(1,3,value=3,step=1,label="Maximum safe passes",elem_id="opt-passes")
                            opt_repair = gr.Checkbox(value=True,label="Repair inconsistent winding",elem_id="opt-repair",
                                info="Reorients faces on the output copy; does not close holes or repair non-manifold edges.")
                            opt_boundary = gr.Checkbox(value=False,label="Protect open boundaries",elem_id="opt-boundary",
                                info="May prevent reaching small budgets. Existing UV and normal constraints remain active.")
                            opt_fallback = gr.Checkbox(value=False,label="Allow degraded UV fallback",elem_id="opt-fallback",
                                info="Off rejects lost UVs or nearest-neighbor transfers. On permits a warned preview that may have texture seams or flat colour.")
                            opt_bounds = gr.Slider(0,20,value=5,step=.1,label="Maximum bounds change (%)",elem_id="opt-bounds",
                                info="AABB corner shift relative to the source diagonal; not a silhouette or thin-part guarantee.")
                            opt_surface = gr.Slider(0,20,value=2,step=.1,label="Maximum sampled surface error (%)",elem_id="opt-surface",
                                info="Deterministic bidirectional point-to-triangle samples, relative to the source diagonal. Rejects excessive deviation; not full Hausdorff distance or proof of every thin detail.")
                        optimize_go = gr.Button("Optimize current asset", variant="primary")
                        with gr.Accordion('Protect parts during optimization',open=False):
                            gr.Markdown('Protect a coordinate region, face IDs, or sharp-edge triangles on the current working mesh. Selected triangles stay exact; reduction protects the cut boundary. These constraints do not carry into later remeshing or LOD export.')
                            protect_box=gr.Textbox(label='Region box: xmin,ymin,zmin,xmax,ymax,zmax',value='',elem_id='protect-box')
                            protect_center=gr.Textbox(label='Region center · Shift-click the working result, or enter X,Y,Z',elem_id='protect-center')
                            protect_radius=gr.Number(value=.1,minimum=.000001,label='Region half-size in current mesh units')
                            protect_region=gr.Button('Use center and half-size as protected box')
                            protect_faces=gr.Textbox(label='Protected triangle IDs (zero-based, comma-separated)',value='')
                            protect_angle=gr.Slider(0,180,value=0,step=1,label='Protect edges sharper than degrees · 0 disables')
                            protect_check=gr.Button('Inspect protected selection',elem_id='protect-check')
                            protect_report=gr.JSON(label='Selection counts / bounds')
                        with gr.Accordion("Surface Lab · normals / AO / ARMW", open=False):
                            gr.Markdown("Requires UVs, albedo and metallic/roughness maps. CPU AO and mesh normals; AI normals may require NVIDIA CUDA and downloaded weights. Reports actual fallback.")
                            surface["resolution"] = gr.Radio(["1024","2048","4096"],value="1024",label="Surface map size")
                            surface["normal"] = gr.Radio(["low","medium","high"],value="low",label="Normal baker")
                            surface["delight"] = gr.Slider(0,1,value=.18,step=.01,label="Delight strength")
                            surface["rays"] = gr.Slider(8,128,value=32,step=8,label="AO rays per surface sample")
                            surface["axis"] = gr.Radio(["x","y","z"],value="y",label="Up axis for wetness")
                            surface["material"] = gr.Textbox(value="concrete",label="Material name")
                            surface["armw"] = gr.Radio(["separate","packed","both"],value="both",label="ARMW output")
                            surface["mode"] = gr.Radio(["safe","optimize"],value="safe",label="Mesh processing")
                            surface["target"] = gr.Number(value=20000,precision=0,label="Surface optimization target")
                            surface_go = gr.Button("Preview surface enhancement")
                        gr.Markdown("#### What this operation can change\nTriangle count and mesh topology. Existing UV-aware "
                                    "passes, winding repair, boundary protection and UV fallback are recorded in optimization_report.json. "
                                    "No separate island-removal cleanup runs; visually inspect small details. There are no wired sliders for crease angle, "
                                    "thin-part protection, texture rebaking or silhouette error.\n\n"
                                    "UV fallback can introduce seams or use flat average albedo if UVs are lost. "
                                    "The report identifies the method and fallback; inspect it before using a result.")

                    with gr.Tab("5 Export", id="export"):
                        gr.Markdown("### Falcon BMS LOD set\nExport the current asset into a fresh folder with real GLBs, "
                                    "OBJ companions and BMS template metadata. Final **BML conversion still requires "
                                    "Blender + the BMS exporter**; this action does not deploy into the game.")
                        lod_count = gr.Slider(1, 7, value=7, step=1, label="Number of LODs", elem_id="lod_count")
                        lod_shared = gr.Checkbox(value=True, label="Shared PBR textures", info="Requires valid UVs on the master.")
                        with gr.Accordion("Advanced · LOD face budgets", open=True):
                            budgets = [gr.Number(value=n, precision=0, label=f"Model_{i} target triangles", elem_id=f"budget_{i}")
                                       for i, n in enumerate(svc.LOD_DEFAULTS)]
                        with gr.Accordion("LOD planning distances · feet",open=False):
                            distances = [gr.Number(value=n,precision=0,label=f"Model_{i} distance (ft)") for i,n in enumerate((500,1500,4000,10000,25000,60000,150000))]
                            distance_preview = gr.Number(value=0,label="Preview camera distance (ft) · 0 = free orbit")
                            unit_scale = gr.Number(value=1,label="Metres per mesh unit",info="AI geometry is usually normalized. Set the measured scale before interpreting distance. This preview is not BMS engine certification.")
                        gr.Markdown("Budgets start from config.yaml. Lower levels must achieve a strict reduction; "
                                    "shorten or scale the ladder for small meshes. Uses the normal-baker choice in Texture.")
                        export_go = gr.Button("Export LOD set", variant="primary")
                        with gr.Accordion('General interchange / BMS handoff',open=False):
                            package_name=gr.Textbox(value='asset',label='Material / texture name prefix')
                            package_bms=gr.Checkbox(value=False,label='Also author static BMS sidecars',elem_id='package-bms')
                            package_axes=gr.Textbox(value='+Z,-X,-Y',label='BMS X,Y,Z from signed source axes',info='Verify your model orientation. Native staged geometry is in feet; Parent.dat matches those staged coordinates.')
                            package_wetness=gr.Slider(0,1,value=0,step=.01,label='Authored wetness · ARMW alpha')
                            gr.Markdown('Every export includes OBJ/MTL interchange and a BMS next-steps guide. Static BMS mode adds JSON Materials.mtl, ordered per-LOD MTI, Parent.dat, PBR PNGs and geometry in BMS XYZ feet. BML export, DDS encoding, database registration and runtime verification remain external. Glass, animation and emissive effects need separate authoring.')
                        with gr.Accordion("Measured scale / orientation / pivot",open=False):
                            field("s_axis",gr.Radio,["X","Y","Z"],value="Y",label="Measure along output axis")
                            field("s_metres",gr.Number,value=1,label="Known dimension (metres)",minimum=.000001)
                            field("s_up",gr.Radio,["X","Y","Z"],value="Y",label="Current asset up axis")
                            field("s_forward",gr.Radio,["+X","-X","+Y","-Y","+Z","-Z"],value="+Z",label="Current asset forward axis")
                            field("s_pivot",gr.Radio,["keep","center","ground center"],value="ground center",label="Output pivot")
                            gr.Markdown("Scales a new working copy uniformly to your known dimension after orientation. Output: metres, Y-up, +Z forward. Supplied masters stay intact.")
                            scale_go=gr.Button("Apply measured scale",elem_id="apply-measured-scale")
                        readiness_go=gr.Button("Check BMS readiness",elem_id="check-bms-readiness")
                        readiness_report=gr.JSON(label="Intermediate readiness · BML / DDS conversion remains external",elem_id="bms-readiness")
                        lod_choice = gr.Dropdown([], label="Inspect an exported LOD")
                        export_files = gr.File(label="Exported files", file_count="multiple", interactive=False)

            gr.HTML(html_template=layout.handle("left"),js_on_load=layout.JS,
                    elem_id="left-divider",elem_classes="mu-layout-divider",min_height=0)
            with gr.Column(scale=8, min_width=200, elem_id="viewport"):
                with gr.Row(elem_id="viewport-tools"):
                    preview_kind = gr.Radio([("Result", "result"), ("Source preview", "source")], value="result",
                                            label="Visible asset", show_label=False, scale=2)
                    display = gr.Radio([("PBR / solid", "solid"), ("Wireframe", "wireframe"),
                                        ("Points", "point_cloud")], value="solid", label="Viewport display", show_label=False, scale=3)
                with gr.Row(elem_id="material-tools"):
                    material_view = gr.Dropdown(view.channels(initial),value="PBR",label="Inspect material",scale=3,min_width=100)
                    bounds = gr.Checkbox(value=False,label="Bounds",scale=1,min_width=70)
                    lighting = gr.Slider(0,2,value=1,step=.1,label="Environment",scale=2,min_width=80)
                    fit = gr.Button("Fit",scale=1,min_width=55)
                result = gr.HTML(value=view.payload(initial),html_template=view.TEMPLATE,css_template=view.VIEWER_CSS,
                                 js_on_load=view.viewer_js(),elem_id="workbench-viewer",min_height=150)
                with gr.Row(elem_id="checkpoint-tools"):
                    checkpoint_label = gr.Textbox(value="Checkpoint",show_label=False,scale=2,min_width=90)
                    accept = gr.Button("Accept / checkpoint",variant="primary",scale=2,min_width=130)
                    discard = gr.Button("Discard preview",scale=1,min_width=100)
                stage_status = gr.Markdown("Loaded an existing project mesh. No inference has run.", elem_id="stage-status")
            gr.HTML(html_template=layout.handle("right"),elem_id="right-divider",
                    elem_classes="mu-layout-divider",min_height=0)
            with gr.Column(scale=3, min_width=200, elem_id="inspectors"):
                gr.HTML('<div class="panel-title">PBR / TEXTURE / MESH INSPECTORS</div>')
                with gr.Tabs(elem_id="inspector-tabs") as inspector_tabs:
                    with gr.Tab("PBR", id="pbr"):
                        gr.Markdown("**Displayed asset materials**\n\nActual embedded maps. glTF: G = roughness, B = metallic.")
                        gallery = gr.Gallery(value=maps, label="PBR channels", columns=2, height=260,
                                             object_fit="contain", allow_preview=False)
                        asset_summary = gr.Markdown(summary, elem_id="asset-summary")
                        download = gr.File(value=initial, label="Displayed GLB", interactive=False)
                    with gr.Tab("Texture", id="texture-inspector"):
                        gr.Markdown("**Texture inspector**\n\nSelect an embedded channel to inspect its pixels and resolution.")
                        channels = svc.texture_choices(initial)
                        texture_channel = gr.Dropdown(channels, value=channels[0] if channels else None,
                                                      label="Texture / PBR channel", elem_id="texture-channel")
                        tex_image, tex_info = svc.texture_preview(initial, channels[0] if channels else None)
                        texture_image = gr.Image(value=tex_image, label="Channel preview", interactive=False, height=280)
                        texture_info = gr.Markdown(tex_info)
                    with gr.Tab("Mesh", id="mesh"):
                        inspection = gr.JSON(value=details, label="Measured from the displayed file",elem_id="mesh-inspection")
                        comparison_info=gr.JSON(label="Comparison roles / cleanup report",elem_id="comparison-info")
                        gr.Markdown("Comparison changes the displayed asset. Operations use the working result; use checkpoints/history to change operation inputs.")
                    with gr.Tab("Project", id="project"):
                        gr.Markdown("**Saved asset projects** · Images, masks, settings, owned meshes, versions and provenance.")
                        profile = gr.Radio(["general","BMS","presentation","printing","gaming"],value="general",label="Project use")
                        saved = gr.Dropdown(svc.STORE.choices(),label="Saved projects")
                        refresh_saved=gr.Button("Refresh saved projects")
                        save = gr.Button("Save project")
                        restore = gr.Button("Open saved project")
                        reset = gr.Button("Use original source as working preview")
                        version_choice = gr.Dropdown([],label="Version / checkpoint history")
                        branch = gr.Button("Continue from selected version")
                        preset_name = gr.Textbox(label="Named settings preset")
                        named_presets = gr.Dropdown([],label="Reusable presets")
                        save_preset = gr.Button("Save settings preset")
                        load_preset = gr.Button("Apply settings preset")
                        snapshot_file = gr.File(label="Project manifest",interactive=False)
                        project_report = gr.JSON(label="Stage state / provenance")
                    with gr.Tab("UV",id="uv"):
                        uv_image = gr.Image(label="UV triangle atlas",interactive=False,height=300)
                        uv_info = gr.Markdown("Open an asset to inspect its actual UVs.")
                        diagnostic_resolution=gr.Radio([128,256,512],value=256,label="Diagnostic raster pixels")
                        diagnostic_go=gr.Button("Analyze UV / PBR",elem_id="analyze-uv-pbr")
                        diagnostic_report=gr.JSON(label="Measured UV / PBR findings and sampling limits",elem_id="uv-diagnostics")
                        overlap_image=gr.Image(label="Overlap · red = sampled overlap",interactive=False)
                        stretch_image=gr.Image(label="Stretch anisotropy · green to red",interactive=False)
                        density_image=gr.Image(label="Relative texel density · blue to red",interactive=False)
                        with gr.Accordion('Repair UVs / rebake textures',open=False):
                            gr.Markdown('Creates new xatlas UV charts and transfers PBR maps from the current mesh or an aligned high-detail source. CPU processing; no GPU vendor restriction. Preserves originals. Tangent normals are approximate, not certified MikkTSpace; inspect seams and thin parts.')
                            rebake_source=gr.File(label='Optional aligned high-detail GLB · current mesh if omitted',file_types=['.glb'],type='filepath',elem_id='rebake-source')
                            rebake_size=gr.Radio([256,512,1024,2048],value=1024,label='CPU rebake atlas pixels')
                            rebake_padding=gr.Slider(1,32,value=4,step=1,label='Atlas padding / dilation pixels')
                            rebake_distance=gr.Slider(0,25,value=2,step=.1,label='Maximum projection distance (% of source diagonal)')
                            rebake_go=gr.Button('Preview UV repair / texture rebake',elem_id='rebake-go')
                    with gr.Tab('Reference',id='reference-inspector'):
                        gr.Markdown('Align an isolated photograph to the displayed mesh. Red = reference only; cyan = mesh only; green = overlap. Orthographic silhouette metrics measure this view, not full 3D accuracy.')
                        align_reference=gr.Image(type='pil',image_mode='RGBA',format='png',label='Masked reference',height=160,elem_id='align-reference')
                        align_copy=gr.Button('Use selected input view')
                        align_yaw=gr.Slider(-180,180,value=0,step=1,label='Yaw (degrees)')
                        align_pitch=gr.Slider(-90,90,value=0,step=1,label='Pitch (degrees)')
                        align_scale=gr.Slider(.01,4,value=.8,step=.01,label='Model framing scale')
                        align_x=gr.Slider(-1,1,value=0,step=.01,label='Horizontal image offset')
                        align_y=gr.Slider(-1,1,value=0,step=.01,label='Vertical image offset')
                        align_go=gr.Button('Compare silhouette',elem_id='align-go')
                        align_image=gr.Image(label='Aligned reference overlay',interactive=False,height=260)
                        align_report=gr.JSON(label='Silhouette agreement / calibration limits')
                    with gr.Tab("Jobs",id="jobs"):
                        gr.Markdown("**Persistent queue** · One operation at a time. Cancel waits for a safe boundary; it does not interrupt a CUDA kernel.")
                        job_choice = gr.Dropdown([],label="Job to inspect / cancel / rerun")
                        cancel_job = gr.Button("Cancel selected job")
                        rerun_job = gr.Button("Rerun frozen request")
                        job_history = gr.JSON(value=[],label="Jobs / progress / errors")
                        job_detail = gr.JSON(label="Frozen request and operation report")
                        refresh_job = gr.Button("Refresh selected job details / logs")
                        job_artifacts = gr.File(label="Worker logs / progress / report",file_count="multiple",interactive=False)

        flat = {"backend":backend,"preset":preset,"paint_preset":paint_preset,**params,
                "prep_provider":prep_provider,"prep_model":prep_model,"prep_view":prep_view,
                "prep_size":prep_size,"prep_crop":prep_crop,**{"prep_"+k:v for k,v in prep.items()},
                "target":target,"opt_passes":opt_passes,"opt_repair":opt_repair,"opt_boundary":opt_boundary,
                "opt_strict":opt_strict,"opt_fallback":opt_fallback,"opt_bounds":opt_bounds,"opt_surface":opt_surface,
                "lod_count":lod_count,"lod_shared":lod_shared,"profile":profile,
                'protect_box':protect_box,'protect_faces':protect_faces,'protect_angle':protect_angle,
                'r_size':rebake_size,'r_padding':rebake_padding,'r_distance':rebake_distance,
                'package_name':package_name,'package_bms':package_bms,'package_axes':package_axes,'package_wetness':package_wetness,
                "unit_scale":unit_scale,"distance_preview":distance_preview,**{f"distance_{i}":v for i,v in enumerate(distances)},
                **{f"budget_{i}":v for i,v in enumerate(budgets)},**{"surface_"+k:v for k,v in surface.items()}}
        settings_inputs = list(flat.values())
        defaults = {k:v.value for k,v in flat.items()}
        images_inputs = [front,left,back,right,reference]

        def collect(values):
            d = dict(zip(flat,values))
            d["preparation"] = {"provider":d["prep_provider"],"model":d["prep_model"],"size":d["prep_size"],"crop":d["prep_crop"],
                                **{k:d["prep_"+k] for k in prep}}
            d["optimization"] = {"target":d["target"],"max_passes":d["opt_passes"],"repair_winding":d["opt_repair"],
                                 "preserve_boundary":d["opt_boundary"],"strict_budget":d["opt_strict"],
                                 "allow_uv_fallback":d["opt_fallback"],"max_bounds_change":d["opt_bounds"],"max_surface_error":d["opt_surface"],
                                 'protected_box':d['protect_box'],'protected_faces':d['protect_faces'],'sharp_angle':d['protect_angle']}
            d["export"] = {"count":d["lod_count"],"shared":d["lod_shared"],"budgets":[d[f"budget_{i}"] for i in range(7)],
                           "distances":[d[f"distance_{i}"] for i in range(7)],"metres_per_unit":d["unit_scale"],
                           'asset_name':d['package_name'],'bms_handoff':d['package_bms'],'bms_axes':d['package_axes'],'wetness':d['package_wetness']}
            d['rebake']={'resolution':int(d['r_size']),'padding':int(d['r_padding']),'max_distance':d['r_distance']}
            d["surface"] = {k:d["surface_"+k] for k in surface}
            d["scale"]={"axis":d["s_axis"],"metres":d["s_metres"],"source_up":d["s_up"],"source_forward":d["s_forward"],"pivot":d["s_pivot"]}
            return d

        def images(values):
            return dict(zip((*VIEWS,"reference"),values))

        def enqueue(stage_name):
            def run(project_path,label,source_path,current_path,*values):
                try:
                    return svc.submit(stage_name,project_path,label,source_path,current_path,
                                      collect(values[:len(flat)]),images(values[len(flat):]))
                except gr.Error as exc:
                    # Keep actionable prerequisites visible beside the viewport;
                    # nonqueued HTTP errors do not reliably display a toast.
                    return gr.skip(),gr.skip(),str(exc.message)
            return run
        for button,stage_name in ((generate,"Generate"),(paint_go,"Texture"),(optimize_go,"Optimize"),
                                  (export_go,"Export"),(surface_go,"Surface"),(scale_go,"Scale")):
            button.click(enqueue(stage_name),[project,name,source,current]+settings_inputs+images_inputs,
                         [project,last_job,stage_status],queue=False)
        def enqueue_rebake(project_path,label,source_path,current_path,high,*values):
            return svc.submit('Rebake',project_path,label,source_path,current_path,collect(values[:len(flat)]),images(values[len(flat):]),high_source=high)
        rebake_go.click(enqueue_rebake,[project,name,source,current,rebake_source]+settings_inputs+images_inputs,[project,last_job,stage_status],queue=False)
        def load_mask(which,*values):
            from dataclasses import replace
            from scripts.workbench.preparation import isolate
            d=collect(values[:len(flat)]);pixels=images(values[len(flat):]).get(which.lower())
            from scripts.gpu_lifecycle import operation
            @operation()
            def run():
                isolated,_=isolate(pixels,replace(svc.Preparation(**d['preparation']),crop=''),svc.ROOT,app.CFG)
                original=pixels.convert('RGBA').copy();original.putalpha(isolated.getchannel('A'))
                from scripts.workbench.mask_edit import image_digest
                return {'image':original,'direction':which,'input_digest':image_digest(pixels)},mask_editor_ui.payload(original)
            return run()
        mask_load.click(load_mask,[prep_view]+settings_inputs+images_inputs,[mask_background,mask_editor])
        def apply_mask(which,background,stroke_data,digests,*pixels):
            from scripts.workbench.mask_edit import apply_strokes,image_digest
            from scripts.workbench.input_readiness import overlay
            if not background or background['direction']!=which or pixels[VIEWS.index(which.lower())] is None or image_digest(pixels[VIEWS.index(which.lower())])!=background['input_digest']:
                raise gr.Error('The selected reference changed. Reload it into the editor before applying strokes.')
            edited=apply_strokes(mask_editor_ui.strokes(background['image'],stroke_data));values=list(pixels);values[VIEWS.index(which.lower())]=edited
            manual=set([*(digests or []),image_digest(edited)])
            hashes=list(dict.fromkeys(image_digest(value) for value in values if value is not None and image_digest(value) in manual))
            return *values,hashes,overlay(edited),'Corrected alpha applied. Save the project or queue generation to retain this revision; source files are untouched.',{**background,'input_digest':image_digest(edited)}
        mask_apply.click(apply_mask,[prep_view,mask_background,mask_strokes,prep['manual_alpha_digests'],front,left,back,right],
            [front,left,back,right,prep['manual_alpha_digests'],prepared_overlay,stage_status,mask_background],queue=False,
            js="(...args)=>{args[2]=window.muMaskEditor?.export()||'';return args;}")
        align_copy.click(lambda which,*pixels:pixels[VIEWS.index(which.lower())],[prep_view,front,left,back,right],align_reference,queue=False)
        def align_mesh(folder,path,original,kind,reference,yaw,pitch,scale,x,y):
            from scripts.export_contracts import load_static_master
            from scripts.workbench.reference_alignment import compare_reference
            visible=svc.preview_asset(folder,path,original,kind)
            if not visible:raise gr.Error('Open a mesh first.')
            return compare_reference(load_static_master(visible),reference,yaw,pitch,scale,x,y)
        align_go.click(align_mesh,[project,current,source,preview_kind,align_reference,align_yaw,align_pitch,align_scale,align_x,align_y],[align_image,align_report])
        def inspect_protection(path,*values):
            from scripts.workbench.protection import selected_faces
            from scripts.workbench.schema import OptimizationRequest
            from scripts.export_contracts import load_static_master
            import numpy as np
            import trimesh
            if not path:raise gr.Error('Open a working mesh first.')
            mesh=load_static_master(path);keep=selected_faces(mesh,OptimizationRequest(**collect(values)['optimization']))
            if not keep.any():raise gr.Error('Choose a box, face IDs, or sharp-edge threshold first.')
            colours=np.tile([92,113,128,255],(len(mesh.faces),1));colours[keep]=[65,222,183,255]
            mesh.visual=trimesh.visual.ColorVisuals(mesh,face_colors=colours)
            from scripts.workbench.projects import digest
            import hashlib
            stamp=hashlib.sha256((digest(path)+str(collect(values)['optimization'])).encode()).hexdigest()
            destination=svc.STATE_DIR/'viewer'/f'protected_{stamp}.glb';destination.parent.mkdir(parents=True,exist_ok=True);mesh.export(destination)
            return view.payload(str(destination)),{'protected_triangles':int(keep.sum()),'total':len(keep),
                'bounds':mesh.bounds.tolist(),'note':'Display overlay only. Operations still use the original working mesh. Change a viewer control to restore the material view.'}
        protect_check.click(inspect_protection,[current]+settings_inputs,[result,protect_report])
        def region_from_center(center,radius):
            import numpy as np
            try:point=np.array([float(v) for v in center.split(',')])
            except (ValueError,AttributeError) as exc:raise gr.Error('Pick or enter a center as X,Y,Z.') from exc
            if point.shape!=(3,) or not np.isfinite(point).all() or not .000001<=radius<=1e9:raise gr.Error('Enter finite center coordinates and a positive half-size.')
            return ','.join(f'{v:.9g}' for v in np.r_[point-radius,point+radius])
        protect_region.click(region_from_center,[protect_center,protect_radius],protect_box,queue=False)

        stage.change(lambda selected:gr.update(selected=selected),stage,workflow,queue=False)
        def switch_model(model, selected_prep, use_multi):
            single = model == "TripoSG 1.5B"
            is_comfy = model in COMFY_BACKENDS
            pixal = model == COMFY_BACKENDS[1]
            views = model == "Hunyuan3D-2mv" or (pixal and use_multi)
            hint = (f"**Reference views · {model}**\n\nUpload 1–4 directions: Front, Left, Back and Right."
                    if views else f"**Input image · {model}**\n\nUpload one front or three-quarter view.")
            if pixal and use_multi:
                hint += " Equal framing, shared FOV and fixed 90° intervals are required."
            return (gr.update(visible=single),gr.update(visible=model=="Hunyuan3D-2mv"),
                    TRIPO_INFO if single else COMFY_INFO if is_comfy else MV_INFO,
                    app.model_config(model if is_comfy else single),hint,
                    gr.update(label="Front" if views else "Input image",height=125 if views else 200),
                    gr.update(visible=views),gr.update(visible=views),
                    gr.update(choices=["Front","Left","Back","Right"] if views else ["Front"],value=selected_prep if views else "Front"),
                    gr.update(visible=is_comfy),gr.update(visible=not is_comfy),gr.update(visible=pixal),gr.update(visible=pixal),
                    gr.update(visible=pixal and use_multi))
        model_outputs=[tripo,mv,capabilities,model_config,view_hint,front,left,rear_views,prep_view,comfy,preset,multi,comfy_camera,rig_confirm]
        backend.change(switch_model,[backend,prep_view,multi],model_outputs,queue=False)
        multi.change(switch_model,[backend,prep_view,multi],model_outputs,queue=False)
        def reference_check(*values):
            from scripts.workbench.input_readiness import check_inputs
            return check_inputs(collect(values[:len(flat)]),images(values[len(flat):]))
        check_references.click(reference_check,settings_inputs+images_inputs,input_report,queue=False)
        for button,action in ((comfy_start,"start"),(comfy_check,"check"),(comfy_stop,"stop"),(comfy_plan,"plan")):
            button.click(lambda *values,action=action:svc.comfy_host(action,collect(values)),settings_inputs,comfy_status,
                         concurrency_id="comfy-host",concurrency_limit=1)
        def apply_shape(p):
            t,m = app.TRIPOSG_PRESETS[p],app.HUNYUAN_MV_PRESETS[p]
            return t["steps"],t["guidance"],t["octree"],max(6,t["octree"]-1),t["faces"],m["steps"],m["octree"],m["guidance"],m["chunks"]
        preset.input(apply_shape,preset,[params[k] for k in ("t_steps","t_guidance","t_octree","t_dense","t_faces","m_steps","m_octree","m_guidance","m_chunks")],queue=False)
        def apply_paint(p):
            d = app.PAINT_PRESETS[p]
            return d["views"],d["resolution"],str(d["render_size"]),str(d["texture_size"])
        paint_preset.input(apply_paint,paint_preset,[params[k] for k in ("p_views","p_resolution","p_render","p_texture")],queue=False)
        def prepare_preview(folder,label,source_path,current_path,*values):
            d = collect(values[:len(flat)])
            original_images=images(values[len(flat):])
            folder,_,_=svc.save_project(folder,label,source_path,current_path,d,original_images)
            from scripts.workbench.preparation import prepare,composite
            from scripts.gpu_lifecycle import operation
            @operation()
            def run():
                image,mask,report=prepare(original_images[d["prep_view"].lower()],svc.Preparation(**d["preparation"]),svc.ROOT,app.CFG)
                prepared_relative=svc.STORE.store_image(folder,image,"inputs/prepared")
                mask_relative=svc.STORE.store_image(folder,mask,"inputs/masks")
                with svc.STORE.edit(folder) as manifest:
                    manifest["inputs"][d["prep_view"].lower()].update(prepared=prepared_relative,mask=mask_relative,preparation=report)
                from scripts.workbench.input_readiness import overlay
                return folder,composite(image,d["preparation"]["background"]),mask,overlay(image),report,"Preparation complete. Review the alpha mask and framing overlay before generating."
            return run()
        prep_go.click(prepare_preview,[project,name,source,current]+settings_inputs+images_inputs,[project,prepared_image,prepared_mask,prepared_overlay,input_report,stage_status],
                      concurrency_id="workbench-preparation",concurrency_limit=1)
        copy_ref.click(lambda image:image,front,reference,queue=False)
        prep_provider.change(lambda p,a,b:(gr.update(interactive=p=="rembg"),
            gr.update(interactive=p=="rembg",value=a if p=="rembg" else False),
            gr.update(interactive=p=="rembg",value=b if p=="rembg" else False)),
            [prep_provider,prep["alpha_matting"],prep["postprocess"]],
            [prep_model,prep["alpha_matting"],prep["postprocess"]],queue=False)
        def enqueue_folder(folder,pattern,skip,label,*values):
            path = Path(folder)
            if not path.is_dir():raise gr.Error("Choose an existing image folder.")
            if Path(pattern).name != pattern or "**" in pattern:raise gr.Error("Use a filename pattern without directory traversal.")
            settings = collect(values)
            settings["backend"] = "TripoSG 1.5B"
            from scripts.workbench.projects import digest
            completed = {json.loads(r["request"]).get("batch_sha") for r in svc.queue().rows() if r["state"]=="completed"} if skip else set()
            count = 0
            for image_path in sorted(path.glob(pattern)):
                if not image_path.is_file():continue
                sha = digest(image_path)
                if skip and sha in completed:continue
                from PIL import Image
                with Image.open(image_path) as im:
                    pixels = im.convert("RGBA")
                project_path = svc.STORE.create(label+"_"+image_path.stem)
                manifest = svc.STORE.snapshot(project_path,settings,{"front":pixels})
                request = {"settings":settings,"images":{"front":str(svc.STORE.resolve(project_path,manifest["inputs"]["front"]["original"]))},"mesh":None,"batch_sha":sha}
                svc.queue().submit(project_path,"Generate",request)
                count += 1
            return f"Queued {count} single-image projects; open their saved projects to inspect each result."
        batch_go.click(enqueue_folder,[batch_folder,batch_pattern,batch_skip,name]+settings_inputs,stage_status,queue=False)
        def enqueue_comparison(label,models,profile,faces,*values):
            report,message=svc.queue_benchmark(label,collect(values[:len(flat)]),images(values[len(flat):]),models,profile,faces)
            return report,message,gr.update(choices=svc.STORE.choices())
        benchmark_go.click(enqueue_comparison,[name,benchmark_models,benchmark_profile,benchmark_faces]+settings_inputs+images_inputs,
                           [benchmark_report,stage_status,saved],queue=False)

        def load(path):
            svc.inspect_asset(path)
            return None,path,path,None,f"Opened `{path}`. Save or run an operation to create an owned asset project."
        open_asset.click(load,existing,[project,source,current,seen_preview,stage_status])
        upload.upload(load,upload,[project,source,current,seen_preview,stage_status])
        reset.click(lambda path:path,source,current)
        lod_choice.change(lambda path:path or gr.skip(),lod_choice,current)

        def render(path,mode,source_path,kind,channel,show_bounds,intensity,fit_id,distance,scale,folder):
            visible=svc.preview_asset(folder,path,source_path,kind)
            summary,details,maps,file = svc.inspect_asset(visible)
            choices = svc.texture_choices(visible)
            first = choices[0] if choices else None
            image,info = svc.texture_preview(visible,first)
            uv,uv_caption = view.uv_atlas(visible) if visible else (None,"No asset loaded.")
            available=view.channels(visible)
            channel_update=gr.update(choices=available) if channel in available else gr.update(choices=available,value="PBR")
            return (summary,details,maps,file,gr.update(choices=choices,value=first),image,info,uv,uv_caption,channel_update,visible)
        viewer_inputs = [current,display,source,preview_kind,material_view,bounds,lighting,fit_count,distance_preview,unit_scale,project]
        render_outputs=[asset_summary,inspection,gallery,download,texture_channel,texture_image,texture_info,uv_image,uv_info,material_view,displayed]
        for control in (current,source):
            control.change(render,viewer_inputs,render_outputs)
        # Updating available roles is metadata, not another user selection.
        # A change handler here queues stale full renders after viewport edits.
        preview_kind.input(render,viewer_inputs,render_outputs)
        def comparison(folder,path,original,kind):
            roles=svc.comparison_assets(folder,path,original)
            labels={"result":"Result","source":"Source preview","raw":"Raw master","accepted":"Accepted"}
            choices=[(labels[k],k) for k,v in roles.items() if v or k=="result"]
            info={"roles":roles,"operations_use":"Working result"}
            if path:
                report=Path(path).parent/"cleanup_comparison.json"
                if report.is_file():info["cleanup_comparison"]=json.loads(report.read_text(encoding="utf-8"))
            return gr.update(choices=choices,value=kind if kind in roles and roles[kind] else "result"),info
        for control in (current,project):control.change(comparison,[project,current,source,preview_kind],[preview_kind,comparison_info],queue=False)
        def redraw(path,mode,source_path,kind,channel,show_bounds,intensity,fit_id,distance,scale,folder):
            if scale<=0 or distance<0:raise gr.Error("Distance must be nonnegative and metres per mesh unit positive.")
            visible=svc.preview_asset(folder,path,source_path,kind)
            return view.payload(visible,mode,channel if channel in view.channels(visible) else "PBR",show_bounds,intensity,fit_id,distance,scale)
        # Inspector work may be slow. It never writes viewport payloads: doing
        # so can restore an obsolete display mode after a later user edit.
        for control in (current,source,display,material_view,bounds,lighting,fit_count,distance_preview,unit_scale):
            control.change(redraw,viewer_inputs,result,queue=False)
        preview_kind.input(redraw,viewer_inputs,result,queue=False)
        fit.click(lambda n:n+1,fit_count,fit_count,queue=False)
        texture_channel.change(svc.texture_preview,[displayed,texture_channel],[texture_image,texture_info])
        diagnostic_go.click(svc.diagnostics,[displayed,diagnostic_resolution],[diagnostic_report,overlap_image,stretch_image,density_image])
        readiness_go.click(lambda path,*values:svc.bms_readiness(path,collect(values)),[current]+settings_inputs,readiness_report)
        def scaled_units(path):
            report=Path(path).parent/"operation.json" if path else None
            return 1 if report and report.is_file() and json.loads(report.read_text(encoding="utf-8")).get("stage")=="Scale" else gr.skip()
        current.change(scaled_units,current,unit_scale,queue=False)
        refresh_gpu.click(svc.telemetry,outputs=gpu,queue=False)
        gr.Timer(10).tick(svc.telemetry,outputs=gpu,queue=False)

        def save_all(project_path,label,source_path,current_path,*values):
            folder,manifest,message = svc.save_project(project_path,label,source_path,current_path,
                collect(values[:len(flat)]),images(values[len(flat):]))
            return folder,gr.update(choices=svc.STORE.choices(),value=folder),manifest,message
        save.click(save_all,[project,name,source,current]+settings_inputs+images_inputs,[project,saved,snapshot_file,stage_status])
        refresh_saved.click(lambda:gr.update(choices=svc.STORE.choices()),outputs=saved,queue=False)
        def restore_all(folder):
            manifest,source_path,current_path,restored_images = svc.open_project(folder)
            values = manifest["settings"]
            entry=manifest["inputs"].get(values.get("prep_view","Front").lower(),{})
            def restored_image(key):
                if not entry.get(key):return None
                from PIL import Image
                with Image.open(svc.STORE.resolve(folder,entry[key])) as pixels:return pixels.copy()
            return (folder,manifest["name"],source_path,current_path,manifest.get("preview"),
                    *[values.get(k,defaults[k]) for k in flat],*[restored_images.get(k) for k in (*VIEWS,"reference")],
                    restored_image("prepared"),restored_image("mask"),None,
                    f"Opened saved project `{folder}` with images, versions and settings.")
        restore.click(restore_all,saved,[project,name,source,current,seen_preview]+settings_inputs+images_inputs+[prepared_image,prepared_mask,prepared_overlay,stage_status])
        def accept_preview(folder,label):
            if not folder: raise gr.Error("Create a project and run an operation first.")
            path = svc.STORE.accept(folder,label)
            original=svc.STORE.load(folder)["source"]
            return str(path),None,str(svc.STORE.resolve(folder,original)) if original else None,f"Accepted checkpoint **{label}**."
        accept.click(accept_preview,[project,checkpoint_label],[current,seen_preview,source,stage_status])
        def discard_preview(folder):
            if not folder:raise gr.Error("No project preview to discard.")
            path = svc.STORE.discard(folder)
            return str(path) if path else None,None,"Preview discarded; immutable output retained in history."
        discard.click(discard_preview,project,[current,seen_preview,stage_status])
        new_asset.click(lambda:([None]*14)+["untitled_asset","New asset. Upload reference views or open a mesh; previous projects and jobs are retained."],
            outputs=[project,source,current,seen_preview,last_job,job_stamp]+images_inputs+[prepared_image,prepared_mask,prepared_overlay,name,stage_status],queue=False)
        version_choice.input(lambda folder,relative:str(svc.STORE.select_version(folder,relative)),[project,version_choice],current)
        branch.click(lambda folder,relative:str(svc.STORE.select_version(folder,relative,branch=True)),[project,version_choice],current)

        presets_path = svc.STATE_DIR / "presets.json"
        def presets():
            return json.loads(presets_path.read_text(encoding="utf-8")) if presets_path.exists() else {}
        def save_named(label,*values):
            if not label.strip():raise gr.Error("Enter a preset name.")
            stored = presets();stored[label.strip()] = collect(values);atomic_json(presets_path,stored)
            return gr.update(choices=list(stored),value=label.strip()),f"Saved preset **{label.strip()}**."
        save_preset.click(save_named,[preset_name]+settings_inputs,[named_presets,stage_status])
        load_preset.click(lambda label:[presets()[label].get(k,defaults[k]) for k in flat],named_presets,settings_inputs)
        demo.load(lambda:gr.update(choices=list(presets())),outputs=named_presets)

        def poll(folder,seen,selected,previous_stamp):
            rows = svc.queue().rows(folder)
            compact = [{k:r[k] for k in ("id","stage","state","progress","message","created","updated","result")} for r in rows]
            choices = [(f"{r['stage']} · {r['state']} · {r['id'][:8]}",r["id"]) for r in rows]
            job = gr.update(choices=choices,value=selected if selected in [r["id"] for r in rows] else (rows[0]["id"] if rows else None))
            if not folder:
                return compact,job,gr.skip(),seen,{},gr.update(choices=[],value=None),gr.update(choices=[],value=None),gr.skip(),gr.update(value=None),previous_stamp
            m = svc.STORE.load(folder)
            preview = m["preview"]
            working = str(svc.STORE.resolve(folder,preview)) if preview else gr.skip()
            versions = [(f"{v.get('label',v['stage'])} · {v['created']} · {v['status']}",v["path"]) for v in m["versions"]]
            lods = []
            files = []
            if preview:
                current_file = svc.STORE.resolve(folder,preview)
                if (current_file.parent / "lod_report.json").exists():
                    report = json.loads((current_file.parent / "lod_report.json").read_text())
                    lods = [(f"{r['lod']} · {r['achieved_faces']:,} actual / {r['target_faces']:,} target",str(current_file.parent / (r['lod']+'.glb'))) for r in report["levels"]]
                files = [str(p) for p in current_file.parent.rglob("*") if p.is_file()]
                archive=current_file.parent/'export_package.zip'
                if archive.exists():
                    files=[str(archive),str(current_file.parent/'export_package.json'),str(current_file.parent/'NEXT_STEPS_BMS.txt'),
                           *[str(p) for p in sorted(current_file.parent.glob('Model_[0-6].glb'))]]
            active = next((r for r in rows if r["state"] in ("running","cancel_pending")),rows[0] if rows else None)
            stamp = (active["id"],active["state"],active["progress"],active["message"]) if active else None
            status = f"**{active['stage']} · {active['state']} · {active['progress']:.0%}** — {active['message']}" if active and stamp!=previous_stamp else gr.skip()
            if active and stamp!=previous_stamp and (active["state"] in ("failed","cancel_pending","interrupted")
                    or (active["state"]=="completed" and "Warnings:" in active["message"])):
                marker="mu-failed" if active["state"]=="failed" else "mu-warning"
                status=f'<span class="{marker}"></span>'+status
            return (compact,job,working if preview != seen else gr.skip(),preview,
                    {"stage_states":m["stage_states"],"accepted":m["accepted"],"preview":preview,"versions":m["versions"]},
                    gr.update(choices=versions),gr.update(choices=lods),status,gr.update(value=files),stamp)
        gr.Timer(2).tick(poll,[project,seen_preview,job_choice,job_stamp],
                         [job_history,job_choice,current,seen_preview,project_report,version_choice,lod_choice,stage_status,export_files,job_stamp],queue=False)
        cancel_job.click(lambda job:svc.queue().cancel(job) or "Cancellation requested.",job_choice,stage_status,queue=False)
        def details_for(job):
            row = svc.queue().get(job)
            if row:
                row["request"] = json.loads(row["request"])
                report=svc.STORE.folder(row["project"])/"jobs"/job/"operation.json"
                if report.exists():row["operation_report"]=json.loads(report.read_text(encoding="utf-8"))
            return row
        def show_job(job):
            row=details_for(job)
            artifacts=[]
            if row:
                folder=svc.STORE.folder(row["project"])
                artifacts=[str(p) for p in (folder/"logs").glob(job+".*") if p.is_file()]
                report=folder/"jobs"/job/"operation.json"
                if report.exists():artifacts.append(str(report))
            return row,artifacts
        job_choice.input(show_job,job_choice,[job_detail,job_artifacts],queue=False)
        refresh_job.click(show_job,job_choice,[job_detail,job_artifacts],queue=False)
        def rerun(job):
            row = details_for(job)
            if not row:raise gr.Error("Select a recorded job.")
            new = svc.queue().submit(row["project"],row["stage"],row["request"])
            return new,f"Queued reproducible rerun `{new[:10]}`."
        rerun_job.click(rerun,job_choice,[last_job,stage_status],queue=False)
        # Keep the WebGL workspace mounted; Gradio visible=False destroys its
        # child DOM and would dispose the scene and camera on each navigation.
        models_view_state = gr.HTML('<span data-open="false"></span>',elem_id='models-view-state')
        model_view = models_ui.mount(model_manager)
        required_keys = gr.State([])
        def selection_requirements(which,*values):
            from scripts.model_manager.catalog import required_models
            selected_settings=collect(values[:len(flat)])
            action={'inputs':'Prepare','generate':'Generate','texture':'Texture','optimize':'Optimize','export':'Export'}[which]
            return required_models(action,selected_settings,images(values[len(flat):]))
        requirement_inputs=[stage]+settings_inputs+images_inputs
        gr.on([component.change for component in requirement_inputs],selection_requirements,requirement_inputs,required_keys,queue=False)
        def requirement_text(keys):
            if not keys:return 'No AI checkpoints required for the selected operation.'
            pending=[s['name'] for s in model_manager.readiness(keys) if not s['ready']]
            return '**Models required:** '+', '.join(pending)+'. Open Models to install or verify.' if pending else '**Selected models ready** · files and runtime prerequisites detected.'
        def open_models(keys=None):
            chosen=next((k for k in (keys or []) if not model_manager.status(k)['ready']),None)
            return gr.update(visible=True),'<span data-open="true"></span>',gr.update(visible=False),gr.update(visible=False),chosen or gr.skip()
        navigation_outputs=[model_view['workspace'],models_view_state,asset_toolbar,stage,model_view['selected']]
        models_button.click(lambda:open_models(),outputs=navigation_outputs,queue=False)
        manage_required.click(open_models,required_keys,navigation_outputs,queue=False)
        def install_workflow(keys):
            if not keys:raise gr.Error('The selected workbench operation needs no AI checkpoints. Select a model or another workflow stage first.')
            model_manager.start()
            pending=[key for key in keys if not model_manager.status(key)['downloaded']]
            import shutil
            required=sum(item['bytes'] for item in model_manager.readiness(keys) if not item['downloaded'])
            drive=model_manager.models_dir
            while not drive.exists() and drive.parent!=drive:drive=drive.parent
            if shutil.disk_usage(drive).free < required+model_manager.reserve:
                raise gr.Error('Insufficient estimated space for the selected workflow models. Choose another model folder before installing.')
            for key in pending:model_manager.submit(key,'install')
            return f'Queued {len(pending)} selected workflow model(s), including missing shared checkpoints. Runtime/build prerequisites are listed separately in each model.'
        model_view['workflow_install'].click(install_workflow,required_keys,model_view['message'],queue=False)
        model_view['close'].click(lambda:(gr.update(visible=False),'<span data-open="false"></span>',gr.update(visible=True),gr.update(visible=True)),
            outputs=navigation_outputs[:4],queue=False)
        model_view['refresh'].click(lambda:model_manager._inventory_cache.clear(),queue=False)
        def model_poll(*values):
            *poll_values,keys=values
            return (*model_view['poll'](*poll_values),requirement_text(keys))
        model_outputs=model_view['poll_outputs']+[models_button,model_readiness]
        gr.Timer(2).tick(model_poll,model_view['poll_inputs']+[required_keys],model_outputs,queue=False)
        demo.load(selection_requirements,requirement_inputs,required_keys,queue=False)
    return demo.queue(default_concurrency_limit=1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=7861)
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--check", action="store_true", help="Construct the UI without launching or loading models")
    args = parser.parse_args()
    demo = build()
    if args.check:
        print(f"Workbench constructed: {len(demo.blocks)} components, {len(demo.fns)} events. No inference run.")
        return
    theme = gr.themes.Base(primary_hue="teal", secondary_hue="emerald", neutral_hue="slate",
        # Gradio's Plex SemiBold files contain only a subset of glyphs; using
        # the complete Regular/Bold faces avoids mixed fallback lettering.
        font=[LocalFont("IBM Plex Sans", weights=[400, 700]),
              LocalFont("Montserrat", weights=[400, 700]),
              "Segoe UI", "sans-serif"],
        font_mono=[LocalFont("IBM Plex Mono", weights=[400, 700]), "Cascadia Code", "Consolas", "monospace"]).set(
        body_background_fill_dark="#09181d", block_background_fill_dark="#10232b",
        input_background_fill_dark="#0b1b22", border_color_primary_dark="#24434b",
        button_primary_background_fill_dark="#42cdb5", button_primary_text_color_dark="#06251f")
    svc.queue()
    from scripts.model_manager.service import get_manager
    manager=get_manager(app.ROOT,app.CFG)
    manager.start()
    import atexit
    atexit.register(manager.close)
    demo.launch(server_name="127.0.0.1", server_port=args.port, inbrowser=not args.no_open,
                share=False, show_error=True, theme=theme, css=CSS+models_ui.CSS,
                favicon_path=str(app.ROOT / "assets" / "logo.png"),
                head=instance_marker(app.ROOT)+"""<script>if(new URL(location.href).searchParams.get('__theme')!=='dark') {
                  const u=new URL(location.href);u.searchParams.set('__theme','dark');location.replace(u.href);
                }</script>""",
                allowed_paths=[str(app.OUT_DIR), str(app.BMS_DIR), str(svc.STATE_DIR), str(svc.STORE.root),str(manager.state/'logs')],
                footer_links=[])


if __name__ == "__main__":
    main()
