"""Native 2D alpha-stroke editor, isolated from Gradio's ImageEditor state loop."""
import base64
import io
import json
from PIL import Image


def payload(image):
    if max(image.size)>4096:raise ValueError('Manual editing supports up to 4096 pixels per side; resize a copy before editing.')
    stream=io.BytesIO();image.save(stream,format='PNG')
    return json.dumps({'image':'data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode()})


def strokes(background,data):
    if background is None or not isinstance(data,str) or not data.startswith('data:image/png;base64,'):
        raise ValueError('Load the mask editor before applying strokes.')
    if len(data)>32*1024*1024:raise ValueError('Stroke image is too large.')
    raw=base64.b64decode(data.split(',',1)[1],validate=True)
    with Image.open(io.BytesIO(raw)) as image:
        if image.size!=background.size:raise ValueError('Stroke dimensions do not match the loaded reference.')
        layer=image.convert('RGBA')
    return {'background':background,'layers':[layer]}


TEMPLATE='''<div class="mu-alpha-editor">
<div class="mu-alpha-tools"><button type="button" data-mode="white" aria-pressed="true">Restore</button><button type="button" data-mode="black" aria-pressed="false">Remove</button><label>Brush <input aria-label="Mask brush size" type="range" min="1" max="100" value="20"></label><button type="button" data-undo>Undo</button><button type="button" data-clear>Clear strokes</button></div>
<canvas aria-label="Foreground and background mask brush"></canvas><p aria-live="polite">Load a selected reference to edit its alpha.</p></div>'''

CSS='''.mu-alpha-editor{width:100%;font-family:var(--mu-font-ui,"Segoe UI",sans-serif)}
.mu-alpha-tools{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-bottom:8px}
.mu-alpha-tools button{background:#17313b;color:#e4f2f6;border:1px solid #355563;border-radius:8px;padding:7px 9px;cursor:pointer;font:inherit}
.mu-alpha-tools button[aria-pressed="true"]{background:#176254;border-color:#42cdb5}
.mu-alpha-tools label{display:flex;align-items:center;gap:6px;color:#c6dce5;font-size:12px}
.mu-alpha-tools input{width:85px;accent-color:#42cdb5}
.mu-alpha-tools button:focus-visible,.mu-alpha-tools input:focus-visible{outline:2px solid #69ecd0;outline-offset:2px}
.mu-alpha-editor canvas{display:block;width:100%;height:auto;max-height:300px;object-fit:contain;background:#233741;border:1px solid #355563;border-radius:8px;touch-action:none;cursor:crosshair}
.mu-alpha-editor p{color:#c6dce5;font-size:12px;line-height:1.45;margin:8px 0}'''

JS=r'''
const canvas=element.querySelector('canvas'), ctx=canvas.getContext('2d');
const layer=document.createElement('canvas'), brush=layer.getContext('2d');
const message=element.querySelector('p');let image=null,mode='white',drawing=false,history=[],last=null,serial=0;
function fit(){if(!image)return;const scale=Math.min(element.clientWidth/image.width,300/image.height);canvas.style.width=(image.width*scale)+'px';canvas.style.height=(image.height*scale)+'px';}
const resize=new ResizeObserver(fit);resize.observe(element);
function render(){if(!image)return;ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(image,0,0);ctx.globalAlpha=.55;ctx.drawImage(layer,0,0);ctx.globalAlpha=1;}
function point(event){const r=canvas.getBoundingClientRect();return [(event.clientX-r.left)*canvas.width/r.width,(event.clientY-r.top)*canvas.height/r.height];}
function draw(event){if(!drawing)return;const p=point(event);brush.strokeStyle=mode;brush.lineWidth=Number(element.querySelector('input').value)*canvas.width/512;brush.lineCap='round';brush.lineJoin='round';brush.beginPath();brush.moveTo(...last);brush.lineTo(...p);brush.stroke();last=p;render();}
canvas.addEventListener('pointerdown',event=>{if(!image)return;history.push(layer.toDataURL('image/png'));if(history.length>10)history.shift();drawing=true;last=point(event);canvas.setPointerCapture(event.pointerId);draw(event);});
canvas.addEventListener('pointermove',draw);canvas.addEventListener('pointerup',event=>{draw(event);drawing=false;});canvas.addEventListener('pointercancel',()=>{drawing=false;});
element.querySelectorAll('[data-mode]').forEach(button=>button.addEventListener('click',()=>{mode=button.dataset.mode;element.querySelectorAll('[data-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));}));
element.querySelector('[data-undo]').addEventListener('click',()=>{if(!history.length)return;const old=new Image();old.onload=()=>{brush.clearRect(0,0,layer.width,layer.height);brush.drawImage(old,0,0);render();};old.src=history.pop();});
element.querySelector('[data-clear]').addEventListener('click',()=>{if(!image)return;history.push(layer.toDataURL('image/png'));if(history.length>10)history.shift();brush.clearRect(0,0,layer.width,layer.height);render();});
window.muMaskEditor={export:()=>image?layer.toDataURL('image/png'):'',get loaded(){return Boolean(image);}};
async function update(){const token=++serial;const data=JSON.parse(props.value||'{}');if(!data.image)return;const next=new Image();next.onerror=()=>{message.textContent='Reference decoding failed. Reload the selected image.';};next.onload=()=>{if(token!==serial)return;image=next;canvas.width=layer.width=image.width;canvas.height=layer.height=image.height;history=[];drawing=false;fit();render();message.textContent='Restore adds foreground; Remove clears alpha. Undo/Clear affect strokes only. '+image.width+' × '+image.height;canvas.dataset.ready='true';};next.src=data.image;}
update();watch('value',update);
'''
