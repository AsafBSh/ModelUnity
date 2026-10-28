/* Exercise CPU-only accuracy tools against an isolated server and synthetic fixture. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('fs');const path=require('path');
const root=path.resolve('.runtime/accuracy-tools');
const url=process.env.MODELUNIFY_TEST_URL||'http://127.0.0.1:17891';
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1440,height:900}});const errors=[];
 page.on('pageerror',error=>{errors.push(error.message);console.error('FRONTEND',error.stack);});
 page.on('console',message=>{if(message.type()==='error'&&message.text().includes('Error executing js_on_load'))errors.push(message.text());});
 const check=async()=>{assert.equal(await page.locator('#workbench-viewer canvas').count(),1);assert.equal(await page.evaluate(()=>document.documentElement.scrollHeight>innerHeight+1),false);};
 async function tab(name){
  const visible=page.locator('#inspector-tabs').getByRole('tab',{name,exact:true});
  if(await visible.count())await visible.click();
  else {await page.locator('#inspector-tabs .overflow-menu > button').click();await page.locator('#inspector-tabs .overflow-dropdown').getByRole('button',{name,exact:true}).click();}
 }
 async function complete(stage){
  console.log('Waiting for',stage);
  await page.waitForFunction(stage=>document.querySelector('#stage-status')?.textContent.includes(stage+' · completed'),stage,{timeout:90000});
  await page.waitForFunction(()=>document.querySelector('#workbench-viewer canvas')?.dataset.ready==='true');
 }
 try{
  for(let attempt=0;;attempt++){
   try{await page.goto(url+'/?__theme=dark',{timeout:60000,waitUntil:'domcontentloaded'});break;}
   catch(error){if(attempt>=50||!error.message.includes('ERR_CONNECTION_REFUSED'))throw error;await page.waitForTimeout(2000);}
  }
  await page.waitForFunction(()=>document.querySelector('#workbench-viewer canvas')?.dataset.ready==='true',null,{timeout:90000});
  await check();
  await page.locator('#view-front input[type=file]').setInputFiles(path.join(root,'reference.png'));
  await page.getByText('Manual mask correction',{exact:true}).click();
  await page.locator('#mask-load').click();
  await page.locator('#mask-editor canvas[data-ready=true]').waitFor({timeout:60000});
  await page.waitForTimeout(2000);
  const editor=page.locator('#mask-editor canvas').last();await editor.scrollIntoViewIfNeeded();
  const rect=await editor.boundingBox();assert(rect&&rect.width>20&&rect.height>20);
  await page.mouse.move(rect.x+rect.width*.2,rect.y+rect.height*.2);
  await page.mouse.down();await page.mouse.move(rect.x+rect.width*.3,rect.y+rect.height*.2,{steps:6});await page.mouse.up();
  await page.locator('#mask-apply').click();
  await page.waitForFunction(()=>document.querySelector('#stage-status')?.textContent.includes('Corrected alpha applied'),null,{timeout:30000});
  await page.screenshot({path:path.join(root,'mask-editor.png')});
  console.log('Mask paint/apply passed');
  await tab('Reference');
  await page.getByRole('button',{name:'Use selected input view',exact:true}).click();
  await page.locator('#align-reference img').first().waitFor();
  await page.locator('#align-go').click();
  await page.getByText('intersection_over_union',{exact:false}).first().waitFor({timeout:30000});
  await page.screenshot({path:path.join(root,'reference-overlay.png')});await check();
  console.log('Reference overlay passed');
  await page.getByRole('radio',{name:'04 Optimize',exact:true}).check();
  await page.getByText('Protect parts during optimization',{exact:true}).click();
  await page.getByLabel('Protected triangle IDs (zero-based, comma-separated)',{exact:true}).fill('0,1');
  await page.getByLabel('Target triangles',{exact:true}).fill('200');
  await page.locator('#protect-check').click();
  await page.waitForFunction(()=>window.muWorkbenchViewer.loaded?.includes('protected_'),null,{timeout:30000});
  const canvas=page.locator('#workbench-viewer canvas');const box=await canvas.boundingBox();
  await page.keyboard.down('Shift');await page.mouse.click(box.x+box.width*.5,box.y+box.height*.5);await page.keyboard.up('Shift');
  const picked=await page.locator('#protect-center textarea').inputValue();
  assert(picked.split(',').length===3,'Shift-click must pick an actual mesh point');
  await page.screenshot({path:path.join(root,'protected-selection.png')});
  console.log('Protected selection and 3D point picking passed');
  await page.getByRole('button',{name:'Optimize current asset',exact:true}).click();await complete('Optimize');
  await tab('UV');await page.getByText('Repair UVs / rebake textures',{exact:true}).click();
  await page.getByRole('radio',{name:'256',exact:true}).last().check();
  await page.locator('#rebake-source input[type=file]').setInputFiles(path.join(root,'fixture.glb'));
  await page.locator('#rebake-go').click();await complete('Rebake');await check();
  await page.screenshot({path:path.join(root,'rebaked-preview.png')});
  await page.getByRole('radio',{name:'05 Export',exact:true}).check();
  await page.locator('#lod_count input[type=number]').fill('1');await page.locator('#lod_count input[type=number]').press('Enter');
  await page.getByText('General interchange / BMS handoff',{exact:true}).click();await page.locator('#package-bms input').check();
  await page.getByRole('button',{name:'Export LOD set',exact:true}).click();await complete('Export');
  await page.screenshot({path:path.join(root,'export-handoff.png')});await check();
  assert.deepEqual(errors,[]);console.log(JSON.stringify({maskPaintAndApply:true,referenceOverlay:true,protectedPickAndOptimization:true,queuedRebake:true,bmsHandoff:true,single3dViewport:true,browserErrors:errors}));
 }catch(error){console.error(error);console.error('Browser errors:',errors);console.error('STATUS',await page.locator('#stage-status').innerText({timeout:3000}).catch(()=>''));console.error(await page.locator('.viewer-message').innerText({timeout:3000}).catch(()=>''));
  await page.screenshot({path:path.join(root,'browser-failure.png'),timeout:5000}).catch(()=>{});throw error;}
 finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
