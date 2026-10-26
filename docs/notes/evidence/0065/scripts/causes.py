"""Group note 0062's stalled stays by the cause that finally blocks them (diagnosis only).

Usage: causes.py STALLED_STAYS_JSON PROFILE_JSONL [PROFILE_JSONL ...] > causes.json
Order of tests: a Mines level; a monster (300+ blocker waits, or a peaceful
monster on the true route at the stall or end step); a locked or closed door
on the true route; no target on this level; a hidden cell on the route;
anything else. MANUAL lists stays traced by hand.
"""
import json, sys, collections
stays = json.load(open(sys.argv[1]))['stays']
# Traced by hand: the hero is shut in a one-cell dead end at (19,12) by a
# floating eye in the hidden doorway (19,13) (map_at.py, step 4629).
MANUAL = {('mt', 1377): 'monster_on_route'}
prof = {}
for f in sys.argv[2:]:
    for line in open(f):
        d = json.loads(line); prof[(d['arm'], d['seed'])] = d
with_mech = {(s['seed'], tuple(s['level']), s['turns']): s for s in stays if s.get('mechanism_steps')}
seen, groups = set(), collections.defaultdict(list)
for s in stays:
    key = (s['seed'], tuple(s['level']), s['turns'])
    if key in seen:
        continue
    seen.add(key)
    waits = (with_mech.get(key, s).get('mechanism_steps') or {}).get('wait_blocker', 0)
    stall, end = s['phases']['stall'], s['phases']['end']
    bars = set((stall.get('other_barriers') or []) + (end.get('other_barriers') or []))
    if (s['arm'], s['seed']) in MANUAL:
        cause = MANUAL[(s['arm'], s['seed'])]
    elif s['level'][0] == 2:
        cause = 'mines_level'
    elif waits >= 300 or 'peaceful_monster' in bars:
        cause = 'monster_on_route'
    elif bars & {'locked', 'closed'}:
        cause = 'locked_or_closed_door'
    elif stall['class'].startswith('no_target'):
        cause = 'target_not_on_level'
    elif stall['class'] in ('stand_known_not_searched', 'searched_next_to_it', 'stand_not_known'):
        cause = 'hidden_passage_not_found'
    else:
        cause = 'route_open_or_other'
    p = prof[(s['arm'], s['seed'])]
    groups[cause].append({'arm': s['arm'], 'seed': s['seed'], 'level': s['level'], 'turns': s['turns'],
                          'searches': p['searches'], 'blocker_waits': waits,
                          'searches_one_candidate': p.get('cands_1', 0),
                          'searches_round_10_plus': p.get('round_10+', 0),
                          'most_searches_one_stand': p['top_stand'][0][1] if p['top_stand'] else 0})
total = sum(r['turns'] for v in groups.values() for r in v)
print(json.dumps({'total_turns': total, 'groups': {
    c: {'stays': len(v), 'turns': sum(r['turns'] for r in v), 'records': sorted(v, key=lambda r: -r['turns'])}
    for c, v in sorted(groups.items(), key=lambda kv: -sum(r['turns'] for r in kv[1]))}}, indent=1))
