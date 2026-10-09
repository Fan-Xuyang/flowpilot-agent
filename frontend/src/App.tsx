import { useEffect, useRef, useState } from 'react';
import * as echarts from 'echarts/core';
import { BarChart, LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import ReactMarkdown from 'react-markdown';
echarts.use([BarChart,LineChart,GridComponent,TooltipComponent,CanvasRenderer]);

type Dataset={id:string;name:string;rows:number;schema:{name:string;type:string}[]};
type Trace={seq:number;type:string;payload:Record<string,unknown>;created:number};
type Task={id:string;query:string;mode:string;status:string;events:Trace[];state:{dataset?:Dataset;plan?:{title?:string;goal?:string;metric_definition?:string;sql?:string;chart?:{kind:string;x:string;y:string;title:string};payload?:Record<string,string|number>};result?:{columns:string[];rows:(string|number|null)[][];truncated:boolean;checksum:string};digest?:string;screenshot?:string;receipt?:{receipt:string};report?:string;usage?:{input_tokens:number|null;output_tokens:number|null;latency_ms:number}[]}};
type TaskSummary=Pick<Task,'id'|'query'|'status'|'mode'>;
const labels:Record<string,string>={queued:'排队中',running:'执行中',completed:'已完成',failed:'执行失败',awaiting_approval:'等待确认',interrupted:'已中断',cancelled:'已取消'};

async function api(path:string,body?:unknown){
  const response=await fetch('/api/'+path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:undefined);
  if(!response.ok){let text='请求失败';try{text=(await response.json()).detail||text;}catch{}throw Error(text);}
  return response.json();
}

function Chart({task}:{task:Task}){
  const element=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    const spec=task.state.plan?.chart,data=task.state.result;
    if(!element.current||!spec||!data||spec.kind==='table')return;
    const chart=echarts.init(element.current);
    const xi=data.columns.indexOf(spec.x),yi=data.columns.indexOf(spec.y);
    chart.setOption({color:['#6c60dd'],tooltip:{trigger:'axis',renderMode:'richText'},grid:{left:65,right:22,top:28,bottom:65},xAxis:{type:'category',data:data.rows.map(r=>r[xi]),axisLabel:{rotate:data.rows.length>8?25:0,color:'#68718a'}},yAxis:{type:'value',axisLabel:{color:'#68718a'},splitLine:{lineStyle:{color:'#edf0f7'}}},series:[{type:spec.kind,data:data.rows.map(r=>r[yi]),barMaxWidth:55,smooth:false,itemStyle:{borderRadius:[5,5,0,0]}}]});
    const observer=new ResizeObserver(()=>chart.resize());observer.observe(element.current);
    return()=>{observer.disconnect();chart.dispose();};
  },[task]);
  return <div className="chart" ref={element} aria-label="查询结果图表"/>;
}

