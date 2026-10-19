"""Apply frozen historical gates after parameter selection; never tune on holdout."""
from math import fsum, isfinite, sqrt


def historical_quality(fit, targets, criteria, windows, *, absolute_tolerance=1e-8):
    required = {'energy_consumption','primary_mix','capacity_or_generation','co2'}
    if {t['family'] for t in targets} != required:
        raise ValueError('All four historical target families required for quality assessment')
    for key in ('maximum_holdout_mape_each_target','maximum_holdout_share_absolute_error',
                'maximum_holdout_normalized_rmse_ratio_to_persistence'):
        if not isfinite(criteria[key]) or criteria[key] < 0:
            raise ValueError('Invalid frozen historical threshold')
    if not isfinite(absolute_tolerance) or absolute_tolerance < 0:
        raise ValueError('Invalid numerical tolerance')
    first,last = windows['already_seen_holdout']
    output = []
    for target in targets:
        rows = [r for r in fit['history_fit'] if r['indicator']==target['id'] and
                r['window']=='already_seen_holdout' and r['status']=='compared']
        reference = {(r['year'],r['indicator']):r for r in fit['baselines']
                     if r['indicator']==target['id'] and r['method']=='last_training_observation'}
        reasons = []
        if {r['year'] for r in rows} != set(range(first,last+1)) or len(rows)!=last-first+1:
            reasons.append('incomplete_holdout_coverage')
        if not rows:
            output.append({'indicator':target['id'],'family':target['family'],'passed':False,
                           'reasons':reasons,'n':0})
            continue
        if any(not isfinite(r[k]) for r in rows for k in ('value','residual')):
            raise ValueError('Nonfinite historical quality inputs')
        scale = target['scale']
        if not isfinite(scale) or scale <= 0:
            raise ValueError('Positive frozen scale required')
        rmse = sqrt(fsum((r['residual']/scale)**2 for r in rows)/len(rows))
        nonzero = [r for r in rows if r['value']!=0]
        mape = fsum(abs(r['residual']/r['value']) for r in nonzero)/len(nonzero) if nonzero else None
        zero_errors = [r for r in rows if r['value']==0 and abs(r['residual'])>absolute_tolerance]
        max_error = max(abs(r['residual']) for r in rows)
        if zero_errors:
            reasons.append('nonzero_prediction_at_zero_observation')
        if mape is not None and mape>criteria['maximum_holdout_mape_each_target']:
            reasons.append('mape_exceeded')
        # Shares must explicitly be fractions; percent-point errors cannot be
        # silently tested against a 0.05 fraction threshold.
        share_error = None
        if target['family']=='primary_mix':
            if target.get('metric_type')!='share_fraction':
                reasons.append('primary_mix_fraction_definition_missing')
            elif any(not 0<=r['value']<=1 or not 0<=r['simulated']<=1 for r in rows):
                reasons.append('share_out_of_bounds')
            else:
                share_error = max_error
                if share_error>criteria['maximum_holdout_share_absolute_error']:
                    reasons.append('share_error_exceeded')
        comparisons = [reference.get((r['year'],r['indicator'])) for r in rows]
        reference_rmse = ratio = None
        if any(b is None for b in comparisons):
            reasons.append('persistence_baseline_missing')
        else:
            for row,base in zip(rows,comparisons):
                if (row['unit'],row['boundary'],row['value']) != (base['unit'],base['boundary'],base['observed']):
                    raise ValueError('Baseline comparison boundary or observed value differs')
            reference_rmse = sqrt(fsum((b['residual']/scale)**2 for b in comparisons)/len(rows))
            if reference_rmse==0:
                ratio = 0. if rmse<=absolute_tolerance/scale else None
                if ratio is None: reasons.append('model_worse_than_exact_persistence')
            else:
                ratio=rmse/reference_rmse
                if ratio>criteria['maximum_holdout_normalized_rmse_ratio_to_persistence']:
                    reasons.append('worse_than_persistence')
        output.append({'indicator':target['id'],'family':target['family'],'n':len(rows),
                       'holdout_mape':mape,'mape_nonzero_observations':len(nonzero),
                       'maximum_absolute_error':max_error,'maximum_share_error_fraction':share_error,
                       'normalized_rmse':rmse,'persistence_normalized_rmse':reference_rmse,
                       'rmse_ratio_to_persistence':ratio,'passed':not reasons,'reasons':reasons})
    return {'passed':all(r['passed'] for r in output),'targets':output,
            'criteria':criteria,'window':'already_seen_holdout',
            'interpretation':'Quality gate only; passing synthetic fixtures is not empirical validation'}
