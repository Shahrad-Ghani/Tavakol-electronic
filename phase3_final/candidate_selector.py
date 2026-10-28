def _structure_failure_count(attempt):
    return len(attempt.get('structure', {}).get('failures', []))


def _fact_failure_count(attempt):
    return len(attempt.get('fact_safety', {}).get('failures', []))


def _hard_gate_failure_count(attempt):
    return sum(1 for x in attempt.get('hard_gates', {}).values() if x.get('status') == 'FAIL')


def _structure_target_distance(attempt):
    """Normalized distance from the declared structure targets.

    Altimate V1 policy: when candidates have the same safety/failure class, closeness
    to the target word-count/density envelope outranks SEO score. Missing
    measurements are neutral so legacy/generic tests remain stable.
    """
    measured = attempt.get('structure', {}).get('measured', {}) or {}
    total = 0.0
    seen = False

    if 'word_count_distance_from_target' in measured:
        seen = True
        dist = float(measured.get('word_count_distance_from_target') or 0.0)
        target = measured.get('word_count_target') or {}
        lo = float(target.get('min') or 0.0)
        hi = float(target.get('max') or 0.0)
        width = max(1.0, hi - lo)
        total += dist / width

    if 'keyword_density_distance_from_target' in measured:
        seen = True
        dist = float(measured.get('keyword_density_distance_from_target') or 0.0)
        target = measured.get('keyword_density_target') or {}
        lo = float(target.get('min') or 0.0)
        hi = float(target.get('max') or 0.0)
        width = max(0.01, hi - lo)
        total += dist / width

    return round(total, 8) if seen else 0.0


def select_best_candidate(attempts):
    if not attempts:
        raise ValueError('No attempts to select from')

    # Frozen Altimate V1 order:
    # identity safety -> fact safety -> structure pass/failure count ->
    # distance from structure targets -> SEO score -> earlier attempt.
    fully_valid = [
        a for a in attempts
        if a.get('hard_gate_pass', True)
        and a.get('fact_safety_pass', True)
        and a.get('contract_pass')
    ]
    if fully_valid:
        return max(
            fully_valid,
            key=lambda a: (-_structure_target_distance(a), a.get('score', 0), -a.get('attempt', 0)),
        )

    identity_and_fact_safe = [
        a for a in attempts
        if a.get('hard_gate_pass', True) and a.get('fact_safety_pass', True)
    ]
    if identity_and_fact_safe:
        return max(
            identity_and_fact_safe,
            key=lambda a: (
                -_structure_failure_count(a),
                -_structure_target_distance(a),
                a.get('score', 0),
                -a.get('attempt', 0),
            ),
        )

    identity_safe = [a for a in attempts if a.get('hard_gate_pass', True)]
    if identity_safe:
        return max(
            identity_safe,
            key=lambda a: (
                -_fact_failure_count(a),
                -_structure_failure_count(a),
                -_structure_target_distance(a),
                a.get('score', 0),
                -a.get('attempt', 0),
            ),
        )

    # If every attempt violates identity, preserve only the least unsafe audit
    # candidate. Finalization will be HARD_GATE_FAILED and not publishable.
    return max(
        attempts,
        key=lambda a: (
            -_hard_gate_failure_count(a),
            -_fact_failure_count(a),
            -_structure_failure_count(a),
            -_structure_target_distance(a),
            a.get('score', 0),
            -a.get('attempt', 0),
        ),
    )
