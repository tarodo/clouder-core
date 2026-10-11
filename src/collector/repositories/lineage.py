"""Raw lineage: source entities and relations, identity map."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ._base import _LOOKUP_CHUNK, RepositoryBase
from .commands import UpsertIdentityCmd, UpsertSourceEntityCmd, UpsertSourceRelationCmd


class LineageMixin(RepositoryBase):
    def upsert_source_entity(
        self, cmd: UpsertSourceEntityCmd, transaction_id: str | None = None
    ) -> None:
        self._data_api.execute(
            """
            INSERT INTO source_entities (
                source, entity_type, external_id, name, normalized_name,
                payload, payload_hash, first_seen_at, last_seen_at, last_run_id
            ) VALUES (
                :source, :entity_type, :external_id, :name, :normalized_name,
                :payload, :payload_hash, :observed_at, :observed_at, :last_run_id
            )
            ON CONFLICT (source, entity_type, external_id) DO UPDATE SET
                name = EXCLUDED.name,
                normalized_name = EXCLUDED.normalized_name,
                payload = EXCLUDED.payload,
                payload_hash = EXCLUDED.payload_hash,
                last_seen_at = EXCLUDED.last_seen_at,
                last_run_id = EXCLUDED.last_run_id
            """,
            {
                "source": cmd.source,
                "entity_type": cmd.entity_type,
                "external_id": cmd.external_id,
                "name": cmd.name,
                "normalized_name": cmd.normalized_name,
                "payload": dict(cmd.payload),
                "payload_hash": cmd.payload_hash,
                "observed_at": cmd.observed_at,
                "last_run_id": cmd.last_run_id,
            },
            transaction_id=transaction_id,
        )

    def batch_upsert_source_entities(
        self,
        commands: list[UpsertSourceEntityCmd],
        transaction_id: str | None = None,
    ) -> None:
        """Upsert source rows; an older observation from another run never
        overwrites a newer one, so replays are order-independent (ADR-0024).
        The same run always re-applies: a replay of the latest data must pick up
        new normalization logic even where rows carry a later processing-time stamp."""
        if not commands:
            return
        self._data_api.batch_execute(
            """
            INSERT INTO source_entities (
                source, entity_type, external_id, name, normalized_name,
                payload, payload_hash, first_seen_at, last_seen_at, last_run_id
            ) VALUES (
                :source, :entity_type, :external_id, :name, :normalized_name,
                :payload, :payload_hash, :observed_at, :observed_at, :last_run_id
            )
            ON CONFLICT (source, entity_type, external_id) DO UPDATE SET
                name = EXCLUDED.name,
                normalized_name = EXCLUDED.normalized_name,
                payload = EXCLUDED.payload,
                payload_hash = EXCLUDED.payload_hash,
                last_seen_at = EXCLUDED.last_seen_at,
                last_run_id = EXCLUDED.last_run_id
            WHERE source_entities.last_run_id = EXCLUDED.last_run_id
               OR source_entities.last_seen_at <= EXCLUDED.last_seen_at
            """,
            [
                {
                    "source": cmd.source,
                    "entity_type": cmd.entity_type,
                    "external_id": cmd.external_id,
                    "name": cmd.name,
                    "normalized_name": cmd.normalized_name,
                    "payload": dict(cmd.payload),
                    "payload_hash": cmd.payload_hash,
                    "observed_at": cmd.observed_at,
                    "last_run_id": cmd.last_run_id,
                }
                for cmd in commands
            ],
            transaction_id=transaction_id,
        )

    def upsert_source_relation(
        self, cmd: UpsertSourceRelationCmd, transaction_id: str | None = None
    ) -> None:
        self._data_api.execute(
            """
            INSERT INTO source_relations (
                source, from_entity_type, from_external_id, relation_type,
                to_entity_type, to_external_id, last_run_id
            ) VALUES (
                :source, :from_entity_type, :from_external_id, :relation_type,
                :to_entity_type, :to_external_id, :last_run_id
            )
            ON CONFLICT (
                source, from_entity_type, from_external_id,
                relation_type, to_entity_type, to_external_id
            ) DO UPDATE SET
                last_run_id = EXCLUDED.last_run_id
            """,
            {
                "source": cmd.source,
                "from_entity_type": cmd.from_entity_type,
                "from_external_id": cmd.from_external_id,
                "relation_type": cmd.relation_type,
                "to_entity_type": cmd.to_entity_type,
                "to_external_id": cmd.to_external_id,
                "last_run_id": cmd.last_run_id,
            },
            transaction_id=transaction_id,
        )

    def batch_upsert_source_relations(
        self,
        commands: list[UpsertSourceRelationCmd],
        transaction_id: str | None = None,
    ) -> None:
        if not commands:
            return
        self._data_api.batch_execute(
            """
            INSERT INTO source_relations (
                source, from_entity_type, from_external_id, relation_type,
                to_entity_type, to_external_id, last_run_id
            ) VALUES (
                :source, :from_entity_type, :from_external_id, :relation_type,
                :to_entity_type, :to_external_id, :last_run_id
            )
            ON CONFLICT (
                source, from_entity_type, from_external_id,
                relation_type, to_entity_type, to_external_id
            ) DO UPDATE SET
                last_run_id = EXCLUDED.last_run_id
            """,
            [
                {
                    "source": cmd.source,
                    "from_entity_type": cmd.from_entity_type,
                    "from_external_id": cmd.from_external_id,
                    "relation_type": cmd.relation_type,
                    "to_entity_type": cmd.to_entity_type,
                    "to_external_id": cmd.to_external_id,
                    "last_run_id": cmd.last_run_id,
                }
                for cmd in commands
            ],
            transaction_id=transaction_id,
        )

    def upsert_identity(self, cmd: UpsertIdentityCmd, transaction_id: str | None = None) -> None:
        self._data_api.execute(
            """
            INSERT INTO identity_map (
                source, entity_type, external_id, clouder_entity_type, clouder_id,
                match_type, confidence, first_seen_at, last_seen_at
            ) VALUES (
                :source, :entity_type, :external_id, :clouder_entity_type, :clouder_id,
                :match_type, :confidence, :observed_at, :observed_at
            )
            ON CONFLICT (source, entity_type, external_id) DO UPDATE SET
                clouder_entity_type = EXCLUDED.clouder_entity_type,
                clouder_id = EXCLUDED.clouder_id,
                match_type = EXCLUDED.match_type,
                confidence = EXCLUDED.confidence,
                last_seen_at = EXCLUDED.last_seen_at
            """,
            {
                "source": cmd.source,
                "entity_type": cmd.entity_type,
                "external_id": cmd.external_id,
                "clouder_entity_type": cmd.clouder_entity_type,
                "clouder_id": cmd.clouder_id,
                "match_type": cmd.match_type,
                "confidence": cmd.confidence,
                "observed_at": cmd.observed_at,
            },
            transaction_id=transaction_id,
        )

    def batch_upsert_identities(
        self,
        commands: list[UpsertIdentityCmd],
        transaction_id: str | None = None,
    ) -> None:
        if not commands:
            return
        self._data_api.batch_execute(
            """
            INSERT INTO identity_map (
                source, entity_type, external_id, clouder_entity_type, clouder_id,
                match_type, confidence, first_seen_at, last_seen_at
            ) VALUES (
                :source, :entity_type, :external_id, :clouder_entity_type, :clouder_id,
                :match_type, :confidence, :observed_at, :observed_at
            )
            ON CONFLICT (source, entity_type, external_id) DO UPDATE SET
                clouder_entity_type = EXCLUDED.clouder_entity_type,
                clouder_id = EXCLUDED.clouder_id,
                match_type = EXCLUDED.match_type,
                confidence = EXCLUDED.confidence,
                last_seen_at = EXCLUDED.last_seen_at
            """,
            [_identity_params(cmd) for cmd in commands],
            transaction_id=transaction_id,
        )

    def find_identities(
        self,
        source: str,
        entity_type: str,
        external_ids: Iterable[str],
        transaction_id: str | None = None,
    ) -> dict[str, str]:
        """external_id -> clouder_id for every id that has an identity.

        The Data API cannot bind arrays (lists go over the wire as JSON), so this
        is an IN list of generated placeholders, chunked to keep each statement
        and response small.
        """
        unique = list(dict.fromkeys(external_ids))
        found: dict[str, str] = {}
        for start in range(0, len(unique), _LOOKUP_CHUNK):
            chunk = unique[start : start + _LOOKUP_CHUNK]
            params: dict[str, Any] = {"source": source, "entity_type": entity_type}
            params.update({f"id{i}": ext for i, ext in enumerate(chunk)})
            placeholders = ", ".join(f":id{i}" for i in range(len(chunk)))
            rows = self._data_api.execute(
                f"""
                SELECT external_id, clouder_id
                FROM identity_map
                WHERE source = :source
                  AND entity_type = :entity_type
                  AND external_id IN ({placeholders})
                """,
                params,
                transaction_id=transaction_id,
            )
            found.update({str(row["external_id"]): str(row["clouder_id"]) for row in rows})
        return found

    def claim_identities(
        self,
        commands: list[UpsertIdentityCmd],
        transaction_id: str | None = None,
    ) -> None:
        """Insert identities that do not exist yet; an existing row always wins.

        Paired with find_identities this is race-safe: if a concurrent run claimed
        the same external id first, this INSERT waits for it, does nothing, and the
        follow-up lookup returns the winner's clouder_id.
        """
        if not commands:
            return
        self._data_api.batch_execute(
            """
            INSERT INTO identity_map (
                source, entity_type, external_id, clouder_entity_type, clouder_id,
                match_type, confidence, first_seen_at, last_seen_at
            ) VALUES (
                :source, :entity_type, :external_id, :clouder_entity_type, :clouder_id,
                :match_type, :confidence, :observed_at, :observed_at
            )
            ON CONFLICT (source, entity_type, external_id) DO NOTHING
            """,
            [_identity_params(cmd) for cmd in commands],
            transaction_id=transaction_id,
        )


def _identity_params(cmd: UpsertIdentityCmd) -> dict[str, Any]:
    return {
        "source": cmd.source,
        "entity_type": cmd.entity_type,
        "external_id": cmd.external_id,
        "clouder_entity_type": cmd.clouder_entity_type,
        "clouder_id": cmd.clouder_id,
        "match_type": cmd.match_type,
        "confidence": cmd.confidence,
        "observed_at": cmd.observed_at,
    }
