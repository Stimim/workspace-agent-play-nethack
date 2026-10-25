import sqlite3,sys,statistics
for db in sys.argv[1:]:
    c=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
    maxes=[];over1k=0;over500=0;stall_turns=0;total=0
    for (rid,outcome) in c.execute("select id,outcome from runs").fetchall():
        rows=c.execute("""select json_extract(payload_json,'$.observation.player.depth'),json_extract(payload_json,'$.observation.player.dungeon_number'),json_extract(payload_json,'$.observation.player.turn') from events where run_id=? and kind='step' order by sequence""",(rid,)).fetchall()
        segs=[];prev=None
        for d,dn,t in rows:
            if t is None: continue
            if not segs or segs[-1][0]!=(d,dn): segs.append([(d,dn),t,t])
            segs[-1][2]=t
        lens=[s[2]-s[1] for s in segs] or [0]
        m=max(lens); maxes.append(m); over1k+=m>1000; over500+=m>500
        stall_turns+=sum(l-500 for l in lens if l>500); total+=sum(lens)
    c.close()
    print(db.split('/')[-2],'runs',len(maxes),'median longest level',statistics.median(maxes),'runs w/ level>500T',over500,'>1000T',over1k,'share of turns beyond 500 on a level %.0f%%'%(100*stall_turns/max(total,1)))
