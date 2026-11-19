"""Generates the SYNTHETIC unstructured document repository (TXT / Markdown / PDF).

Every document is fictional coursework data, consistent with seed_data.py, and is
explicitly marked "SYNTHETIC DEMONSTRATION DOCUMENT". Some documents deliberately
use noisy plate spellings (spaces, hyphens, OCR errors) and one is a look-alike
distractor for a different vehicle (DL01AB1243) to show context-aware retrieval.

Run:  python documents/generate_documents.py     (overwrites the generated files)
PDFs are written with a tiny built-in writer, so no PDF library is needed to
create them; pypdf is used only for reading.
"""
import os
import textwrap

ROOT = os.path.dirname(os.path.abspath(__file__))
BANNER = "SYNTHETIC DEMONSTRATION DOCUMENT - VehicleTrustAI coursework data. Not a real record."


def doc(doc_id, folder, fmt, title, doc_type, date, issuer, plate_display, fields, body):
    lines = [BANNER, "", title.upper(), "", f"Document ID: {doc_id}"]
    if doc_type:
        lines.append(f"Document Type: {doc_type}")
    lines += [f"Issued By: {issuer}", f"Date: {date}"]
    if plate_display:
        lines.append(f"Registration Number: {plate_display}")
    lines += [f"{k}: {v}" for k, v in fields]
    lines += [""] + [p.strip() for p in body.strip().split("\n\n")]
    return {"id": doc_id, "folder": folder, "fmt": fmt, "title": title, "text": "\n".join(lines) + "\n"}


