"""
Capa EXTRACT.

Responsabilidad única: obtener los datos crudos y aterrizarlos en
data/raw/, sin limpiar ni transformar nada. Esa disciplina es la que
te salva cuando el negocio cambia de opinión sobre cómo limpiar algo:
siempre puedes re-transformar desde el crudo, sin volver a "extraer".

Fuente real: NYC Taxi & Limousine Commission (TLC), trip records feb-mar 2019.
"""
from pathlib import Path
from datetime import datetime, timezone
import seaborn as sns
import pandas as pd

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def extract_raw_trips() -> pd.DataFrame:
    """Obtiene los datos crudos de viajes de taxi (sin transformar)."""
    df = sns.load_dataset("taxis")
    return df


def land_raw_data(df: pd.DataFrame) -> Path:
    """Aterriza el crudo en data/raw/ con timestamp, como un landing zone real."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RAW_DIR / f"trips_raw_{ts}.csv"
    df.to_csv(out_path, index=False)
    return out_path


if __name__ == "__main__":
    df_raw = extract_raw_trips()
    print(f"Filas extraídas: {len(df_raw)}")
    print(f"Columnas: {list(df_raw.columns)}")
    path = land_raw_data(df_raw)
    print(f"Aterrizado en: {path}")