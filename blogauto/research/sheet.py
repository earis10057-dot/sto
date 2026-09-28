"""엑셀(xlsx) 스프레드시트에 행을 누적 저장한다."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill


def _open(path: Path):
    if path.exists():
        return load_workbook(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    wb.remove(wb.active)
    return wb


def _sheet(wb, name: str, header: list[str]):
    if name in wb.sheetnames:
        return wb[name]
    ws = wb.create_sheet(name)
    ws.append(header)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="2F4B7C")
    ws.freeze_panes = "A2"
    for i, h in enumerate(header, start=1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = max(10, len(h) * 2 + 4)
    return ws


def upsert_rows(
    path: Path,
    sheet: str,
    header: list[str],
    rows: Iterable[list[Any]],
    replace_if: Callable[[list[Any]], bool] | None = None,
) -> int:
    """rows 를 시트 끝에 추가한다.

    replace_if 가 주어지면, 기존 행 중 조건에 맞는 행을 먼저 지운다
    (같은 날 두 번 실행해도 데이터가 중복되지 않게 하기 위함).
    """
    wb = _open(path)
    ws = _sheet(wb, sheet, header)
    rows = list(rows)
    if replace_if is not None:
        kept = [list(r) for r in ws.iter_rows(min_row=2, values_only=True) if not replace_if(list(r))]
        ws.delete_rows(2, ws.max_row)
        for r in kept:
            ws.append(r)
    for r in rows:
        ws.append(r)
    wb.save(path)
    return len(rows)


def replace_sheet(path: Path, sheet: str, header: list[str], rows: Iterable[list[Any]]) -> None:
    wb = _open(path)
    if sheet in wb.sheetnames:
        del wb[sheet]
    ws = _sheet(wb, sheet, header)
    for r in rows:
        ws.append(r)
    wb.save(path)


def read_rows(path: Path, sheet: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    wb = load_workbook(path, read_only=True)
    if sheet not in wb.sheetnames:
        return []
    it = wb[sheet].iter_rows(values_only=True)
    header = next(it, None) or []
    return [dict(zip(header, r)) for r in it]
