"""Conservative local limits; not a Cloudflare account-wide billing cap."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3


class R2BudgetExceeded(RuntimeError):
    pass


class OperationBudget:
    def __init__(self, path, class_a=100_000, class_b=1_000_000, dry_run=False, clock=None):
        self.path = Path(path)
        self.limits = {'A': class_a, 'B': class_b}
        self.dry_run = dry_run
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.preview_counts = {'A': 0, 'B': 0}

    def reserve(self, category):
        if category not in self.limits:
            raise ValueError('Categoría R2 desconocida')
        moment = self.clock()
        cutoff = (moment - timedelta(days=32)).date().isoformat()
        day = moment.date().isoformat()
        if self.dry_run:
            total = self._read(category, cutoff) + self.preview_counts[category]
            if total >= self.limits[category]:
                raise R2BudgetExceeded(f'Limite preventiva de operaciones R2 {category} alcanzado; se detiene el bot.')
            self.preview_counts[category] += 1
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with sqlite3.connect(self.path, timeout=15) as connection:
                connection.execute('CREATE TABLE IF NOT EXISTS usage (day TEXT, category TEXT, amount INTEGER NOT NULL, PRIMARY KEY(day,category))')
                connection.execute('BEGIN IMMEDIATE')
                total = connection.execute('SELECT COALESCE(SUM(amount),0) FROM usage WHERE category=? AND day>=?',
                                           (category, cutoff)).fetchone()[0]
                if total >= self.limits[category]:
                    raise R2BudgetExceeded(f'Limite preventiva de operaciones R2 {category} alcanzado; se detiene el bot.')
                connection.execute('INSERT INTO usage VALUES(?,?,1) ON CONFLICT(day,category) DO UPDATE SET amount=amount+1',
                                   (day,category))
        except sqlite3.Error:
            raise R2BudgetExceeded('No se puede leer el contador R2; se bloquean operaciones para proteger el consumo.') from None

    def _read(self, category, cutoff):
        if not self.path.exists():
            return 0
        try:
            with sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro', uri=True) as connection:
                return connection.execute('SELECT COALESCE(SUM(amount),0) FROM usage WHERE category=? AND day>=?',
                                          (category,cutoff)).fetchone()[0]
        except sqlite3.Error:
            raise R2BudgetExceeded('No se puede comprobar el contador R2; revisa data/r2_usage.db.') from None
