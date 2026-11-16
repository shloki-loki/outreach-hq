import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import timedelta
from outreach import store, supervisor
from outreach.util import now

class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.p = patch.object(store, 'DATA_DIR', Path(self.temp.name) / 'data')
        self.p.start(); self.addCleanup(self.p.stop)

    def test_claim_conflict_and_handoff(self):
        item = supervisor.queue('add', kind='engineering', owner='codex', title='Fix issue')
        supervisor.queue('claim', ident=item['id'], owner='codex')
        for owner in ('codex', 'claude'):
            with self.assertRaises(ValueError): supervisor.queue('claim', ident=item['id'], owner=owner)
        with self.assertRaises(ValueError): supervisor.queue('assign', ident=item['id'], owner='claude', detail='handoff')
        supervisor.queue('release', ident=item['id'], owner='codex', detail='Evidence saved; remaining tests')
        supervisor.queue('assign', ident=item['id'], owner='claude', detail='Codex allowance unavailable')
        supervisor.queue('claim', ident=item['id'], owner='claude')
        with self.assertRaises(ValueError): supervisor.queue('done', ident=item['id'], owner='codex', detail='done', ref='abc')
        with self.assertRaises(ValueError): supervisor.queue('done', ident=item['id'], owner='claude', detail='done')
        result = supervisor.queue('done', ident=item['id'], owner='claude', detail='Tests pass', ref='commit:abc')
        self.assertEqual(result['status'], 'done')
        self.assertTrue(store.load('journal')['entries'])

    def test_duplicate_lead_work_and_missing_packet(self):
        store.save('leads', {'leads': [{'id': 'L0001', 'company': 'Example'}]})
        supervisor.queue('add', kind='research', lead='L0001', owner='codex', title='Research')
        with self.assertRaises(ValueError):
            supervisor.queue('add', kind='research', lead='L0001', owner='claude', title='Duplicate')
        packet = supervisor.packet('L0001')
        self.assertFalse(packet['ready_for_review'])
        self.assertIn('sourced personalization hook', packet['missing'])

    def test_expired_lease_and_health_report(self):
        item = supervisor.queue('add', kind='engineering', owner='codex', title='Fix')
        supervisor.queue('claim', ident=item['id'], owner='codex')
        data = store.load('work')
        data['items'][0]['lease_until'] = (now() - timedelta(hours=1)).isoformat()
        store.save('work', data)
        self.assertTrue(any('claim expired' in a for a in supervisor.report()['alerts']))
        with self.assertRaises(ValueError): supervisor.queue('done', ident=item['id'], owner='codex', detail='late', ref='abc')
        supervisor.queue('claim', ident=item['id'], owner='codex')
        report = supervisor.report(record=True)
        self.assertEqual(len(report['work']), 1)
        self.assertEqual(store.load('runs')['runs'][-1]['agent'], 'supervisor/check')


class FounderBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.p = patch.object(store, 'DATA_DIR', Path(self.temp.name) / 'data')
        self.p.start(); self.addCleanup(self.p.stop)
        def lead(i, **kw):
            base = dict(id=f'L{i:04d}', company=f'Co{i}', source='founder_reoutreach', type='company', stage='new',
                        open=True, score={'total': 45 + i},
                        contacts=[dict(id='C1', name='A B', title='Co-Founder & CEO', role_type='founder', email=f'a@co{i}.com', email_status='verified')])
            base.update(kw); return base
        leads = [lead(i) for i in range(1, 8)]
        leads.append(lead(8, stage='rejected'))
        leads.append(lead(9, contacts=[dict(id='C1', name='A B', email='', email_status='none')]))
        leads.append(lead(10, source='linkedin', type='job'))
        store.save('leads', {'leads': leads})
        store.save('messages', {'messages': [{'id': 'M0001', 'lead_id': 'L0007', 'status': 'sent'}]})

    def test_batch_picks_eligible_tops_up_and_never_doubles(self):
        first = supervisor.founder_batch(count=4, owner='codex')
        self.assertEqual(first['queued'], 4)
        items = supervisor.queue('list')
        self.assertEqual([x['lead_id'] for x in items], ['L0006', 'L0005', 'L0004', 'L0003'])  # best score first
        self.assertEqual(supervisor.founder_batch(count=4, owner='codex')['queued'], 0)     # same day: no doubling
        self.assertEqual(supervisor.founder_batch(count=10, owner='codex')['queued'], 2)    # only L0001-2 left
        leads = {x['lead_id'] for x in supervisor.queue('list')}
        self.assertFalse(leads & {'L0007', 'L0008', 'L0009', 'L0010'})  # messaged, rejected, no address, not founder
        self.assertEqual(supervisor.batch_status()['created'], 6)

    def test_handover_moves_unstarted_and_expired_never_active(self):
        supervisor.founder_batch(count=3, owner='codex')
        a, b, c = supervisor.queue('list')
        supervisor.queue('claim', ident=a['id'], owner='codex')          # active: stays with codex
        supervisor.queue('claim', ident=b['id'], owner='codex')          # expired: moves
        data = store.load('work')
        data['items'][1]['lease_until'] = (now() - timedelta(minutes=5)).isoformat()
        store.save('work', data)
        with self.assertRaises(ValueError): supervisor.handover('claude', 'codex', '')
        moved = supervisor.handover('claude', 'codex', 'GPT limit used up for today')
        self.assertEqual(sorted(moved['ids']), sorted([b['id'], c['id']]))
        nxt = supervisor.claim_next('claude')
        self.assertEqual(nxt['status'], 'working')
        self.assertEqual(nxt['owner'], 'claude')
        self.assertEqual(supervisor.claim_next('grok'), {})
        supervisor.handover('grok', None, 'Claude busy')
        self.assertTrue(any(x['owner'] == 'grok' for x in supervisor.queue('list')))

    def test_batch_skips_do_not_email_recent_sends_and_non_heads(self):
        def lead(i, contacts):
            return dict(id=f'L{i:04d}', company=f'Co{i}', source='founder_reoutreach', type='company', stage='new',
                        open=True, score={'total': 90 - i}, contacts=contacts)
        def person(cid, email, role='founder', title='Founder'):
            return dict(id=cid, name=f'P {cid}', title=title, role_type=role, email=email, email_status='verified')
        store.save('leads', {'leads': [
            lead(20, [person('C1', 'gone@x20.com')]),                                   # on the do-not-email list
            lead(21, [person('C1', 'sent@x21.com')]),                                   # cold-emailed last week (other lead)
            lead(22, [person('C1', 'hr@x22.com', 'recruiter', 'Talent Partner')]),      # recruiter only
            lead(23, [person('C1', 'pm@x23.com', 'employee', 'Product Analyst')]),      # not a function head
            lead(24, [person('C1', 'gone@x24.com'), person('C2', 'ops@x24.com', 'employee', 'Head of Operations')]),
            lead(25, [person('C1', 'vp@x25.com', 'employee', 'VP Strategy'), person('C2', 'f@x25.com')]),
            lead(26, [person('C1', 'cto@x26.com', title='Co-Founder & CTO'), person('C2', 'ceo@x26.com', title='Co-Founder & CEO')]),
        ]})
        store.save('suppression', {'emails': {'gone@x20.com': {'reason': 'already emailed'},
                                              'gone@x24.com': {'reason': 'already emailed'}}})
        store.save('messages', {'messages': [{'id': 'M0009', 'lead_id': 'L0999', 'to': 'sent@x21.com', 'kind': 'cold',
                                              'status': 'sent', 'sent_at': (now() - timedelta(days=7)).isoformat()}]})
        supervisor.founder_batch(count=10, owner='codex')
        picked = {x['lead_id']: x['contact_id'] for x in supervisor.queue('list')}
        self.assertEqual(picked, {'L0024': 'C2', 'L0025': 'C2', 'L0026': 'C2'})   # head when founder excluded; founder first; CEO first

    def test_batch_identity_survives_reassignment_and_status_splits_outcomes(self):
        supervisor.founder_batch(count=3, owner='codex')
        a, b, c = supervisor.queue('list')
        supervisor.queue('assign', ident=c['id'], owner='claude', detail='rewritten detail with no batch tag')
        for item, detail, ref in ((a, 'drafted M0042 to A B', 'M0042'), (b, 'rejected: shut down in 2025', b['lead_id'])):
            supervisor.queue('claim', ident=item['id'], owner='codex')
            supervisor.queue('done', ident=item['id'], owner='codex', detail=detail, ref=ref)
        status = supervisor.batch_status()
        self.assertEqual((status['created'], status['drafted'], status['rejected'], status['open']), (3, 1, 1, 1))
