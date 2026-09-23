"""Strict non-secret Reviewer registry used by formal runtime entry points."""

from dataclasses import dataclass
import json
from pathlib import Path
import re

from grokbuddy.domain.model import HubError


_ACTOR_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_AGENT_ID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z"
)
_SERVER_ID = re.compile(r"[0-9]{1,20}\Z")
_CREDENTIAL_REF = re.compile(r"GrokBuddy/[A-Za-z0-9._/-]{1,180}\Z")


def _invalid(message):
    raise HubError("Reviewer registry " + message)


def _read_json(path, description):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise HubError(f"{description} is missing or malformed") from exc


@dataclass(frozen=True)
class ReviewerRegistration:
    actor_id: str
    display_name: str
    enabled: bool
    credential_ref: str
    reviewer_type: str
    agent_id: str
    server_id: str


@dataclass(frozen=True)
class ReviewerRegistry:
    version: int
    active_reviewer_actor_id: str
    reviewers: dict[str, ReviewerRegistration]

    @property
    def active(self):
        return self.reviewers[self.active_reviewer_actor_id]

    @classmethod
    def load(cls, path):
        data = _read_json(path, "Reviewer registry")
        if not isinstance(data, dict) or set(data) != {
                "version", "activeReviewer", "reviewers"}:
            _invalid("must contain only version, activeReviewer and reviewers")
        if data["version"] != 1:
            _invalid("version is unsupported")
        active = data["activeReviewer"]
        raw_reviewers = data["reviewers"]
        if not isinstance(active, str) or not _ACTOR_ID.fullmatch(active):
            _invalid("activeReviewer is missing or invalid")
        if (not isinstance(raw_reviewers, dict) or not raw_reviewers
                or len(raw_reviewers) > 100):
            _invalid("reviewers must be a non-empty bounded object")
        reviewers = {}
        execution_identities = set()
        for actor_id, raw in raw_reviewers.items():
            if not isinstance(actor_id, str) or not _ACTOR_ID.fullmatch(actor_id):
                _invalid("contains an invalid reviewer actor ID")
            if not isinstance(raw, dict) or set(raw) != {
                    "displayName", "enabled", "credentialRef", "connector"}:
                _invalid(f"entry {actor_id} has missing or unknown fields")
            display_name = raw["displayName"]
            enabled = raw["enabled"]
            credential_ref = raw["credentialRef"]
            connector = raw["connector"]
            if (not isinstance(display_name, str) or not display_name.strip()
                    or display_name != display_name.strip() or len(display_name) > 200):
                _invalid(f"entry {actor_id} has an invalid displayName")
            if type(enabled) is not bool:
                _invalid(f"entry {actor_id} enabled must be a boolean")
            if (not isinstance(credential_ref, str)
                    or not _CREDENTIAL_REF.fullmatch(credential_ref)):
                _invalid(f"entry {actor_id} has an invalid credentialRef")
            if not isinstance(connector, dict) or set(connector) != {
                    "type", "agentId", "serverId"}:
                _invalid(f"entry {actor_id} has an invalid connector")
            if connector["type"] != "grok_bot":
                _invalid(f"entry {actor_id} connector type is unsupported")
            agent_id, server_id = connector["agentId"], connector["serverId"]
            if not isinstance(agent_id, str) or not _AGENT_ID.fullmatch(agent_id):
                _invalid(f"entry {actor_id} has an invalid agentId")
            if not isinstance(server_id, str) or not _SERVER_ID.fullmatch(server_id):
                _invalid(f"entry {actor_id} has an invalid serverId")
            identity = (connector["type"], agent_id, server_id)
            if identity in execution_identities:
                _invalid("maps more than one actor to the same execution identity")
            execution_identities.add(identity)
            reviewers[actor_id] = ReviewerRegistration(
                actor_id=actor_id,
                display_name=display_name,
                enabled=enabled,
                credential_ref=credential_ref,
                reviewer_type=connector["type"],
                agent_id=agent_id,
                server_id=server_id,
            )
        if active not in reviewers:
            _invalid("activeReviewer is not registered")
        if not reviewers[active].enabled:
            _invalid("activeReviewer is disabled")
        return cls(version=1, active_reviewer_actor_id=active, reviewers=reviewers)

    def register_with(self, runtime):
        """Ensure stable actors exist through the audited Application path."""
        for reviewer in self.reviewers.values():
            runtime.hub.ensure_registry_reviewer(
                "system",
                reviewer.actor_id,
                reviewer.display_name,
                reviewer.agent_id,
                reviewer.server_id,
            )


def load_service_reviewer_registry(service_config_path):
    """Load the registry referenced by service config and reject legacy drift."""
    service_path = Path(service_config_path).resolve()
    service = _read_json(service_path, "Service config")
    if not isinstance(service, dict):
        raise HubError("Service config must be an object")
    value = service.get("reviewerRegistryPath")
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise HubError("Service config must define reviewerRegistryPath")
    root = service_path.parent.parent.resolve()
    registry_path = (root / value).resolve()
    try:
        registry_path.relative_to(root)
    except ValueError as exc:
        raise HubError("Reviewer registry path must stay inside the repository") from exc
    registry = ReviewerRegistry.load(registry_path)
    legacy_assertion = service.get("reviewerActor")
    if legacy_assertion is not None and legacy_assertion != registry.active_reviewer_actor_id:
        raise HubError("Service reviewerActor conflicts with active Reviewer registry entry")
    return registry, registry_path
