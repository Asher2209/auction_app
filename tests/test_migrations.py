"""The migration chain builds the schema the models describe (so a MySQL database built with `flask db upgrade` works).

The whole chain runs for real on a throwaway SQLite file. The migrations target MySQL, which can ALTER constraints in
place; SQLite cannot, so the two non-batch constraint calls are routed through Alembic's batch mode here.
"""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.extensions import db

VERSIONS = Path(__file__).resolve().parent.parent / "migrations" / "versions"
# left by the abandoned listing-details feature (b15d3tails02): nullable and unused, kept rather than dropped with their data
LEFTOVER_TABLES = {"category_questions", "product_answers"}
LEFTOVER_COLUMNS = {("products", "condition"), ("products", "known_issues"), ("products", "whats_included"), ("products", "pickup_location")}


class _SqliteOp:
    def __init__(self, op):
        self._op = op

    def __getattr__(self, name):
        return getattr(self._op, name)

    def create_foreign_key(self, name, source, referent, local_cols, remote_cols, **kw):
        with self._op.batch_alter_table(source) as b:
            b.create_foreign_key(name, referent, local_cols, remote_cols, **kw)

    def drop_constraint(self, name, table_name, type_=None, **kw):
        with self._op.batch_alter_table(table_name) as b:
            b.drop_constraint(name, type_=type_)


def _chain():
    mods = {}
    for path in VERSIONS.glob("*.py"):
        spec = importlib.util.spec_from_file_location(f"_migration_{path.stem}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mods[mod.revision] = mod
    children = {}
    for mod in mods.values():
        children.setdefault(mod.down_revision, []).append(mod)
    order, cur = [], None
    while cur in children:
        assert len(children[cur]) == 1, f"the chain branches after {cur}"
        order.append(children[cur][0])
        cur = order[-1].revision
    assert len(order) == len(mods), "some migrations are not on the chain"
    return order


@pytest.fixture
def migrated(tmp_path):
    """Run every upgrade(), then the newest downgrade() and upgrade() again; return an engine on the result."""
    engine = sa.create_engine(f"sqlite:///{(tmp_path / 'chain.db').as_posix()}")
    order = _chain()
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn, opts={"render_as_batch": True})
        with Operations.context(ctx):
            from alembic import op
            for mod in order:
                mod.op = _SqliteOp(op)
            for mod in order:
                mod.upgrade()
            order[-1].downgrade()
            order[-1].upgrade()
    yield engine
    engine.dispose()


def test_the_migrated_schema_matches_the_models(app, migrated):
    insp = sa.inspect(migrated)
    problems = []
    assert set(insp.get_table_names()) - {"alembic_version"} == set(db.metadata.tables) | LEFTOVER_TABLES
    for name, table in db.metadata.tables.items():
        cols = {c["name"]: c for c in insp.get_columns(name)}
        problems += [f"{name}.{c} only in the database" for c in set(cols) - set(table.c.keys()) if (name, c) not in LEFTOVER_COLUMNS]
        for c in table.c:
            if c.name not in cols:
                problems.append(f"{name}.{c.name} missing")
            elif not c.primary_key and bool(c.nullable) != bool(cols[c.name]["nullable"]):
                problems.append(f"{name}.{c.name} nullable: model {c.nullable}, database {cols[c.name]['nullable']}")
        have = {tuple(u["column_names"]) for u in insp.get_unique_constraints(name)}
        have |= {tuple(i["column_names"]) for i in insp.get_indexes(name) if i["unique"]}
        want = {(c.name,) for c in table.c if c.unique}
        want |= {tuple(c.name for c in u.columns) for u in table.constraints if isinstance(u, sa.UniqueConstraint)}
        want |= {tuple(c.name for c in i.columns) for i in table.indexes if i.unique}
        problems += [f"{name} unique {u} missing" for u in want - have] + [f"{name} unique {u} only in the database" for u in have - want]
        fks = {(tuple(f["constrained_columns"]), f["referred_table"]) for f in insp.get_foreign_keys(name)}
        problems += [f"{name}.{fk.parent.name} foreign key missing" for fk in table.foreign_keys
                     if ((fk.parent.name,), fk.column.table.name) not in fks]
    assert problems == []


def test_the_migrated_schema_holds_the_rows_the_card_flow_writes(migrated):
    """The cases the old migrated schema refused: an ungraded card, a repeated certificate, a URL-only image."""
    with migrated.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")  # no parent rows here: this test is about NOT NULL and UNIQUE rules
        conn.exec_driver_sql("INSERT INTO collectible_verifications (product_id, collectible_type, grader, certificate_number) VALUES (1, 'trading_card', NULL, NULL)")
        for product in (2, 3):  # the same certificate twice: flagged for review by the app, not refused by the database
            conn.exec_driver_sql(f"INSERT INTO collectible_verifications (product_id, collectible_type, grader, certificate_number) VALUES ({product}, 'trading_card', 'PSA', '99999999')")
        conn.exec_driver_sql("INSERT INTO collectible_cards (id, product_id, card_type_id, card_name, condition, platform_card_id) VALUES (1, 1, 1, 'Charizard', 'Near Mint', 'CARD-000001')")
        conn.exec_driver_sql("INSERT INTO card_images (collectible_card_id, image_type, url) VALUES (1, 'front', 'https://images.example/c.png')")
    with pytest.raises(sa.exc.IntegrityError):  # a platform card ID still identifies exactly one card
        with migrated.begin() as conn:
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            conn.exec_driver_sql("INSERT INTO collectible_cards (product_id, card_type_id, card_name, condition, platform_card_id) VALUES (2, 1, 'Copy', 'Near Mint', 'CARD-000001')")
