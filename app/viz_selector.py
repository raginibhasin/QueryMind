"""
Visualization Selector.

Deliberately rule-based rather than another LLM call: it's faster, free,
deterministic (same result shape always gets the same chart), and easy to
justify in a report/viva. The rules look only at the SHAPE of the result
set (column count, data types, cardinality) -- never its meaning.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any


@dataclass
class VizChoice:
    chart_type: str  # 'metric' | 'bar' | 'line' | 'pie' | 'table'
    config: Dict[str, Any] = field(default_factory=dict)


DATE_HINTS = ("date", "year", "month", "day", "time", "created_at", "quarter")


def _is_numeric(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def choose_visualization(columns: List[str], rows: List[Dict[str, Any]]) -> VizChoice:
    if not rows or not columns:
        return VizChoice("table")

    # Single row, single column -> a headline number, not a chart.
    if len(rows) == 1 and len(columns) == 1:
        return VizChoice("metric", {"label": columns[0], "value": rows[0][columns[0]]})

    numeric_cols = [c for c in columns if all(_is_numeric(r.get(c)) for r in rows)]
    non_numeric_cols = [c for c in columns if c not in numeric_cols]

    # Exactly one categorical/date column + one numeric column is the
    # classic "group by" shape.
    if len(non_numeric_cols) == 1 and len(numeric_cols) == 1:
        category_col = non_numeric_cols[0]
        value_col = numeric_cols[0]
        distinct_categories = len({r.get(category_col) for r in rows})

        looks_like_date = any(hint in category_col.lower() for hint in DATE_HINTS)
        if looks_like_date and len(rows) > 2:
            return VizChoice("line", {"x_key": category_col, "y_key": value_col})

        if distinct_categories <= 8:
            return VizChoice("pie", {"label_key": category_col, "value_key": value_col})

        return VizChoice("bar", {"x_key": category_col, "y_key": value_col})

    # Two numeric columns + a small number of rows: still readable as a bar chart.
    if len(non_numeric_cols) == 1 and len(numeric_cols) >= 2 and len(rows) <= 20:
        return VizChoice(
            "bar",
            {"x_key": non_numeric_cols[0], "y_keys": numeric_cols},
        )

    # Everything else (wide results, many columns, free-form SELECTs): a table.
    return VizChoice("table")
