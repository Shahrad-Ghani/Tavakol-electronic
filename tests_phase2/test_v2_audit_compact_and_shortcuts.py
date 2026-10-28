from pathlib import Path


def test_v2_audit_window_is_compact_and_has_enter_shortcut():
    text = Path("run_ui.py").read_text(encoding="utf-8")
    assert 'self.geometry("1240x700")' in text
    assert 'self.minsize(1080, 620)' in text
    assert 'Enter = Approve & Next' in text
    assert 'self.bind("<Return>", self._on_enter_approve)' in text
    assert 'def _on_enter_approve' in text
    assert 'self.approve()' in text


def test_v2_audit_window_uses_compact_status_grid_not_tall_text_box():
    text = Path("run_ui.py").read_text(encoding="utf-8")
    assert 'self.detail_vars = {' in text
    assert 'details_grid = ttk.Frame(details)' in text
    assert 'self.details_text = tk.Text' not in text
