"""Admin CLI (Typer): create-admin-user, run-connector, seed.

`alembic upgrade head` (via the `migrator` compose service) is the migration
entrypoint, not this file — this only covers operational tasks that don't
belong in a one-shot migration container.
"""

from __future__ import annotations

import json

import typer

from wardline.common.logging import configure_logging, get_logger
from wardline.common.security import generate_api_key, lookup_key_for_index
from wardline.storage.db import sync_session
from wardline.storage.models.governance import ROLE_ADMIN, ApiKey, User

app = typer.Typer()
logger = get_logger(__name__)


@app.command("create-admin-user")
def create_admin_user(email: str) -> None:
    """Create (or reuse) a user with the admin role and mint a fresh API key for them."""
    with sync_session() as db:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            user = User(email=email, role=ROLE_ADMIN)
            db.add(user)
            db.flush()
        plaintext, key_hash = generate_api_key()
        api_key = ApiKey(
            user_id=user.id,
            key_hash=key_hash,
            lookup_hash=lookup_key_for_index(plaintext),
            scopes=["*"],
        )
        db.add(api_key)
        db.flush()
        typer.echo(f"user_id={user.id}")
        typer.echo(f"api_key={plaintext}  (shown once — store it now)")


@app.command("run-connector")
def run_connector(name: str, params_json: str = "{}") -> None:
    """Run a registered connector synchronously and print the resulting job stats."""
    from wardline.connectors.registry import get_connector
    from wardline.ingestion.pipeline import run_connector_job

    configure_logging()
    params = json.loads(params_json)
    connector = get_connector(name)
    stats = run_connector_job(connector, params)
    typer.echo(json.dumps(stats, indent=2))


@app.command("list-connectors")
def list_connectors() -> None:
    from wardline.connectors.registry import list_connectors as _list

    for connector_name in _list():
        typer.echo(connector_name)


@app.command("generate-iceberg-signing-key")
def generate_iceberg_signing_key() -> None:
    """One-time setup for Iceberg export signing (commercialization
    roadmap Phase 2 / Pillar 3.3): generates a fresh ML-DSA-65 keypair.
    The seed is a real secret -- set it as ICEBERG_SIGNING_KEY_SEED (or
    drop it at /run/secrets/iceberg_signing_key_seed) and flip
    iceberg_export_signing_enabled on. The public key isn't secret --
    publish/document it for customers to verify receipts against."""
    from wardline.storage.iceberg_signing import generate_signing_keypair

    seed_b64, public_b64 = generate_signing_keypair()
    typer.echo(f"seed (secret — set as ICEBERG_SIGNING_KEY_SEED): {seed_b64}")
    typer.echo(f"public key (safe to publish): {public_b64}")


if __name__ == "__main__":
    app()
