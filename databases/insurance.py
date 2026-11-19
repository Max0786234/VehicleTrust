"""Insurance Records database (insurance_records.db) — 5 relational tables.

    insurance_providers 1──* insurance_policies *──1 policy_holders
                                   1
                     ┌─────────────┴─────────────┐
                     *                           *
             coverage_details             insurance_claims

`recorded_vehicle_number` is the cross-database identifier (no FK can span DB files).
"""
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import declarative_base, relationship

from databases.common import object_exists, path, row_dict, table_columns, wanted
from matching import normalize_plate

Base = declarative_base()
SERVICE_KEY = "insurance_records"
HUB_TABLE = "insurance_policies"


class InsuranceProvider(Base):
    __tablename__ = "insurance_providers"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(96), unique=True, nullable=False, index=True)
    irdai_code = Column(String(16), nullable=True)
    claims_helpline = Column(String(24), nullable=True)
    policies = relationship("InsurancePolicy", back_populates="provider")


class PolicyHolder(Base):
    __tablename__ = "policy_holders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    holder_code = Column(String(16), unique=True, nullable=False, index=True)
    full_name = Column(String(96), nullable=False, index=True)
    city = Column(String(64), nullable=True)
    kyc_status = Column(String(16), nullable=False, default="VERIFIED")
    policies = relationship("InsurancePolicy", back_populates="holder")


class InsurancePolicy(Base):
    __tablename__ = "insurance_policies"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    policy_number = Column(String(64), unique=True, index=True, nullable=False)
    recorded_vehicle_number = Column(String(32), index=True, nullable=False)
    provider_id = Column(Integer, ForeignKey("insurance_providers.id", ondelete="RESTRICT"), nullable=False, index=True)
    holder_id = Column(Integer, ForeignKey("policy_holders.id", ondelete="RESTRICT"), nullable=True, index=True)
    policy_start_date = Column(String(16), nullable=False)
    expiry_date = Column(String(16), nullable=False)
    policy_status = Column(String(32), nullable=False, index=True)
    provider = relationship("InsuranceProvider", back_populates="policies")
    holder = relationship("PolicyHolder", back_populates="policies")
    coverages = relationship("CoverageDetail", back_populates="policy", cascade="all, delete-orphan")
    claims = relationship("InsuranceClaim", back_populates="policy", cascade="all, delete-orphan")


class CoverageDetail(Base):
    __tablename__ = "coverage_details"
    id = Column(Integer, primary_key=True, autoincrement=True)
    policy_id = Column(Integer, ForeignKey("insurance_policies.id", ondelete="CASCADE"), nullable=False, index=True)
    coverage_type = Column(String(48), nullable=False)
    sum_insured = Column(Float, nullable=True)
    premium = Column(Float, nullable=True)
    deductible = Column(Float, nullable=True)
    policy = relationship("InsurancePolicy", back_populates="coverages")


class InsuranceClaim(Base):
    __tablename__ = "insurance_claims"
    id = Column(Integer, primary_key=True, autoincrement=True)
    policy_id = Column(Integer, ForeignKey("insurance_policies.id", ondelete="CASCADE"), nullable=False, index=True)
    claim_number = Column(String(32), unique=True, nullable=False, index=True)
    claim_date = Column(String(16), nullable=False)
    claim_type = Column(String(32), nullable=False)
    claim_amount = Column(Float, nullable=True)
    claim_status = Column(String(24), nullable=False)
    description = Column(Text, nullable=True)
    policy = relationship("InsurancePolicy", back_populates="claims")


FLAT_FIELDS = ["policy_number", "recorded_vehicle_number", "insurer", "policy_start_date", "expiry_date", "policy_status"]


def to_flat(p: InsurancePolicy) -> Dict[str, Any]:
    return {
        "id": p.id,
        "policy_number": p.policy_number,
        "recorded_vehicle_number": p.recorded_vehicle_number,
        "insurer": p.provider.name if p.provider else None,
        "policy_start_date": p.policy_start_date,
        "expiry_date": p.expiry_date,
        "policy_status": p.policy_status,
        "provider_id": p.provider_id,
        "holder_id": p.holder_id,
        "holder_name": p.holder.full_name if p.holder else None,
    }


