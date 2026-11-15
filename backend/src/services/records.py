"""Shared validation for business day samples."""
import math
from fastapi import HTTPException

from src.services.business import metadata


def validate(records):
    """Validate required fields and coerce numeric columns. Mutates and returns the list."""
    columns = metadata()['columns']
    for index, row in enumerate(records):
        for column in columns:
            value = row.get(column['key'])
            if value is None or value == '':
                raise HTTPException(422, f'第 {index+1} 行缺少字段 {column["label"]}')
            if column['type'] == 'number':
                try:
                    if isinstance(value, bool) or not math.isfinite(float(value)):
                        raise ValueError()
                    row[column['key']] = float(value)
                except (TypeError, ValueError, OverflowError):
                    raise HTTPException(422, f'第 {index+1} 行 {column["label"]} 必须为有限数值')
    return records


def business(records):
    """Strip sync bookkeeping fields and sort by business day."""
    columns = [c['key'] for c in metadata()['columns']]
    clean = [{key: row[key] for key in columns if key in row} for row in records]
    clean.sort(key=lambda row: str(row.get('day', '')))
    return clean
