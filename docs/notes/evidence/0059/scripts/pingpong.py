import sqlite3,sys,re
pat=re.compile(r'Move to search spot \((\d+), (\d+)\) \((\d+) steps\)')
for db in sys.argv[1:]:
    c=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
    tot=0;runs=0;walk=0
    for (rid,) in c.execute("select id from runs").fetchall():
        rows=c.execute("""select json_extract(payload_json,'$.selection.rationale') from events where run_id=? and kind='step' order by sequence""",(rid,)).fetchall()
        n=0
        for (r1,),(r2,) in zip(rows,rows[1:]):
            m1=pat.search(r1 or ''); m2=pat.search(r2 or '')
            if m1 and m1.group(3)=='1' and m2 and (m2.group(1),m2.group(2))!=(m1.group(1),m1.group(2)): n+=1
            if m1: walk+=1
        tot+=n; runs+= n>0
    print(db,'arrive-then-leave events',tot,'runs',runs,'search-spot walk steps',walk)
    c.close()
