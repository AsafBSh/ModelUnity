"""Compile the real task/run declarations with a tiny isolated, nonregistered fixture."""
from pathlib import Path
import argparse,re,subprocess,uuid


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--iscc',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    root=Path(__file__).resolve().parents[2];out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    bundle=out/'bundle';bundle.mkdir()
    (bundle/'run.bat').write_text('@exit /b 0\n')
    (bundle/'Setup ComfyUI.bat').write_text('@echo unexpected > setup-marker.txt\n@exit /b 1\n')
    (bundle/'README.txt').write_text('Installer validation fixture, not an application build.')
    source=(root/'packaging/installer.iss').read_text()
    source=source.replace('#define MyAppName       "Modelunify"','#define MyAppName       "Modelunify validation fixture"')
    source=re.sub(r'AppId=.*',lambda m:'AppId={{'+str(uuid.uuid4())+'}',source)
    source=source.replace('[Setup]','[Setup]\nUninstallable=no\nUsePreviousTasks=no')
    source=re.sub(r'\[Icons\].*?(?=\[Run\])','',source,flags=re.S)
    source+='''
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  if WizardIsTaskSelected('comfy') then Log('MODELUNIFY_COMFY_SELECTED=true')
  else Log('MODELUNIFY_COMFY_SELECTED=false');
  if WizardIsTaskSelected('comfy\\pixalmv') then Log('MODELUNIFY_PIXALMV_SELECTED=true')
  else Log('MODELUNIFY_PIXALMV_SELECTED=false');
  Result := '';
end;
'''
    script=out/'fixture.iss';script.write_text(source,encoding='utf-8')
    flags={'creationflags':subprocess.CREATE_NO_WINDOW} if hasattr(subprocess,'CREATE_NO_WINDOW') else {}
    compile_result=subprocess.run([str(args.iscc.resolve()),'/Qp','/DMyAppVersion=1.0',f'/DBundleRoot={bundle}',
        '/DInstallerName=fixture',f'/O{out}',str(script)],capture_output=True,text=True,**flags)
    (out/'compile.log').write_text(compile_result.stdout+compile_result.stderr,encoding='utf-8');compile_result.check_returncode()
    for name,tasks in (('default',None),('pixal-mv','comfy\\pixalmv')):
        dest=out/name;log=out/f'{name}.log'
        command=[str(out/'fixture.exe'),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/NOICONS',f'/DIR={dest}',f'/LOG={log}']
        if tasks:command.append('/TASKS='+tasks)
        subprocess.run(command,check=True,**flags)
        text=log.read_text(encoding='utf-8-sig')
        if 'MODELUNIFY_COMFY_SELECTED='+('true' if tasks else 'false') not in text:raise RuntimeError('Unexpected default/selected runtime task state.')
        if tasks and 'MODELUNIFY_PIXALMV_SELECTED=true' not in text:raise RuntimeError('Multiview task selection was lost.')
        if (dest/'setup-marker.txt').exists():raise RuntimeError('Silent installer unexpectedly launched optional setup.')
    print('PASS: real installer declarations compile; optional runtime is off by default; model selection works; silent setup starts no downloads.')


if __name__=='__main__':main()
