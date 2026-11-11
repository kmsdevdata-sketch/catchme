"""Create tables and declared indexes once before the workers start.
Demo only — real projects use Alembic migrations."""
from . import models  # noqa: F401  (register models)
from .db import Base, engine

if __name__ == "__main__":
    Base.metadata.create_all(engine)
    for table in Base.metadata.sorted_tables:  # create_all skips indexes of existing tables
        for index in table.indexes:
            index.create(engine, checkfirst=True)
