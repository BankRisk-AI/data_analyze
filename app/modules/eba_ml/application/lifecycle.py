from __future__ import annotations

from app.core.exceptions import InvalidParameter
from app.modules.eba_ml.domain.exceptions import ProtectedModelError


def can_delete(model: dict, confirmation: str) -> None:
    if model.get("protected") or model.get("status") == "champion":
        raise ProtectedModelError("protected and champion models cannot be deleted")
    if confirmation != model.get("name"):
        raise InvalidParameter("exact model name confirmation is required")


def delete_sql(model_id: int) -> str:
    return "DELETE FROM ml_model WHERE model_id = %s"


def hard_delete(conn, model_id: int, confirmation: str, artifact_store) -> None:
    with conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT name, status, protected, artifact_sha256
                           FROM ml_model WHERE model_id=%s FOR UPDATE""", (model_id,))
            model = cur.fetchone()
            if model is None:
                raise ValueError("model does not exist")
            name, status, protected, sha = model
            can_delete(
                {"name": name, "status": status, "protected": protected},
                confirmation)
            cur.execute("DELETE FROM ml_model WHERE model_id=%s", (model_id,))
            cur.execute("""INSERT INTO audit_log (action, entity, entity_id, detail)
                           VALUES ('delete','ml_model',%s,%s)""",
                        (str(model_id), '{"hard_delete":true}'))
            cur.execute("SELECT 1 FROM ml_model WHERE artifact_sha256=%s LIMIT 1", (sha,))
            still_referenced = cur.fetchone() is not None
    if not still_referenced:
        artifact_store.remove(sha)
