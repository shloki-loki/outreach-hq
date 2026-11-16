"""Shared, model-independent coordination. No model calls or sending side effects."""
from datetime import timedelta
from . import store
from .util import load_config, now, now_iso, parse_iso

KINDS = ('research', 'draft', 'followup', 'review', 'engineering')
WORKERS = ('codex', 'claude', 'grok')   # grok joins when Shlok adds it; same rules, same queue


def routing():
    return load_config('routing')['owners']


def batch_config():
    cfg = load_config('routing')
    b = dict(cfg.get('founder_batch', {}))
    b.setdefault('per_day', 60)
    b.setdefault('owner', routing().get('draft', 'codex'))
    b['fallback'] = cfg.get('fallback', {}).get('draft', [b['owner'], 'claude'])
    return b


def _today():
    return now().date().isoformat()


def _tag(day):
    return f'founder-batch {day}'


def queue(action, *, ident=None, kind=None, lead=None, owner=None, title='', detail='', ref=''):
    if action == 'list':
        with store.locked():
            store.sync()
            return store.load('work')['items']
    if owner not in WORKERS:
        raise ValueError('owner must be one of ' + ', '.join(WORKERS))
    result = {}
    def change():
        result.clear()
        data = store.load('work')
        if action == 'add':
            if kind not in KINDS or not title.strip():
                raise ValueError('a valid kind and title are required')
            if lead and not store.find(store.load('leads')['leads'], lead):
                raise ValueError('unknown lead')
            if lead and any(x.get('lead_id') == lead and x['kind'] == kind and x['status'] != 'done' for x in data['items']):
                raise ValueError('unfinished work of this kind already exists for the lead')
            item = dict(id=store.next_id(data['items'], 'W'), kind=kind, lead_id=lead,
                        owner=owner, title=title.strip(), detail=detail, status='queued',
                        created_at=now_iso(), lease_until=None, result='', ref='')
            data['items'].append(item)
        else:
            item = store.find(data['items'], ident)
            if not item:
                raise ValueError('unknown work item')
            if item['status'] == 'done':
                raise ValueError('work is already done')
            active = item['status'] == 'working' and (parse_iso(item.get('lease_until')) or now()) > now()
            if action == 'claim':
                if active:
                    raise ValueError('work is already claimed; release it before another session starts')
                if item['owner'] != owner:
                    raise ValueError('reassign first, with a reason')
                item.update(status='working', lease_until=(now() + timedelta(hours=2)).isoformat())
            elif action == 'assign':
                if active or not detail.strip():
                    raise ValueError('release active work first and supply a reassignment reason')
                item.update(owner=owner, status='queued', lease_until=None, detail=detail)
            elif action in ('done', 'release'):
                if item['owner'] != owner or item['status'] != 'working' or (action == 'done' and not active):
                    raise ValueError('only the working owner may finish or release')
                if not detail.strip() or (action == 'done' and not ref.strip()):
                    raise ValueError('supply a result/handoff and a reference for completion')
                item.update(status='done' if action == 'done' else 'queued', lease_until=None,
                            result=detail, ref=ref)
            else:
                raise ValueError('unknown action')
        item['updated_at'] = now_iso()
        store.save('work', data)
        store.journal(owner, 'update', f"Work {item['id']}: {action}", detail or title, ref or item['id'])
        result.update(item)
    store.transact(change, f'supervisor work: {action}')
    return result


def founder_batch(count=None, owner=None):
    """Queue today's founder emails: one `draft` item per company (research a hook, write, queue for approval).

    Idempotent per day: running it twice tops up to `per_day`, never past it. Picks founder-list companies
    that are open, not rejected, have a contact with an address, and have never had a message or draft work."""
    cfg = batch_config()
    count = cfg['per_day'] if count is None else count
    owner = owner or cfg['owner']
    if owner not in WORKERS:
        raise ValueError('owner must be one of ' + ', '.join(WORKERS))
    day, created = _today(), []
    def change():
        created.clear()
        work = store.load('work')
        leads = store.load('leads')['leads']
        messaged = {m['lead_id'] for m in store.load('messages')['messages']}
        worked = {x.get('lead_id') for x in work['items'] if x['kind'] == 'draft'}
        today = [x for x in work['items'] if x.get('detail', '').startswith(_tag(day))]
        room = max(0, count - len(today))
        pool = [l for l in leads if l.get('source') == 'founder_reoutreach' and l.get('type') == 'company'
                and l.get('open', True) is not False and l.get('stage') not in ('rejected', 'skipped')
                and l['id'] not in messaged and l['id'] not in worked
                and any(c.get('email') and c.get('email_status') in ('verified', 'published', 'pattern')
                        for c in l.get('contacts', []))]
        pool.sort(key=lambda l: (-((l.get('score') or {}).get('total') or 0), l['id']))
        for lead in pool[:room]:
            item = dict(id=store.next_id(work['items'], 'W'), kind='draft', lead_id=lead['id'], owner=owner,
                        title=f"Founder email: {lead.get('company')}",
                        detail=f"{_tag(day)}: research one sourced hook, write a v3 offer email, queue it with message draft",
                        status='queued', created_at=now_iso(), lease_until=None, result='', ref='')
            work['items'].append(item)
            created.append(item['id'])
        if created:
            store.save('work', work)
            store.journal('supervisor', 'update', f'Founder batch {day}: {len(created)} queued for {owner}',
                          f"{len(today) + len(created)} of {count} for today; {len(pool) - len(created)} founder companies left after this",
                          created[0])
    store.transact(change, 'supervisor: founder batch')
    return dict(day=day, owner=owner, queued=len(created), ids=created)


