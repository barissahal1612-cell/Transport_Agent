"""Yükleme raporu. Hücre değeri, şifre veya kullanıcı verisi İÇERMEZ: yalnızca sayılar ve (sheet, satır, tür)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SkipIssue:
    sheet: str
    row: int  # Excel satır numarası (başlık = 1)
    kind: str
    column: str | None = None


@dataclass
class SheetCounts:
    read: int = 0
    loaded: int = 0
    skipped: int = 0
    deleted: int = 0


@dataclass
class IngestReport:
    applied: bool = False
    load_id: str = ""
    sheets: dict[str, SheetCounts] = field(default_factory=dict)
    skipped: list[SkipIssue] = field(default_factory=list)  # kayıt atlanan sorunlar
    warnings: list[SkipIssue] = field(default_factory=list)  # kayıt yüklenir, tutarsızlık raporlanır

    def counts(self, sheet: str) -> SheetCounts:
        return self.sheets.setdefault(sheet, SheetCounts())

    def skip(self, sheet: str, row: int, kind: str, column: str | None = None) -> None:
        self.counts(sheet).skipped += 1
        self.skipped.append(SkipIssue(sheet, row, kind, column))

    def warn(self, sheet: str, row: int, kind: str, column: str | None = None) -> None:
        self.warnings.append(SkipIssue(sheet, row, kind, column))

    def render(self) -> str:
        mode = "APPLY" if self.applied else "DRY-RUN (AWS çağrısı yapılmadı)"
        lines = [f"Mod: {mode}", f"load_id: {self.load_id}", "",
                 f"{'sheet':<12}{'okunan':>8}{'yüklenen':>10}{'atlanan':>9}{'silinen':>9}"]
        for name, c in self.sheets.items():
            lines.append(f"{name:<12}{c.read:>8}{c.loaded:>10}{c.skipped:>9}{c.deleted:>9}")
        for title, items in (("Atlanan kayıtlar (sheet,satır,tür)", self.skipped),
                             ("Uyarılar / tutarsızlıklar (sheet,satır,tür)", self.warnings)):
            if items:
                lines += ["", title + ":"]
                lines += [f"  {i.sheet},{i.row},{i.kind}" + (f",{i.column}" if i.column else "") for i in items]
        return "\n".join(lines)
