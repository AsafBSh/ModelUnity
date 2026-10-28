/* Actual isolated jobs: count miss, surface-error rejection, success and checkpoint isolation. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const out=path.resolve(process.env.MODELUNIFY_TEST_OUTPUT||'.runtime/optimization-reliability/ui-safeguards');
 fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1440,height:900}});
 const errors=[];page.on('pageerror',error=>errors.push(error.message));
 const triangles=async()=>Number((await page.locator('#asset-summary').innerText()).match(/([\d,]+) triangles/)[1].replaceAll(',',''));
 async function run(expected){
  await page.getByRole('button',{name:'Optimize current asset',exact:true}).click();
  await page.waitForFunction(()=>/Optimize queued/.test(document.querySelector('#stage-status').textContent));
  await page.waitForFunction(pattern=>new RegExp(pattern).test(document.querySelector('#stage-status').textContent),expected,{timeout:120000});
 }
 try {
  for(let attempt=0;;attempt++) {
   try {await page.goto((process.env.MODELUNIFY_TEST_URL||'http://127.0.0.1:7861')+'/?__theme=dark',{waitUntil:'domcontentloaded'});break;}
   catch(error){if(attempt>=30||!error.message.includes('ERR_CONNECTION_REFUSED'))throw error;await page.waitForTimeout(2000);}
  }
  await page.waitForFunction(()=>window.muWorkbenchViewer&&['true','empty'].includes(document.querySelector('#workbench-viewer canvas')?.dataset.ready),null,{timeout:60000});
  const initial=await page.evaluate(()=>window.muWorkbenchViewer.loaded);
  await page.getByText('Import a GLB',{exact:true}).click();
  await page.locator('input[type=file][accept=".glb"]').setInputFiles(process.env.MODELUNIFY_TEST_MESH||'bms_export/residential_5/Model_0.glb');
  await page.waitForFunction(previous=>document.querySelector('#workbench-viewer canvas')?.dataset.ready==='true'&&window.muWorkbenchViewer.loaded!==previous,initial,{timeout:60000});
  const originalTriangles=await triangles();
  assert.equal(originalTriangles,40000,'This real-asset regression expects the inspected residential master');
  await page.locator('#project-name textarea').fill('optimization_safeguards_validation');
  await page.getByRole('radio',{name:'04 Optimize',exact:true}).check();
  await page.getByLabel('Target triangles',{exact:true}).fill('2000');
  await page.locator('#opt-strict input[type=checkbox]').check();
  await page.getByText('Optimization safeguards',{exact:true}).click();
  const passes=page.locator('#opt-passes input[type=number]');
  await passes.fill('1');await passes.press('Tab');
  await run('Strict triangle budget not reached');
  assert.equal(await triangles(),originalTriangles,'Failed budget replaced original preview');
  await passes.fill('3');await passes.press('Tab');
  await run('Sampled surface error');
  assert.equal(await triangles(),originalTriangles,'Surface-error rejection replaced the original preview');
  await page.getByLabel('Target triangles',{exact:true}).fill('8000');
  await run('Optimize.*completed');
  await page.waitForFunction(()=>/7,999 triangles/.test(document.querySelector('#asset-summary').textContent));
  await page.getByRole('button',{name:'Accept / checkpoint',exact:true}).click();
  await page.getByText('Accepted checkpoint',{exact:false}).waitFor();
  const accepted=await page.evaluate(()=>window.muWorkbenchViewer.loaded);
  await page.locator('#controls').evaluate(e=>e.scrollTop=0);
  await page.screenshot({path:path.join(out,'bounded-optimization.png')});
  await page.getByLabel('Target triangles',{exact:true}).fill('1');
  await page.locator('#opt-boundary input[type=checkbox]').check();
  await run('Strict triangle budget not reached');
  assert.equal(await triangles(),7999,'Failed retry replaced the accepted mesh');
  assert.equal(await page.evaluate(()=>window.muWorkbenchViewer.loaded),accepted,'Failed retry changed the viewport asset');
  await page.locator('#controls').evaluate(e=>e.scrollTop=0);
  await page.screenshot({path:path.join(out,'optimization-safeguards.png')});
  assert.deepEqual(errors,[]);
  const report={passed:true,onePassBudgetRejected:true,countMetButSurfaceErrorRejected:true,workingBudgetAchieved:7999,failedRetryPreservesCheckpoint:true,browserErrors:errors};
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }catch(error){await page.screenshot({path:path.join(out,'failure.png')});throw error;}
 finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
