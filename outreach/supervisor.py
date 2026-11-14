"""Shared, model-independent coordination. No model calls or sending side effects."""
from datetime import timedelta
from . import store
from .util import load_config, now, now_iso, parse_iso

KINDS = ('research', 'draft', 'followup', 'review', 'engineering')
WORKERS = ('codex', 'claude')


def routing():
    return load_config('routing')['owners']


def queue(action, *, ident=None, kind=None, lead=None, owner=None, title='', detail='', ref=''):
    if action == 'list':
        with store.locked():
            store.sync()
            return store.load('work')['items']
    if owner not in WORKERS:
        raise ValueError('owner must be codex or claude')
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
        result = dict(owners=routing(), alerts=alerts, open_issues=issues,
                      work=[x for x in work if x['status'] != 'done'],
                      model_execution='external workers; no LLM is launched by this command')
        if record:
            store.log_run('supervisor/check', not alerts, '; '.join(alerts) or 'Deterministic checks passed',
                          {'alerts': len(alerts), 'open_work': len(result['work'])})
        return result
