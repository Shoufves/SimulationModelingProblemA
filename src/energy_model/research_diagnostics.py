"""Supplementary, descriptive research diagnostics; no model or detector changes."""
from collections import Counter, defaultdict
from itertools import combinations, permutations
import json
import math
import re


def pooled_source_exposure(modes):
    """Merge named origins; leave unidentified region buckets unallocated.

    HHI lower is an infimum when an unspecified bucket can split arbitrarily.
    Upper conservatively permits all unidentified volume to share the largest
    named country; geographic exclusions are intentionally not invented.
    """
    if len(modes) < 2:
        raise ValueError('At least two transport modes required')
    named = defaultdict(float)
    mode_totals = {}
    provenance = []
    unknown = 0.0
    labels = set()
    route_country_squares = []
    for mode, rows in sorted(modes.items()):
        totals = [r for r in rows if r['row_type'] == 'total']
        parts = [r for r in rows if r['row_type'] == 'origin']
        if len(totals) != 1 or len(parts) + 1 != len(rows):
            raise ValueError('Invalid total or row type')
        if len({r['origin'] for r in parts}) != len(parts):
            raise ValueError('Duplicate origin within mode')
        labels.update((r['year'], r['unit'], r['source_id'], r['destination']) for r in rows)
        total = float(totals[0]['value'])
        vals = [float(r['value']) for r in parts]
        if not all(math.isfinite(x) and x >= 0 for x in [total, *vals]) or total <= 0:
            raise ValueError('Nonfinite or negative trade value')
        if not math.isclose(math.fsum(vals), total, rel_tol=1e-9, abs_tol=1e-8):
            raise ValueError('Trade parts do not reconcile')
        mode_totals[mode] = total
        for r, value in zip(parts, vals):
            grouped = r['origin'].startswith('Other ')
            if grouped:
                unknown += value
            else:
                named[r['origin']] += value
                route_country_squares.append(value * value)
            provenance.append(dict(mode=mode, origin=r['origin'], value=value,
                is_unresolved_bucket=grouped, sheet=r['sheet'], cell=r['cell']))
    if len(labels) != 1:
        raise ValueError('Year/unit/source/destination mismatch')
    total = math.fsum(mode_totals.values())
    ordered = sorted(named.items(), key=lambda item: (-item[1], item[0]))
    largest = ordered[0][1] if ordered else 0.0
    known_square = math.fsum(v * v for v in named.values())
    factor = 10000 / (total * total)
    route_hhi = math.fsum(route_country_squares) * factor
    merged_hhi = known_square * factor
    result = dict(total_bcm_gcv40=total, mode_totals=mode_totals,
        unresolved_bcm=unknown, named_country_hhi_lower=merged_hhi,
        conservative_country_hhi_upper=(known_square + 2*largest*unknown + unknown**2)*factor,
        separated_route_country_hhi_lower=route_hhi,
        omitted_common_origin_cross_term=merged_hhi-route_hhi,
        largest_named_origin=ordered[0][0] if ordered else None,
        largest_named_share=largest/total,
        single_origin_exposure_upper=(largest+unknown)/total,
        countries=[dict(origin=k, bcm=v, share=v/total) for k,v in ordered],
        input_cells=provenance,
        interpretation='Annual gross-import exposure, not outage probability, domestic consumption share, physical pipeline capacity, or Q3 channel calibration.')
    return result


def factorial_attribution(values, players):
    """Exact Shapley and anchored factorial interactions; standard methods."""
    players = tuple(players)
    keys = {frozenset(c) for size in range(len(players)+1) for c in combinations(players, size)}
    if set(values) != keys or not all(math.isfinite(x) for x in values.values()):
        raise ValueError('Complete finite factorial table required')
    phi = dict.fromkeys(players, 0.0)
    orders = list(permutations(players))
    for order in orders:
        prior = frozenset()
        for player in order:
            after = prior | {player}
            phi[player] += (values[after]-values[prior])/len(orders)
            prior = after
    interaction = {}
    for size in range(2, len(players)+1):
        for group in combinations(players, size):
            interaction['+'.join(group)] = math.fsum(
                (-1)**(size-k)*values[frozenset(s)]
                for k in range(size+1) for s in combinations(group, k))
    return dict(shapley=phi, anchored_interactions=interaction,
        full_minus_empty=values[frozenset(players)]-values[frozenset()],
        efficiency_residual=math.fsum(phi.values())-(values[frozenset(players)]-values[frozenset()]))


