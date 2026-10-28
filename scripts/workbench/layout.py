"""Client-only, persistent side-panel sizing for the single-view workbench."""

CSS = """
#workspace {
    --mu-default-left:340px; --mu-default-right:310px;
    grid-template-columns:var(--mu-left,var(--mu-default-left)) 14px minmax(0,1fr)
        14px var(--mu-right,var(--mu-default-right));
    gap:0!important;
}
#controls {grid-column:1;grid-row:1;}
#viewport {grid-column:3;grid-row:1;}
#inspectors {grid-column:5;grid-row:1;}
#workspace > .mu-layout-divider {
    grid-row:1;height:100%;min-height:0!important;min-width:0!important;
    padding:0!important;margin:0!important;border:0!important;background:transparent!important;
    display:flex!important;align-items:stretch;
}
#left-divider {grid-column:2;}
#right-divider {grid-column:4;}
#workspace > .mu-layout-divider .html-container,
#workspace > .mu-layout-divider .prose {
    height:100%!important;width:100%!important;min-height:0;min-width:0;
    padding:0!important;margin:0!important;max-width:none;
}
.mu-panel-handle {
    position:relative;width:100%;height:100%;cursor:col-resize;touch-action:none;
    display:flex;align-items:center;justify-content:center;outline:none;
}
.mu-panel-handle::before {
    content:'';position:absolute;width:3px;height:48px;border-radius:3px;
    background:#426676;transition:background .12s ease,height .12s ease;
}
.mu-panel-handle:hover::before,.mu-panel-handle:focus-visible::before,
.mu-panel-handle[aria-grabbed=true]::before {background:#69e5cf;height:80px;}
.mu-panel-handle:focus-visible {outline:2px solid #69e5cf;outline-offset:-3px;border-radius:5px;}
body.mu-panel-resizing,body.mu-panel-resizing * {cursor:col-resize!important;user-select:none!important;}
body.mu-panel-resizing #workbench-viewer {pointer-events:none;}
#layout-reset-control {padding:0!important;border:0!important;background:transparent!important;min-height:0!important;}
#reset-panel-layout {width:100%;min-height:26px;padding:4px 6px;font-size:11px!important;}
#app-header > .column:last-child {gap:4px!important;}
@media(max-width:1250px) {#workspace {--mu-default-left:290px;--mu-default-right:270px;}}
@media(max-width:1050px) {#workspace {--mu-default-left:270px;--mu-default-right:240px;}}
@media(prefers-reduced-motion:reduce) {.mu-panel-handle::before {transition:none;}}
"""


def handle(side):
    panel = "settings" if side == "left" else "inspector"
    target = "controls" if side == "left" else "inspectors"
    return (f'<div id="mu-{side}-handle" class="mu-panel-handle" role="separator" tabindex="0" '
            f'aria-label="Resize {side} {panel} panel" aria-orientation="vertical" aria-controls="{target}" '
            'aria-keyshortcuts="ArrowLeft ArrowRight Home End" '
            'title="Drag to resize · Arrow keys adjust · Shift moves faster · Double-click resets this panel"></div>')


RESET = ('<button id="reset-panel-layout" class="secondary" type="button" '
         'title="Restore the default settings and inspector widths">Reset layout</button>')

