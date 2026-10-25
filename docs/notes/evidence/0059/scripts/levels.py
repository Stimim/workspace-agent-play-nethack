import sqlite3,sys
db,seeds=sys.argv[1],[int(s) for s in sys.argv[2:]]
c=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
for seed in seeds:
    rid=c.execute("select id from runs where suite_seed=?",(seed,)).fetchone()[0]
    rows=c.execute("""select json_extract(payload_json,'$.observation.player.depth'),json_extract(payload_json,'$.observation.player.dungeon_number'),
      json_extract(payload_json,'$.observation.player.turn'),json_extract(payload_json,'$.selection.goal.kind'),
      json_extract(payload_json,'$.selection.stuck_reason'),json_extract(payload_json,'$.selection.source'),
      json_extract(payload_json,'$.action.name'),json_extract(payload_json,'$.selection.rationale')
      from events where run_id=? and kind='step' order by sequence""",(rid,)).fetchall()
    print('seed',seed,'steps',len(rows))
    segs=[]
    for d,dn,t,g,s,src,a,r in rows:
        k=(d,dn)
        if not segs or segs[-1]['k']!=k: segs.append({'k':k,'t0':t,'t1':t,'n':0,'st':{},'fb':0,'srch':0,'first_stuck':None,'acts':{}})
        e=segs[-1]; e['t1']=t; e['n']+=1
        if s:
            e['st'][s]=e['st'].get(s,0)+1
            if e['first_stuck'] is None: e['first_stuck']=(t,s,(r or '')[:120])
        if src=='model_fallback': e['fb']+=1
        if a and 'SEARCH' in a: e['srch']+=1
        e['acts'][a]=e['acts'].get(a,0)+1
    for e in segs:
        if e['t1']-e['t0']>150 or e['fb']>30:
            print('  D%s/%s T%d-%d steps %d fb %d search %d stuck %s'%(e['k'][0],e['k'][1],e['t0'],e['t1'],e['n'],e['fb'],e['srch'],e['st']))
            if e['first_stuck']: print('    first stuck',e['first_stuck'])
            print('    acts',sorted(e['acts'].items(),key=lambda x:-x[1])[:4])
c.close()
