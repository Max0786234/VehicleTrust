"""Vehicle Registry database service (port 8101, vehicle_registry.db). Runs on machine-2."""
from typing import Optional

from pydantic import BaseModel, Field

import config
from databases import registry as db
from databases.service_factory import build_service_app
from matching import normalize_plate


class VehicleRegistryCreate(BaseModel):
    registration_number: str = Field(..., min_length=4, max_length=20)
    make: str = Field(..., min_length=2, max_length=50)
    model: str = Field(..., min_length=1, max_length=50)
    colour: str = Field(..., min_length=2, max_length=30)
    vehicle_type: str = Field("Motor Car", min_length=2, max_length=30)
    registration_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    state: str = Field(..., min_length=2, max_length=30)
    owner_id: Optional[int] = None
    owner_name: Optional[str] = Field(None, max_length=96)


class VehicleRegistryUpdate(BaseModel):
    registration_number: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    colour: Optional[str] = None
    vehicle_type: Optional[str] = None
    registration_date: Optional[str] = None
    state: Optional[str] = None
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None


def create_record(session, data):
    norm = normalize_plate(data["registration_number"])
    if session.query(db.Vehicle).filter(db.Vehicle.registration_number == norm).first():
        raise ValueError(f"Registration {norm} already exists")
    vm = db.get_or_create_model(session, data["make"], data["model"], data["vehicle_type"])
    vehicle = db.Vehicle(registration_number=norm, model_id=vm.id, colour=data["colour"].strip(),
                         registration_date=data["registration_date"].strip(), state=data["state"].strip())
    session.add(vehicle)
    session.flush()
    db.apply_flat_update(session, vehicle, {k: data[k] for k in ("owner_id", "owner_name") if data.get(k) is not None})
    return vehicle


app = build_service_app("vehicle_registry", "Vehicle Registry Database Service", VehicleRegistryCreate,
                        VehicleRegistryUpdate, create_record, "registration_number", "Record")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.service_port("vehicle_registry"))
