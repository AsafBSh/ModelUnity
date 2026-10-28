/* Model-aware ComfyUI controls and single-window layout. No inference. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const out=path.resolve(process.env.MODELUNIFY_TEST_OUTPUT||'.runtime/comfyui/validation/ui');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1440,height:900}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto((process.env.MODELUNIFY_TEST_URL||'http://127.0.0.1:7861')+'/?__theme=dark');
  await page.getByRole('heading',{name:'MODELUNIFY',exact:true}).waitFor();
  if(process.argv.includes('--infer')){
   await page.getByRole('button',{name:'New asset',exact:true}).click();
   await page.getByRole('radio',{name:'01 Inputs',exact:true}).check();
   await page.getByRole('radio',{name:'rembg',exact:true}).check();
  }
  await page.getByRole('radio',{name:'02 Generate',exact:true}).check();
  async function select(name,views){
   await page.getByRole('radio',{name,exact:true}).check();
   await page.waitForTimeout(800);
   assert.equal(await page.locator('#view-left').isVisible(),views);
   assert.equal(await page.locator('#view-back').isVisible(),views);
   assert.equal(await page.locator('#view-right').isVisible(),views);
   assert.equal(await page.locator('#workbench-viewer canvas').count(),1);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollHeight>innerHeight+1),false);
  }
  await select('TRELLIS.2 · ComfyUI',false);
  assert.equal(await page.locator('#c_multiview').isVisible(),false);
  assert.equal(await page.locator('#c_resolution').isVisible(),true);
  assert.equal(await page.locator('#m_steps').isVisible(),false);
  await page.locator('#c_resolution').getByRole('radio',{name:'512',exact:true}).check();
  await page.locator('#c_texture_size').getByRole('radio',{name:'1024',exact:true}).check();
  if(process.argv.includes('--host')){
   await page.getByText('Local ComfyUI host',{exact:true}).click();
   await page.getByRole('button',{name:'Check model',exact:true}).click();
   await page.getByText('Nodes and checkpoint selections available; inference not yet validated.',{exact:false}).waitFor({timeout:30000});
  }
  if(process.argv.includes('--infer')){
   await page.locator('#project-name textarea').fill('comfy_browser_validation');
   await page.locator('#view-front input[type=file]').setInputFiles(process.env.MODELUNIFY_TEST_REFERENCE||'.runtime/comfyui/validation/axe.png');
   await page.locator('#view-front img').waitFor();
   for(const [id,value] of [['c_resolution','512'],['c_texture_size','1024']]){
    await page.locator('#'+id).getByRole('radio',{name:value,exact:true}).check();
   }
   await page.getByText('Working mesh · raw master retained',{exact:true}).click();
   for(const [id,value] of [['c_remesh_resolution','512'],['c_faces','200000']]){
    const field=page.locator('#'+id+' input[type=number]');await field.fill(value);await field.press('Tab');
   }
   await page.getByRole('button',{name:'Generate mesh',exact:true}).click();
   await page.locator('#stage-status').getByText(/Generate queued/).waitFor();
   await page.locator('#stage-status').getByText(/Generate.*completed/).waitFor({timeout:300000});
   await page.waitForFunction(()=>document.querySelector('#workbench-viewer canvas')?.dataset.ready==='true',null,{timeout:90000});
   const summary=await page.locator('#asset-summary').innerText();
   assert.match(summary,/UVs: valid/);assert.match(summary,/metallic_roughness/);
   assert.equal(await page.locator('#workbench-viewer canvas').count(),1);
   await page.screenshot({path:path.join(out,'trellis-generated-pbr.png')});
   fs.writeFileSync(path.join(out,'inference-result.json'),JSON.stringify({passed:true,summary,browserErrors:errors},null,2));
   assert.deepEqual(errors,[]);
   console.log(JSON.stringify({passed:true,realQueuedInference:true,pbr:true,rawMasterRetained:true,browserErrors:errors}));
   return;
  }
  await select('Pixal3D · ComfyUI',false);
  await page.locator('#c_multiview input').check();await page.waitForTimeout(800);
  for(const name of ['front','left','back','right'])assert.equal(await page.locator('#view-'+name).isVisible(),true);
  await page.locator('#c_fov').scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(out,'pixal-multiview.png')});
  await select('TRELLIS.2 · ComfyUI',false);
  await select('Hunyuan3D-2mv',true);
  await select('TripoSG 1.5B',false);
  assert.equal(await page.locator('#c_resolution').isVisible(),false);
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({passed:true,models:4,comfyMultiview:true,singleViewport:true,pageScroll:false,browserErrors:errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
