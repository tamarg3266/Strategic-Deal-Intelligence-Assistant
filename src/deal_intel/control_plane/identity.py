import csv
from pathlib import Path

from pydantic import BaseModel

from deal_intel.contracts.schemas import SourceType


class RequesterIdentity(BaseModel):
    requester_id: str
    display_name: str
    role: str
    allowed_account_ids: set[str]
    allowed_source_types: set[SourceType]
    can_view_sensitive_pricing: bool
    can_request_approval: bool
    can_view_restricted_account: bool


class IdentityResolver:
    """Resolves fixture identities. Production replaces this with authenticated claims."""

    def __init__(self, permissions_path: Path) -> None:
        self.permissions_path = permissions_path

    def resolve(self, requester_id: str) -> RequesterIdentity | None:
        with self.permissions_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                if row["user_id"] != requester_id:
                    continue
                return RequesterIdentity(
                    requester_id=requester_id,
                    display_name=row["user_name"],
                    role=row["role"],
                    allowed_account_ids=self._csv_set(row["allowed_account_ids"]),
                    allowed_source_types=self._source_types(row["allowed_source_types"]),
                    can_view_sensitive_pricing=self._bool(row["can_view_sensitive_pricing"]),
                    can_request_approval=self._bool(row["can_request_approval"]),
                    can_view_restricted_account=self._bool(row["can_view_restricted_account"]),
                )
        return None

    @staticmethod
    def _csv_set(value: str) -> set[str]:
        return {part.strip() for part in value.split(",") if part.strip()}

    @classmethod
    def _source_types(cls, value: str) -> set[SourceType]:
        allowed = {"salesforce", "gong", "pricing", "policies", "slack"}
        values = cls._csv_set(value)
        if not values <= allowed:
            raise ValueError("Permission fixture contains an unsupported source type")
        return values  # type: ignore[return-value]

    @staticmethod
    def _bool(value: str) -> bool:
        return value.strip().lower() == "true"
