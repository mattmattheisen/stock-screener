"""Offline, non-destructive comparison of price exports and independent reference data.

Never modifies a database or infers corporate actions from price jumps.
Reference rows must be provided by an independently validated data provider.
"""
import csv
import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

DB_FIELDS = ('symbol', 'date', 'close', 'adj_close', 'volume')
REF_FIELDS = ('symbol', 'date', 'close', 'adj_close', 'volume', 'source_id')


def _number(value):
    try:
        n = Decimal(str(value).strip())
        return n if n.is_finite() and n > 0 else None
    except (InvalidOperation, ValueError):
        return None


def _integer(value):
    try:
        n = Decimal(str(value).strip())
        if not n.is_finite() or n < 0 or n != n.to_integral_value():
            return None
        return int(n)
    except (InvalidOperation, ValueError):
        return None


def _records(path, fields):
    with Path(path).open(newline='', encoding='utf-8-sig') as file:
        rdr = csv.DictReader(file)
        if rdr.fieldnames is None or not set(fields).issubset(set(rdr.fieldnames)):
            raise ValueError(f'{path}: required columns {fields}')
        rows = {}
        for line, row in enumerate(rdr, start=2):
            symbol = (row.get('symbol') or '').strip().upper()
            raw_date = (row.get('date') or '').strip()
            try:
                date.fromisoformat(raw_date)
            except ValueError as exc:
                raise ValueError(f'{path}:{line}: bad ISO date') from exc
            if None in row:
                raise ValueError(f'{path}:{line}: unexpected extra CSV fields')
            if not symbol:
                raise ValueError(f'{path}:{line}: blank symbol')
            key = (symbol, raw_date)
            if key in rows:
                raise ValueError(f'{path}:{line}: duplicate {key}')
            rows[key] = row
        return rows


def reconcile(db_csv, reference_csv, *, as_of, tolerance=Decimal('0.0001')):
    """Return a review report; never update statements or an automatic backfill.

    Trade-date cutoff alone does not establish point-in-time authenticity.
    """
    cutoff = date.fromisoformat(as_of)
    tolerance = Decimal(str(tolerance))
    if not tolerance.is_finite() or tolerance < 0:
        raise ValueError('tolerance must be finite and nonnegative')
    db = _records(db_csv, DB_FIELDS)
    ref = _records(reference_csv, REF_FIELDS)
    audit = []
    for key in sorted(set(db) | set(ref)):
        symbol, d = key
        if date.fromisoformat(d) > cutoff:
            continue
        a, b = db.get(key), ref.get(key)
        if a is None:
            status = 'MISSING_DB_ROW'
        elif b is None:
            status = 'NO_REFERENCE_EVIDENCE'
        elif not (b.get('source_id') or '').strip():
            status = 'UNATTRIBUTED_REFERENCE'
        else:
            b_raw, b_adj, a_raw, a_adj = (
                _number(b['close']), _number(b['adj_close']),
                _number(a['close']), _number(a['adj_close'])
            )
            a_vol, b_vol = _integer(a['volume']), _integer(b['volume'])
            if b_raw is None or b_adj is None or b_vol is None:
                status = 'INVALID_REFERENCE'
            elif a_raw is None or abs(a_raw - b_raw) > tolerance:
                status = 'RAW_CLOSE_CONFLICT'
            elif a_vol is None or a_vol != b_vol:
                status = 'VOLUME_CONFLICT_REVIEW_SPLITS'
            elif a_adj is None:
                status = 'PROPOSE_ADJ_CLOSE_REVIEW'
            elif abs(a_adj - b_adj) > tolerance:
                status = 'ADJUSTED_CLOSE_CONFLICT'
            else:
                status = 'MATCHED_NUMERICALLY_UNCERTIFIED'
        audit.append(dict(
            symbol=symbol, date=d, status=status,
            db_adj_close='' if a is None else (a.get('adj_close') or ''),
            reference_adj_close='' if b is None else (b.get('adj_close') or ''),
            source_id='' if b is None else (b.get('source_id') or ''),
        ))

    def digest(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    return dict(
        as_of=as_of, db_sha256=digest(db_csv),
        reference_sha256=digest(reference_csv),
        reference_is_independently_certified=False, rows=audit,
    )


def write_report(report, output_path):
    Path(output_path).write_text(
        json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8'
    )


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db-export', required=True)
    parser.add_argument('--reference', required=True)
    parser.add_argument('--as-of', required=True)
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    write_report(reconcile(args.db_export, args.reference, as_of=args.as_of), args.report)
