def decide_retry(
    *,
    attempt: int,
    score: int,
    previous_score,
    threshold: int,
    contract_pass: bool,
    fact_safety_pass: bool = True,
    hard_gate_pass: bool = True,
    actionable_retry_needed: bool = True,
    min_improvement: int = 10,
    max_attempts_guard: int = 4,
):
    improvement = None if previous_score is None else score - previous_score

    if attempt >= max_attempts_guard:
        return {
            'retry': False,
            'reason': 'SAFETY_GUARD_REACHED',
            'improvement': improvement,
        }

    # Identity and technical safety are absolute and independent of SEO score.
    if not hard_gate_pass:
        return {
            'retry': True,
            'reason': 'HARD_GATE_NOT_MET',
            'improvement': improvement,
        }

    if not fact_safety_pass:
        return {
            'retry': True,
            'reason': 'FACT_SAFETY_NOT_MET',
            'improvement': improvement,
        }

    if not contract_pass:
        return {
            'retry': True,
            'reason': 'STRUCTURE_CONTRACT_NOT_MET',
            'improvement': improvement,
        }

    if score >= threshold:
        return {
            'retry': False,
            'reason': 'SEO_THRESHOLD_AND_CONTRACT_REACHED',
            'improvement': improvement,
        }

    # V4.1: below-threshold score alone is not enough to buy another model call.
    # If every remaining deficit is warning-only/non-writer/non-actionable, finalize.
    if not actionable_retry_needed:
        return {
            'retry': False,
            'reason': 'NO_ACTIONABLE_FAILURES',
            'improvement': improvement,
        }

    if attempt == 1:
        return {
            'retry': True,
            'reason': 'MANDATORY_SECOND_ATTEMPT',
            'improvement': None,
        }

    if improvement is not None and improvement >= min_improvement:
        return {
            'retry': True,
            'reason': 'IMPROVEMENT_AT_LEAST_10',
            'improvement': improvement,
        }

    return {
        'retry': False,
        'reason': 'IMPROVEMENT_BELOW_10',
        'improvement': improvement,
    }
