"""
Capa LOAD.

Materializa el esquema estrella en SQLite (data/warehouse/nyc_taxi.db).

Decisiones:
  - DDL explícito: llaves primarias y foráneas declaradas en la base,
    no solo validadas en Python (defensa en profundidad).
  - Idempotente: DROP + CREATE en cada corrida (full refresh).
  - Timestamps en TEXT ISO-8601, el estándar de SQLite.
"""
from pathlib import Path
import sqlite3
import pandas as pd

WAREHOUSE_DIR = Path(__file__).resolve().parent.parent / "data" / "warehouse"
DB_PATH = WAREHOUSE_DIR / "nyc_taxi.db"

DDL = """
DROP TABLE IF EXISTS fact_trips;
DROP TABLE IF EXISTS dim_zone;
DROP TABLE IF EXISTS dim_payment;
DROP TABLE IF EXISTS dim_taxi_type;

CREATE TABLE dim_zone (
    zone_id     INTEGER PRIMARY KEY,
    zone        TEXT NOT NULL UNIQUE,
    borough     TEXT NOT NULL
);

CREATE TABLE dim_payment (
    payment_id  INTEGER PRIMARY KEY,
    payment     TEXT NOT NULL UNIQUE
);

CREATE TABLE dim_taxi_type (
    taxi_type_id INTEGER PRIMARY KEY,
    color        TEXT NOT NULL UNIQUE
);

CREATE TABLE fact_trips (
    trip_id          INTEGER PRIMARY KEY,
    pickup_ts        TEXT NOT NULL,
    dropoff_ts       TEXT NOT NULL,
    pickup_zone_id   INTEGER NOT NULL REFERENCES dim_zone(zone_id),
    dropoff_zone_id  INTEGER NOT NULL REFERENCES dim_zone(zone_id),
    payment_id       INTEGER NOT NULL REFERENCES dim_payment(payment_id),
    taxi_type_id     INTEGER NOT NULL REFERENCES dim_taxi_type(taxi_type_id),
    passengers       INTEGER NOT NULL,
    distance         REAL NOT NULL,
    fare             REAL NOT NULL,
    tip              REAL NOT NULL,
    tolls            REAL NOT NULL,
    total            REAL NOT NULL,
    duration_min     REAL NOT NULL,
    speed_mph        REAL NOT NULL
);
"""

# Orden de carga: dimensiones primero, fact al final (las FK lo exigen)
LOAD_ORDER = ["dim_zone", "dim_payment", "dim_taxi_type", "fact_trips"]


def load_star_schema(tables: dict[str, pd.DataFrame]) -> Path:
    """Crea el warehouse y carga las tablas respetando las FK."""
    WAREHOUSE_DIR.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")  # SQLite las trae apagadas por default
        conn.executescript(DDL)

        for name in LOAD_ORDER:
            df = tables[name].copy()
            # Timestamps a TEXT ISO-8601
            for col in df.select_dtypes(include=["datetime"]):
                df[col] = df[col].dt.strftime("%Y-%m-%d %H:%M:%S")
            df.to_sql(name, conn, if_exists="append", index=False)
            n = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            print(f"  {name:<15} {n:>5} filas cargadas")

        # Verificación final de integridad desde la base misma
        orphans = conn.execute("""
            SELECT COUNT(*) FROM fact_trips f
            LEFT JOIN dim_zone zp ON f.pickup_zone_id  = zp.zone_id
            LEFT JOIN dim_zone zd ON f.dropoff_zone_id = zd.zone_id
            WHERE zp.zone_id IS NULL OR zd.zone_id IS NULL
        """).fetchone()[0]
        print(f"\n  Verificación FK zonas (huérfanos): {orphans}")

    return DB_PATH


if __name__ == "__main__":
    # Orquestación mínima: reutilizamos las capas anteriores
    from transform import read_latest_raw, clean_trips, build_star_schema

    raw = read_latest_raw()
    clean = clean_trips(raw)
    tables = build_star_schema(clean)

    print("\n--- Cargando a SQLite ---")
    db = load_star_schema(tables)
    print(f"\nWarehouse listo: {db}")
