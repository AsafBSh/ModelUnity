"""Model library and live installation activity inside the existing workbench."""
from html import escape
from pathlib import Path
import json
import shutil
import time
import gradio as gr
from scripts.model_manager.service import ACTIVE

CSS = """
#models-view-state {display:none!important;}
.gradio-container:has(#models-view-state [data-open="true"]) #workspace {display:none!important;}
#models-workspace {flex:1 1 0!important;min-height:0!important;overflow:hidden;gap:10px;}
#models-title {flex:0 0 auto;align-items:center;gap:12px;}
#models-title .prose h2 {margin:0;font-size:20px;color:#d9f7ef;}
#models-grid {display:grid!important;grid-template-columns:minmax(240px,.9fr) minmax(320px,1.2fr) minmax(300px,1fr);gap:12px;flex:1 1 0!important;min-height:0;overflow:hidden;}
#models-grid > .column {min-height:0!important;height:100%;overflow-y:auto!important;overflow-x:hidden;padding:14px;background:#13212b;border:1px solid #293e4a;border-radius:12px;display:block!important;}
#models-grid > .column > * {margin-bottom:12px;}
#models-grid .row {gap:8px;}
#models-grid .prose p {font-size:13px;line-height:1.5;}
#models-grid :is(input,textarea) {border-radius:10px!important;}
#models-grid :is(button,input,textarea):focus-visible {outline:2px solid #62e6ce;outline-offset:2px;}
#models-grid button {min-height:36px;border-radius:10px;}
#models-grid .form {min-width:0;}
#mm-library td {font-size:12px;overflow-wrap:anywhere;}
.mu-model-detail h3 {margin:0 0 9px;font-size:19px;color:#d9f7ef;}
.mu-model-detail p {line-height:1.55;overflow-wrap:anywhere;font-size:13px;}
.mu-model-detail a {color:#7bedda;text-decoration:underline;text-underline-offset:3px;}
.mu-model-detail dl {margin:12px 0;font-size:13px;}
.mu-model-detail dt {color:#a7c5cb;margin-top:10px;font-weight:700;}
.mu-model-detail dd {margin:3px 0 0;overflow-wrap:anywhere;color:#e0edf2;}
.mu-model-state {font-weight:700;color:#e5c282;}
.mu-model-state.ready {color:#7bedb2;}
.mu-download {padding:12px;background:#0c1b23;border:1px solid #293e4a;border-radius:10px;}
.mu-download strong {display:block;color:#d9f7ef;margin-bottom:7px;}
.mu-download p {margin:7px 0;font-size:13px;line-height:1.5;overflow-wrap:anywhere;}
.mu-download progress {width:100%;height:14px;accent-color:#53d6be;}
.mu-download progress::-webkit-progress-bar {background:#233a45;border-radius:7px;}
.mu-download progress::-webkit-progress-value {background:#53d6be;border-radius:7px;}
.mu-download small {color:#a7c5cb;font-variant-numeric:tabular-nums;}
#mm-inline-readiness {padding:8px 10px!important;border:1px solid #36534f;border-radius:10px;background:#102c2a;font-size:12px;}
#mm-inline-readiness .prose p {margin:0;font-size:12px;}
@media(max-width:1250px){#models-grid {grid-template-columns:minmax(215px,.8fr) minmax(280px,1fr) minmax(260px,1fr);gap:8px;}#models-grid > .column {padding:10px;}}
@media(max-width:950px){#models-grid {grid-template-columns:minmax(210px,.8fr) minmax(300px,1.2fr);overflow:auto;}#mm-activity {grid-column:1/-1;min-height:350px!important;} }
"""


def size(value):
    if value is None: return 'Unknown'
    for unit in ('B','KiB','MiB','GiB','TiB'):
        if value < 1024 or unit=='TiB': return f'{value:.1f} {unit}'
        value /= 1024


