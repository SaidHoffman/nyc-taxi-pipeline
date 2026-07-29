"""
Capa TRANSFORM — parte 1: limpieza.

Reglas de negocio acordadas:
  R1. Nulos categóricos (payment, zonas, boroughs) -> imputar "Unknown".
      Motivo: los viajes tienen montos válidos; eliminarlos sesga el ingreso.
  R2. Eliminar duración <= 0 min          (físicamente imposible)
  R3. Eliminar velocidad > 60 mph         (error de medidor)
  R4. Eliminar distance == 0              (decisión: solo viajes operativamente válidos)
  R5. Eliminar passengers == 0            (decisión: solo viajes operativamente válidos)

Principio: ninguna fila se elimina en silencio. Cada regla loggea cuánto quitó.
"""
from pathlib import Path
import pandas as pd

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

CATEGORICAL_COLS = [
    "payment", "pickup_zone", "dropoff_zone", "pickup_borough", "dropoff_borough"
]
MAX_SPEED_MPH = 60


def read_latest_raw() -> pd.DataFrame:
    """Lee el crudo más reciente del landing zone."""
    latest = sorted(RAW_DIR.glob("trips_raw_*.csv"))[-1]
    print(f"Leyendo crudo: {latest.name}")
    return pd.read_csv(latest, parse_dates=["pickup", "dropoff"])


def clean_trips(df: pd.DataFrame) -> pd.DataFrame:
    """Aplica las reglas R1-R5 y loggea el impacto de cada una."""
    df = df.copy()
    audit = []

    # R1: imputar nulos categóricos
    nulls_before = int(df[CATEGORICAL_COLS].isna().sum().sum())
    df[CATEGORICAL_COLS] = df[CATEGORICAL_COLS].fillna("Unknown")
    audit.append(("R1 imputar 'Unknown' (celdas)", nulls_before))

    # Columnas derivadas que necesitamos para las reglas y el análisis
    df["duration_min"] = (df["dropoff"] - df["pickup"]).dt.total_seconds() / 60
    df["speed_mph"] = df["distance"] / (df["duration_min"] / 60)

    # R2: duración imposible
    mask = df["duration_min"] <= 0
    audit.append(("R2 duración <= 0 (filas)", int(mask.sum())))
    df = df[~mask]

    # R3: velocidad imposible
    mask = df["speed_mph"] > MAX_SPEED_MPH
    audit.append((f"R3 velocidad > {MAX_SPEED_MPH} mph (filas)", int(mask.sum())))
    df = df[~mask]

    # R4: distancia cero
    mask = df["distance"] == 0
    audit.append(("R4 distance == 0 (filas)", int(mask.sum())))
    df = df[~mask]

    # R5: cero pasajeros
    mask = df["passengers"] == 0
    audit.append(("R5 passengers == 0 (filas)", int(mask.sum())))
    df = df[~mask]

    print("\n--- Auditoría de limpieza ---")
    for regla, n in audit:
        print(f"  {regla:<38} {n:>5}")
    print(f"  {'Filas finales':<38} {len(df):>5}")

    return df.reset_index(drop=True)


def build_dim_zone(df: pd.DataFrame) -> pd.DataFrame:
    """
    Dimensión de rol: UNA sola tabla de zonas para origen y destino.
    Unimos ambas fuentes, deduplicamos, y asignamos llave sustituta.
    """
    pickup = df[["pickup_zone", "pickup_borough"]].rename(
        columns={"pickup_zone": "zone", "pickup_borough": "borough"}
    )
    dropoff = df[["dropoff_zone", "dropoff_borough"]].rename(
        columns={"dropoff_zone": "zone", "dropoff_borough": "borough"}
    )
    dim = (
        pd.concat([pickup, dropoff], ignore_index=True)
        .drop_duplicates(subset=["zone"])
        .sort_values("zone")
        .reset_index(drop=True)
    )
    dim.insert(0, "zone_id", dim.index + 1)  # llave sustituta 1..N
    return dim


def build_simple_dim(df: pd.DataFrame, col: str, id_name: str) -> pd.DataFrame:
    """Dimensión genérica de una columna: valores únicos + llave sustituta."""
    dim = (
        df[[col]].drop_duplicates().sort_values(col).reset_index(drop=True)
    )
    dim.insert(0, id_name, dim.index + 1)
    return dim


def build_fact(
    df: pd.DataFrame,
    dim_zone: pd.DataFrame,
    dim_payment: pd.DataFrame,
    dim_taxi: pd.DataFrame,
) -> pd.DataFrame:
    """
    Tabla de hechos: solo llaves foráneas + métricas.
    Nota: pickup_zone_id y dropoff_zone_id apuntan a la MISMA Dim_Zone.
    """
    zone_map = dict(zip(dim_zone["zone"], dim_zone["zone_id"]))
    pay_map = dict(zip(dim_payment["payment"], dim_payment["payment_id"]))
    taxi_map = dict(zip(dim_taxi["color"], dim_taxi["taxi_type_id"]))

    fact = pd.DataFrame({
        "trip_id": range(1, len(df) + 1),
        "pickup_ts": df["pickup"],
        "dropoff_ts": df["dropoff"],
        "pickup_zone_id": df["pickup_zone"].map(zone_map),
        "dropoff_zone_id": df["dropoff_zone"].map(zone_map),
        "payment_id": df["payment"].map(pay_map),
        "taxi_type_id": df["color"].map(taxi_map),
        "passengers": df["passengers"],
        "distance": df["distance"],
        "fare": df["fare"],
        "tip": df["tip"],
        "tolls": df["tolls"],
        "total": df["total"],
        "duration_min": df["duration_min"].round(2),
        "speed_mph": df["speed_mph"].round(2),
    })

    # Validación de integridad referencial: ninguna llave puede quedar nula
    fk_cols = ["pickup_zone_id", "dropoff_zone_id", "payment_id", "taxi_type_id"]
    orphans = int(fact[fk_cols].isna().sum().sum())
    assert orphans == 0, f"¡{orphans} llaves foráneas sin match! Revisa las dimensiones."

    return fact


def build_star_schema(df_clean: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Orquesta la construcción del esquema estrella completo."""
    dim_zone = build_dim_zone(df_clean)
    dim_payment = build_simple_dim(df_clean, "payment", "payment_id")
    dim_taxi = build_simple_dim(df_clean, "color", "taxi_type_id")
    fact = build_fact(df_clean, dim_zone, dim_payment, dim_taxi)

    tables = {
        "dim_zone": dim_zone,
        "dim_payment": dim_payment,
        "dim_taxi_type": dim_taxi,
        "fact_trips": fact,
    }
    print("\n--- Esquema estrella ---")
    for name, t in tables.items():
        print(f"  {name:<15} {len(t):>5} filas x {len(t.columns)} cols")
    return tables


if __name__ == "__main__":
    raw = read_latest_raw()
    print(f"Filas crudas: {len(raw)}")
    clean = clean_trips(raw)
    tables = build_star_schema(clean)
    print("\nMuestra de dim_zone:")
    print(tables["dim_zone"].head(3).to_string(index=False))
    print("\nMuestra de fact_trips:")
    print(tables["fact_trips"].head(3).to_string(index=False))