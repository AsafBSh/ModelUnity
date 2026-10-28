/* Same-camera validation renders of normalized display copies; no source edits. */
const fs=require('node:fs'),path=require('node:path');const {chromium}=require('playwright');
(async()=>{
 const rows=JSON.parse(fs.readFileSync('.runtime/workbench-layout/benchmark_views.json','utf8'));
 const out=path.resolve('.runtime/benchmarks/20261021-workbench/screenshots');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--enable-unsafe-swiftshader']});
 try{
 const page=await browser.newPage({viewport:{width:1440,height:900}});await page.goto('http://127.0.0.1:7863/?__theme=dark');
 await page.waitForFunction(()=>document.querySelector('#workbench-viewer canvas')?.dataset.ready==='true',null,{timeout:60000});
 for(const row of rows){
  const url='/gradio_api/file='+encodeURI(row.file.replaceAll('\\','/'));
  await page.evaluate(async url=>{const w=window.muWorkbenchViewer;await w.viewer.loadModel(url);w.details.scene.forceWireframe=false;w.details.scene.forcePointsCloud=false;},url);
  for(const [name,alpha,beta] of [['front',Math.PI/2,Math.PI/2],['side',0,Math.PI/2],['three-quarter',.9,1.05]]){
   await page.evaluate(({alpha,beta})=>{const d=window.muWorkbenchViewer.details,c=d.camera;c.stopInterpolation();c.setTarget(new c.target.constructor(0,0,0),false,false,true);c.alpha=alpha;c.beta=beta;c.radius=1.8;c.lowerRadiusLimit=.01;c.upperRadiusLimit=10;c.minZ=.001;c.maxZ=100;d.markSceneMutated();},{alpha,beta});
   await page.waitForTimeout(700);await page.locator('#workbench-viewer canvas').screenshot({path:path.join(out,`${row.case}_${row.model}_${name}.png`)});
  }
 }
 console.log(JSON.stringify({rendered:rows.length,cameras:3}));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
