from copy import deepcopy


def _as_int(value):
    try:
        return int(value or 0)
    except Exception:
        return 0


def normalize_usage(usage):
    """Normalize Responses API usage into stable token counters."""
    usage = usage or {}
    if hasattr(usage, 'model_dump'):
        usage = usage.model_dump()
    if not isinstance(usage, dict):
        return {'input_tokens': 0, 'cached_input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0}

    inp = _as_int(usage.get('input_tokens') or usage.get('prompt_tokens'))
    out = _as_int(usage.get('output_tokens') or usage.get('completion_tokens'))
    details = usage.get('input_tokens_details') or usage.get('prompt_tokens_details') or {}
    cached = _as_int(details.get('cached_tokens') if isinstance(details, dict) else 0)
    cached = min(cached, inp)
    total = _as_int(usage.get('total_tokens')) or inp + out
    return {
        'input_tokens': inp,
        'cached_input_tokens': cached,
        'output_tokens': out,
        'total_tokens': total,
    }


def estimate_cost_usd(model, usage, pricing):
    n = normalize_usage(usage)
    rates = (pricing or {}).get(model) or {}
    uncached = max(0, n['input_tokens'] - n['cached_input_tokens'])
    input_rate = float(rates.get('input', 0.0))
    cached_rate = float(rates.get('cached_input', input_rate))
    output_rate = float(rates.get('output', 0.0))
    cost = (uncached * input_rate + n['cached_input_tokens'] * cached_rate + n['output_tokens'] * output_rate) / 1_000_000.0
    return round(cost, 8)


def stage_record(stage, api_meta, pricing):
    api_meta = api_meta or {}
    model = api_meta.get('model')
    usage = normalize_usage(api_meta.get('usage'))
    return {
        'stage': stage,
        'provider': api_meta.get('provider', 'openai'),
        'model': model,
        'response_id': api_meta.get('response_id'),
        'usage': usage,
        'estimated_cost_usd': estimate_cost_usd(model, api_meta.get('usage'), pricing),
    }


def summarize_stage_records(records, pricing_basis=None):
    records = [deepcopy(x) for x in records if isinstance(x, dict)]
    totals = {'input_tokens': 0, 'cached_input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0}
    total_cost = 0.0
    for r in records:
        u = r.get('usage') or {}
        for k in totals:
            totals[k] += _as_int(u.get(k))
        total_cost += float(r.get('estimated_cost_usd') or 0.0)
    return {
        'pricing_basis': pricing_basis,
        'stages': records,
        'totals': totals,
        'estimated_total_cost_usd': round(total_cost, 8),
    }
