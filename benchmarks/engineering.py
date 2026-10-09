"""Copied into each repository; real local HTTP/browser checks in isolated temp storage."""
import json
import os
from pathlib import Path
import platform
import sqlite3
import statistics
import site
import subprocess
import sys
import tempfile
import time
import httpx
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
IS_BROWSER = ROOT.name == 'flow-pilot'
PORT = 8302 if IS_BROWSER else 8301
BASE = f'http://127.0.0.1:{PORT}'


def main():
    suite = json.loads((ROOT/'benchmarks/cases.json').read_text(encoding='utf-8'))
    process = None
    outcomes = []
    checks = []
    client = httpx.Client(base_url=BASE, timeout=30, trust_env=False)
    with tempfile.TemporaryDirectory(prefix='agent-evaluation-') as temp:
        def start():
            nonlocal process
            env = {**os.environ, 'APP_DATA_DIR': temp, 'OPENAI_API_KEY': '',
                   'PYTHONPATH':os.pathsep.join([str(ROOT), *site.getsitepackages(), os.environ.get('PYTHONPATH','')])}
            # Windows venv redirectors can leave a child alive after terminating the wrapper.
            executable=getattr(sys,'_base_executable',sys.executable) if os.name=='nt' else sys.executable
            process = subprocess.Popen([executable, str(ROOT/'start.py'), str(PORT)], cwd=ROOT, env=env,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(150):
                if process.poll() is not None:
                    raise RuntimeError('Isolated evaluation server exited.')
                try:
                    if client.get('/api/health').status_code == 200:
                        return
                except httpx.TransportError:
                    pass
                time.sleep(.1)
            raise TimeoutError('Evaluation server did not start.')

        def stop():
            nonlocal process
            if process is not None:
                process.terminate()
                process.wait(timeout=15)
                process = None

        def settle(tid):
            deadline=time.monotonic()+60
            while time.monotonic()<deadline:
                task=client.get('/api/tasks/'+tid).json()
                if task['status'] not in {'queued','running'}:
                    return task
                time.sleep(.1)
            raise TimeoutError('Task did not settle.')

        def check(name, condition):
            checks.append({'name':name,'passed':bool(condition)})
            if not condition:
                raise AssertionError(name)

        try:
            start()
            ds = None if IS_BROWSER else client.get('/api/datasets').json()[0]['id']
            # Fixed, spaced subset of the synthetic suite; 6 page-tool + 6 DOM tasks.
            selected = suite['cases'][::8][:12] if IS_BROWSER else suite['cases'][::10]
            for index,case in enumerate(selected):
                query=('DOM 路径：' if IS_BROWSER and index%2 else '')+case['query']
                started=time.perf_counter()
                response=client.post('/api/tasks',json={'query':query,'mode':'demo','dataset_id':ds})
                response.raise_for_status()
                tid=response.json()['id']
                task=settle(tid)
                if IS_BROWSER:
                    check('approval_checkpoint_'+case['id'],task['status']=='awaiting_approval')
                    payload=task['state']['plan']['payload']
                    check('field_values_'+case['id'],payload==case['expected'])
                    check('unapproved_submission_'+case['id'],client.post('/portal/submit',json={**payload,'task_id':tid}).status_code==403)
                    check('wrong_digest_'+case['id'],client.post('/api/tasks/'+tid+'/approve',json={'digest':'0'*64,'approve':True}).status_code==409)
                    if index==0:
                        stop(); start()
                        check('restart_preserves_pending_approval',client.get('/api/tasks/'+tid).json()['status']=='awaiting_approval')
                    approved=client.post('/api/tasks/'+tid+'/approve',json={'digest':task['state']['digest'],'approve':True})
                    approved.raise_for_status()
                    task=settle(tid)
                    check('receipt_values_'+case['id'],task['state'].get('receipt',{}).get('payload')==case['expected'])
                    receipt=task['state']['receipt']['receipt']
                    repeated=client.post('/portal/submit',json={**payload,'task_id':tid})
                    check('duplicate_submission_'+case['id'],repeated.status_code==200 and repeated.json()['receipt']==receipt)
                    check('duplicate_confirmation_'+case['id'],client.post('/api/tasks/'+tid+'/approve',json={'digest':task['state']['digest'],'approve':True}).status_code==409)
                    if index==0:
                        # Inject the crash window after receipt persistence but before completed checkpoint.
                        stop()
                        saved=task['state'].copy(); saved.pop('receipt',None); saved.pop('report',None)
                        with closing(sqlite3.connect(Path(temp)/'state.sqlite3')) as conn:
                            with conn:
                                conn.execute('UPDATE tasks SET status=?,state=? WHERE id=?',('running',json.dumps(saved,ensure_ascii=False),tid))
                        start()
                        check('startup_marks_inflight_interrupted',client.get('/api/tasks/'+tid).json()['status']=='interrupted')
                        client.post('/api/tasks/'+tid+'/resume',json={}).raise_for_status()
                        task=settle(tid)
                        check('receipt_reused_after_crash_window',task['state'].get('receipt',{}).get('receipt')==receipt)
                        check('idempotence_event_recorded',any(e['type']=='idempotent' for e in task['events']))
                else:
                    from evaluate import oracle, matches
                    import csv
                    with (ROOT/'examples/sales.csv').open(encoding='utf-8') as source:
                        expected=oracle(list(csv.DictReader(source)),case['expected'])
                    check('numeric_result_'+case['id'],matches(task['state']['result'],expected))
                check('completed_'+case['id'],task['status']=='completed')
                report=client.get('/api/tasks/'+tid+'/report')
                check('report_export_'+case['id'],report.status_code==200 and len(report.text)>100)
                events=task['events']; cursor=events[-2]['seq']
                replay=client.get('/api/tasks/'+tid+'/events',headers={'Last-Event-ID':str(cursor)}).text
                replay_ids=[int(line[4:]) for line in replay.splitlines() if line.startswith('id: ')]
                check('sse_cursor_'+case['id'],replay_ids==[e['seq'] for e in events if e['seq']>cursor])
                outcomes.append({'id':case['id'],'route':'semantic-dom' if IS_BROWSER and index%2 else 'page-tool' if IS_BROWSER else 'duckdb',
                                 'completed':True,'elapsed_ms':round((time.perf_counter()-started)*1000,2)})
            if IS_BROWSER:
                # Missing information must not silently generate an application or receipt.
                response=client.post('/api/tasks',json={'query':'研发部采购电脑','mode':'demo'})
                missing=settle(response.json()['id'])
                check('missing_fields_not_submitted',missing['status']=='failed' and not missing['state'].get('receipt'))
        finally:
            stop()
            client.close()
    latencies=sorted(x['elapsed_ms'] for x in outcomes)
    result={'scope':'本地合成门户/数据集的真实 HTTP 工具流程；无模型。重启计时包含服务启动，人工确认由测试发出，不代表真人等待时间。',
            'model':'none','python':platform.python_version(),'platform':platform.platform(),
            'completed':sum(x['completed'] for x in outcomes),'total':len(outcomes),
            'checks_passed':sum(x['passed'] for x in checks),'checks_total':len(checks),
            'p50_ms':round(statistics.median(latencies),2),'p95_ms':latencies[int(.95*(len(latencies)-1))],
            'cases':outcomes,'checks':checks}
    (ROOT/'benchmarks/engineering-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in {'cases','checks'}},ensure_ascii=False))


if __name__=='__main__':
    main()
