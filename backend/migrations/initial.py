from sqlalchemy import inspect, text
from src.config.database import Base, engine
from src import models


# Columns added after the first demo release; create_all does not alter existing tables.
_ADDED = {
    'datasets': {'mode': "VARCHAR(20) NOT NULL DEFAULT 'manual'",
                 'current_version_id': 'INTEGER NULL',
                 'source_id': 'INTEGER NULL'},
    'jobs': {'dataset_version_id': 'INTEGER NULL'},
    'dataset_versions': {'rebuild_reason': "VARCHAR(1000) NOT NULL DEFAULT ''"},
}


def _add_missing_columns():
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table, columns in _ADDED.items():
            if table not in existing:
                continue
            present = {column['name'] for column in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in present:
                    connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))


def migrate():
    Base.metadata.create_all(engine)
    _add_missing_columns()


if __name__ == '__main__':
    migrate()
