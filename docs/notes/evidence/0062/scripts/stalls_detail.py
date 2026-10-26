"""Per stalled run: longest stay level, its searches, distinct search stands, and the earlier visited levels."""
import sqlite3,sys,json,re
db=sys.argv[1]
c=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
out=[]
for rid,seed in c.execute("select id,suite_seed from runs").fetchall():
    rows=c.execute("""select json_extract(payload_json,'$.observation.player.dungeon_number'),json_extract(payload_json,'$.observation.player.depth'),
      json_extract(payload_json,'$.observation.player.turn'),json_extract(payload_json,'$.action.name'),json_extract(payload_json,'$.selection.rationale'),json_extract(payload_json,'$.selection.goal.kind')
      from events where run_id=? and kind='step' order by sequence""",(rid,)).fetchall()
    segs=[]
    for dn,d,t,a,r,g in rows:
        if d is None: continue
        k=(dn,d)
        if not segs or segs[-1]['k']!=k: segs.append({'k':k,'t0':t,'t1':t,'srch':0,'stands':set(),'goal':{}})
        e=segs[-1]; e['t1']=t; e['goal'][g]=e['goal'].get(g,0)+1
        if a and 'SEARCH' in a:
            e['srch']+=1
            m=re.search(r'at \((\d+), (\d+)\)',r or '')
            if m: e['stands'].add(m.groups())
    if not segs: continue
    L=max(segs,key=lambda e:e['t1']-e['t0'])
    if L['t1']-L['t0']<=1000: continue
    i=segs.index(L)
    out.append({'seed':seed,'level':L['k'],'turns':L['t1']-L['t0'],'search':L['srch'],'stands':len(L['stands']),
      'goal':max(L['goal'],key=L['goal'].get),'before':[s['k'] for s in segs[:i]],'after':[s['k'] for s in segs[i+1:]][:4]})
c.close()
for o in sorted(out,key=lambda o:-o['turns']): print(json.dumps(o))