def deployment_signature(public):
    """A signature of realised additional public commitments, not policy labels."""
    fields = ('year','action','capacity_mw','decision','online','amount_cny')
    entries = [{k:r[k] for k in fields} for r in public]
    return json.dumps(sorted(entries,key=lambda r:json.dumps(r,sort_keys=True)),sort_keys=True,separators=(',',':'))


def prose_sentences(text):
    rows = []
    fenced = False
    for line in text.splitlines():
        if line.strip().startswith(('```','~~~')):
            fenced = not fenced
            continue
        if fenced or line.lstrip().startswith(('#','|','![','$$')):
            continue
        line = re.sub(r'\[([^\]]+)\]\([^)]*\)',r'\1',line)
        line = re.sub(r'^[\s>*\-\d.]+','',line).replace('**','')
        for sentence in re.split(r'[。！？；\n]',line):
            normal = ''.join(re.findall(r'[\u4e00-\u9fffA-Za-z0-9]',sentence)).lower()
            if len(normal) >= 12:
                rows.append((sentence.strip(),normal))
    return rows


def text_profile(text, corpus, n=12):
    """Transparent writing metrics; deliberately no AI authorship prediction."""
    sentences = prose_sentences(text)
    if not sentences or n < 4:
        raise ValueError('No usable prose or invalid n-gram length')
    counts = Counter(normal for _,normal in sentences)
    repeated = sum(v-1 for v in counts.values())
    indexed = defaultdict(set)
    for name, content in corpus.items():
        for _,normal in prose_sentences(content):
            for i in range(len(normal)-n+1):
                indexed[normal[i:i+n]].add(name)
    grams = total = 0
    matches = []
    labels = ('依据：','机制：','适用条件：','主要限制：','后续检验：','边界：')
    template = 0
    for raw,normal in sentences:
        template += any(label in raw for label in labels)
        source_counts = Counter()
        for i in range(len(normal)-n+1):
            total += 1
            sources = indexed.get(normal[i:i+n],())
            if sources:
                grams += 1
                source_counts.update(sources)
        if source_counts:
            matches.append(dict(sentence=raw, sources=dict(source_counts.most_common(3))))
    numeric = [raw for raw,_ in sentences if re.search(r'\d',raw)]
    anchored = [raw for raw in numeric if re.search(r'\[E\d+\]',raw)]
    def rate(num,den):
        return dict(numerator=num,denominator=den,percent=100*num/den if den else None)
    return dict(prose_sentences=len(sentences), prose_normalized_characters=sum(len(s) for _,s in sentences),
        repeated_sentence_rate=rate(repeated,len(sentences)),
        explicit_template_label_rate=rate(template,len(sentences)),
        local_12gram_overlap=rate(grams,total),
        numeric_sentence_explicit_anchor_rate=rate(len(anchored),len(numeric)),
        repeated_sentences=[dict(normalized=s,count=count) for s,count in counts.items() if count>1],
        overlap_locations=matches,
        formal_aigc_detector_percent=None,true_ai_authorship_percent=None,external_plagiarism_percent=None,
        interpretation='Descriptive metrics only. Local overlap includes legitimate reuse of team material; it is neither external plagiarism nor AI-generation probability. Anchors are a syntactic measure, not proof of a claim.')


def verify_evidence_claims(claims, manuscripts, resolve):
    """Bind registered manuscript phrases to freshly resolved numerical evidence."""
    checked = []
    declared = set()
    for claim in claims:
        ident = claim['id']
        if ident in declared:
            raise ValueError('Duplicate evidence id: '+ident)
        declared.add(ident)
        text = manuscripts[claim['manuscript']]
        phrase = claim['phrase']
        if phrase not in text or '['+ident+']' not in phrase:
            raise ValueError('Evidence phrase/anchor missing: '+ident)
        numbers = []
        for item in claim['values']:
            raw = resolve(item['source'])
            value = float(raw)*item.get('scale',1)
            rendered = format(value,item['format'])
            if rendered != item['rendered'] or rendered not in phrase:
                raise ValueError('Evidence numeric mismatch: '+ident)
            numbers.append(dict(source=item['source'],raw=raw,rendered=rendered))
        checked.append(dict(id=ident,manuscript=claim['manuscript'],phrase=phrase,values=numbers))
    used = {s for text in manuscripts.values() for s in re.findall(r'\[(E\d+)\]',text)}
    if used != declared:
        raise ValueError('Undeclared or unused evidence anchors')
    return checked
