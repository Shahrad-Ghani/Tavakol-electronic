# Altimate V1.0.1 Hotfix — implementation summary

- `phase2/metadata_state.py`: Current and historical admin authority guards, explicit-override/PN checks.
- `phase2/pipeline.py`: eligibility before `mark_searching` and network I/O.
- `metadata_manager.py`: protection at transaction commit, including late/stale Phase2 results.
- `orchestrator/engine.py`: no indiscriminate requeue on Part Number Ready; late queue checkpoint guard and resume routing.
- `admin_audit.py`: Existing decision logic remains unchanged; the UI now makes rejected items discoverable.
- `run_ui.py`: PN search/filter, empty-folder Manual Mode resume.
- `regenerator.py`: unsupported input format converted to temporary PNG for Image Edit.
- `phase2/resolver_v43.py`: Cloudflare challenge detection/cooldown, keeping BLOCKED truthfully classified.
- `recover_datasheet_authority.py`: opt-in conservative recovery + backup + CSV report.
- `upgrade_from_altimate_v100.py`: guarded transfer of runtime assets from active V1.0.0 installation.
- `tests_altimate_v101/`: offline regression of PDF/Sales-only authority and recovery.

Never copy the new recovery tool into an old codebase and invoke it during an active process. Stop workers and Publisher first.