def details(manager, key):
    if key not in manager.models:return '<section class="mu-model-detail"><h3>Select a model</h3><p>Choose an entry from the library to inspect its files and requirements.</p></section>'
    status = manager.status(key)
    missing = [s for s in manager.readiness([key]) if not s['downloaded']]
    estimated = sum(s['bytes'] for s in missing)
    runtime = '; '.join(status['runtime_errors']) or 'Prerequisite files/modules detected; inference has not been validated by this check.'
    shared = ', '.join(manager.models[k].name for k in status['dependencies']) or 'None'
    label = 'Recorded file size' if status['downloaded'] else 'Estimated model size'
    return f'''<section class="mu-model-detail" aria-label="Selected model details">
      <h3>{escape(status['name'])}</h3>
      <p class="mu-model-state {'ready' if status['ready'] else ''}">{escape(status['state'])}{' · busy' if status['in_use'] else ''}</p>
      <p>{escape(status['description'])}</p>
      <dl><dt>{label}</dt><dd>{size(status['bytes'])}</dd>
      <dt>Missing files, including shared dependencies</dt><dd>Approximately {size(estimated)}; exact transfer sizes resolve when installation starts.</dd>
      <dt>Shared dependencies</dt><dd>{escape(shared)}</dd>
      <dt>Dependencies still required</dt><dd>{escape(', '.join(status['missing_dependencies']) or 'None')}</dd>
      <dt>Location</dt><dd>{escape(status['location'] or str(manager.models_dir))}</dd>
      <dt>Revision</dt><dd>{escape(status['revision'] or 'Resolved and pinned when installed')}</dd>
      <dt>Runtime</dt><dd>{escape(runtime)}</dd></dl>
      <p><a href="{escape(status['source'],quote=True)}" target="_blank" rel="noopener noreferrer">Model source, capabilities and license</a></p>
      <p>Downloaded files are separate from runtime readiness. Busy indicates an operation holds this component; it is not a measurement of GPU residency.</p>
    </section>'''


def progress(manager, row):
    if not row:
        return '<section class="mu-download"><strong>No installation activity</strong><p>Select a model and choose Install / repair. Downloads continue when you return to the workbench.</p></section>'
    total, done, speed_value = row['total'],row['done'],row['speed']
    label = manager.models[row['model']].name if row['model'] in manager.models else 'Runtime / host'
    if total and row['state'] not in ('resolving','installing','verifying'):
        bar = f'<progress max="{total}" value="{min(done,total)}" aria-label="Measured file progress"></progress>'
        amount = f'{size(done)} / {size(total)}'
    else:
        bar = '<progress aria-label="Stage progress is not measured in bytes"></progress>' if row['state'] in ACTIVE else ''
        amount = 'Stage progress; no byte percentage is available.'
    eta = ''
    if speed_value > 0 and total >= done and row['state']=='downloading':
        eta = f' · about {max(1,round((total-done)/speed_value))} s remaining'
    rate = f' · {size(speed_value)}/s' if speed_value > 0 and row['state']=='downloading' else ''
    elapsed = round(time.time()-row['created']) if row['state'] in ACTIVE else round(row['updated']-row['created'])
    return f'<section class="mu-download" aria-live="polite"><strong>{escape(label)} · {escape(row["state"])}</strong>{bar}<p>{escape(row["message"])}</p><small>{amount}{rate}{eta} · {elapsed} s elapsed</small></section>'