DOCUMENTS = [
    # ------------------------------------------------------------------ insurance policies (PDF)
    doc("DOC-INS-POL-001", "insurance_policies", "pdf", "Motor Insurance Policy Schedule", "Insurance Policy",
        "2026-01-01", "HDFC ERGO General Insurance", "DL 01 AB 1234",
        [("Policy Number", "POL-HDFC-9901"), ("Insured Name", "Aarav Sharma"), ("Make", "Honda"), ("Model", "City"),
         ("Colour", "White"), ("Period of Insurance", "2026-01-01 to 2027-01-01"), ("Policy Status", "ACTIVE"),
         ("Cover", "Comprehensive Own Damage with Personal Accident Cover")],
        """This schedule certifies comprehensive cover for the private car described above, registered in Delhi.

Insured Declared Value is as per the proposal form. Own damage claims are subject to the compulsory deductible of INR 1000. The policy must be produced on demand under Section 158 of the Motor Vehicles Act."""),
    doc("DOC-INS-POL-002", "insurance_policies", "pdf", "Motor Insurance Policy Schedule", "Insurance Policy",
        "2022-08-10", "ICICI Lombard", "MH12DE1432",
        [("Policy Number", "POL-ICICI-2022"), ("Insured Name", "Vikram Joshi"), ("Make", "Tata"), ("Model", "Nexon"),
         ("Colour", "Blue"), ("Period of Insurance", "2022-08-10 to 2023-08-09"), ("Policy Status", "ACTIVE AT ISSUE")],
        """Package policy for a Tata Nexon registered at Pune RTO.

Renewal reminder: this policy expires on 2023-08-09. No renewal has been recorded by the insurer as of the date of this schedule."""),
    doc("DOC-INS-POL-003", "insurance_policies", "pdf", "Motor Insurance Policy Schedule", "Insurance Policy",
        "2026-02-01", "Reliance General Insurance", "AP09CA3322",
        [("Policy Number", "POL-RELIANCE-33A"), ("Insured Name", "Kavya Reddy"), ("Make", "Honda"), ("Model", "Amaze"),
         ("Colour", "Lunar Silver"), ("Period of Insurance", "2026-02-01 to 2027-02-01"), ("Policy Status", "ACTIVE")],
        """Comprehensive cover for a Honda Amaze. The proposer declared no other subsisting motor policy for this vehicle."""),
    doc("DOC-INS-POL-004", "insurance_policies", "pdf", "Motor Insurance Policy Schedule", "Insurance Policy",
        "2026-06-01", "Cholamandalam MS General Insurance", "AP 09 CA 3322",
        [("Policy Number", "POL-CHOLA-33B"), ("Insured Name", "Kavya Reddy"), ("Make", "Honda"), ("Model", "Amaze"),
         ("Period of Insurance", "2026-06-01 to 2027-06-01"), ("Policy Status", "ACTIVE")],
        """Second comprehensive policy issued for the same Honda Amaze while policy POL-RELIANCE-33A remains in force. Concurrent own-damage policies should be investigated for possible duplicate claims."""),
    doc("DOC-INS-POL-005", "insurance_policies", "pdf", "Motor Insurance Policy Renewal Schedule", "Insurance Policy",
        "2026-05-15", "SBI General Insurance", "GJ01AB7777",
        [("Policy Number", "POL-SBI-7777"), ("Insured Name", "Hitesh Patel"), ("Make", "Mahindra"), ("Model", "XUV700"),
         ("Colour", "Everest White"), ("Period of Insurance", "2026-05-15 to 2027-05-14"), ("Policy Status", "ACTIVE")],
        """Online renewal processed without physical inspection. The underwriting note states that no theft intimation was checked against police records at the time of renewal."""),
    doc("DOC-INS-POL-006", "insurance_policies", "pdf", "Motor Insurance Policy Schedule", "Insurance Policy",
        "2026-01-15", "ICICI Lombard", "KL07BQ8899",
        [("Policy Number", "POL-ICICI-8899"), ("Insured Name", "Joseph Mathew"), ("Make", "Maruti Suzuki"),
         ("Model", "Baleno"), ("Colour", "Pearl White"), ("Period of Insurance", "2026-01-15 to 2027-01-15"),
         ("Policy Status", "ACTIVE")],
        """Comprehensive cover for a Maruti Suzuki Baleno registered at Ernakulam RTO. Vehicle identity was confirmed from the chassis plate during the 2025 inspection."""),
    # ------------------------------------------------------------------ claims / cancellation (TXT)
    doc("DOC-INS-CNL-001", "insurance_policies", "txt", "Policy Cancellation Notice", "Insurance Cancellation Notice",
        "2023-11-20", "ICICI Lombard", "DL03CC8899",
        [("Policy Number", "POL-ICICI-8899B"), ("Insured Name", "Farhan Qureshi"), ("Make", "Maruti Suzuki"),
         ("Model", "Dzire"), ("Policy Status", "CANCELLED")],
        """The policy is cancelled with effect from 2023-11-20 because the premium instalment was dishonoured.

The vehicle is not insured by this company from the cancellation date. Any loss after this date is not payable."""),
    doc("DOC-INS-CLM-001", "insurance_claims", "txt", "Motor Claim Settlement Report", "Insurance Claim Report",
        "2026-04-02", "HDFC ERGO General Insurance", "DL01AB1234",
        [("Claim Number", "CLM-HDFC-2026-0412"), ("Policy Number", "POL-HDFC-9901"), ("Claim Date", "2026-03-18"),
         ("Make", "Honda"), ("Model", "City"), ("Colour", "White"), ("Claim Status", "SETTLED"),
         ("Amount Settled", "INR 42500")],
        """Surveyor report: rear bumper and right tail-lamp damaged in a low-speed collision near Connaught Place, New Delhi. Damage consistent with the reported cause.

Repairs completed at an authorised Honda workshop. Claim settled under the comprehensive section after deductible."""),
    doc("DOC-INS-CLM-002", "insurance_claims", "txt", "Theft Claim Repudiation Letter", "Insurance Claim Report",
        "2024-07-30", "United India Insurance", "AS01BC4433",
        [("Claim Number", "CLM-UNITED-2024-1107"), ("Policy Number", "POL-UNITED-4433"), ("Claim Type", "THEFT"),
         ("Make", "Maruti Suzuki"), ("Model", "WagonR"), ("Claim Status", "REJECTED")],
        """The theft claim is repudiated. Police FIR AS-DSP-2024-0112 records the theft on 2024-02-14, while the policy commenced on 2024-06-21.

A loss that occurred before the policy inception date is not covered. The insured may approach the Insurance Ombudsman within one year."""),
    doc("DOC-INS-CLM-003", "insurance_claims", "txt", "Total Loss Settlement Report", "Insurance Claim Report",
        "2024-03-28", "Tata AIG General Insurance", "HP01CC2323",
        [("Claim Number", "CLM-TATA-2024-0305"), ("Policy Number", "POL-TATA-2323"), ("Make", "MG"), ("Model", "Hector"),
         ("Claim Status", "SETTLED"), ("Settlement Basis", "Total loss")],
        """Vehicle damaged beyond economical repair in a landslide on NH-5 near Shimla. Settled as a total loss; the salvage was retained by the owner, who undertook to deposit it at a registered scrapping facility."""),
    doc("DOC-INS-CLM-004", "insurance_claims", "txt", "Total Loss Settlement Report", "Insurance Claim Report",
        "2019-10-30", "Oriental Insurance", "WB02K0001",
        [("Claim Number", "CLM-ORI-2019-0914"), ("Policy Number", "POL-ORIENTAL-01"), ("Make", "Mercedes-Benz"),
         ("Model", "C-Class"), ("Colour", "Obsidian Black"), ("Claim Status", "SETTLED")],
        """Vehicle submerged during flooding in Kolkata. Engine and electricals damaged beyond repair. Settled as a constructive total loss; the registration certificate must be surrendered on scrapping."""),
    doc("DOC-INS-CLM-005", "insurance_claims", "txt", "Claim Intimation Acknowledgement", "Insurance Claim Report",
        "2026-04-23", "Reliance General Insurance", "AP09CA3322",
        [("Claim Number", "CLM-REL-2026-0422"), ("Policy Number", "POL-RELIANCE-33A"), ("Claim Type", "FLOOD_DAMAGE"),
         ("Claim Status", "UNDER_REVIEW")],
        """Flood damage claim registered. A second policy for the same vehicle (Cholamandalam POL-CHOLA-33B) was found during de-duplication checks; the claim is on hold pending clarification from the insured."""),
    # ------------------------------------------------------------------ inspection reports (TXT)
    doc("DOC-INSP-001", "inspection_reports", "txt", "Pre-Renewal Vehicle Inspection Report", "Vehicle Inspection Report",
        "2025-12-20", "HDFC ERGO Inspection Desk", "DL-01-AB-1234",
        [("Make", "Honda"), ("Model", "City"), ("Colour", "White"), ("Odometer", "48210 km"), ("Owner", "Aarav Sharma")],
        """Photographs of all four sides taken. Rear bumper shows minor scuff marks. Chassis and engine numbers match the registration certificate. Vehicle fit for renewal."""),
    doc("DOC-INSP-002", "inspection_reports", "txt", "Vehicle Inspection Report", "Vehicle Inspection Report",
        "2026-05-30", "Bajaj Allianz Survey Team", "KA05MJ5555",
        [("Make", "Maruti Suzuki"), ("Model", "Swift"), ("Colour", "Fire Red"), ("Owner", "Deepak Hegde")],
        """The vehicle has been repainted. Observed colour is Fire Red; the RC carries a colour change endorsement dated 2022-11-03. Original factory colour was Crimson Red."""),
    doc("DOC-INSP-003", "inspection_reports", "txt", "Post-Recovery Inspection Report", "Vehicle Inspection Report",
        "2022-06-04", "Chennai Police Motor Vehicle Inspector", "TN02KK6789",
        [("Make", "Tata"), ("Model", "Altroz"), ("Colour", "High Street Gold"), ("Related FIR", "TN-ANN-2022-0890")],
        """Recovered vehicle inspected. Fake number plates were fitted and have been removed. Chassis number verified against RTO records. Minor scratches on left doors; vehicle roadworthy."""),
    doc("DOC-INSP-004", "inspection_reports", "txt", "Pre-Sale Inspection Report", "Vehicle Inspection Report",
        "2025-08-28", "Noida Pre-Owned Car Evaluators", "UP16BT9900",
        [("Make", "Toyota"), ("Model", "Innova Crysta"), ("Colour", "Grey"), ("Seller", "Ramesh Gupta"),
         ("Buyer", "Suresh Yadav")],
        """Inspection performed before sale. The buyer Suresh Yadav will apply for transfer of ownership at Noida RTO. Insurance policy POL-NEWIND-1800 shown by the seller had already expired."""),
    doc("DOC-INSP-005", "inspection_reports", "txt", "Vehicle Inspection Report", "Vehicle Inspection Report",
        "2026-02-11", "Delhi Pre-Owned Car Evaluators", "DL01AB1243",
        [("Make", "Maruti Suzuki"), ("Model", "Alto"), ("Colour", "Grey"), ("Owner", "Sunil Kumar")],
        """Routine inspection of a Maruti Suzuki Alto registered in Delhi. Note: this registration number differs from DL01AB1234 only by two transposed digits, and the vehicle is a different car."""),
    # ------------------------------------------------------------------ registration certificates (PDF)
    doc("DOC-RC-001", "registration_certificates", "pdf", "Certificate of Registration (Form 23)", "Registration Certificate",
        "2023-02-14", "Delhi North RTO (Mall Road)", "DL01AB1234",
        [("RC Number", "RC-DL01AB1234-2020"), ("Registered Owner", "Aarav Sharma"), ("Make", "Honda"), ("Model", "City"),
         ("Colour", "White"), ("Date of Registration", "2020-05-15"), ("Valid Until", "2035-05-15"), ("RC Status", "VALID")],
        """Certificate reissued after transfer of ownership from Rohan Mehta to Aarav Sharma on 2023-02-10."""),
    doc("DOC-RC-002", "registration_certificates", "pdf", "Certificate of Registration (Form 23)", "Registration Certificate",
        "2016-02-11", "Kolkata RTO (Beltala)", "WB02K0001",
        [("RC Number", "RC-WB02K0001-2016"), ("Registered Owner", "Sanjay Banerjee"), ("Make", "Mercedes-Benz"),
         ("Model", "C-Class"), ("Colour", "Obsidian Black"), ("Valid Until", "2031-02-11"), ("RC Status", "VALID")],
        """Original certificate of registration as issued in 2016."""),
    doc("DOC-RC-003", "registration_certificates", "pdf", "Certificate of Registration (Form 23)", "Registration Certificate",
        "2025-09-05", "Noida RTO (Gautam Buddh Nagar)", "UP16BT9900",
        [("RC Number", "RC-UP16BT9900-2018"), ("Registered Owner", "Suresh Yadav"), ("Make", "Toyota"),
         ("Model", "Innova Crysta"), ("Colour", "Grey"), ("RC Status", "VALID")],
        """Certificate reissued in the name of Suresh Yadav after transfer of ownership from Ramesh Gupta on 2025-09-02."""),
    doc("DOC-RC-004", "registration_certificates", "pdf", "Certificate of Registration (Form 23)", "Registration Certificate",
        "2021-05-10", "Patna DTO", "BR01XY6655",
        [("RC Number", "RC-BR01XY6655-2018"), ("Registered Owner", "Ritu Kumari"), ("Make", "Tata Motors"),
         ("Model", "Tiago"), ("Colour", "Pristine White"), ("RC Status", "VALID")],
        """Certificate reissued after transfer by inheritance from Manoj Sinha."""),
    # ------------------------------------------------------------------ RTO notices (Markdown)
    doc("DOC-RTO-NOT-001", "rto_notices", "md", "Notice of Suspension of Registration", "RTO Notice",
        "2023-08-12", "Ahmedabad RTO", "GJ01AB7777",
        [("RC Number", "RC-GJ01AB7777-2022"), ("Related FIR", "GJ-NAV-2023-0457"), ("RC Status", "SUSPENDED")],
        """On receipt of theft intimation from Navrangpura Police Station, the registration of the Mahindra XUV700 is suspended. No transfer, NOC or duplicate RC may be issued until recovery is reported."""),
    doc("DOC-RTO-NOT-002", "rto_notices", "md", "Acknowledgement of Deregistration Application", "RTO Notice",
        "2024-04-01", "Shimla RLA", "HP01CC2323",
        [("RC Number", "RC-HP01CC2323-2020"), ("RC Status", "SUSPENDED"), ("Make", "MG"), ("Model", "Hector")],
        """Application for cancellation of registration received. Final cancellation will follow on submission of the Certificate of Deposit from a Registered Vehicle Scrapping Facility."""),
    doc("DOC-RTO-NOT-003", "rto_notices", "md", "Public Notice: High Security Registration Plates", "RTO Notice",
        "2025-01-10", "Transport Department, Government of NCT of Delhi", None,
        [("Applies To", "All vehicles registered in Delhi")],
        """All vehicles registered in Delhi must display High Security Registration Plates (HSRP). Enforcement drives will check plates against registration records; vehicles with tampered or non-standard plates will be challaned."""),
    doc("DOC-RTO-NOT-004", "rto_notices", "md", "Transfer of Ownership Acknowledgement (Form 29/30)", "RTO Notice",
        "2025-09-02", "Noida RTO (Gautam Buddh Nagar)", "UP 16 BT 9900",
        [("Previous Owner", "Ramesh Gupta"), ("New Owner", "Suresh Yadav"), ("Make", "Toyota"), ("Model", "Innova Crysta")],
        """Transfer of ownership recorded. The new owner must transfer the insurance policy or obtain a fresh policy within 14 days."""),
    doc("DOC-RTO-NOT-005", "rto_notices", "md", "Public Notice: Insurance Enforcement Drive", "RTO Notice",
        "2024-03-01", "Transport Commissioner, Maharashtra", None,
        [("Applies To", "All vehicles registered in Maharashtra")],
        """A month-long drive will check motor insurance validity at toll plazas using the national insurance database. Owners of uninsured vehicles will be fined under Section 196 of the Motor Vehicles Act."""),
    # ------------------------------------------------------------------ theft complaints (TXT)
    doc("DOC-FIR-001", "theft_complaints", "txt", "First Information Report - Motor Vehicle Theft", "Theft Complaint",
        "2023-08-10", "Navrangpura Police Station, Ahmedabad", "GJ-01-AB-7777",
        [("FIR Number", "GJ-NAV-2023-0457"), ("Complainant", "Hitesh Patel"), ("Make", "Mahindra"), ("Model", "XUV700"),
         ("Colour", "Everest White"), ("Theft Status", "STOLEN")],
        """The complainant parked the vehicle outside a shopping complex on C.G. Road at about 19:30 and found it missing at 22:40. Both keys are with the complainant."""),
    doc("DOC-FIR-002", "theft_complaints", "txt", "First Information Report - Motor Vehicle Theft", "Theft Complaint",
        "2024-02-14", "Dispur Police Station, Guwahati", "AS01BC4433",
        [("FIR Number", "AS-DSP-2024-0112"), ("Complainant", "Bikram Das"), ("Make", "Maruti Suzuki"), ("Model", "WagonR"),
         ("Colour", "Silky Silver"), ("Theft Status", "STOLEN")],
        """Vehicle stolen overnight from the apartment parking at Beltola. The complainant states the vehicle was not insured at the time of theft as the earlier policy had lapsed."""),
    doc("DOC-FIR-003", "theft_complaints", "txt", "First Information Report - Motor Vehicle Theft", "Theft Complaint",
        "2022-05-20", "Anna Nagar Police Station, Chennai", "TN02KK6789",
        [("FIR Number", "TN-ANN-2022-0890"), ("Complainant", "Lakshmi Narayanan"), ("Make", "Tata"), ("Model", "Altroz"),
         ("Theft Status", "STOLEN")],
        """Vehicle stolen from street parking on 2nd Avenue, Anna Nagar."""),
    # ------------------------------------------------------------------ police investigation (TXT)
    doc("DOC-POL-INV-001", "police_investigations", "txt", "Investigation Progress Report", None,
        "2026-09-30", "Navrangpura Police Station, Ahmedabad", None,
        [("FIR Number", "GJ-NAV-2023-0457"), ("Investigating Officer", "SI Harshad Patel"), ("Status", "ACTIVE")],
        """CCTV review shows the vehicle crossing the Gujarat-Rajasthan border on 2023-08-11. An ANPR camera at Shamlaji captured plate text GJO1AB7777, which is the stolen Mahindra XUV700 with a misread digit.

The vehicle has not been recovered. An insurer enquiry in 2026 about a renewed policy for this vehicle has been noted; the RC remains suspended."""),
    doc("DOC-POL-INV-002", "police_investigations", "txt", "Vehicle Recovery Memo", "Police Investigation Report",
        "2022-06-02", "Koyambedu Police Station, Chennai", "TN 02 KK 6789",
        [("FIR Number", "TN-ANN-2022-0890"), ("Investigating Officer", "SI R. Meena"), ("Theft Status", "RECOVERED")],
        """Vehicle recovered at Koyambedu market parking with fake number plates. Accused apprehended. Vehicle released to the owner after inspection on 2022-06-04."""),
    doc("DOC-POL-INV-003", "police_investigations", "txt", "Investigation Status Report", "Police Investigation Report",
        "2025-03-01", "Dispur Police Station, Guwahati", "AS01BC4433",
        [("FIR Number", "AS-DSP-2024-0112"), ("Investigating Officer", "SI Bikash Bora"), ("Status", "DORMANT")],
        """No leads after twelve months. Case kept open; vehicle details circulated to neighbouring states."""),
    # ------------------------------------------------------------------ scrapping certificates (PDF)
    doc("DOC-SCRAP-001", "scrapping_certificates", "pdf", "Certificate of Deposit (Vehicle Scrapping)", "Scrapping Certificate",
        "2021-03-01", "Kolkata Registered Vehicle Scrapping Facility", "WB02K0001",
        [("Certificate Number", "COD-WB-2021-00087"), ("Make", "Mercedes-Benz"), ("Model", "C-Class"),
         ("Vehicle Status", "SCRAPPED")],
        """The vehicle has been received and scrapped. The registering authority must cancel the registration certificate on receipt of this certificate."""),
    doc("DOC-SCRAP-002", "scrapping_certificates", "pdf", "Scrapping Application Receipt", "Scrapping Certificate",
        "2024-04-01", "Shimla Registered Vehicle Scrapping Facility", "HP01CC2323",
        [("Make", "MG"), ("Model", "Hector"), ("Vehicle Status", "PENDING_SCRAP")],
        """Application received. The vehicle will be dismantled after physical verification of the chassis number. A Certificate of Deposit will be issued after scrapping."""),
    # ------------------------------------------------------------------ compliance (TXT)
    doc("DOC-COMP-001", "compliance", "txt", "Pollution Under Control Certificate", "Compliance Certificate",
        "2026-07-01", "Authorised PUC Centre, New Delhi", "DL01AB1234",
        [("Make", "Honda"), ("Model", "City"), ("Fuel", "Petrol"), ("Valid Until", "2027-01-01"), ("Result", "PASS")],
        """Emission levels within the prescribed limits."""),
    doc("DOC-COMP-002", "compliance", "txt", "e-Challan: Driving Without Valid Insurance", "Compliance Notice",
        "2024-03-15", "Pune Traffic Police", "MH12DE1432",
        [("Challan Number", "ECH-MH12-2024-77812"), ("Make", "Tata"), ("Model", "Nexon"), ("Offence", "Section 196 MV Act"),
         ("Insurance Status", "EXPIRED")],
        """Vehicle detected without valid insurance during the Maharashtra enforcement drive. Last policy POL-ICICI-2022 expired on 2023-08-09."""),
    doc("DOC-COMP-003", "compliance", "txt", "Pollution Under Control Certificate", "Compliance Certificate",
        "2026-08-20", "Authorised PUC Centre, New Delhi", "DL08CZ1010",
        [("Make", "Hyundai"), ("Model", "Exter"), ("Valid Until", "2027-02-20"), ("Result", "PASS")],
        """Emission levels within the prescribed limits. Owner: Aarav Sharma."""),
]