def handover(to_owner, from_owner=None, reason='', kind='draft'):
    """Move unstarted work to the next model when one runs out of quota or misses its slot.

    Queued items and expired claims of `from_owner` (or of every other owner) are reassigned to `to_owner`.
    Active claims are never taken."""
    if to_owner not in WORKERS or not reason.strip():
        raise ValueError('a valid new owner and a reason are required')
    moved = []
    def change():
        moved.clear()
        work = store.load('work')
        for item in work['items']:
            if item['kind'] != kind or item['owner'] == to_owner or item['status'] == 'done':
                continue
            if from_owner and item['owner'] != from_owner:
                continue
            until = parse_iso(item.get('lease_until'))
            if item['status'] == 'working' and until and until > now():
                continue
            old = item['owner']
            item.update(owner=to_owner, status='queued', lease_until=None, updated_at=now_iso(),
                        detail=f"{item.get('detail', '')} | handed from {old} to {to_owner}: {reason}")
            moved.append(item['id'])
        if moved:
            store.save('work', work)
            store.journal('supervisor', 'update', f'Handover to {to_owner}: {len(moved)} {kind} items',
                          reason, moved[0])
    store.transact(change, 'supervisor: handover')
    return dict(to=to_owner, moved=len(moved), ids=moved)


def claim_next(owner, kind='draft'):
    """Claim the oldest queued item for this owner. Returns {} when there is nothing to do."""
    items = [x for x in queue('list') if x['owner'] == owner and x['kind'] == kind and x['status'] == 'queued']
    for item in items:
        try:
            return queue('claim', ident=item['id'], owner=owner)
        except ValueError:
            continue
    return {}


def batch_status(day=None):
    day = day or _today()
    items = [x for x in queue('list') if x.get('detail', '').startswith(_tag(day))]
    by = {}
    for x in items:
        key = f"{x['owner']}/{x['status']}"
        by[key] = by.get(key, 0) + 1
    return dict(day=day, target=batch_config()['per_day'], created=len(items),
                done=sum(x['status'] == 'done' for x in items), by_owner_status=by)


def packet(lead_id):
    """Assemble existing evidence once. Missing evidence is explicit, never generated."""
    with store.locked():
        store.sync()
        lead = store.find(store.load('leads')['leads'], lead_id)
        if not lead:
            raise ValueError('unknown lead')
        messages = [m for m in store.load('messages')['messages'] if m['lead_id'] == lead_id]
        research = lead.get('research', {})
        missing = []
        if not research.get('done'): missing.append('research')
        if not research.get('hook') or not research.get('hook_source'): missing.append('sourced personalization hook')
        if not lead.get('open', True): missing.append('posting closed: do not draft or send')
        if not lead.get('contacts'): missing.append('contact')
        if not any(m.get('status') in ('draft', 'approved') for m in messages): missing.append('email draft awaiting review')
        if lead.get('apply_url') and not lead.get('apply', {}).get('answers'):
            missing.append('application answers or confirmation no questions are required')
        return dict(lead_id=lead_id, company=lead.get('company'), title=lead.get('title'),
                    apply_url=lead.get('apply_url'), research=research, contacts=lead.get('contacts', []),
                    application=lead.get('apply', {}), messages=messages,
                    missing=missing, ready_for_review=not missing,
                    note='Readiness is completeness only, not factual validation or approval.')


def report(record=False):
    with store.locked():
        store.sync()
        work = store.load('work')['items']
        messages = store.load('messages')['messages']
        issues = [x for x in store.load('issues')['issues'] if x.get('status') == 'open']
        latest = {x['agent']: x for x in store.load('runs')['runs']}
        alerts = []
        for agent, hours in (('lead-scout/scrape', 8), ('follow-up/track', 26), ('follow-up/digest', 26)):
            at = parse_iso(latest.get(agent, {}).get('at'))
            if not at or now() - at > timedelta(hours=hours): alerts.append(f'{agent}: missing or stale heartbeat')
            elif not latest[agent].get('ok'): alerts.append(f'{agent}: last run failed')
        for m in messages:
            at = parse_iso(m.get('sending_at'))
            if m.get('status') == 'failed' or (m.get('status') == 'sending' and at and now() - at > timedelta(minutes=30)):
                alerts.append(f"{m['id']}: {m['status']}; needs investigation")
        for item in work:
            until = parse_iso(item.get('lease_until'))
            if item['status'] == 'working' and until and until <= now():
                alerts.append(f"{item['id']}: claim expired; inspect partial work before reclaiming")
        day = _today()
        batch = [x for x in work if x.get('detail', '').startswith(_tag(day))]
        if now().hour >= 18 and batch_config()['per_day'] and sum(x['status'] == 'done' for x in batch) < batch_config()['per_day']:
            left = [x for x in batch if x['status'] != 'done']
            alerts.append(f"founder batch {day}: {sum(x['status'] == 'done' for x in batch)} of {batch_config()['per_day']} done, "
                          f"{len(left)} still open (owners: {', '.join(sorted({x['owner'] for x in left})) or 'none queued'})")
        result = dict(owners=routing(), alerts=alerts, open_issues=issues,
                      work=[x for x in work if x['status'] != 'done'],
                      model_execution='external workers; no LLM is launched by this command')
        if record:
            store.log_run('supervisor/check', not alerts, '; '.join(alerts) or 'Deterministic checks passed',
                          {'alerts': len(alerts), 'open_work': len(result['work'])})
        return result
