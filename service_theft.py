"""Theft & Scrapping database service (port 8104, theft_scrapping.db). Runs on machine-1."""
from typing import Optional

from pydantic import BaseModel, Field

import config
from databases import theft as db
from databases.service_factory import build_service_app
from matching import normalize_plate


class TheftScrappingCreate(BaseModel):
    reported_plate: str = Field(..., min_length=4, max_length=20)
    theft_status: str = Field("CLEAR")
    report_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    scrapping_status: str = Field("ACTIVE")


class TheftScrappingUpdate(BaseModel):
    reported_plate: Optional[str] = None
    theft_status: Optional[str] = None
    report_date: Optional[str] = None
    scrapping_status: Optional[str] = None


def create_record(session, data):
    norm = normalize_plate(data["reported_plate"])
    if session.query(db.TheftScrappingRecord).filter(db.TheftScrappingRecord.reported_plate == norm).first():
        raise ValueError(f"Reported plate {norm} already exists")
    rec = db.TheftScrappingRecord(reported_plate=norm, theft_status=data["theft_status"].strip().upper(),
                                  report_date=data["report_date"].strip(),
                                  scrapping_status=data["scrapping_status"].strip().upper())
    session.add(rec)
    return rec


app = build_service_app("theft_scrapping", "Theft and Scrapping Database Service", TheftScrappingCreate,
                        TheftScrappingUpdate, create_record, "reported_plate", "Record")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.service_port("theft_scrapping"))
