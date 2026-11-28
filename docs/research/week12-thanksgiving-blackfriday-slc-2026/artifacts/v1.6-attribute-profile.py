import os,sys,time,json,threading,signal
sys.path.insert(0,'/tmp/v16-profile-mod')
import portable_model_pack as pack
LOG='/tmp/v16-attr-profile.jsonl'; PACK='/root/runs/week-11/inputs/models/portable-models-2026-11-21-pr51-verified-core/v1.6--season-2026.slcpkg'; ENGINE='/tmp/v16-attr-engine'; t0=time.monotonic()
def mem():
 d={}
 for line in open('/proc/self/smaps_rollup'):
  if line.startswith(('Rss:','Pss:','Private_Dirty:','Private_Clean:','Shared_Clean:','Shared_Dirty:')):
   k,v,*_=line.split();d[k.rstrip(':')+'_kib']=int(v)
 for line in open('/proc/self/status'):
  if line.startswith(('VmHWM:','VmPeak:')):
   k,v,*_=line.split();d[k.rstrip(':')+'_kib']=int(v)
 d['host_available_kib']=int(open('/proc/meminfo').read().split('MemAvailable:')[1].split()[0])
 return d
def emit(kind,**kw):
 with open(LOG,'a') as f:f.write(json.dumps({'kind':kind,'t_sec':round(time.monotonic()-t0,3),**mem(),**kw},sort_keys=True)+'\n');f.flush();os.fsync(f.fileno())
def monitor():
 while True:
  time.sleep(.25);m=mem()
  if m['Rss_kib']>4*1024*1024 or m['host_available_kib']<1536*1024:
   emit('safety_stop',reason='rss_over_4GiB' if m['Rss_kib']>4*1024*1024 else 'available_under_1_5GiB');os.kill(os.getpid(),signal.SIGTERM)
threading.Thread(target=monitor,daemon=True).start()
def attr_cb(key,value,start,end,n):
 e={'attribute':key,'serialized_pair_start_byte':start,'serialized_pair_end_byte':end,'serialized_pair_bytes':end-start,'decoded_attribute_count':n,'type':type(value).__module__+'.'+type(value).__name__,'entries':len(value) if hasattr(value,'__len__') else None,'shallow_bytes':sys.getsizeof(value)}
 if key=='pool' and isinstance(value,dict):
  cells=rows=rowdicts=0;size=sys.getsizeof(value)
  for cell in value.values():
   cells+=1;size+=sys.getsizeof(cell)
   if isinstance(cell,(list,tuple)):
    for row in cell:
     rows+=1;size+=sys.getsizeof(row)
     if isinstance(row,tuple) and len(row)>1 and isinstance(row[1],dict):rowdicts+=1;size+=sys.getsizeof(row[1])
  e['pool_shallow_lower_bound']={'cells':cells,'historical_rows':rows,'row_dicts':rowdicts,'bytes':size}
 if key=='contextual_sampler':
  a=vars(value);e['sampler_attributes']={k:{'type':type(v).__module__+'.'+type(v).__name__,'entries':len(v) if hasattr(v,'__len__') else None,'shallow_bytes':sys.getsizeof(v)} for k,v in a.items()}
  sp=a.get('source_pool');e['source_pool_cells']=len(sp) if hasattr(sp,'__len__') else None
  if isinstance(sp,dict):e['source_pool_shallow_lower_bound']={'cells':len(sp),'row_entries':sum(len(x) for x in sp.values() if hasattr(x,'__len__')),'bytes':sys.getsizeof(sp)+sum(sys.getsizeof(x) for x in sp.values())+sum(sys.getsizeof(row) for cell in sp.values() if isinstance(cell,(tuple,list)) for row in cell)}
 emit('reference_attribute',**e)
pack._PROFILE_ATTRIBUTE_CALLBACK=attr_cb
emit('start',pack_module=pack.__file__,load_function_module=pack.load_pack.__module__)
try:
 emit('load_start')
 ref,snapshot,manifest,config=pack.load_pack(PACK,expected_sha256='6cf1e83677dc325632c49b2659de3ab04c856fc63d44b19fccc26a6f674f03a2',expected_code_commit='1bb3bd50c4df5896e4d693245e48329c20c63254',engine_dir=ENGINE)
 s=ref.contextual_sampler;emit('loaded',pool_is_source_pool=ref.pool is s.source_pool,pool_contents_equal=ref.pool==s.source_pool,pool_cells=len(ref.pool),source_pool_cells=len(s.source_pool),reference_attrs=len(vars(ref)))
finally:emit('exit')