# Installed through the HTML component's supported on-load hook, without a
# server callback or rebuilding/replacing the persistent Babylon viewer.
JS = r"""
(() => {
 const key='modelunify.workbench.panel-widths.v1';
 let dispose=null;
 const mounting=new MutationObserver(attach);
 mounting.observe(document.body,{childList:true,subtree:true});
 attach();
 function attach(){
  if(!element.isConnected){if(dispose){dispose();mounting.disconnect();}return;}
  if(dispose)return;
  const workspace=element.closest('#workspace');
  const left=workspace?.querySelector('#mu-left-handle');
  const right=workspace?.querySelector('#mu-right-handle');
  const reset=document.getElementById('reset-panel-layout');
  if(!left||!right||!reset||!workspace.querySelector('#inspectors'))return;
  let preferred={},current={},drag=null;
  try{
   const saved=JSON.parse(localStorage.getItem(key));
   for(const side of ['left','right'])if(typeof saved?.[side]==='number'&&Number.isFinite(saved[side])&&saved[side]>0)
    preferred[side]=saved[side];
  }catch(_){} // Storage can be unavailable in private/restricted browser profiles.
  const listeners=[];
  const listen=(node,type,fn)=>{node.addEventListener(type,fn);listeners.push(()=>node.removeEventListener(type,fn));};
  const clamp=(value,min,max)=>Math.max(min,Math.min(value,max));
  function limits(){
   const width=Math.max(1,workspace.getBoundingClientRect().width-28);
   // Preserve usable controls and at least a 360px viewer on desktop widths.
   // Smaller windows share the available space rather than creating page scroll.
   const viewer=Math.min(360,Math.max(1,width*.45));
   const budget=width-viewer;
   const leftMin=Math.min(260,budget*.53),rightMin=Math.min(230,budget*.47);
   return {budget,leftMin,rightMin};
  }
  function defaults(){
   const style=getComputedStyle(workspace);
   return {left:parseFloat(style.getPropertyValue('--mu-default-left'))||340,
           right:parseFloat(style.getPropertyValue('--mu-default-right'))||310};
  }
  function save(){try{localStorage.setItem(key,JSON.stringify(preferred));}catch(_){}}
  function apply(){
   const bounds=limits(),base=defaults();
   let l=clamp(preferred.left??base.left,bounds.leftMin,560);
   let r=clamp(preferred.right??base.right,bounds.rightMin,500);
   if(l+r>bounds.budget){
    const extra=(l-bounds.leftMin)+(r-bounds.rightMin);
    const factor=extra>0?Math.max(0,(bounds.budget-bounds.leftMin-bounds.rightMin)/extra):0;
    l=bounds.leftMin+(l-bounds.leftMin)*factor;r=bounds.rightMin+(r-bounds.rightMin)*factor;
   }
   current={left:l,right:r};
   workspace.style.setProperty('--mu-left',l+'px');workspace.style.setProperty('--mu-right',r+'px');
   for(const [side,handle] of [['left',left],['right',right]]){
    const min=bounds[side+'Min'];
    const max=Math.max(min,Math.min(side==='left'?560:500,bounds.budget-current[side==='left'?'right':'left']));
    handle.setAttribute('aria-valuemin',Math.round(min));handle.setAttribute('aria-valuemax',Math.round(max));
    handle.setAttribute('aria-valuenow',Math.round(current[side]));
    handle.setAttribute('aria-valuetext',Math.round(current[side])+' pixels');
   }
  }
  function set(side,value){
   const handle=side==='left'?left:right;
   preferred[side]=clamp(value,Number(handle.getAttribute('aria-valuemin')),Number(handle.getAttribute('aria-valuemax')));
   apply();
  }
  function finish(cancel=false){
   if(!drag)return;
   const old=drag;drag=null;
   if(cancel){preferred=old.preferred;apply();}else save();
   document.body.classList.remove('mu-panel-resizing');
   old.handle.removeAttribute('aria-grabbed');
   if(old.handle.hasPointerCapture(old.pointer))old.handle.releasePointerCapture(old.pointer);
  }
  for(const [side,handle] of [['left',left],['right',right]]){
   listen(handle,'pointerdown',event=>{
    if(event.button!==0||drag)return;
    event.preventDefault();handle.focus();
    drag={side,handle,pointer:event.pointerId,x:event.clientX,width:current[side],preferred:{...preferred}};
    handle.setPointerCapture(event.pointerId);handle.setAttribute('aria-grabbed','true');
    document.body.classList.add('mu-panel-resizing');
   });
   listen(handle,'pointermove',event=>{
    if(drag?.handle!==handle||event.pointerId!==drag.pointer)return;
    set(side,drag.width+(event.clientX-drag.x)*(side==='left'?1:-1));
   });
   listen(handle,'pointerup',event=>{if(event.pointerId===drag?.pointer)finish();});
   listen(handle,'pointercancel',()=>finish(true));
   listen(handle,'lostpointercapture',()=>finish(true));
   listen(handle,'dblclick',()=>{finish(true);delete preferred[side];apply();save();});
   listen(handle,'keydown',event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();
    const step=event.shiftKey?40:12;
    const delta=(event.key==='ArrowRight'?step:-step)*(side==='left'?1:-1);
    const value=event.key==='Home'?Number(handle.getAttribute('aria-valuemin')):
     event.key==='End'?Number(handle.getAttribute('aria-valuemax')):current[side]+delta;
    set(side,value);save();
   });
  }
  listen(document,'keydown',event=>{if(event.key==='Escape'&&drag){event.preventDefault();finish(true);}});
  listen(window,'blur',()=>finish(true));
  listen(reset,'click',()=>{finish(true);preferred={};apply();try{localStorage.removeItem(key);}catch(_){}});
  const resize=new ResizeObserver(apply);resize.observe(workspace);
  apply();workspace.dataset.resizable='true';
  dispose=()=>{finish(true);resize.disconnect();for(const remove of listeners)remove();};
 }
})();
"""
