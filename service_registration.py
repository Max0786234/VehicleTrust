"""Registration Authority (RTO) database service (port 8103, registration_authority.db). Runs on machine-2."""
from typing import Optional

from pydantic import BaseModel, Field

import config
from databases import registration as db
from databases.service_factory import build_service_app
from matching import normalize_plate


class RegistrationAuthorityCreate(BaseModel):
    plate_identifier: str = Field(..., min_length=4, max_length=20)
    make: str = Field(..., min_length=2, max_length=50)
    model: str = Field(..., min_length=1, max_length=50)
    colour: str = Field(..., min_length=2, max_length=30)
    registration_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    state: str = Field(..., min_length=2, max_length=30)
    authority_reference: str = Field(..., min_length=3, max_length=50)


class RegistrationAuthorityUpdate(BaseModel):
    plate_identifier: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    colour: Optional[str] = None
    registration_date: Optional[str] = None
    state: Optional[str] = None
    authority_reference: Optional[str] = None
    office_id: Optional[int] = None


def create_record(session, data):
    norm = normalize_plate(data["plate_identifier"])
    if session.query(db.RTORegistration).filter(db.RTORegistration.plate_identifier == norm).first():
        raise ValueError(f"Plate identifier {norm} already exists")
    office = db.get_or_create_office(session, norm, data["state"])
    reg = db.RTORegistration(plate_identifier=norm, office_id=office.id, make=data["make"].strip(),
                             model=data["model"].strip(), colour=data["colour"].strip(),
                             registration_date=data["registration_date"].strip(), state=data["state"].strip(),
                             authority_reference=data["authority_reference"].strip())
    session.add(reg)
    return reg


app = build_service_app("registration_authority", "Registration Authority Database Service",
                        RegistrationAuthorityCreate, RegistrationAuthorityUpdate, create_record,
                        "plate_identifier", "Record")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.service_port("registration_authority"))