def get_or_create_provider(session, name: str) -> InsuranceProvider:
    name = name.strip()
    provider = session.query(InsuranceProvider).filter(InsuranceProvider.name == name).first()
    if not provider:
        provider = InsuranceProvider(name=name)
        session.add(provider)
        session.flush()
    return provider


def apply_flat_update(session, policy: InsurancePolicy, updates: Dict[str, Any]) -> None:
    if updates.get("insurer"):
        policy.provider_id = get_or_create_provider(session, updates["insurer"]).id
    if updates.get("recorded_vehicle_number"):
        policy.recorded_vehicle_number = normalize_plate(updates["recorded_vehicle_number"])
    for field in ("policy_number", "policy_start_date", "expiry_date"):
        if updates.get(field) is not None:
            setattr(policy, field, str(updates[field]).strip())
    if updates.get("policy_status"):
        policy.policy_status = str(updates["policy_status"]).strip().upper()
    if updates.get("holder_id") is not None:
        if session.get(PolicyHolder, int(updates["holder_id"])) is None:
            raise ValueError(f"policy_holders#{updates['holder_id']} does not exist (FK holder_id)")
        policy.holder_id = int(updates["holder_id"])


RELATIONS = ["provider", "holder", "coverage", "claims"]


def expand(session, p: InsurancePolicy, include: Optional[List[str]] = None) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    related: Dict[str, Any] = {}
    paths: List[Dict[str, Any]] = []
    if p.provider and wanted(include, "provider"):
        related["provider"] = row_dict(p.provider)
        paths.append(path("insurance_policies", p.id, "provider_id", "insurance_providers", p.provider_id, "provider"))
    if p.holder and wanted(include, "holder"):
        related["holder"] = row_dict(p.holder)
        paths.append(path("insurance_policies", p.id, "holder_id", "policy_holders", p.holder_id, "holder"))
    if wanted(include, "coverage"):
        related["coverage"] = [row_dict(c) for c in p.coverages]
        for c in p.coverages:
            paths.append(path("insurance_policies", p.id, "policy_id", "coverage_details", c.id, "coverage", "reverse"))
    if wanted(include, "claims"):
        related["claims"] = [row_dict(c) for c in p.claims]
        for c in p.claims:
            paths.append(path("insurance_policies", p.id, "policy_id", "insurance_claims", c.id, "claims", "reverse"))
    return related, paths


def needs_migration(engine) -> bool:
    with engine.connect() as conn:
        return object_exists(conn, HUB_TABLE) and "provider_id" not in table_columns(conn, HUB_TABLE)


def migrate(engine, session_factory) -> Dict[str, Any]:
    """Rebuilds the flat policy table: the free-text `insurer` column becomes an FK
    to insurance_providers. Policy ids are preserved."""
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE insurance_policies RENAME TO _legacy_insurance_policies"))
        legacy = conn.execute(text(
            "SELECT id, policy_number, recorded_vehicle_number, insurer, policy_start_date, expiry_date, policy_status "
            "FROM _legacy_insurance_policies ORDER BY id")).fetchall()
        # The legacy unique index keeps its old name after a rename; drop it so create_all can recreate it.
        for (idx,) in conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='_legacy_insurance_policies' "
                "AND name NOT LIKE 'sqlite_%'")).fetchall():
            conn.execute(text(f'DROP INDEX "{idx}"'))
    Base.metadata.create_all(bind=engine)
    session = session_factory()
    try:
        for row in legacy:
            provider = get_or_create_provider(session, row.insurer)
            session.add(InsurancePolicy(
                id=row.id, policy_number=row.policy_number,
                recorded_vehicle_number=normalize_plate(row.recorded_vehicle_number),
                provider_id=provider.id, policy_start_date=row.policy_start_date,
                expiry_date=row.expiry_date, policy_status=row.policy_status))
        session.commit()
        migrated = session.query(InsurancePolicy).count()
    finally:
        session.close()
    if migrated < len(legacy):
        raise RuntimeError(f"Insurance migration verification failed ({migrated} < {len(legacy)})")
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE _legacy_insurance_policies"))
    return {"legacy_rows": len(legacy), "migrated_rows": migrated}


def post_create(engine) -> None:
    return None
