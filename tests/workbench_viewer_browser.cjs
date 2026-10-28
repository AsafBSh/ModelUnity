/* Real rendered-image regression: viewport controls must redraw a stationary scene.
 * Run against a local workbench; uploads an existing GLB without processing it.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const out = path.resolve(process.env.MODELUNIFY_TEST_OUTPUT || '.runtime/viewer-redraw');
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    args: ['--enable-unsafe-swiftshader'],
  });
  const page = await browser.newPage({ viewport: { width: 1366, height: 768 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const frame = () => page.evaluate(() => window.muWorkbenchViewer.details.scene.getFrameId());
  const camera = () => page.evaluate(() => {
    const c = window.muWorkbenchViewer.details.camera;
    return { alpha: c.alpha, beta: c.beta, radius: c.radius, target: c.target.asArray() };
  });
  async function idle() {
    // Wait until the render-on-demand viewer has actually gone idle.
    let previous = await frame();
    for (let attempt = 0; attempt < 60; attempt++) {
      await page.waitForTimeout(250);
      const current = await frame();
      if (current === previous) return current;
      previous = current;
    }
    throw new Error('Viewer never returned to idle rendering');
  }
  const checks = [];
  async function checkRedraw(name, action, state) {
    const beforeFrame = await idle();
    await page.evaluate(() => { window.muRegressionScene = window.muWorkbenchViewer.details.scene; });
    const beforeCamera = await camera();
    const beforeImage = await page.locator('#workbench-viewer canvas').screenshot();
    await action();
    await page.waitForFunction(state);
    await page.waitForFunction(f => window.muWorkbenchViewer.details.scene.getFrameId() > f,
      beforeFrame, { timeout: 5000 }).catch(async error => {
        console.error(name, { beforeFrame, currentFrame: await frame(),
          viewer: await page.evaluate(() => ({ disposed: window.muWorkbenchViewer.details.scene.isDisposed,
            sameScene: window.muRegressionScene === window.muWorkbenchViewer.details.scene,
            mutated: window.muWorkbenchViewer.viewer._sceneMutated,
            message: document.querySelector('.viewer-message').textContent })) });
        throw error;
      });
    await idle();
    const afterImage = await page.locator('#workbench-viewer canvas').screenshot({ path: path.join(out, name + '.png') });
    assert(await page.evaluate(() => window.muRegressionScene === window.muWorkbenchViewer.details.scene),
      name + ': replaced the viewer scene');
    assert(!beforeImage.equals(afterImage), name + ': rendered image did not change');
    assert.deepEqual(await camera(), beforeCamera, name + ': changed the camera');
    checks.push(name);
  }
  try {
    for (let attempt = 0; ; attempt++) {
      try {
        await page.goto((process.env.MODELUNIFY_TEST_URL || 'http://127.0.0.1:7861') + '/?__theme=dark',
          { waitUntil: 'domcontentloaded', timeout: 60000 });
        break;
      } catch (error) {
        if (attempt >= 30 || !error.message.includes('ERR_CONNECTION_REFUSED')) throw error;
        await page.waitForTimeout(2000);
      }
    }
    await page.getByRole('heading', { name: 'MODELUNIFY', exact: true }).waitFor();
    await page.locator('#workbench-viewer canvas').waitFor();
    await page.waitForFunction(() => window.muWorkbenchViewer &&
      ['true', 'empty'].includes(document.querySelector('#workbench-viewer canvas')?.dataset.ready));
    const initialUrl = await page.evaluate(() => window.muWorkbenchViewer.loaded);
    await page.getByText('Import a GLB', { exact: true }).click();
    await page.locator('input[type=file][accept=".glb"]').setInputFiles(
      process.env.MODELUNIFY_TEST_MESH || 'bms_export/residential_5/Model_0.glb');
    await page.waitForFunction(previous => document.querySelector('#workbench-viewer canvas')?.dataset.ready === 'true' &&
      window.muWorkbenchViewer.loaded !== previous, initialUrl, { timeout: 60000 });
    await checkRedraw('wireframe',
      () => page.getByRole('radio', { name: 'Wireframe', exact: true }).check(),
      () => window.muWorkbenchViewer.details.scene.forceWireframe);
    await checkRedraw('solid',
      () => page.getByRole('radio', { name: 'PBR / solid', exact: true }).check(),
      () => !window.muWorkbenchViewer.details.scene.forceWireframe);
    await checkRedraw('points',
      () => page.getByRole('radio', { name: 'Points', exact: true }).check(),
      () => window.muWorkbenchViewer.details.scene.forcePointsCloud);
    await page.getByRole('radio', { name: 'PBR / solid', exact: true }).check();
    await page.waitForFunction(() => !window.muWorkbenchViewer.details.scene.forcePointsCloud);
    await checkRedraw('environment-dark',
      () => page.locator('#material-tools input[type=range]').press('Home'),
      () => window.muWorkbenchViewer.details.scene.environmentIntensity === 0);
    await checkRedraw('environment-bright',
      () => page.locator('#material-tools input[type=range]').press('End'),
      () => window.muWorkbenchViewer.details.scene.environmentIntensity === 2);
    assert.deepEqual(errors, [], 'Browser errors');
    const report = { passed: true, stationaryCamera: true, idleAfterChanges: true,
      renderedImageChecks: checks, browserErrors: errors };
    fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
  } catch (error) {
    await page.screenshot({ path: path.join(out, 'failure.png') });
    throw error;
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
