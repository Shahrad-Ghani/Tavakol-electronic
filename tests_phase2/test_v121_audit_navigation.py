from pathlib import Path


def test_audit_decisions_use_auto_advance_helper():
    text = Path('run_ui.py').read_text(encoding='utf-8')
    assert 'def _advance_after_decision' in text
    approve = text.split('def approve(self):', 1)[1].split('def submit_disapproval', 1)[0]
    disapprove = text.split('def submit_disapproval(self):', 1)[1].split('def prev_item', 1)[0]
    assert 'self._advance_after_decision(' in approve
    assert 'self._advance_after_decision(' in disapprove
    assert 'Confirm Disapprove & Next' in text


def test_audit_auto_advance_tracks_stable_source_reference():
    text = Path('run_ui.py').read_text(encoding='utf-8')
    helper = text.split('def _advance_after_decision', 1)[1].split('def approve(self):', 1)[0]
    assert 'reviewed_in_session' in helper
    assert 'source_reference' in helper
    assert 'End of this audit sequence' in helper
    assert 'self.session_order[current_pos + 1:]' in helper
