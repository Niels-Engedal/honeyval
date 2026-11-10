#!/usr/bin/env python3
"""Audit NVD CVE descriptions joined to FIRST EPSS, optionally joined to MITRE CWE mitigations.

Outputs counts.json, all_entries.csv, candidate_source_pairs.csv, stratified_samples.csv.
All source material is *unlabeled*: possible CWE mitigations are NOT automatically negative seeds.

Usage:
 python audit_cve_epss_sources.py --years 2024 2025 --cwe-candidates seed_source_audit/candidate_source_pairs.csv

Uses official NVD yearly JSON 2.0 gz feeds and FIRST current EPSS CSV.gz. Downloads
are cached in --cache-dir; reruns reuse cached data. Standard library only.
"""
import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
import io
import json
from pathlib import Path
import random
import re
import sys
import time
from urllib.request import Request, urlopen

FIRST_URL = 'https://epss.empiricalsecurity.com/epss_scores-current.csv.gz'
NVD_URL = 'https://nvd.nist.gov/feeds/json/cve/2.0/nvdcve-2.0-{year}.json.gz'
CWE_ID = re.compile(r'^CWE-\d+$')
FIELDS = [
 'cve_id','year','nvd_status','description','description_length','epss',
 'epss_percentile','epss_band','cvss_score','cvss_version','weakness_ids',
 'first_cwe_id','first_cwe_mitigation','has_cwe_mitigation','patch_reference_count',
 'has_patch_reference','reference_count','candidate_source_pair','nvd_url',
]


