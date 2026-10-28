/* Browser validation against the running local preview. No GPU inference. */
const fs = require('fs');
const path = require('path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const out = path.resolve(process.env.MODELUNIFY_TEST_OUTPUT || '.runtime/workbench_preview/screenshots');
  const url = process.env.MODELUNIFY_TEST_URL || 'http://127.0.0.1:7861';
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROME_PATH || path.join(process.env.ProgramFiles || 'C:/Program Files', 'Google/Chrome/Application/chrome.exe'),
    args: ['--enable-unsafe-swiftshader'],
  });
  const deviceScaleFactor = process.argv.includes('--high-dpi') ? 2 : 1;
  const page = await browser.newPage({ viewport: { width: 1366, height: 768 }, deviceScaleFactor });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  try {
    for (let attempt = 0; ; attempt++) {
      try {
        await page.goto(url + '/?__theme=dark', { waitUntil: 'domcontentloaded', timeout: 60000 });
        break;
      } catch (error) {
        if (attempt >= 60 || !error.message.includes('ERR_CONNECTION_REFUSED')) throw error;
        await page.waitForTimeout(2000);
      }
    }
    await page.getByRole('heading', { name: 'MODELUNIFY', exact: true }).waitFor();
    await page.locator('#workbench-viewer canvas').first().waitFor({ timeout: 60000 });
    await page.waitForTimeout(3500);
    async function assertLayout() {
      const layout = await page.evaluate(() => ({
        pageScroll: document.documentElement.scrollHeight > innerHeight + 1,
        panels: ['controls', 'viewport', 'inspectors'].map(id => {
          const e = document.getElementById(id), r = e.getBoundingClientRect();
          return { id, top:r.top, bottom:r.bottom, right:r.right, height:r.height,
                   overflow:getComputedStyle(e).overflowY, scrollHeight:e.scrollHeight, clientHeight:e.clientHeight };
        }), children: ['stage-tabs', 'inspector-tabs'].map(id => {
          const e=document.getElementById(id), r=e.getBoundingClientRect(), parent=e.closest('#controls, #inspectors').getBoundingClientRect();
          return {id,left:r.left,right:r.right,parentLeft:parent.left,parentRight:parent.right};
        }), width:innerWidth, height:innerHeight,
      }));
      if (layout.pageScroll || layout.panels.some(r => r.top < 0 || r.bottom > layout.height + 1 || r.right > layout.width + 1 || r.height < 240)) {
        throw new Error('Workbench does not fit one window: ' + JSON.stringify(layout));
      }
      if (layout.children.some(r => r.left < r.parentLeft || r.right > r.parentRight)) {
        throw new Error('Panel content wrapped outside its scrollbar: ' + JSON.stringify(layout));
      }
      if (await page.locator('#workbench-viewer canvas').count() !== 1) throw new Error('Expected exactly one 3D viewport');
      return layout;
    }
    await assertLayout();
    for (const direction of ['front', 'left', 'back', 'right']) {
      await page.locator('#view-' + direction).waitFor({ state: 'visible' });
    }
    if (process.argv.includes('--layout-only')) {
      const sizes = [{width:1280,height:720}, {width:1366,height:768}, {width:1536,height:864}, {width:1600,height:900}];
      for (const size of sizes) {
        await page.setViewportSize(size);
        for (const stage of ['01 Inputs', '02 Generate', '03 Texture', '04 Optimize', '05 Export']) {
          await page.getByRole('radio', {name:stage, exact:true}).check();
          await page.waitForTimeout(250);
          await assertLayout();
        }
      }
      await page.getByRole('radio', {name:'02 Generate', exact:true}).check();
      await page.locator('#controls').evaluate(e=>e.scrollTop=0);
      await page.waitForTimeout(800);
      await page.screenshot({path:path.join(out,'compact-workbench.png'),fullPage:true});
      const bar = await page.locator('#controls').evaluate(e=>({width:getComputedStyle(e,'::-webkit-scrollbar').width,
        color:getComputedStyle(e,'::-webkit-scrollbar-thumb').backgroundColor}));
      if (bar.width !== '16px') throw new Error('Expected a 16px scrollbar');
      // Exercise the native keyboard path, including focus visibility and model-aware fields.
      const single = page.getByRole('radio', {name:'TripoSG 1.5B',exact:true});
      await single.focus();
      await single.press('Space');
      await page.locator('#view-left').waitFor({state:'hidden'});
      const multi = page.getByRole('radio', {name:'Hunyuan3D-2mv',exact:true});
      await multi.focus();
      await multi.press('Space');
      await page.locator('#view-left').waitFor({state:'visible'});
      const projectName = page.locator('#project-name textarea');
      await projectName.focus();
      const focus = await projectName.evaluate(e=>({focused:document.activeElement===e,
        outline:getComputedStyle(e).outlineStyle, width:getComputedStyle(e).outlineWidth}));
      if (!focus.focused || focus.outline === 'none' || parseFloat(focus.width) < 2) {
        throw new Error('Keyboard focus is not visible: '+JSON.stringify(focus));
      }
      if (errors.length) throw new Error(errors.join('\n'));
      console.log(JSON.stringify({passed:true,singleViewport:true,pageScroll:false,sizes,deviceScaleFactor,
        keyboardModelSelection:true,visibleFocus:true,scrollbar:bar,browserErrors:errors}));
      return;
    }
    if (process.env.MODELUNIFY_TEST_MESH) {
      await page.getByText('Import a GLB',{exact:true}).click();
      await page.locator('input[type=file][accept=".glb"]').setInputFiles(process.env.MODELUNIFY_TEST_MESH);
    }
    await page.waitForFunction(()=>document.querySelector('#workbench-viewer canvas')?.dataset.ready==='true',null,{timeout:60000});
    const camera=await page.evaluate(()=>{const c=window.muWorkbenchViewer.details.camera;c.alpha=.7;c.beta=1.1;c.radius=4;return {alpha:c.alpha,beta:c.beta,radius:c.radius};});
    await page.getByRole('radio',{name:'Wireframe',exact:true}).check();
    await page.waitForFunction(()=>window.muWorkbenchViewer.details.scene.forceWireframe);
    await page.getByRole('radio',{name:'PBR / solid',exact:true}).check();
    await page.getByLabel('Inspect material',{exact:true}).click();
    await page.getByRole('option',{name:'Roughness',exact:true}).click();
    await page.waitForFunction(()=>window.muWorkbenchViewer.loaded?.includes('_Roughness.glb'));
    const changed=await page.evaluate(()=>{const c=window.muWorkbenchViewer.details.camera;return {alpha:c.alpha,beta:c.beta,radius:c.radius};});
    for(const k of Object.keys(camera))if(Math.abs(camera[k]-changed[k])>1e-5)throw new Error('Camera changed on material switch: '+JSON.stringify({camera,changed}));
    await page.getByLabel('Inspect material',{exact:true}).click();
    await page.getByRole('option',{name:'PBR',exact:true}).click();
    await page.locator('#view-front input[type=file]').setInputFiles(process.env.MODELUNIFY_TEST_REFERENCE || '.runtime/benchmark-building.png');
    await page.locator('#view-front img').waitFor();
    await page.getByRole('radio',{name:'02 Generate',exact:true}).check();
    await page.getByRole('radio',{name:'TripoSG 1.5B',exact:true}).check();
    await page.locator('#view-left').waitFor({state:'hidden'});
    await page.locator('#view-back').waitFor({state:'hidden'});
    await page.getByRole('radio',{name:'HQ',exact:true}).first().check();
    await page.waitForFunction(()=>document.querySelector('#t_steps input[type=number]').value==='75');
    await page.locator('#t_steps input[type=number]').fill('61');
    await page.locator('#t_steps input[type=number]').press('Tab');
    await page.getByRole('radio',{name:'Hunyuan3D-2mv',exact:true}).check();
    for(const d of ['front','left','back','right'])await page.locator('#view-'+d).waitFor({state:'visible'});
    await page.getByRole('radio',{name:'04 Optimize',exact:true}).check();
    await page.locator('#project-name textarea').fill('workbench_browser_validation');
    await page.getByRole('button',{name:'Optimize current asset',exact:true}).click();
    await page.locator('#stage-status').getByText(/Optimize.*completed/).waitFor({timeout:120000});
    await page.waitForFunction(()=>/([\d,]+) triangles/.test(document.querySelector('#asset-summary').textContent) && Number(document.querySelector('#asset-summary').textContent.match(/([\d,]+) triangles/)[1].replaceAll(',',''))<=8000,null,{timeout:30000});
    const achieved=Number((await page.locator('#asset-summary').innerText()).match(/([\d,]+) triangles/)[1].replaceAll(',',''));
    await page.getByRole('button',{name:'Accept / checkpoint',exact:true}).click();
    await page.getByText('Accepted checkpoint',{exact:false}).waitFor();
    async function inspector(name){
      const tab=page.getByRole('tab',{name,exact:true});
      if(await tab.isVisible())await tab.click();
      else {await page.locator('#inspector-tabs .overflow-menu > button').click();await page.locator('#inspector-tabs .overflow-dropdown').getByRole('button',{name,exact:true}).click();}
    }
    await inspector('Project');
    await page.getByRole('button',{name:'Save project',exact:true}).click();
    await page.getByText('Project saved, including image pixels',{exact:false}).waitFor();
    await page.locator('#project-name textarea').fill('unsaved_change');
    await page.getByRole('button',{name:'Open saved project',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#project-name textarea').value==='workbench_browser_validation');
    await page.getByRole('radio',{name:'02 Generate',exact:true}).check();
    await page.getByRole('radio',{name:'TripoSG 1.5B',exact:true}).check();
    await page.locator('#view-front img').waitFor();
    if(await page.locator('#t_steps input[type=number]').inputValue()!=='61')throw new Error('Restoring a project replaced custom values with a preset');
    await page.getByRole('radio',{name:'05 Export',exact:true}).check();
    await page.locator('#lod_count input[type=number]').fill('2');await page.locator('#lod_count input[type=number]').press('Tab');
    await page.locator('#budget_1 input').fill('2000');
    await page.getByRole('button',{name:'Export LOD set',exact:true}).click();
    await page.locator('#stage-status').getByText(/Export.*completed/).waitFor({timeout:120000});
    const qualityWarningsVisible=(await page.locator('#stage-status').innerText()).includes('Warnings:');
    if(qualityWarningsVisible && await page.locator('#stage-status .mu-warning').count()!==1) {
      throw new Error('Completed-job warnings are missing the warning status treatment');
    }
    await inspector('UV');
    await page.getByText('Actual UV triangle edges',{exact:false}).waitFor();
    await page.getByRole('radio',{name:'02 Generate',exact:true}).check();
    await page.getByRole('radio',{name:'Hunyuan3D-2mv',exact:true}).check();
    await page.locator('#controls').evaluate(e=>e.scrollTop=0);
    await assertLayout();
    await page.waitForTimeout(800);
    await page.waitForFunction(()=>document.querySelector('.viewer-message')?.textContent.startsWith('PBR'));
    await page.screenshot({path:path.join(out,'cad-workbench.png'),fullPage:true});
    await page.getByRole('button',{name:'New asset',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#workbench-viewer canvas')?.dataset.ready==='empty');
    if(await page.locator('#workbench-viewer canvas').count()!==1)throw new Error('New asset replaced/duplicated the viewport');
    if(errors.length)throw new Error(errors.join('\n'));
    console.log(JSON.stringify({passed:true,cameraPreserved:true,savedProjects:true,customSettingsRestored:true,optimizedTriangles:achieved,exportedLODs:2,qualityWarningsVisible,browserErrors:errors}));
  } catch (error) {
    await page.screenshot({ path: path.join(out, 'failure.png'), fullPage: true });
    throw error;
  } finally {
    await browser.close();
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
