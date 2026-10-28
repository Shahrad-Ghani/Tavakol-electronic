def expensive_escalation_decision(attempts, threshold=80, cutoff=60, best_candidate=None):
    """Integrated V2.1 compatibility shim.

    The expensive writer tier is disabled. All writer attempts use the configured
    Luna writer plus deterministic/local repair.
    """
    best_score = None
    candidates = [a for a in (attempts or []) if isinstance(a, dict)]
    if best_candidate and isinstance(best_candidate, dict):
        best_score = best_candidate.get("score")
    elif candidates:
        best_score = max((a.get("score", 0) for a in candidates), default=0)
    return {"escalate": False, "reason": "EXPENSIVE_MODEL_DISABLED_V2.1", "best_score": best_score}
