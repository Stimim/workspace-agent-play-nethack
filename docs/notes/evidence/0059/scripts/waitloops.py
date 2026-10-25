import sqlite3,os,sys
for arm in sys.argv[1:]:
    db=os.path.expanduser(arm+'/runs.sqlite3')
    c=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
    q="""select r.suite_seed, r.outcome,
      sum(json_extract(e.payload_json,'$.selection.source')='model_fallback'),
      sum(json_extract(e.payload_json,'$.selection.stuck_reason')='navigation_budget_exhausted'),
      count(*)
      from runs r join events e on e.run_id=r.id and e.kind='step' group by r.id"""
    rows=c.execute(q).fetchall(); c.close()
    bad=[r for r in rows if (r[2] or 0)>=100]
    print(arm, 'runs',len(rows),'runs with >=100 model-fallback steps',len(bad))
    for r in sorted(bad,key=lambda r:-r[2]): print('  seed',r[0],r[1],'fallback',r[2],'budget-stuck',r[3],'steps',r[4])
