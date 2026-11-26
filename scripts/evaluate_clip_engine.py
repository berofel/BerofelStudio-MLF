"""Evaluate cached Clip Engine candidates against manually marked intervals.

This evaluator uses only local JSON and the Python standard library. It never
opens media, runs Parakeet, or claims that its scores predict virality.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys


def _interval(item: dict, start_key: str, end_key: str) -> tuple[float, float]:
    try:
        start, end = float(item[start_key]), float(item[end_key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Intervalo sem {start_key}/{end_key} numéricos.") from exc
    if not math.isfinite(start + end) or start < 0 or end <= start:
        raise ValueError(f"Intervalo inválido: {start}–{end}.")
    return start, end


def _flatten_candidates(payload: dict) -> list[dict]:
    result = payload.get('result', payload)
    candidates = result.get('candidates')
    if candidates is None:
        candidates = [candidate for clip in result.get('clips', [])
                      for candidate in clip.get('candidates', [])]
    if not isinstance(candidates, list):
        raise ValueError('O arquivo de resultado não contém uma lista de candidatos.')
    validated = []
    for candidate in candidates:
        start, end = _interval(candidate, 'source_start', 'source_end')
        try:
            score = float(candidate['score'])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError('Candidato sem score numérico.') from exc
        if not math.isfinite(score):
            raise ValueError('Candidato com score não finito.')
        validated.append({**candidate, 'source_start': start,
                          'source_end': end, 'score': score})
    return sorted(validated, key=lambda item: (-item['score'],
        item['source_start'], item['source_end']))


def _overlap_ratio(candidate: dict, label: dict) -> tuple[float, float]:
    other_start = label['start'] if 'start' in label else label['source_start']
    other_end = label['end'] if 'end' in label else label['source_end']
    left = max(candidate['source_start'], other_start)
    right = min(candidate['source_end'], other_end)
    intersection = max(0., right - left)
    shorter = min(candidate['source_end'] - candidate['source_start'],
                  other_end - other_start)
    ratio = intersection / shorter if shorter > 0 else 0.
    union = ((candidate['source_end'] - candidate['source_start']) +
             (other_end - other_start) - intersection)
    iou = intersection / union if union > 0 else 0.
    return ratio, iou


def evaluate(candidates: list[dict], labels: list[dict], *, top_k: int = 5,
             match_overlap: float = .50, duplicate_overlap: float = .60) -> dict:
    """Compute one-to-one temporal matching and ranking diagnostics."""
    if top_k < 1 or not 0. < match_overlap <= 1.:
        raise ValueError('top_k deve ser positivo e match_overlap deve estar em (0, 1].')
    normalized_labels = []
    for label in labels:
        start, end = _interval(label, 'start', 'end')
        normalized_labels.append({**label, 'start': start, 'end': end})
    ranked = sorted(candidates, key=lambda item: (-float(item['score']),
        float(item['source_start']), float(item['source_end'])))
    top = ranked[:top_k]
    unmatched = set(range(len(normalized_labels)))
    matches = []
    for candidate_index, candidate in enumerate(top):
        choices = []
        for label_index in unmatched:
            ratio, iou = _overlap_ratio(candidate, normalized_labels[label_index])
            if ratio >= match_overlap:
                choices.append((iou, ratio, -label_index, label_index))
        if not choices:
            continue
        _iou, ratio, _tie, label_index = max(choices)
        unmatched.remove(label_index)
        label = normalized_labels[label_index]
        start_error = abs(candidate['source_start'] - label['start'])
        end_error = abs(candidate['source_end'] - label['end'])
        matches.append({'candidate_rank': candidate_index + 1,
            'label_index': label_index, 'overlap_shorter_ratio': round(ratio, 4),
            'start_error_seconds': round(start_error, 4),
            'end_error_seconds': round(end_error, 4),
            'total_boundary_error_seconds': round(start_error + end_error, 4)})

    duplicate_count = 0
    for index, candidate in enumerate(ranked):
        if any(_overlap_ratio(candidate, earlier)[0] >= duplicate_overlap
               for earlier in ranked[:index]):
            duplicate_count += 1
    denominator = min(top_k, len(ranked))
    return {
        'method': 'greedy one-to-one matching by descending score; temporal overlap / shorter interval',
        'candidates': len(ranked), 'labels': len(normalized_labels),
        'top_k': top_k, 'top_candidates_evaluated': denominator,
        'match_overlap_threshold': match_overlap,
        'precision_at_k': (round(len(matches) / denominator, 4) if denominator else None),
        'recall_at_k': (round(len(matches) / len(normalized_labels), 4)
                        if normalized_labels else None),
        'matched_count': len(matches), 'unmatched_label_indices': sorted(unmatched),
        'mean_total_boundary_error_seconds': (
            round(sum(item['total_boundary_error_seconds'] for item in matches) /
                  len(matches), 4) if matches else None),
        'temporal_duplicate_rate': (round(duplicate_count / len(ranked), 4)
                                    if ranked else None),
        'temporal_duplicates': duplicate_count,
        'matches': matches,
        'limitations': [
            'Temporal matching does not judge semantic quality or editorial completeness.',
            'Duplicate rate is temporal only; it does not compare transcript meaning.',
            'Metrics describe these human labels, not viral potential.',
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result', required=True, type=Path,
                        help='JSON de resultado cacheado/exportado pelo Clip Engine.')
    parser.add_argument('--labels', required=True, type=Path,
                        help='JSON local: {"labels":[{"start":12.4,"end":35.0}]} em segundos de origem.')
    parser.add_argument('--top-k', type=int, default=5)
    parser.add_argument('--match-overlap', type=float, default=.50,
                        help='Interseção mínima dividida pelo menor intervalo (0–1].')
    parser.add_argument('--output', type=Path,
                        help='Opcional: salvar o relatório JSON nesta pasta/arquivo local.')
    args = parser.parse_args(argv)
    try:
        result_payload = json.loads(args.result.read_text(encoding='utf-8'))
        labels_payload = json.loads(args.labels.read_text(encoding='utf-8'))
        labels = labels_payload.get('labels')
        if not isinstance(labels, list):
            raise ValueError('O arquivo de rótulos precisa conter "labels": [].')
        report = evaluate(_flatten_candidates(result_payload), labels,
                          top_k=args.top_k, match_overlap=args.match_overlap)
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        print(f'Erro ao avaliar candidatos: {exc}', file=sys.stderr)
        return 2
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding='utf-8')
    else:
        print(serialized, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
