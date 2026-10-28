/* Actual pointer/keyboard resizing, persistence and stationary-viewer checks. No inference. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const out=path.resolve(process.env.MODELUNIFY_TEST_OUTPUT||'.runtime/workbench-layout');
 fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1440,height:900},deviceScaleFactor:2});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const key='modelunify.workbench.panel-widths.v1';
 const sizes=()=>page.evaluate(()=>Object.fromEntries(['controls','viewport','inspectors'].map(id=>[id,document.getElementById(id).getBoundingClientRect().width])));
 async function ready(){
  await page.locator('#workspace[data-resizable=true]').waitFor({timeout:60000});
  await page.waitForFunction(()=>document.querySelector('#workbench-viewer canvas')?.dataset.ready==='true',null,{timeout:60000});
 }
 async function layout(){
  await page.waitForTimeout(200);
  const value=await sizes();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollHeight>innerHeight+1||document.documentElement.scrollWidth>innerWidth+1),false);
  assert.equal(await page.locator('#workbench-viewer canvas').count(),1);
  for(const side of ['left','right']){
   const box=await page.locator('#mu-'+side+'-handle').boundingBox();
   assert.ok(box&&box.width>=13&&box.height>200,'Divider must retain a full-height hit target');
  }
  assert.ok(value.controls>0&&value.inspectors>0&&value.viewport>=359,value);
  return value;
 }
 async function drag(side,dx,finish=true){
  const box=await page.locator('#mu-'+side+'-handle').boundingBox();
  await page.mouse.move(box.x+box.width/2,box.y+box.height/2);
  await page.mouse.down();await page.mouse.move(box.x+box.width/2+dx,box.y+box.height/2,{steps:8});
  if(finish)await page.mouse.up();
  await page.waitForTimeout(250);
 }
 try{
  await page.goto((process.env.MODELUNIFY_TEST_URL||'http://127.0.0.1:7861')+'/?__theme=dark');
  await ready();
  await page.getByRole('button',{name:'Reset layout',exact:true}).click();
  const initial=await layout();
  await page.evaluate(()=>{
   window.layoutTestCanvas=document.querySelector('#workbench-viewer canvas');
   const c=window.muWorkbenchViewer.details.camera;
   window.layoutTestCamera={alpha:c.alpha,beta:c.beta,radius:c.radius,target:c.target.asArray()};
   window.layoutTestAsset=window.muWorkbenchViewer.loaded;
  });
  await drag('left',100);
  const left=await layout();assert.ok(Math.abs(left.controls-initial.controls-100)<3);
  assert.ok(Math.abs(left.inspectors-initial.inspectors)<2);
  await drag('right',-80);
  const expanded=await layout();assert.ok(Math.abs(expanded.inspectors-initial.inspectors-80)<3);
  assert.ok(Math.abs(expanded.controls-left.controls)<2);
  const viewer=await page.evaluate(()=>{
   const c=window.muWorkbenchViewer.details.camera,canvas=document.querySelector('#workbench-viewer canvas');
   return {sameCanvas:canvas===window.layoutTestCanvas,sameAsset:window.muWorkbenchViewer.loaded===window.layoutTestAsset,
    old:window.layoutTestCamera,now:{alpha:c.alpha,beta:c.beta,radius:c.radius,target:c.target.asArray()},
    canvasWidth:canvas.width,renderWidth:window.muWorkbenchViewer.details.scene.getEngine().getRenderWidth()};
  });
  assert.equal(viewer.sameCanvas,true);assert.equal(viewer.sameAsset,true);assert.deepEqual(viewer.old,viewer.now);
  assert.equal(viewer.canvasWidth,viewer.renderWidth);
  await page.screenshot({path:path.join(out,'panels-expanded.png')});
  await page.reload();await ready();
  const restored=await layout();assert.ok(Math.abs(restored.controls-expanded.controls)<2);assert.ok(Math.abs(restored.inspectors-expanded.inspectors)<2);
  await page.getByRole('radio',{name:'04 Optimize',exact:true}).check();
  assert.ok(Math.abs((await sizes()).controls-restored.controls)<2);
  const handle=page.getByRole('separator',{name:'Resize left settings panel',exact:true});
  await handle.focus();await handle.press('ArrowRight');
  assert.ok(Math.abs((await sizes()).controls-restored.controls-12)<2);
  await handle.press('Shift+ArrowLeft');
  assert.ok(Math.abs((await sizes()).controls-restored.controls+28)<2);
  const beforeCancel=await sizes();
  await drag('left',80,false);await page.keyboard.press('Escape');await page.mouse.up();
  assert.ok(Math.abs((await sizes()).controls-beforeCancel.controls)<2);
  assert.equal(await page.locator('body.mu-panel-resizing').count(),0);
  const preferred=await sizes();
  await page.setViewportSize({width:900,height:720});await layout();
  await page.setViewportSize({width:1440,height:900});await layout();
  assert.ok(Math.abs((await sizes()).controls-preferred.controls)<2);assert.ok(Math.abs((await sizes()).inspectors-preferred.inspectors)<2);
  await drag('left',3000);await drag('right',-3000);
  const limited=await layout();assert.ok(limited.controls<=561&&limited.inspectors<=501);
  await handle.press('Home');assert.ok((await sizes()).controls>=259&&(await sizes()).controls<=261);
  await page.locator('#mu-right-handle').dblclick();assert.ok(Math.abs((await sizes()).inspectors-initial.inspectors)<2);
  await page.getByRole('button',{name:'Reset layout',exact:true}).click();
  assert.equal(await page.evaluate(key=>localStorage.getItem(key),key),null);
  const reset=await layout();assert.ok(Math.abs(reset.controls-initial.controls)<2);assert.ok(Math.abs(reset.inspectors-initial.inspectors)<2);
  await page.evaluate(key=>localStorage.setItem(key,'{broken json'),key);
  await page.reload();await ready();await layout();
  await page.getByRole('button',{name:'Reset layout',exact:true}).click();
  assert.deepEqual(errors,[]);
  const report={passed:true,initial,expanded,limited,persistence:true,keyboard:true,cancel:true,reset:true,
   responsive:true,singleViewport:true,cameraPreserved:true,browserErrors:errors};
  fs.writeFileSync(path.join(out,'validation.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
 }catch(e){await page.screenshot({path:path.join(out,'failure.png')});throw e;}
 finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
