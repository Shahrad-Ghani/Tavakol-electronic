def choose_mode(product):
    s = product['source']
    # Altimate V1: after the maximum two PDF attempts, any safe fact set is used
    # for technical-light content. Sparse facts never trigger more PDF calls.
    if s.get('datasheet_status') == 'FULL_DATASHEET' and s.get('facts_path') and int(s.get('useful_fact_count') or 0) > 0:
        return 'TECHNICAL_LIGHT'
    if s.get('datasheet_status') == 'NO_FULL_DATASHEET':
        return 'SALES_ONLY_NO_DATASHEET'
    return 'SALES_ONLY_INSUFFICIENT_FACTS'


def prompt_mode(content_mode):
    return 'TECHNICAL_LIGHT' if content_mode == 'TECHNICAL_LIGHT' else 'COMMERCIAL_ONLY'


def validate_route_contract(product):
    s = product['source']
    if s.get('datasheet_status') == 'FULL_DATASHEET' and int(s.get('useful_fact_count') or 0) > 0 and not s.get('facts_path'):
        raise ValueError('FULL_DATASHEET with usable facts requires source.facts_path')
    if s.get('datasheet_status') == 'NO_FULL_DATASHEET' and s.get('facts_path'):
        raise ValueError('NO_FULL_DATASHEET must not expose technical facts_path')
