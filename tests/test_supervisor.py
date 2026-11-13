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
