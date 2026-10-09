import json
from pathlib import Path
import hashlib
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.agent import demo_plan
from app.baseline_v1 import demo_plan as baseline_plan

suite_path=ROOT/'benchmarks/cases.json'
suite=json.loads(suite_path.read_text(encoding='utf-8'))
outputs={}
for name,planner in [('v1',baseline_plan),('v2',demo_plan)]:
    results=[]
    for case in suite['cases']:
        error=None
        try:
            actual=planner(case['query']).payload.model_dump()
            correct_fields=sum(actual[k]==v for k,v in case['expected'].items())
        except Exception as exc:actual=None;correct_fields=0;error=str(exc)
        results.append({'id':case['id'],'query':case['query'],'exact':actual==case['expected'],'correct_fields':correct_fields,'expected':case['expected'],'actual':actual,'error':error})
    refused=0
    for text in suite['negative']:
        try:planner(text)
        except ValueError:refused+=1
    outputs[name]={'exact':sum(x['exact'] for x in results),'total':len(results),'field_correct':sum(x['correct_fields'] for x in results),'field_total':5*len(results),'negative_rejected':refused,'negative_total':len(suite['negative']),'cases':results}
    print(name,outputs[name]['exact'],'/',len(results))
report={'scope':'采购字段规则抽取回归；不是浏览器端到端成功率或真实模型准确率。','suite_sha256':hashlib.sha256(suite_path.read_bytes()).hexdigest(),'model':'none','results':outputs}
(ROOT/'benchmarks/results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
current=outputs['v2']
if current['exact']!=current['total'] or current['negative_rejected']!=current['negative_total']:
    raise SystemExit('Rule regression failed; inspect benchmarks/results.json.')