def mount(manager):
    """Return navigation controls; everything stays in the app's single window."""
    with gr.Column(visible=False,elem_id='models-workspace') as workspace:
        with gr.Row(elem_id='models-title'):
            gr.Markdown('## Models and downloads')
            workflow_install=gr.Button('Install workflow models',scale=0,min_width=190,elem_id='mm-install-workflow')
            close = gr.Button('Back to workbench',scale=0,min_width=170,elem_id='mm-close')
        with gr.Row(elem_id='models-grid'):
            with gr.Column(elem_id='mm-catalog'):
                search = gr.Textbox(value='',label='Search models',placeholder='Name or capability',elem_id='mm-search')
                category = gr.Dropdown(['All','Generate','Texture','Prepare','Normals','Support'],value='All',label='Category')
                library = gr.Dataframe(headers=['Model','State','Size'],datatype=['str','str','str'],value=[],
                    interactive=False,wrap=True,column_widths=['48%','34%','18%'],max_height=420,label='Model library · select a row',elem_id='mm-library')
                library_keys = gr.State([])
                refresh = gr.Button('Refresh installed files',elem_id='mm-refresh')
                with gr.Accordion('Storage and credentials',open=False):
                    location = gr.Textbox(value=str(manager.models_dir),label='Folder for new model installations',elem_id='mm-directory')
                    save_location = gr.Button('Use this model folder',elem_id='mm-save-directory')
                    disk = gr.Markdown()
                    gr.Markdown('Existing installations keep their recorded locations. External/shared caches are discovered but never removed by this manager.')
                    token = gr.Textbox(label='Hugging Face token · optional, session only',type='password',elem_id='mm-token')
                    set_token = gr.Button('Use token for this session')
                    gr.Markdown('Credentials stay in server memory and are cleared when the server stops. They are not saved in projects, logs or Git.')
            with gr.Column(elem_id='mm-details'):
                selected = gr.Dropdown([(m.name,k) for k,m in manager.models.items()],value='hunyuan',label='Selected model',elem_id='mm-selected')
                info = gr.HTML(value=details(manager,'hunyuan'),elem_id='mm-model-info')
                install = gr.Button('Install / repair',variant='primary',elem_id='mm-install')
                with gr.Row():
                    verify = gr.Button('Verify files',elem_id='mm-verify')
                    update = gr.Button('Update model',elem_id='mm-update')
                gr.Markdown('Install includes missing shared checkpoints. Comfy models also offer runtime installation below. Updates resolve the upstream revision explicitly; inference never installs models.')
                message = gr.Markdown('Choose only the models needed for your workflow.',elem_id='mm-message')
                with gr.Accordion('Register an existing model folder',open=False):
                    existing_folder=gr.Textbox(label='Existing repository folder',placeholder='Full path to extracted model files')
                    register=gr.Button('Verify and register existing files')
                    gr.Markdown('Checks this folder against the upstream file hashes. The folder stays external and read-only; removal never deletes its files. Existing Hub snapshots use their revision folder name.')
                with gr.Accordion('ComfyUI runtime and paint extensions',open=False):
                    gr.Markdown('**Windows / NVIDIA CUDA.** ComfyUI is installed in its own environment. Original research stacks are Linux-first. Paint builds require compatible VS2022 C++ and CUDA tools already installed.')
                    runtime = gr.Button('Install / repair ComfyUI runtime',elem_id='mm-runtime')
                    runtime_check=gr.Button('Verify ComfyUI runtime',elem_id='mm-runtime-check')
                    with gr.Row():
                        start = gr.Button('Start host')
                        stop = gr.Button('Stop host')
                        check = gr.Button('Check host')
                    build = gr.Button('Build paint extensions',elem_id='mm-paint-build')
                    paint_check=gr.Button('Verify paint runtime',elem_id='mm-paint-check')
                    gr.Markdown('Stop an existing Comfy host before runtime repair. After adding a new model folder, restart an owned host to load its model paths. External hosts are not stopped automatically.')
                with gr.Accordion('Remove owned model files',open=False):
                    remove_plan = gr.State(None)
                    preview_remove = gr.Button('Preview removal',elem_id='mm-preview-remove')
                    removal = gr.JSON(label='Exact files and logical bytes to remove')
                    confirm = gr.Checkbox(label='Remove only the owned files listed above',value=False,elem_id='mm-confirm-remove')
                    remove = gr.Button('Remove reviewed installation',interactive=False,elem_id='mm-remove')
            with gr.Column(elem_id='mm-activity'):
                job = gr.Dropdown([],label='Installation activity',elem_id='mm-job')
                live = gr.HTML(value=progress(manager,None),elem_id='mm-progress')
                with gr.Row():
                    cancel = gr.Button('Cancel installation',interactive=False,elem_id='mm-cancel')
                    retry = gr.Button('Retry / resume',interactive=False,elem_id='mm-retry')
                log = gr.Textbox(label='Live installation log',lines=14,max_lines=18,interactive=False,elem_id='mm-log')
                logfile = gr.File(label='Download installation log',interactive=False)
                gr.Markdown('Closing this view does not cancel jobs. Interrupted jobs remain visible after restart; choose Retry / resume to continue retained partial files.')
                with gr.Accordion('Discard retained download files',open=False):
                    partial_plan=gr.State(None)
                    preview_partial=gr.Button('Preview retained download files',elem_id='mm-preview-partial')
                    partial_info=gr.JSON(label='Uninstalled files and logical bytes')
                    partial_confirm=gr.Checkbox(label='Discard only the uninstalled files listed above',value=False)
                    discard=gr.Button('Discard reviewed download files',interactive=False,elem_id='mm-discard-partial')

    stamp = gr.State(None)
    def rows(query,group):
        values = [v for v in manager.inventory() if (not group or group=='All' or v['group']==group) and (query or '').lower() in (v['name']+' '+v['description']).lower()]
        return [[v['name'],v['state'],size(v['bytes'])] for v in values],[v['key'] for v in values]

    def logs(job_id):
        if not job_id:return '',None
        ordinary = manager.state/'logs'/(job_id+'.log')
        installer = manager.state/'logs'/(job_id+'.installer.log')
        path = installer if installer.exists() else ordinary
        if not path.exists():return '',None
        with path.open('rb') as stream:
            stream.seek(max(0,path.stat().st_size-16000))
            text = stream.read().decode('utf-8',errors='replace')
        text=manager.redact(text)
        return text,str(path)

    def poll(key,chosen,query,group,last):
        jobs = manager.jobs()
        choices = [(f"{manager.models[r['model']].name if r['model'] in manager.models else 'Runtime'} · {r['state']} · {r['id'][:8]}",r['id']) for r in jobs]
        chosen = chosen if any(r['id']==chosen for r in jobs) else jobs[0]['id'] if jobs else None
        row = next((r for r in jobs if r['id']==chosen),None)
        active = sum(r['state'] in ACTIVE for r in jobs)
        table,keys = rows(query,group)
        info_value = details(manager,key)
        current = json.dumps([table,info_value,choices,chosen])
        changed = current != last
        disk_path = manager.models_dir
        while not disk_path.exists() and disk_path.parent!=disk_path:disk_path=disk_path.parent
        try:disk_text=f'**Destination drive:** {size(shutil.disk_usage(disk_path).free)} free · transfer headroom {size(manager.reserve)}'
        except OSError:disk_text='**Destination drive unavailable.** Reconnect it or choose another folder.'
        text,path = logs(chosen)
        return (table if changed else gr.skip(),keys if changed else gr.skip(),info_value if changed else gr.skip(),
            gr.update(choices=choices) if changed else gr.skip(),progress(manager,row),text,path,
            gr.update(interactive=bool(row and row['state'] in ACTIVE)),
            gr.update(interactive=bool(row and row['state'] in ('failed','cancelled','interrupted'))),
            disk_text,current,
            gr.update(value=f'Models · {active} active' if active else 'Models'))

    def changed_model(key):
        return details(manager,key),None,None,False,gr.update(interactive=False)
    selected.change(changed_model,selected,[info,remove_plan,removal,confirm,remove],queue=False)
    search.input(rows,[search,category],[library,library_keys],queue=False)
    category.change(rows,[search,category],[library,library_keys],queue=False)
    def choose(keys,event:gr.SelectData):
        index = event.index[0] if isinstance(event.index,(list,tuple)) else event.index
        return keys[index] if 0 <= index < len(keys) else gr.skip()
    library.select(choose,library_keys,selected,queue=False)

    def enqueue(key,action):
        try:
            manager.start()
            if action=='install' and manager.record(key):action='repair'
            job_id=manager.submit(key,action)
            return gr.update(choices=[(r['id'][:8]+' · '+r['state'],r['id']) for r in manager.jobs()],value=job_id),f'Queued {action}. Follow Installation activity; no generation has started.'
        except Exception as exc: raise gr.Error(str(exc)) from None
    for button,action in ((install,'install'),(verify,'verify'),(update,'update')):
        button.click(lambda key,action=action:enqueue(key,action),selected,[job,message],queue=False)
    def register_folder(key,path):
        if not path:raise gr.Error('Enter an existing model repository folder.')
        try:
            manager.start();new=manager.submit(key,'register',{'existing_dir':path})
            return gr.update(choices=[(r['id'][:8]+' · '+r['state'],r['id']) for r in manager.jobs()],value=new),'Queued read-only verification of existing files.'
        except Exception as exc:raise gr.Error(str(exc)) from None
    register.click(register_folder,[selected,existing_folder],[job,message],queue=False)
    for button,action in ((runtime,'runtime'),(runtime_check,'runtime-check'),(build,'paint-build'),(paint_check,'paint-check'),(start,'host-start'),(stop,'host-stop'),(check,'host-check')):
        button.click(lambda action=action:enqueue('runtime',action),outputs=[job,message],queue=False)
    def latest(job_id):return job_id or (manager.jobs()[0]['id'] if manager.jobs() else None)
    cancel.click(lambda job_id:manager.cancel(latest(job_id)),job,queue=False)
    def retry_job(job_id):
        try:
            manager.start(); new=manager.retry(latest(job_id))
            return gr.update(choices=[(r['id'][:8]+' · '+r['state'],r['id']) for r in manager.jobs()],value=new)
        except Exception as exc: raise gr.Error(str(exc)) from None
    retry.click(retry_job,job,job,queue=False)
    def save_folder(path):
        try: return manager.set_directory(path)
        except Exception as exc: raise gr.Error(str(exc)) from None
    save_location.click(save_folder,location,message,queue=False)
    def use_token(value):
        manager.token=value.strip() or None
        return '', 'Session token updated. Existing jobs and project files contain no credential.'
    set_token.click(use_token,token,[token,message],queue=False)
    def preview(key):
        try:
            result=manager.removal_plan(key)
            return result,result,False,gr.update(interactive=False)
        except Exception as exc: raise gr.Error(str(exc)) from None
    preview_remove.click(preview,selected,[remove_plan,removal,confirm,remove],queue=False)
    confirm.change(lambda yes,plan:gr.update(interactive=bool(yes and plan)),[confirm,remove_plan],remove,queue=False)
    def delete(key,plan,yes):
        if not yes or not plan or plan['model']!=key:raise gr.Error('Preview and confirm this installation first.')
        try:return manager.remove(key,plan['signature']),None,None,False,gr.update(interactive=False)
        except Exception as exc:raise gr.Error(str(exc)) from None
    remove.click(delete,[selected,remove_plan,confirm],[message,remove_plan,removal,confirm,remove],queue=False)
    def partial_preview(job_id):
        try:
            result=manager.partial_plan(latest(job_id))
            return result,result,False,gr.update(interactive=False)
        except Exception as exc:raise gr.Error(str(exc)) from None
    preview_partial.click(partial_preview,job,[partial_plan,partial_info,partial_confirm,discard],queue=False)
    partial_confirm.change(lambda yes,plan:gr.update(interactive=bool(yes and plan and plan['files'])),[partial_confirm,partial_plan],discard,queue=False)
    def discard_files(job_id,plan,yes):
        if not yes or not plan or plan['job']!=latest(job_id):raise gr.Error('Preview and confirm partial files for this job first.')
        try:return manager.discard_partial(latest(job_id),plan['signature']),None,None,False,gr.update(interactive=False)
        except Exception as exc:raise gr.Error(str(exc)) from None
    discard.click(discard_files,[job,partial_plan,partial_confirm],[message,partial_plan,partial_info,partial_confirm,discard],queue=False)
    return {'workspace':workspace,'close':close,'selected':selected,'poll':poll,'poll_inputs':[selected,job,search,category,stamp],
            'poll_outputs':[library,library_keys,info,job,live,log,logfile,cancel,retry,disk,stamp],
            'refresh':refresh,'message':message,'job':job,'workflow_install':workflow_install}
