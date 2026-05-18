"""extend connection_type allow-list with selects/routes-to/consumed-by (#92)

Companion to migration 0022 (#91) which added the K8s runtime Part
subtypes (deployment, statefulset, service, ingress, secret,
configmap, job). This migration extends the `connection_type`
enum on both `contracts` and `contract_subtype_proposals` so the
K8s runtime parts can be wired together with the right edge
labels:

  - selects:      service     -> deployment | statefulset
  - routes-to:    ingress     -> service
  - consumed-by:  secret      -> deployment | statefulset | job
                  configmap   -> deployment | statefulset | job

The router-side `CONNECTION_RULES` table is updated in the same
PR; the DB-level CHECK here only enforces enum membership. Note
that `runs` already exists in the enum (added in #62) and gets
reused for the deployment/statefulset → container edge — no DDL
change for that.

Revision ID: 0023
Revises: 0022
Create Date: 2026-05-18
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_CONNECTION_TYPES = (
    "'builds-from', 'instantiates', 'runs', "
    "'member-of', 'depends-on', 'submodule', 'serves-static'"
)
_NEW_CONNECTION_TYPES = (
    "'builds-from', 'instantiates', 'runs', "
    "'member-of', 'depends-on', 'submodule', 'serves-static', "
    "'selects', 'routes-to', 'consumed-by'"
)


def upgrade() -> None:
    # The contracts.connection_type CHECK is at the clean
    # single-prefix `ck_contracts_connection_type_allowed` name —
    # migrations 0010 and 0017 both used `op.create_check_constraint`
    # with a short constraint name so the convention prefixed only
    # once. Same story for `contract_subtype_proposals` after 0017
    # cleaned up that table's name in the equivalent constraint move.
    op.execute(
        "ALTER TABLE contracts DROP CONSTRAINT ck_contracts_connection_type_allowed"
    )
    op.create_check_constraint(
        "connection_type_allowed",
        "contracts",
        f"connection_type IS NULL OR connection_type IN ({_NEW_CONNECTION_TYPES})",
    )

    op.execute(
        "ALTER TABLE contract_subtype_proposals "
        "DROP CONSTRAINT ck_contract_subtype_proposals_connection_type_allowed"
    )
    op.create_check_constraint(
        "connection_type_allowed",
        "contract_subtype_proposals",
        f"new_connection_type IS NULL OR new_connection_type IN ({_NEW_CONNECTION_TYPES})",
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE contract_subtype_proposals "
        "DROP CONSTRAINT ck_contract_subtype_proposals_connection_type_allowed"
    )
    op.create_check_constraint(
        "connection_type_allowed",
        "contract_subtype_proposals",
        f"new_connection_type IS NULL OR new_connection_type IN ({_OLD_CONNECTION_TYPES})",
    )

    op.execute(
        "ALTER TABLE contracts DROP CONSTRAINT ck_contracts_connection_type_allowed"
    )
    op.create_check_constraint(
        "connection_type_allowed",
        "contracts",
        f"connection_type IS NULL OR connection_type IN ({_OLD_CONNECTION_TYPES})",
    )
