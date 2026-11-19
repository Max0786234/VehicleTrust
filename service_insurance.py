"""Insurance Records database service (port 8102, insurance_records.db). Runs on machine-2."""
from typing import Optional

from pydantic import BaseModel, Field

import config
from databases import insurance as db
from databases.service_factory import build_service_app
from matching import normalize_plate


class InsuranceCreate(BaseModel):
    policy_number: str = Field(..., min_length=4, max_length=50)
    recorded_vehicle_number: str = Field(..., min_length=4, max_length=20)
    insurer: str = Field(..., min_length=2, max_length=60)
    policy_start_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    expiry_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    policy_status: str = Field("ACTIVE")
    holder_id: Optional[int] = None


class InsuranceUpdate(BaseModel):
    policy_number: Optional[str] = None
    recorded_vehicle_number: Optional[str] = None
    insurer: Optional[str] = None
    policy_start_date: Optional[str] = None
    expiry_date: Optional[str] = None
    policy_status: Optional[str] = None
    holder_id: Optional[int] = None


def create_record(session, data):
    number = data["policy_number"].strip()
    if session.query(db.InsurancePolicy).filter(db.InsurancePolicy.policy_number == number).first():
        raise ValueError(f"Policy number {number} already exists")
    provider = db.get_or_create_provider(session, data["insurer"])
    policy = db.InsurancePolicy(policy_number=number,
                                recorded_vehicle_number=normalize_plate(data["recorded_vehicle_number"]),
                                provider_id=provider.id, policy_start_date=data["policy_start_date"].strip(),
                                expiry_date=data["expiry_date"].strip(),
                                policy_status=data["policy_status"].strip().upper())
    session.add(policy)
    session.flush()
    if data.get("holder_id") is not None:
        db.apply_flat_update(session, policy, {"holder_id": data["holder_id"]})
    return policy


app = build_service_app("insurance_records", "Insurance Records Database Service", InsuranceCreate,
                        InsuranceUpdate, create_record, "recorded_vehicle_number", "Policy")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.service_port("insurance_records"))