# ----------------------------------------------------------------------------- tiny PDF writer
def _pdf_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_pdf(path: str, text: str, title: str, subject: str) -> None:
    lines = []
    for para in text.split("\n"):
        lines.extend(textwrap.wrap(para, 92) or [""])
    pages = [lines[i:i + 58] for i in range(0, len(lines), 58)] or [[]]
    objects = []  # index 0 -> object 1
    objects.append("<< /Type /Catalog /Pages 2 0 R >>")
    kids_placeholder = len(objects)
    objects.append(None)
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    page_ids = []
    for page_lines in pages:
        content = "BT /F1 10 Tf 13 TL 50 800 Td " + " ".join(f"({_pdf_escape(l)}) Tj T*" for l in page_lines) + " ET"
        objects.append(f"<< /Length {len(content.encode('latin-1'))} >>\nstream\n{content}\nendstream")
        content_id = len(objects)
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>")
        page_ids.append(len(objects))
    objects[kids_placeholder] = f"<< /Type /Pages /Kids [{' '.join(f'{i} 0 R' for i in page_ids)}] /Count {len(page_ids)} >>"
    objects.append(f"<< /Title ({_pdf_escape(title)}) /Subject ({_pdf_escape(subject)}) /Producer (VehicleTrustAI synthetic generator) >>")
    info_id = len(objects)

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{obj}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info {info_id} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    with open(path, "wb") as fh:
        fh.write(out)


def main() -> None:
    for d in DOCUMENTS:
        folder = os.path.join(ROOT, d["folder"])
        os.makedirs(folder, exist_ok=True)
        target = os.path.join(folder, f"{d['id']}.{d['fmt']}")
        if d["fmt"] == "pdf":
            write_pdf(target, d["text"], d["title"], f"{d['id']} (synthetic)")
        elif d["fmt"] == "md":
            body = d["text"].replace(d["title"].upper(), f"# {d['title']}", 1)
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(body)
        else:
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(d["text"])
    print(f"Generated {len(DOCUMENTS)} synthetic documents under {ROOT}")


if __name__ == "__main__":
    main()
