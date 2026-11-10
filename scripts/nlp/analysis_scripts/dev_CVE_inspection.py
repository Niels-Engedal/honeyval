#!/usr/bin/env python3
"""Stream an authenticated sample/audit of oi-uae/cyber-security.

Run after accepting the conditions on the Hugging Face dataset page and
logging in with `hf auth login` (or setting HF_TOKEN).

  pip install -U datasets huggingface_hub
  python audit_oi_uae_cyber_security.py --config balanced --per-task 12

Produces counts.json and stratified_samples.csv. The lexical checks are
triage *indicators*, NOT actual enticingness/secure-state labels.
"""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import random
import re

from datasets import load_dataset

POS = re.compile(
    r"\b(vulnerab\w*|exploit\w*|unauthenticat\w*|bypass\w*|inject\w*|"
    r"remote.code.execution|arbitrary.code|path.traversal|data.leak\w*|"
    r"privilege.escalation|improper.access|exposed|allows? attackers?)\b", re.I)
NEG = re.compile(
    r"\b(patch\w*|fix(?:ed|es)?|remediat\w*|mitigat\w*|"
    r"prevent\w*|protect\w*|restrict\w*|block\w*|enforc\w*|"
    r"validat\w*|saniti[sz]\w*|secure\w*|hardening)\b", re.I)


def consider(reservoir, key, value, seen, n, rng):
    k = seen[key]
    if len(reservoir[key]) < n:
        reservoir[key].append(value)
    else:
        j = rng.randrange(k)
        if j < n:
            reservoir[key][j] = value


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', choices=['balanced', 'full'], default='balanced')
    p.add_argument('--split', choices=['train', 'validation'], default='train')
    p.add_argument('--limit', type=int, default=0,
                   help='Stop after this many records (0 = scan whole split)')
    p.add_argument('--per-task', type=int, default=12,
                   help='Stratified sample conversations per task type')
    p.add_argument('--out', default='cyber_security_audit')
    args = p.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20261110)

    # Balanced is the default config; the author's page explicitly names 'full'.
    kwargs = dict(split=args.split, streaming=True)
    ds = (load_dataset('oi-uae/cyber-security', 'full', **kwargs)
          if args.config == 'full'
          else load_dataset('oi-uae/cyber-security', **kwargs))

    task_counts = Counter()
    domain_counts = Counter()
    source_counts = Counter()
    task_signals = defaultdict(Counter)
    field_counts = Counter()
    reservoirs = defaultdict(list)
    seen = Counter()
    rows = 0

    for idx, row in enumerate(ds):
        if args.limit and idx >= args.limit:
            break
        rows += 1
        meta = row.get('metadata') or {}
        task = str(meta.get('task_type') or 'MISSING')
        domain = str(meta.get('domain') or 'MISSING')
        source = str(meta.get('source') or 'MISSING')
        task_counts[task] += 1
        domain_counts[domain] += 1
        source_counts[source] += 1
        for field in ('cve_id', 'severity', 'published'):
            if meta.get(field) is not None:
                field_counts[field] += 1

        msgs = row.get('messages') or []
        if not isinstance(msgs, list):
            continue
        users = [str(m.get('content') or '') for m in msgs
                 if isinstance(m, dict) and m.get('role') == 'user']
        assistants = [str(m.get('content') or '') for m in msgs
                      if isinstance(m, dict) and m.get('role') == 'assistant']
        # Only assistant answers are scanned, to avoid counting prompt words.
        atext = '\n'.join(assistants)
        has_pos = bool(POS.search(atext))
        has_neg = bool(NEG.search(atext))
        task_signals[task]['mentions_vulnerability_terms'] += int(has_pos)
        task_signals[task]['mentions_security_fix_terms'] += int(has_neg)
        task_signals[task]['mentions_both'] += int(has_pos and has_neg)
        task_signals[task]['assistant_text_nonempty'] += int(bool(atext.strip()))

        sample = {
            'row_index': idx,
            'task_type': task,
            'domain': domain,
            'source': source,
            'cve_id': meta.get('cve_id') or '',
            'severity': meta.get('severity') or '',
            'positive_keyword_signal': has_pos,
            'negative_keyword_signal': has_neg,
            'user_text': '\n\n'.join(users)[:5000],
            'assistant_text': atext[:10000],
            'manual_label': '',  # reviewer: positive, negative, mixed, irrelevant
            'notes': '',
        }
        seen[task] += 1
        consider(reservoirs, task, sample, seen, args.per_task, rng)
        if rows % 50000 == 0:
            print(f'Processed {rows:,} conversations ...', flush=True)

    report = {
        'repo': 'oi-uae/cyber-security',
        'config': args.config,
        'split': args.split,
        'rows_scanned': rows,
        'note': 'Keyword matches are triage signals, NOT enticingness labels. '
                'An answer can describe both an attack and its mitigation.',
        'task_counts': dict(task_counts.most_common()),
        'domain_counts': dict(domain_counts.most_common()),
        'source_counts': dict(source_counts.most_common()),
        'metadata_present_counts': dict(field_counts),
        'task_keyword_signals': {k: dict(v) for k, v in task_signals.items()},
    }
    (out / 'counts.json').write_text(json.dumps(report, indent=2), encoding='utf-8')

    cols = [
        'row_index', 'task_type', 'domain', 'source', 'cve_id', 'severity',
        'positive_keyword_signal', 'negative_keyword_signal',
        'user_text', 'assistant_text', 'manual_label', 'notes'
    ]
    with (out / 'stratified_samples.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        for task in sorted(reservoirs):
            for sample in reservoirs[task]:
                writer.writerow(sample)

    print(f"Scanned {rows:,} records. Saved {out / 'counts.json'} and "
          f"{out / 'stratified_samples.csv'}")
    print('Top task types:', task_counts.most_common(12))
    print('Manual next step: label sampled assistant texts as positive, '
          'negative, mixed, or irrelevant. Do NOT assume advice = secure state.')


if __name__ == '__main__':
    main()
