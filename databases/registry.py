"""Vehicle Registry database (vehicle_registry.db) — 5 relational tables.

    manufacturers 1──* vehicle_models *──1 vehicle_categories
                          1
                          │ model_id
                          *
    vehicle_owners 1──* vehicles            (owner_id, nullable for legacy rows)

A SQL VIEW named `vehicle_registry` reproduces the Phase 2 flat table so the SQL
console and older queries keep working.
"""
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import declarative_base, relationship

from databases.common import object_exists, path, row_dict, wanted
from matching import normalize_plate

Base = declarative_base()
SERVICE_KEY = "vehicle_registry"
HUB_TABLE = "vehicles"
LEGACY_TABLE = "vehicle_registry"


class Manufacturer(Base):
    __tablename__ = "manufacturers"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), unique=True, nullable=False, index=True)
    country = Column(String(64), nullable=True)
    models = relationship("VehicleModel", back_populates="manufacturer")


class VehicleCategory(Base):
    __tablename__ = "vehicle_categories"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(32), unique=True, nullable=False, index=True)
    description = Column(String(128), nullable=True)
    models = relationship("VehicleModel", back_populates="category")


class VehicleModel(Base):
    __tablename__ = "vehicle_models"
    __table_args__ = (UniqueConstraint("manufacturer_id", "name", "category_id", name="uq_model_per_maker_category"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    manufacturer_id = Column(Integer, ForeignKey("manufacturers.id", ondelete="RESTRICT"), nullable=False, index=True)
    category_id = Column(Integer, ForeignKey("vehicle_categories.id", ondelete="RESTRICT"), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    fuel_type = Column(String(16), nullable=True)
    manufacturer = relationship("Manufacturer", back_populates="models")
    category = relationship("VehicleCategory", back_populates="models")
    vehicles = relationship("Vehicle", back_populates="model")


class VehicleOwner(Base):
    __tablename__ = "vehicle_owners"
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_code = Column(String(16), unique=True, nullable=False, index=True)
    full_name = Column(String(96), nullable=False, index=True)
    owner_type = Column(String(16), nullable=False, default="INDIVIDUAL")
    city = Column(String(64), nullable=True)
    state = Column(String(32), nullable=True)
    phone_masked = Column(String(16), nullable=True)
    vehicles = relationship("Vehicle", back_populates="owner")


class Vehicle(Base):
    __tablename__ = "vehicles"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    registration_number = Column(String(32), unique=True, index=True, nullable=False)
    model_id = Column(Integer, ForeignKey("vehicle_models.id", ondelete="RESTRICT"), nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("vehicle_owners.id", ondelete="RESTRICT"), nullable=True, index=True)
    colour = Column(String(32), nullable=False)
    registration_date = Column(String(16), nullable=False)
    state = Column(String(32), nullable=False, index=True)
    chassis_number = Column(String(32), unique=True, nullable=True)
    engine_number = Column(String(32), nullable=True)
    model = relationship("VehicleModel", back_populates="vehicles")
    owner = relationship("VehicleOwner", back_populates="vehicles")


# ----------------------------------------------------------------------------
# Flat (Phase 2 compatible) representation
# ----------------------------------------------------------------------------
FLAT_FIELDS = ["registration_number", "make", "model", "colour", "vehicle_type", "registration_date", "state"]


def to_flat(v: Vehicle) -> Dict[str, Any]:
    return {
        "id": v.id,
        "registration_number": v.registration_number,
        "make": v.model.manufacturer.name if v.model else None,
        "model": v.model.name if v.model else None,
        "colour": v.colour,
        "vehicle_type": v.model.category.name if v.model else None,
        "registration_date": v.registration_date,
        "state": v.state,
        "owner_id": v.owner_id,
        "owner_name": v.owner.full_name if v.owner else None,
        "model_id": v.model_id,
        "chassis_number": v.chassis_number,
        "engine_number": v.engine_number,
    }


def get_or_create_model(session, make: str, model: str, vehicle_type: str, fuel_type: Optional[str] = None) -> VehicleModel:
    make, model, vehicle_type = make.strip(), model.strip(), (vehicle_type or "Motor Car").strip()
    maker = session.query(Manufacturer).filter(Manufacturer.name == make).first()
    if not maker:
        maker = Manufacturer(name=make)
        session.add(maker)
        session.flush()
    category = session.query(VehicleCategory).filter(VehicleCategory.name == vehicle_type).first()
    if not category:
        category = VehicleCategory(name=vehicle_type)
        session.add(category)
        session.flush()
    vm = session.query(VehicleModel).filter_by(manufacturer_id=maker.id, name=model, category_id=category.id).first()
    if not vm:
        vm = VehicleModel(manufacturer_id=maker.id, category_id=category.id, name=model, fuel_type=fuel_type)
        session.add(vm)
        session.flush()
    return vm


def next_owner_code(session) -> str:
    count = session.query(VehicleOwner).count()
    code = f"OWN-{count + 1:04d}"
    while session.query(VehicleOwner).filter(VehicleOwner.owner_code == code).first():
        count += 1
        code = f"OWN-{count + 1:04d}"
    return code


def apply_flat_update(session, vehicle: Vehicle, updates: Dict[str, Any]) -> None:
    """Applies Phase 2 style flat field updates, re-resolving normalized FK rows when needed."""
    current = to_flat(vehicle)
    if any(k in updates for k in ("make", "model", "vehicle_type")):
        vm = get_or_create_model(
            session,
            updates.get("make") or current["make"],
            updates.get("model") or current["model"],
            updates.get("vehicle_type") or current["vehicle_type"],
        )
        vehicle.model_id = vm.id
        vehicle.model = vm
    if "registration_number" in updates and updates["registration_number"]:
        vehicle.registration_number = normalize_plate(updates["registration_number"])
    for field in ("colour", "registration_date", "state", "chassis_number", "engine_number"):
        if updates.get(field) is not None:
            setattr(vehicle, field, str(updates[field]).strip())
    if updates.get("owner_id") is not None:
        owner = session.get(VehicleOwner, int(updates["owner_id"]))
        if owner is None:
            raise ValueError(f"vehicle_owners#{updates['owner_id']} does not exist (FK owner_id)")
        vehicle.owner_id = owner.id
    elif updates.get("owner_name"):
        owner = VehicleOwner(owner_code=next_owner_code(session), full_name=str(updates["owner_name"]).strip(),
                             state=vehicle.state)
        session.add(owner)
        session.flush()
        vehicle.owner_id = owner.id


# ----------------------------------------------------------------------------
# Local FK-PK context discovery
# ----------------------------------------------------------------------------
RELATIONS = ["model", "manufacturer", "category", "owner", "owner_vehicles"]


def expand(session, v: Vehicle, include: Optional[List[str]] = None) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    related: Dict[str, Any] = {}
    paths: List[Dict[str, Any]] = []
    vm = v.model
    if vm and wanted(include, "model"):
        related["model"] = row_dict(vm)
        paths.append(path("vehicles", v.id, "model_id", "vehicle_models", vm.id, "model"))
    if vm and wanted(include, "manufacturer"):
        related["manufacturer"] = row_dict(vm.manufacturer)
        paths.append(path("vehicle_models", vm.id, "manufacturer_id", "manufacturers", vm.manufacturer_id, "manufacturer"))
    if vm and wanted(include, "category"):
        related["category"] = row_dict(vm.category)
        paths.append(path("vehicle_models", vm.id, "category_id", "vehicle_categories", vm.category_id, "category"))
    if v.owner and wanted(include, "owner"):
        related["owner"] = row_dict(v.owner)
        paths.append(path("vehicles", v.id, "owner_id", "vehicle_owners", v.owner_id, "owner"))
    if v.owner and wanted(include, "owner_vehicles"):
        others = [o for o in v.owner.vehicles if o.id != v.id]
        related["owner_other_vehicles"] = [to_flat(o) for o in others]
        for o in others:
            paths.append(path("vehicle_owners", v.owner_id, "owner_id", "vehicles", o.id, "owner_vehicles", "reverse"))
    return related, paths


def attribute_search(session, context: Dict[str, Any]) -> List[Vehicle]:
    q = session.query(Vehicle).join(VehicleModel).join(Manufacturer)
    if context.get("make"):
        q = q.filter(Manufacturer.name.ilike(f"%{context['make']}%"))
    if context.get("model"):
        q = q.filter(VehicleModel.name.ilike(f"%{context['model']}%"))
    if context.get("colour"):
        q = q.filter(Vehicle.colour.ilike(f"%{context['colour']}%"))
    if context.get("state"):
        q = q.filter(Vehicle.state.ilike(f"%{context['state']}%"))
    return q.all()


# ----------------------------------------------------------------------------
# Migration from the Phase 2 single-table schema
# ----------------------------------------------------------------------------
FLAT_VIEW_SQL = """
CREATE VIEW IF NOT EXISTS vehicle_registry AS
SELECT v.id, v.registration_number, m.name AS make, vm.name AS model, v.colour,
       c.name AS vehicle_type, v.registration_date, v.state, o.full_name AS owner_name
FROM vehicles v
JOIN vehicle_models vm ON vm.id = v.model_id
JOIN manufacturers m ON m.id = vm.manufacturer_id
JOIN vehicle_categories c ON c.id = vm.category_id
LEFT JOIN vehicle_owners o ON o.id = v.owner_id
"""


def needs_migration(engine) -> bool:
    with engine.connect() as conn:
        return object_exists(conn, LEGACY_TABLE, "table")


def migrate(engine, session_factory) -> Dict[str, Any]:
    """Moves rows from the flat `vehicle_registry` table into the normalized tables,
    preserving each vehicle's id (audit logs and cleansing proposals reference it)."""
    with engine.begin() as conn:
        legacy = conn.execute(text(
            "SELECT id, registration_number, make, model, colour, vehicle_type, registration_date, state "
            "FROM vehicle_registry ORDER BY id")).fetchall()
    Base.metadata.create_all(bind=engine)
    session = session_factory()
    try:
        for row in legacy:
            vm = get_or_create_model(session, row.make, row.model, row.vehicle_type)
            session.add(Vehicle(id=row.id, registration_number=normalize_plate(row.registration_number),
                                model_id=vm.id, colour=row.colour, registration_date=row.registration_date,
                                state=row.state))
        session.commit()
        migrated = session.query(Vehicle).count()
    finally:
        session.close()
    if migrated < len(legacy):
        raise RuntimeError(f"Registry migration verification failed ({migrated} < {len(legacy)})")
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE vehicle_registry"))
    return {"legacy_rows": len(legacy), "migrated_rows": migrated}


def post_create(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(FLAT_VIEW_SQL))