export default function App(){
  const [kind,setKind]=useState('data'),[configured,setConfigured]=useState(false),[datasets,setDatasets]=useState<Dataset[]>([]),[dataset,setDataset]=useState('');
  const [tasks,setTasks]=useState<TaskSummary[]>([]),[task,setTask]=useState<Task|null>(null),[query,setQuery]=useState(''),[mode,setMode]=useState('demo');
  const [metric,setMetric]=useState('销售额 = SUM(sales)，不含币种换算；按数据文件原始口径。'),[error,setError]=useState(''),[busy,setBusy]=useState(false),[uploading,setUploading]=useState(false);
  const stream=useRef<EventSource|null>(null),selected=useRef<string|null>(null);
  const browser=kind==='browser';
  async function refresh(){setTasks(await api('tasks'));}
  async function refreshData(){const data=await api('datasets');setDatasets(data);setDataset(id=>id||data[0]?.id||'');}
  async function load(id:string,connect=true){
    selected.current=id;const data:Task=await api('tasks/'+id);if(selected.current!==id)return;setTask(data);
    stream.current?.close();
    if(connect&&['running','queued'].includes(data.status)){
      const after=data.events.at(-1)?.seq||0;
      const es=new EventSource('/api/tasks/'+id+'/events?after='+after);stream.current=es;
      es.addEventListener('trace',async e=>{const event:Trace=JSON.parse((e as MessageEvent).data);setTask(t=>t?.id===id?{...t,events:t.events.some(x=>x.seq===event.seq)?t.events:[...t.events,event]}:t);});
      es.addEventListener('settled',()=>{es.close();if(selected.current===id)void load(id,false).catch(e=>setError(e.message));void refresh();});
      es.onerror=()=>{ // EventSource reconnects with Last-Event-ID; keep the task running on the server.
        if(es.readyState===EventSource.CLOSED)void load(id,false).catch(e=>setError(e.message));
      };
    }
  }
  useEffect(()=>{api('health').then(h=>{setKind(h.kind);setConfigured(h.live_configured);if(h.kind==='data')void refreshData().catch(e=>setError(e.message));}).catch(e=>setError(e.message));void refresh().catch(e=>setError(e.message));return()=>stream.current?.close();},[]);
  async function run(){setBusy(true);setError('');try{const created=await api('tasks',{query,mode,dataset_id:dataset,metrics:browser?{}:{销售额:metric}});await load(created.id);await refresh();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function action(name:string,body:unknown={}){if(!task)return;setBusy(true);setError('');try{await api('tasks/'+task.id+'/'+name,body);await load(task.id);await refresh();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function upload(file:File){setUploading(true);setError('');try{const form=new FormData();form.append('file',file);const response=await fetch('/api/datasets',{method:'POST',body:form});const data=await response.json();if(!response.ok)throw Error(data.detail);await refreshData();setDataset(data.id);}catch(e){setError((e as Error).message);}finally{setUploading(false);}}
  const result=task?.state.result,plan=task?.state.plan;
  const currentDataset=datasets.find(d=>d.id===dataset);
  const usage=task?.state.usage?.reduce((a,b)=>({input:a.input+(b.input_tokens||0),output:a.output+(b.output_tokens||0),ms:a.ms+b.latency_ms}),{input:0,output:0,ms:0});
  return <div className={'app '+(browser?'flow':'data')}>
    <aside><a className="brand" href="/"><span>{browser?'F':'D'}</span><div>{browser?'FlowPilot':'DataCanvas'}<small>{browser?'浏览器业务执行 Agent':'数据分析与可视化 Agent'}</small></div></a>
      <button className="new-task" onClick={()=>{selected.current=null;stream.current?.close();setTask(null);setQuery('');setError('');}}>＋ 新建任务</button>
      <div className="side-heading">任务记录 <span>{tasks.length}</span></div><nav>{tasks.map(t=><button key={t.id} className={task?.id===t.id?'selected':''} onClick={()=>void load(t.id).catch(e=>setError(e.message))}><span>{t.query}</span><small>{labels[t.status]} · {t.mode==='demo'?'演示':'模型'}</small></button>)}</nav>
      {!browser&&<><div className="side-heading">数据集 <span>{datasets.length}</span></div><label className="upload">{uploading?'导入中…':'↑ 导入 CSV / Excel'}<input type="file" accept=".csv,.xlsx" disabled={uploading} onChange={e=>{const f=e.target.files?.[0];if(f)void upload(f);e.target.value='';}}/></label><p className="tiny">最大 5 MB / 20,000 行。内置数据为合成样例。</p><div className="dataset-list">{datasets.map(d=><button key={d.id} className={d.id===dataset?'selected':''} onClick={()=>setDataset(d.id)}>{d.name}<small>{d.rows} 行 · {d.schema.length} 列</small></button>)}</div></>}
      <footer>樊旭阳 · AI 全栈项目实践<br/>React / TypeScript / FastAPI<br/>{browser?'页面观察 → 执行 → 验证':'字段口径 → SQL → 图表证据'}</footer></aside>
    <main><header><div><p className="eyebrow">{browser?'BROWSER WORKFLOW STUDIO':'AGENTIC ANALYTICS WORKSPACE'}</p><h1>{browser?'让任务走完业务流程':'让数据回答具体问题'}</h1><p className="subtitle">{browser?'每一步可检查，提交前由你确认，完成后验证回执。':'从指标口径到查询和图表，保留能复核的分析证据。'}</p></div><span className="local">● 本地应用</span></header>
      <section className="composer"><div className="composer-top"><label>运行模式 <select value={mode} onChange={e=>setMode(e.target.value)}><option value="demo">演示规划</option><option value="live" disabled={!configured}>真实模型{configured?'':'（未配置）'}</option></select></label><span>{mode==='demo'?'未调用模型 · 实际执行工具与业务流程':'使用本地配置的兼容模型接口'}</span></div>
      <label className="question-label" htmlFor="query">{browser?'描述要完成的业务任务':'描述分析目标'}</label><textarea id="query" placeholder={browser?'例如：为研发部申请 3 台笔记本电脑，预算 18000 元，用于开发测试。':'例如：按区域比较销售额，再看按月趋势。'} value={query} maxLength={2000} onChange={e=>setQuery(e.target.value)}/>
      {!browser&&<details className="metrics"><summary>指标口径与字段</summary><input aria-label="指标口径" value={metric} onChange={e=>setMetric(e.target.value)} maxLength={300}/><p>{currentDataset?.schema.map(x=>x.name+' ('+x.type+')').join(' · ')}</p></details>}
      <div className="composer-actions"><button className="text-button" onClick={()=>setQuery(browser?'为研发部申请 3 台笔记本电脑，预算 18000 元，用于开发测试。':'按区域比较销售额，并生成图表。')}>填入示例任务</button><button className="primary" disabled={busy||!query.trim()||(!browser&&!dataset)} onClick={run}>{busy?'正在创建…':browser?'准备执行 ↗':'开始分析 ↗'}</button></div></section>
      {error&&<div className="error" role="alert">{error}</div>}
      {task&&<div className="task-status"><span className={'pill '+task.status}>{labels[task.status]}</span><code>任务 {task.id.slice(0,8)}</code><span className="grow"/>{task.status==='interrupted'&&<button onClick={()=>void action('resume')} disabled={busy}>恢复任务</button>}{['running','queued','awaiting_approval','interrupted'].includes(task.status)&&<button onClick={()=>void action('cancel')} disabled={busy}>取消任务</button>}{task.state.report&&<a href={'/api/tasks/'+task.id+'/report'}>导出 Markdown ↓</a>}</div>}
      <div className="work-area"><section className="results"><div className="panel-heading"><h2>{browser?'执行结果与确认':'图表与分析证据'}</h2><span className="tiny">{task?.mode==='demo'?'演示规划 · 真实执行':''}</span></div>
      {!task?<div className="empty"><span>{browser?'⌘':'▥'}</span><h3>{browser?'先描述任务，再检查执行过程':'从一份数据和一个问题开始'}</h3><p>{browser?'内置采购门户支持完整的填写、确认和回执验证。':'上传业务表格，或用合成销售样例体验分析流程。'}</p></div>:<>
      {plan&&<div className="plan"><h3>{plan.title||plan.goal}</h3><p>{plan.metric_definition}</p>{plan.sql&&<pre><code>{plan.sql}</code></pre>}</div>}
      {result&&<><h3 className="chart-title">{plan?.chart?.title}</h3>{plan?.chart?.kind!=='table'&&<Chart task={task}/>}<div className="table-scroll"><table><thead><tr>{result.columns.map((c,i)=><th key={i}>{c}</th>)}</tr></thead><tbody>{result.rows.slice(0,100).map((row,i)=><tr key={i}>{row.map((v,j)=><td key={j}>{v===null?'NULL':String(v)}</td>)}</tr>)}</tbody></table></div><p className="tiny">查询返回 {result.rows.length} 行{result.truncated?'（已截断）':''}；页面最多展示 100 行。结果 SHA-256：{result.checksum.slice(0,16)}…</p></>}
      {browser&&plan?.payload&&<dl className="payload">{Object.entries(plan.payload).map(([k,v])=><div key={k}><dt>{{department:'部门',item:'物品',quantity:'数量',budget:'预算上限',reason:'用途'}[k]||k}</dt><dd>{v}</dd></div>)}</dl>}
      {task.status==='awaiting_approval'&&<div className="approval"><h3>请核对本次提交内容</h3><p>当前申请已填写并保存。确认只向本地演示门户提交，不产生真实采购。</p><div><button className="primary" disabled={busy} onClick={()=>void action('approve',{digest:task.state.digest,approve:true})}>确认并提交到演示门户</button><button disabled={busy} onClick={()=>void action('approve',{digest:task.state.digest,approve:false})}>拒绝提交</button></div></div>}
      {task.state.receipt&&<div className="receipt"><strong>回执已校验</strong><code>{task.state.receipt.receipt}</code></div>}
      {browser&&task.state.screenshot&&<details className="screenshot" open><summary>浏览器页面截图</summary><img src={'/api/tasks/'+task.id+'/screenshot?v='+task.events.length} alt="Agent 执行后的采购门户页面"/></details>}
      {task.state.report&&<details className="report"><summary>完整证据报告</summary><ReactMarkdown>{task.state.report}</ReactMarkdown></details>}
      {task.status==='failed'&&<div className="error">{String(task.events.at(-1)?.payload.message||'执行失败，请查看轨迹。')}</div>}
      </>}</section>
      <section className="trace"><div className="panel-heading"><h2>执行轨迹</h2><span className="tiny">持久化事件</span></div>{task?.events.length?<ol>{task.events.map(e=><li key={e.seq}><div><strong>{String(e.payload.message||e.type)}</strong><time>{new Date(e.created*1000).toLocaleTimeString('zh-CN')}</time></div><details><summary>{e.type} · #{e.seq}</summary><pre>{JSON.stringify(e.payload,null,2)}</pre></details></li>)}</ol>:<p className="muted">任务启动后展示观察、计划、执行、验证与异常事件。刷新页面后可从左侧任务记录恢复查看。</p>}{usage&&<div className="usage"><h3>模型调用记录</h3><p>输入 {usage.input} / 输出 {usage.output} tokens</p><p>调用耗时合计 {(usage.ms/1000).toFixed(2)} 秒</p></div>}</section></div>
      <p className="bottom-note">{browser?'本地演示限定自建门户；页面工具与语义 DOM 路径均需通过字段和回执校验。':'查询使用独立 DuckDB 进程和只读连接；图表来自结构化配置，模型不能生成任意前端脚本。'}</p>
    </main></div>;
}
