"""Keep energy end uses and each nonenergy material service identifiable."""


def service_key(row):
    sector = row['sector']
    if sector == 'nonenergy_feedstock':
        carrier = row.get('carrier')
        if carrier not in ('coal', 'oil', 'gas'):
            raise ValueError('Missing nonenergy carrier')
        return sector + '/' + carrier
    return sector