def download(url, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and destination.stat().st_size > 0:
        print(f'Using cached {destination}')
        return destination
    print(f'Downloading {url} -> {destination}')
    for attempt in range(3):
        try:
            req = Request(url, headers={'User-Agent':'AcademicCVESeedAudit/1.0 (research)'})
            with urlopen(req, timeout=120) as response, destination.open('wb') as output:
                import shutil
                shutil.copyfileobj(response, output)
            if not destination.stat().st_size:
                raise RuntimeError('Downloaded empty file')
            return destination
        except Exception as e:
            destination.unlink(missing_ok=True)
            if attempt == 2:
                raise RuntimeError(f'Could not download {url}: {e}') from e
            time.sleep(2 ** attempt)


def open_compressed(path):
    if str(path).endswith('.gz'):
        return gzip.open(path, 'rt', encoding='utf-8-sig')
    return open(path, 'rt', encoding='utf-8-sig')


def load_epss(path):
    scores = {}
    header_comment = ''
    with open_compressed(path) as f:
        # FIRST includes one or more # comment lines before the CSV header.
        for line in f:
            if line.startswith('#'):
                header_comment += line.strip() + '\n'
                continue
            reader = csv.DictReader([line] + list(f))
            for row in reader:
                cve = (row.get('cve') or '').strip()
                if not cve: continue
                try:
                    scores[cve] = (float(row['epss']), float(row['percentile']))
                except (TypeError, ValueError, KeyError):
                    continue
            break
    return scores, header_comment.strip()


def load_cwe_mitigations(path):
    if not path: return {}
    mitigations = {}
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            if row.get('dataset') != 'CWE' or not CWE_ID.fullmatch(row.get('id','')):
                continue
            m = (row.get('mitigations') or '').strip()
            if m: mitigations[row['id']] = m
    return mitigations


def get_english(items):
    for it in items or []:
        if it.get('lang','').lower() == 'en' and it.get('value'):
            return ' '.join(it['value'].split())
    return ''


def get_cvss(metrics):
    for family, version in [('cvssMetricV40','4.0'),('cvssMetricV31','3.1'),
                             ('cvssMetricV30','3.0'),('cvssMetricV2','2.0')]:
        items = metrics.get(family, [])
        if items:
            primary = next((item for item in items if item.get('type') == 'Primary'), items[0])
            score = (primary.get('cvssData') or {}).get('baseScore')
            if score is not None: return score, version
    return '', ''


def parse_nvd(path, epss, cwe_mit):
    with open_compressed(path) as f:
        doc = json.load(f)
    vulnerabilities = doc.get('vulnerabilities', [])
    for item in vulnerabilities:
        obj = item.get('cve', item)
        cve_id = obj.get('id','')
        if not cve_id.startswith('CVE-'): continue
        desc = get_english(obj.get('descriptions'))
        status = obj.get('vulnStatus','')
        if not desc or status.lower() in ('rejected','withdrawn') or 'rejected' in desc[:60].lower():
            continue
        if cve_id not in epss: continue
        sc, pct = epss[cve_id]
        ids = []
        for weakness in obj.get('weaknesses', []):
            for d in weakness.get('description', []):
                if CWE_ID.fullmatch(d.get('value','')) and d['value'] not in ids:
                    ids.append(d['value'])
        matches = [c for c in ids if c in cwe_mit]
        first = matches[0] if matches else ''
        refs = obj.get('references', [])
        patches = [r for r in refs if any(t.lower() in ('patch', 'vendor advisory') for t in r.get('tags',[]))]
        cvss, version = get_cvss(obj.get('metrics', {}))
        band = 'high (>=90th percentile)' if pct >= .90 else 'low (<=10th percentile)' if pct <= .10 else 'middle'
        yield {
            'cve_id': cve_id,'year': cve_id.split('-')[1], 'nvd_status':status,
            'description': desc, 'description_length':len(desc), 'epss':sc,
            'epss_percentile':pct, 'epss_band':band, 'cvss_score':cvss,
            'cvss_version':version, 'weakness_ids':' | '.join(ids),
            'first_cwe_id': first, 'first_cwe_mitigation':cwe_mit.get(first,''),
            'has_cwe_mitigation':int(bool(first)),
            'patch_reference_count':len(patches), 'has_patch_reference':int(bool(patches)),
            'reference_count':len(refs),
            'candidate_source_pair':int(bool(first)),
            'nvd_url':f'https://nvd.nist.gov/vuln/detail/{cve_id}',
        }


def write_csv(path, rows):
    with path.open('w', encoding='utf-8', newline='') as f:
        writer=csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def sample_diverse(rows, n_per_band, seed):
    """Sample across EPSS bins with CWE diversity instead of only popular CWEs."""
    randomizer = random.Random(seed)
    sampled = []
    for band in ['high (>=90th percentile)','middle','low (<=10th percentile)']:
        pool = [r for r in rows if r['epss_band'] == band]
        group = defaultdict(list)
        for row in pool:
            group[row['first_cwe_id'] or 'no-CWE-match'].append(row)
        for g in group.values(): randomizer.shuffle(g)
        keys = list(group); randomizer.shuffle(keys)
        chosen=[]
        while keys and len(chosen) < n_per_band:
            nextkeys=[]
            for k in keys:
                if len(chosen) == n_per_band: break
                chosen.append(group[k].pop())
                if group[k]: nextkeys.append(k)
            keys=nextkeys
            randomizer.shuffle(keys)
        sampled.extend(chosen)
    return sampled


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--years', nargs='+', type=int, default=[2024, 2025])
    p.add_argument('--cwe-candidates', type=Path, help='CWE/CAPEC audit candidate_source_pairs.csv')
    p.add_argument('--out', type=Path, default=Path('cve_epss_audit'))
    p.add_argument('--cache-dir', type=Path, default=Path('cve_epss_cache'))
    p.add_argument('--epss-file', type=Path, help='Use existing CSV or CSV.gz instead of downloading current EPSS')
    p.add_argument('--nvd-file', type=Path, action='append', help='Use local NVD JSON(.gz) instead of downloading yearly feeds; repeatable')
    p.add_argument('--per-band', type=int, default=30)
    p.add_argument('--seed', type=int, default=42)
    args=p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    epss_file=args.epss_file or download(FIRST_URL, args.cache_dir / 'epss_scores-current.csv.gz')
    scores, epss_header = load_epss(epss_file)
    cwe_mit=load_cwe_mitigations(args.cwe_candidates)
    nvd_files=args.nvd_file or [download(NVD_URL.format(year=y), args.cache_dir / f'nvdcve-2.0-{y}.json.gz') for y in args.years]
    all_rows=[]
    for nf in nvd_files:
        rows=list(parse_nvd(nf, scores, cwe_mit))
        print(f'{nf}: {len(rows)} CVEs with description and EPSS')
        all_rows.extend(rows)
    all_rows=list({r['cve_id']:r for r in all_rows}.values())
    candidates=[r for r in all_rows if r['candidate_source_pair']]
    counts={
      'note':'These are source candidates, NOT enticingness labels. CWE mitigations are not verified secure-state descriptions.',
      'created_utc':datetime.now(timezone.utc).isoformat(),
      'epss_source':str(epss_file), 'epss_metadata':epss_header,
      'nvd_sources':[str(path) for path in nvd_files],
      'cwe_candidate_source':str(args.cwe_candidates) if args.cwe_candidates else None,
      'epss_scored_population':len(scores),
      'nvd_joined_rows':len(all_rows),
      'by_epss_band':dict(Counter(r['epss_band'] for r in all_rows)),
      'with_cvss':sum(r['cvss_score'] != '' for r in all_rows),
      'with_cwe_ids':sum(bool(r['weakness_ids']) for r in all_rows),
      'with_cwe_mitigation':len(candidates),
      'with_patch_reference':sum(r['has_patch_reference'] for r in all_rows),
      'cwe_mitigation_matches_by_band':dict(Counter(r['epss_band'] for r in candidates)),
      'distinct_cwes_among_candidates':len({r['first_cwe_id'] for r in candidates}),
    }
    samples=sample_diverse(candidates if cwe_mit else all_rows, args.per_band,args.seed)
    write_csv(args.out/'all_entries.csv', all_rows)
    write_csv(args.out/'candidate_source_pairs.csv', candidates)
    write_csv(args.out/'stratified_samples.csv',samples)
    (args.out/'counts.json').write_text(json.dumps(counts,indent=2),encoding='utf-8')
    print(json.dumps(counts,indent=2))
    print('Outputs:',args.out.resolve())


if __name__=='__main__':
    main()
