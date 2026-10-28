/* Actual UI diagnostics, preserved-camera raw comparison, and queued scale. No inference. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const out=path.resolve(process.env.MODELUNIFY_TEST_OUTPUT||'.runtime/workbench-inspection');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1440,height:900}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 async function tab(name){
  const selected=page.getByRole('tab',{name,exact:true});
  if(await selected.count())await selected.click();
  else{await page.locator('#inspector-tabs .overflow-menu > button').click();await page.locator('#inspector-tabs .overflow-dropdown').getByRole('button',{name,exact:true}).click();}
 }
 async function idle(){
  let previous=-1;
  for(let i=0;i<80;i++){
   const frame=await page.evaluate(()=>window.muWorkbenchViewer.details.scene.getFrameId());
   if(frame===previous)return;previous=frame;await page.waitForTimeout(250);
  }
  throw new Error('Viewer did not settle');
 }
 try{
  await page.goto((process.env.MODELUNIFY_TEST_URL||'http://127.0.0.1:7863')+'/?__theme=dark');
  await page.waitForFunction(()=>document.querySelector('#workbench-viewer canvas')?.dataset.ready==='true',null,{timeout:60000});
  await tab('Project');
  await page.getByLabel('Saved projects',{exact:true}).click();
  await page.getByRole('option',{name:/Inspection fixture/}).last().click();
  await page.getByRole('button',{name:'Open saved project',exact:true}).click();
  await page.getByRole('radio',{name:'Raw master',exact:true}).waitFor({timeout:30000});
  await page.waitForFunction(()=>window.muWorkbenchViewer.loaded?.includes('/projects/Inspection_fixture_'));
  const workingUrl=await page.evaluate(()=>window.muWorkbenchViewer.loaded);
  await page.getByRole('button',{name:'Check reference inputs',exact:true}).click();
  await page.getByText('Input readiness / framing findings',{exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#input-readiness')?.textContent.includes('foreground_fraction'));
  assert((await page.locator('#input-readiness').textContent()).includes('alignment_verified'));
  await tab('UV');
  await page.getByRole('button',{name:'Analyze UV / PBR',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#uv-diagnostics').textContent.includes('stretch_anisotropy_median'),null,{timeout:30000});
  assert((await page.locator('#uv-diagnostics').textContent()).includes('overlap_pixels'));
  const camera=()=>page.evaluate(()=>{const c=window.muWorkbenchViewer.details.camera;return {alpha:c.alpha,beta:c.beta,radius:c.radius,target:c.target.asArray()}});
  await idle();const before=await camera();
  await page.getByRole('radio',{name:'Raw master',exact:true}).check();
  await page.waitForFunction(()=>window.muWorkbenchViewer.loaded?.includes('/jobs/fixture/master.glb'));
  await idle();
  assert.deepEqual(await camera(),before);
  await tab('Mesh');
  await page.waitForFunction(()=>document.querySelector('#mesh-inspection').textContent.includes('master.glb'));
  await page.getByRole('radio',{name:'Result',exact:true}).check();
  await page.waitForFunction(url=>window.muWorkbenchViewer.loaded===url,workingUrl);
  await page.getByRole('radio',{name:'05 Export',exact:true}).check();
  await page.getByText('Measured scale / orientation / pivot',{exact:true}).click();
  await page.locator('#s_axis').getByRole('radio',{name:'X',exact:true}).check();
  await page.locator('#s_metres input').fill('7');await page.locator('#s_metres input').press('Tab');
  await page.getByRole('button',{name:'Apply measured scale',exact:true}).click();
  await page.waitForFunction(url=>window.muWorkbenchViewer.loaded?.includes('/jobs/')&&window.muWorkbenchViewer.loaded!==url,workingUrl,{timeout:120000});
  await page.getByRole('button',{name:'Check BMS readiness',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#bms-readiness').textContent.includes('final_game_ready'),null,{timeout:30000});
  const text=await page.locator('#bms-readiness').textContent();assert(text.includes('dimensions_metres'));assert(text.includes('false'));
  await tab('Mesh');
  await page.waitForFunction(()=>document.querySelector('#mesh-inspection').textContent.includes('asset.glb'));
  assert.equal(await page.locator('#workbench-viewer canvas').count(),1);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollHeight>innerHeight+1),false);
  assert.deepEqual(errors,[]);await page.screenshot({path:path.join(out,'inspection-scale.png')});
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({passed:true,inputChecks:true,uvPbr:true,rawComparison:true,cameraPreserved:true,queuedScale:true,bmsReadiness:true,browserErrors:errors},null,2));
  console.log(fs.readFileSync(path.join(out,'result.json'),'utf8'));
 }catch(e){await page.screenshot({path:path.join(out,'failure.png')});throw e;}finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
