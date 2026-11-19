"""Synthetic demonstration data for the five VehicleTrustAI databases.

ALL DATA IS SYNTHETIC (coursework demonstration only; not real people or vehicles).

The four Phase 2 lists below are the core 33 vehicle identities and are unchanged.
The Phase 3 sections add the related-table rows (owners, providers, claims, RTO
offices, transfers, police stations, ...) keyed by registration number, plus a
few deliberate cross-database discrepancies used to demonstrate conflict detection.

Usage:
    python seed_data.py                 # non-destructive init/migrate/seed of all 5 DBs
    python seed_data.py --only machine-2  # only this machine's databases
    python seed_data.py --reset         # back up, delete and re-create the databases
"""
import datetime
import hashlib

SYNTHETIC_REGISTRY_DATA = [
    ("DL01AB1234", "Honda", "City", "White", "Sedan", "2020-05-15", "Delhi"),
    ("MH12DE1432", "Tata", "Nexon", "Blue", "Compact SUV", "2021-08-10", "Maharashtra"),
    ("KA05MJ5555", "Maruti Suzuki", "Swift", "Crimson Red", "Hatchback", "2019-03-22", "Karnataka"),
    ("TN09AZ4321", "Hyundai", "Creta", "Silver", "SUV", "2022-01-14", "Tamil Nadu"),
    ("UP16BT9900", "Toyota", "Innova Crysta", "Grey", "MUV", "2018-11-05", "Uttar Pradesh"),
    ("HR26DK8392", "Kia", "Seltos", "Aurora Black", "SUV", "2021-04-18", "Haryana"),
    ("GJ01AB7777", "Mahindra", "XUV700", "Everest White", "SUV", "2022-09-30", "Gujarat"),
    ("WB02K0001", "Mercedes-Benz", "C-Class", "Obsidian Black", "Luxury Sedan", "2016-02-11", "West Bengal"),
    ("AP09CA3322", "Honda", "Amaze", "Lunar Silver", "Sedan", "2020-10-12", "Andhra Pradesh"),
    ("TS07EA4455", "Hyundai", "i20", "Polar White", "Hatchback", "2021-07-25", "Telangana"),
    ("KL07BQ8899", "Maruti Suzuki", "Baleno", "Pearl White", "Hatchback", "2019-12-01", "Kerala"),
    ("RJ14CD1122", "Tata", "Harrier", "Daytona Grey", "SUV", "2023-03-10", "Rajasthan"),
    ("PB10AB5050", "Mahindra", "Thar", "Rocky Black", "4x4 SUV", "2022-06-18", "Punjab"),
    ("CH01AA1111", "Toyota", "Fortuner", "Super White", "SUV", "2020-08-04", "Chandigarh"),
    ("UK07TA2233", "Renault", "Kiger", "Radiant Red", "Compact SUV", "2021-11-20", "Uttarakhand"),
    ("MP04CC8877", "Hyundai", "Venue", "Typhoon Silver", "Compact SUV", "2020-01-15", "Madhya Pradesh"),
    ("GA03B9988", "Royal Enfield", "Classic 350", "Stealth Black", "Motorcycle", "2019-09-09", "Goa"),
    ("BR01XY6655", "Tata", "Tiago", "Pristine White", "Hatchback", "2018-04-14", "Bihar"),
    ("AS01BC4433", "Maruti Suzuki", "WagonR", "Silky Silver", "Hatchback", "2017-06-21", "Assam"),
    ("OD02DD1212", "Honda", "Elevate", "Phoenix Orange", "SUV", "2023-10-05", "Odisha"),
    ("JH01EE3434", "Mahindra", "Scorpio-N", "Deep Forest", "SUV", "2022-12-12", "Jharkhand"),
    ("CG04FF7878", "Maruti Suzuki", "Brezza", "Magma Grey", "Compact SUV", "2021-05-19", "Chhattisgarh"),
    ("PY01AA9090", "Volkswagen", "Virtus", "Wild Cherry Red", "Sedan", "2022-08-08", "Puducherry"),
    ("JK02BB5656", "Skoda", "Slavia", "Brilliant Silver", "Sedan", "2023-01-22", "Jammu and Kashmir"),
    ("HP01CC2323", "MG", "Hector", "Starry Black", "SUV", "2020-07-17", "Himachal Pradesh"),
    ("TR01DD8989", "Tata", "Punch", "Tropical Mist", "Micro SUV", "2022-03-03", "Tripura"),
    ("22BH1234AA", "Kia", "Sonet", "Glacier White Pearl", "Compact SUV", "2022-04-11", "Bharat Series"),
    ("23BH5678BB", "Hyundai", "Verna", "Abyss Black", "Sedan", "2023-05-29", "Bharat Series"),
    ("DL03CC8899", "Maruti Suzuki", "Dzire", "Arctic White", "Sedan", "2019-06-14", "Delhi"),
    ("KA01HG4321", "Honda", "City", "Golden Brown", "Sedan", "2021-09-09", "Karnataka"),
    ("TN02KK6789", "Tata", "Altroz", "High Street Gold", "Hatchback", "2020-11-28", "Tamil Nadu"),
    ("MH02BW9000", "BMW", "3 Series", "Mineral White", "Luxury Sedan", "2021-02-14", "Maharashtra"),
    ("DL08CZ1010", "Hyundai", "Exter", "Ranger Khaki", "Micro SUV", "2023-08-15", "Delhi"),
]

SYNTHETIC_INSURANCE_DATA = [
    ("POL-HDFC-9901", "DL01AB1234", "HDFC ERGO General Insurance", "2026-01-01", "2027-01-01", "ACTIVE"),
    ("POL-ICICI-2022", "MH12DE1432", "ICICI Lombard", "2022-08-10", "2023-08-09", "EXPIRED"),
    ("POL-BAJAJ-5501", "KA05MJ5555", "Bajaj Allianz General Insurance", "2026-03-01", "2027-03-01", "ACTIVE"),
    ("POL-TATA-4321", "TN09AZ4321", "Tata AIG General Insurance", "2026-01-10", "2027-01-09", "ACTIVE"),
    ("POL-NEWIND-1800", "UP16BT9900", "The New India Assurance", "2022-11-05", "2023-11-04", "EXPIRED"),
    ("POL-DIGIT-8392", "HR26DK8392", "Go Digit General Insurance", "2026-04-01", "2027-04-01", "ACTIVE"),
    ("POL-SBI-7777", "GJ01AB7777", "SBI General Insurance", "2026-05-15", "2027-05-14", "ACTIVE"),
    ("POL-ORIENTAL-01", "WB02K0001", "Oriental Insurance", "2019-02-11", "2020-02-10", "EXPIRED"),
    ("POL-RELIANCE-33A", "AP09CA3322", "Reliance General Insurance", "2026-02-01", "2027-02-01", "ACTIVE"),
    ("POL-CHOLA-33B", "AP09CA3322", "Cholamandalam MS General Insurance", "2026-06-01", "2027-06-01", "ACTIVE"),
    ("POL-ICICI-8899", "KL07BQ8899", "ICICI Lombard", "2026-01-15", "2027-01-15", "ACTIVE"),
    ("POL-HDFC-1122", "RJ14CD1122", "HDFC ERGO General Insurance", "2027-01-01", "2028-01-01", "ACTIVE"),
    ("POL-BAJAJ-5050", "PB10AB5050", "Bajaj Allianz General Insurance", "2026-06-01", "2027-06-01", "ACTIVE"),
    ("POL-NEWIND-1111", "CH01AA1111", "The New India Assurance", "2026-08-01", "2027-08-01", "ACTIVE"),
    ("POL-TATA-2233", "UK07TA2233", "Tata AIG General Insurance", "2024-11-20", "2025-11-19", "EXPIRED"),
    ("POL-RELIANCE-87", "MP04CC8877", "Reliance General Insurance", "2026-01-10", "2027-01-10", "ACTIVE"),
    ("POL-IFFCO-9988", "GA03B9988", "IFFCO Tokio General Insurance", "2026-09-01", "2027-09-01", "ACTIVE"),
    ("POL-NATIONAL-65", "BR01XY6655", "National Insurance Company", "2021-04-14", "2022-04-13", "EXPIRED"),
    ("POL-UNITED-4433", "AS01BC4433", "United India Insurance", "2024-06-21", "2025-06-20", "EXPIRED"),
    ("POL-DIGIT-1212", "OD02DD1212", "Go Digit General Insurance", "2026-10-01", "2027-10-01", "ACTIVE"),
    ("POL-ICICI-3434", "JH01EE3434", "ICICI Lombard", "2026-02-15", "2027-02-15", "ACTIVE"),
    ("POL-SBI-7878", "CG04FF7878", "SBI General Insurance", "2024-05-19", "2025-05-18", "EXPIRED"),
    ("POL-HDFC-9090", "PY01AA9090", "HDFC ERGO General Insurance", "2026-08-01", "2027-08-01", "ACTIVE"),
    ("POL-BAJAJ-5656", "JK02BB5656", "Bajaj Allianz General Insurance", "2026-01-20", "2027-01-20", "ACTIVE"),
    ("POL-TATA-2323", "HP01CC2323", "Tata AIG General Insurance", "2023-07-17", "2024-07-16", "EXPIRED"),
    ("POL-DIGIT-22BH", "22BH1234AA", "Go Digit General Insurance", "2026-04-01", "2027-04-01", "ACTIVE"),
    ("POL-HDFC-23BH", "23BH5678BB", "HDFC ERGO General Insurance", "2024-05-29", "2025-05-28", "EXPIRED"),
    ("POL-CHOLA-8899A", "DL03CC8899", "Cholamandalam MS", "2022-06-14", "2023-06-13", "EXPIRED"),
    ("POL-ICICI-8899B", "DL03CC8899", "ICICI Lombard", "2023-06-14", "2024-06-13", "CANCELLED"),
    ("POL-RELIANCE-43", "KA01HG4321", "Reliance General Insurance", "2026-09-01", "2027-09-01", "ACTIVE"),
    ("POL-NEWIND-6789", "TN02KK6789", "The New India Assurance", "2026-11-01", "2027-11-01", "ACTIVE"),
    ("POL-BAJAJ-9000", "MH02BW9000", "Bajaj Allianz General Insurance", "2026-02-01", "2027-02-01", "ACTIVE"),
    ("POL-HDFC-1010", "DL08CZ1010", "HDFC ERGO General Insurance", "2026-08-01", "2027-08-01", "ACTIVE"),
]

SYNTHETIC_REGISTRATION_DATA = [
    ("DL01AB1234", "Honda", "City", "White", "2020-05-15", "Delhi", "RTO-DL01-2020-9812"),
    ("MH12DE1432", "Tata", "Nexon", "Blue", "2021-08-10", "Maharashtra", "RTO-MH12-2021-4411"),
    ("KA05MJ5555", "Maruti Suzuki", "Swift", "Fire Red", "2019-03-22", "Karnataka", "RTO-KA05-2019-0021"),
    ("TN09AZ4321", "Hyundai", "Creta", "Silver", "2022-01-14", "Tamil Nadu", "RTO-TN09-2022-3189"),
    ("UP16BT9900", "Toyota", "Innova Crysta", "Grey", "2018-11-05", "Uttar Pradesh", "RTO-UP16-2018-7712"),
    ("HR26DK8392", "Kia", "Seltos", "Aurora Black", "2021-04-18", "Haryana", "RTO-HR26-2021-5529"),
    ("GJ01AB7777", "Mahindra", "XUV700", "Everest White", "2022-09-30", "Gujarat", "RTO-GJ01-2022-8819"),
    ("WB02K0001", "Mercedes-Benz", "C-Class", "Obsidian Black", "2016-02-11", "West Bengal", "RTO-WB02-2016-1102"),
    ("AP09CA3322", "Honda", "Amaze", "Lunar Silver", "2020-10-12", "Andhra Pradesh", "RTO-AP09-2020-4321"),
    ("TS07EA4455", "Hyundai", "i20", "Polar White", "2021-07-25", "Telangana", "RTO-TS07-2021-7711"),
    ("KL07BQ8899", "Maruti Suzuki", "Swift", "Pearl White", "2019-12-01", "Kerala", "RTO-KL07-2019-8923"),
    ("RJ14CD1122", "Tata", "Harrier", "Daytona Grey", "2023-03-10", "Rajasthan", "RTO-RJ14-2023-3321"),
    ("PB10AB5050", "Mahindra", "Thar", "Rocky Black", "2022-06-18", "Punjab", "RTO-PB10-2022-5501"),
    ("CH01AA1111", "Toyota", "Fortuner", "Super White", "2020-08-04", "Chandigarh", "RTO-CH01-2020-0011"),
    ("UK07TA2233", "Renault", "Kiger", "Radiant Red", "2021-11-20", "Uttarakhand", "RTO-UK07-2021-4412"),
    ("MP04CC8877", "Hyundai", "Venue", "Typhoon Silver", "2020-01-15", "Madhya Pradesh", "RTO-MP04-2020-6677"),
    ("GA03B9988", "Royal Enfield", "Classic 350", "Stealth Black", "2019-09-09", "Goa", "RTO-GA03-2019-9988"),
    ("BR01XY6655", "Tata Motors", "Tiago", "Pristine White", "2018-04-14", "Bihar", "RTO-BR01-2018-2231"),
    ("AS01BC4433", "Maruti Suzuki", "WagonR", "Silky Silver", "2017-06-21", "Assam", "RTO-AS01-2017-6644"),
    ("OD02DD1212", "Honda", "Elevate", "Phoenix Orange", "2023-10-05", "Odisha", "RTO-OD02-2023-1212"),
    ("JH01EE3434", "Mahindra", "Scorpio-N", "Forest Green", "2022-12-12", "Jharkhand", "RTO-JH01-2022-3434"),
    ("CG04FF7878", "Maruti Suzuki", "Brezza", "Magma Grey", "2021-05-19", "Chhattisgarh", "RTO-CG04-2021-7878"),
    ("PY01AA9090", "Volkswagen", "Virtus", "Wild Cherry Red", "2022-08-08", "Puducherry", "RTO-PY01-2022-9090"),
    ("JK02BB5656", "Skoda", "Slavia", "Brilliant Silver", "2023-01-22", "Jammu and Kashmir", "RTO-JK02-2023-5656"),
    ("HP01CC2323", "MG", "Hector", "Starry Black", "2020-07-17", "Himachal Pradesh", "RTO-HP01-2020-2323"),
    ("TR01DD8989", "Tata", "Punch", "Tropical Mist", "2022-03-03", "Tripura", "RTO-TR01-2022-8989"),
    ("22BH1234AA", "Kia", "Sonet", "Glacier White Pearl", "2022-04-11", "Bharat Series", "MoRTH-BH2022-1234"),
    ("23BH5678BB", "Hyundai", "Verna", "Abyss Black", "2023-05-29", "Bharat Series", "MoRTH-BH2023-5678"),
    ("DL03CC8899", "Maruti Suzuki", "Dzire", "Arctic White", "2019-06-14", "Delhi", "RTO-DL03-2019-8899"),
    ("KA01HG4321", "Honda", "City", "Golden Brown", "2021-09-09", "Karnataka", "RTO-KA01-2021-4321"),
    ("TN02KK6789", "Tata", "Altroz", "High Street Gold", "2020-11-28", "Tamil Nadu", "RTO-TN02-2020-6789"),
    ("MH02BW9000", "BMW", "3 Series", "Mineral White", "2021-02-14", "Maharashtra", "RTO-MH02-2021-9000"),
    ("DL08CZ1010", "Hyundai", "Exter", "Ranger Khaki", "2023-08-15", "Delhi", "RTO-DL08-2023-1010"),
]

SYNTHETIC_THEFT_DATA = [
    ("DL01AB1234", "CLEAR", "2020-05-15", "ACTIVE"),
    ("MH12DE1432", "CLEAR", "2021-08-10", "ACTIVE"),
    ("KA05MJ5555", "CLEAR", "2019-03-22", "ACTIVE"),
    ("TN09AZ4321", "CLEAR", "2022-01-14", "ACTIVE"),
    ("UP16BT9900", "CLEAR", "2018-11-05", "ACTIVE"),
    ("HR26DK8392", "CLEAR", "2021-04-18", "ACTIVE"),
    ("GJ01AB7777", "STOLEN", "2023-08-10", "ACTIVE"),
    ("WB02K0001", "CLEAR", "2016-02-11", "SCRAPPED"),
    ("AP09CA3322", "CLEAR", "2020-10-12", "ACTIVE"),
    ("TS07EA4455", "CLEAR", "2021-07-25", "ACTIVE"),
    ("KL07BQ8899", "CLEAR", "2019-12-01", "ACTIVE"),
    ("RJ14CD1122", "CLEAR", "2023-03-10", "ACTIVE"),
    ("PB10AB5050", "CLEAR", "2022-06-18", "ACTIVE"),
    ("CH01AA1111", "CLEAR", "2020-08-04", "ACTIVE"),
    ("UK07TA2233", "CLEAR", "2021-11-20", "ACTIVE"),
    ("MP04CC8877", "CLEAR", "2020-01-15", "ACTIVE"),
    ("GA03B9988", "CLEAR", "2019-09-09", "ACTIVE"),
    ("BR01XY6655", "CLEAR", "2018-04-14", "ACTIVE"),
    ("AS01BC4433", "STOLEN", "2024-02-14", "ACTIVE"),
    ("OD02DD1212", "CLEAR", "2023-10-05", "ACTIVE"),
    ("JH01EE3434", "CLEAR", "2022-12-12", "ACTIVE"),
    ("CG04FF7878", "CLEAR", "2021-05-19", "ACTIVE"),
    ("PY01AA9090", "CLEAR", "2022-08-08", "ACTIVE"),
    ("JK02BB5656", "CLEAR", "2023-01-22", "ACTIVE"),
    ("HP01CC2323", "CLEAR", "2020-07-17", "PENDING_SCRAP"),
    ("TR01DD8989", "CLEAR", "2022-03-03", "ACTIVE"),
    ("22BH1234AA", "CLEAR", "2022-04-11", "ACTIVE"),
    ("23BH5678BB", "CLEAR", "2023-05-29", "ACTIVE"),
    ("DL03CC8899", "CLEAR", "2019-06-14", "ACTIVE"),
    ("KA01HG4321", "CLEAR", "2021-09-09", "ACTIVE"),
    ("TN02KK6789", "RECOVERED", "2022-05-20", "ACTIVE"),
    ("MH02BW9000", "CLEAR", "2021-02-14", "ACTIVE"),
    ("DL08CZ1010", "CLEAR", "2023-08-15", "ACTIVE"),
]




# =============================================================================
# PHASE 3 — related-table data
# =============================================================================
MANUFACTURER_COUNTRIES = {
    "Honda": "Japan", "Tata": "India", "Tata Motors": "India", "Maruti Suzuki": "India", "Hyundai": "South Korea",
    "Toyota": "Japan", "Kia": "South Korea", "Mahindra": "India", "Mercedes-Benz": "Germany", "Renault": "France",
    "Royal Enfield": "India", "Volkswagen": "Germany", "Skoda": "Czech Republic", "MG": "United Kingdom / China",
    "BMW": "Germany",
}
CATEGORY_DESCRIPTIONS = {
    "Sedan": "Three-box passenger car", "Hatchback": "Compact passenger car with rear hatch",
    "SUV": "Sport utility vehicle", "Compact SUV": "Sub-4 metre sport utility vehicle",
    "Micro SUV": "Entry-level crossover", "MUV": "Multi utility vehicle", "Luxury Sedan": "Premium sedan",
    "4x4 SUV": "Four-wheel-drive off-roader", "Motorcycle": "Two-wheeler", "Motor Car": "Generic motor car",
}
FUEL_TYPES = {"Nexon": "Petrol", "Innova Crysta": "Diesel", "XUV700": "Diesel", "Thar": "Diesel",
              "Fortuner": "Diesel", "Scorpio-N": "Diesel", "Harrier": "Diesel", "Classic 350": "Petrol"}

# plate -> (current registry owner, owner type, city)
REGISTRY_OWNERS = {
    "DL01AB1234": ("Aarav Sharma", "INDIVIDUAL", "New Delhi"),
    "MH12DE1432": ("Priya Kulkarni", "INDIVIDUAL", "Pune"),
    "KA05MJ5555": ("Deepak Hegde", "INDIVIDUAL", "Bengaluru"),
    "TN09AZ4321": ("Meenakshi Sundaram", "INDIVIDUAL", "Chennai"),
    "UP16BT9900": ("Ramesh Gupta", "INDIVIDUAL", "Noida"),
    "HR26DK8392": ("Neha Malik", "INDIVIDUAL", "Gurugram"),
    "GJ01AB7777": ("Hitesh Patel", "INDIVIDUAL", "Ahmedabad"),
    "WB02K0001": ("Sanjay Banerjee", "INDIVIDUAL", "Kolkata"),
    "AP09CA3322": ("Kavya Reddy", "INDIVIDUAL", "Hyderabad"),
    "TS07EA4455": ("Kavya Reddy", "INDIVIDUAL", "Hyderabad"),
    "KL07BQ8899": ("Joseph Mathew", "INDIVIDUAL", "Kochi"),
    "RJ14CD1122": ("Zenith Fleet Services Pvt Ltd", "COMPANY", "Jaipur"),
    "PB10AB5050": ("Gurpreet Singh", "INDIVIDUAL", "Ludhiana"),
    "CH01AA1111": ("Harleen Kaur", "INDIVIDUAL", "Chandigarh"),
    "UK07TA2233": ("Ankit Rawat", "INDIVIDUAL", "Dehradun"),
    "MP04CC8877": ("Pooja Chouhan", "INDIVIDUAL", "Bhopal"),
    "GA03B9988": ("Rohan D'Souza", "INDIVIDUAL", "Mapusa"),
    "BR01XY6655": ("Ritu Kumari", "INDIVIDUAL", "Patna"),
    "AS01BC4433": ("Bikram Das", "INDIVIDUAL", "Guwahati"),
    "OD02DD1212": ("Sasmita Mohanty", "INDIVIDUAL", "Bhubaneswar"),
    "JH01EE3434": ("Amit Oraon", "INDIVIDUAL", "Ranchi"),
    "CG04FF7878": ("Shalini Verma", "INDIVIDUAL", "Raipur"),
    "PY01AA9090": ("Arun Pillai", "INDIVIDUAL", "Puducherry"),
    "JK02BB5656": ("Imran Bhat", "INDIVIDUAL", "Jammu"),
    "HP01CC2323": ("Vivek Thakur", "INDIVIDUAL", "Shimla"),
    "TR01DD8989": ("Mousumi Debbarma", "INDIVIDUAL", "Agartala"),
    "22BH1234AA": ("Siddharth Menon", "INDIVIDUAL", "Bengaluru"),
    "23BH5678BB": ("Nandini Rao", "INDIVIDUAL", "Hyderabad"),
    "DL03CC8899": ("Farhan Qureshi", "INDIVIDUAL", "New Delhi"),
    "KA01HG4321": ("Ananya Iyer", "INDIVIDUAL", "Bengaluru"),
    "TN02KK6789": ("Karthik Subramanian", "INDIVIDUAL", "Chennai"),
    "MH02BW9000": ("Zenith Fleet Services Pvt Ltd", "COMPANY", "Mumbai"),
    "DL08CZ1010": ("Aarav Sharma", "INDIVIDUAL", "New Delhi"),
}

INSURANCE_PROVIDER_INFO = {
    "HDFC ERGO General Insurance": ("IRDAI-146", "1800-2700-700"),
    "ICICI Lombard": ("IRDAI-115", "1800-2666"),
    "Bajaj Allianz General Insurance": ("IRDAI-113", "1800-209-5858"),
    "Tata AIG General Insurance": ("IRDAI-108", "1800-266-7780"),
    "The New India Assurance": ("IRDAI-190", "1800-209-1415"),
    "Go Digit General Insurance": ("IRDAI-158", "1800-258-5956"),
    "SBI General Insurance": ("IRDAI-144", "1800-102-1111"),
    "Oriental Insurance": ("IRDAI-556", "1800-118-485"),
    "Reliance General Insurance": ("IRDAI-103", "1800-3009"),
    "Cholamandalam MS General Insurance": ("IRDAI-123", "1800-208-9100"),
    "Cholamandalam MS": ("IRDAI-123", "1800-208-9100"),
    "IFFCO Tokio General Insurance": ("IRDAI-106", "1800-103-5499"),
    "National Insurance Company": ("IRDAI-058", "1800-345-0330"),
    "United India Insurance": ("IRDAI-545", "1800-425-333-33"),
}

# policy_number -> holder name when it differs from the current registry owner
POLICY_HOLDER_OVERRIDES = {
    "POL-ICICI-2022": "Vikram Joshi",        # expired policy taken by the previous owner (transfer 2024)
    "POL-NATIONAL-65": "Manoj Sinha",        # policy from before the 2021 inheritance transfer
}

# policy_number -> list of claims
INSURANCE_CLAIMS = {
    "POL-HDFC-9901": [("CLM-HDFC-2026-0412", "2026-03-18", "ACCIDENT_DAMAGE", 42500.0, "SETTLED",
                       "Rear bumper and tail-lamp damage after a low-speed collision near Connaught Place, New Delhi.")],
    "POL-BAJAJ-5501": [("CLM-BAJAJ-2026-0610", "2026-06-10", "GLASS_DAMAGE", 8200.0, "SETTLED",
                        "Windshield replacement after stone impact on NICE Road, Bengaluru.")],
    "POL-RELIANCE-33A": [("CLM-REL-2026-0422", "2026-04-22", "FLOOD_DAMAGE", 61000.0, "UNDER_REVIEW",
                          "Engine water ingress during urban flooding; surveyor visit pending.")],
    "POL-DIGIT-8392": [("CLM-DIGIT-2026-0830", "2026-08-30", "ACCIDENT_DAMAGE", 125000.0, "SETTLED",
                        "Front-end collision on NH-48 near Gurugram toll plaza.")],
    "POL-ICICI-8899B": [("CLM-ICICI-2023-1201", "2023-12-01", "ACCIDENT_DAMAGE", 30000.0, "REJECTED",
                         "Claim rejected: policy was cancelled for non-payment of premium before the loss date.")],
    "POL-TATA-2323": [("CLM-TATA-2024-0305", "2024-03-05", "TOTAL_LOSS", 390000.0, "SETTLED",
                       "Vehicle declared total loss after landslide damage on NH-5; salvage retained by owner for scrapping.")],
    "POL-ORIENTAL-01": [("CLM-ORI-2019-0914", "2019-09-14", "TOTAL_LOSS", 1450000.0, "SETTLED",
                         "Total loss after flood submersion; vehicle surrendered for scrapping.")],
    "POL-UNITED-4433": [("CLM-UNITED-2024-1107", "2024-07-02", "THEFT", 410000.0, "REJECTED",
                         "Theft claim rejected: loss (FIR AS-DSP-2024-0112 dated 2024-02-14) occurred before policy inception on 2024-06-21.")],
}

RTO_OFFICE_INFO = {
    "DL01": ("Delhi North RTO (Mall Road)", "New Delhi"), "DL03": ("Delhi South RTO (Sheikh Sarai)", "New Delhi"),
    "DL08": ("Delhi West RTO (Wazirpur)", "New Delhi"), "MH12": ("Pune RTO", "Pune"),
    "MH02": ("Mumbai West RTO (Andheri)", "Mumbai"), "KA05": ("Bengaluru South RTO (Jayanagar)", "Bengaluru"),
    "KA01": ("Bengaluru Central RTO (Koramangala)", "Bengaluru"), "TN09": ("Chennai West RTO (K.K. Nagar)", "Chennai"),
    "TN02": ("Chennai North-West RTO (Anna Nagar)", "Chennai"), "UP16": ("Noida RTO (Gautam Buddh Nagar)", "Noida"),
    "HR26": ("Gurugram RTO", "Gurugram"), "GJ01": ("Ahmedabad RTO", "Ahmedabad"), "WB02": ("Kolkata RTO (Beltala)", "Kolkata"),
    "AP09": ("Hyderabad Central RTO (Khairatabad)", "Hyderabad"), "TS07": ("Ranga Reddy RTO", "Hyderabad"),
    "KL07": ("Ernakulam RTO", "Kochi"), "RJ14": ("Jaipur RTO", "Jaipur"), "PB10": ("Ludhiana RTO", "Ludhiana"),
    "CH01": ("Chandigarh Registering & Licensing Authority", "Chandigarh"), "UK07": ("Dehradun RTO", "Dehradun"),
    "MP04": ("Bhopal RTO", "Bhopal"), "GA03": ("Mapusa ARTO", "Mapusa"), "BR01": ("Patna DTO", "Patna"),
    "AS01": ("Guwahati DTO (Kamrup Metro)", "Guwahati"), "OD02": ("Bhubaneswar RTO", "Bhubaneswar"),
    "JH01": ("Ranchi DTO", "Ranchi"), "CG04": ("Raipur RTO", "Raipur"), "PY01": ("Puducherry Transport Department", "Puducherry"),
    "JK02": ("Jammu RTO", "Jammu"), "HP01": ("Shimla RLA", "Shimla"), "TR01": ("Agartala DTO", "Agartala"),
    "MoRTH-BH": ("MoRTH Bharat Series (BH) Registration Portal", "New Delhi"),
}

# plate -> list of (transfer_date, previous_owner, new_owner, reason)
OWNERSHIP_TRANSFERS = {
    "DL01AB1234": [("2023-02-10", "Rohan Mehta", "Aarav Sharma", "SALE")],
    "MH12DE1432": [("2024-01-15", "Vikram Joshi", "Priya Kulkarni", "SALE")],
    "UP16BT9900": [("2025-09-02", "Ramesh Gupta", "Suresh Yadav", "SALE")],   # registry not yet updated (conflict)
    "KA01HG4321": [("2022-07-19", "Nikhil Rao", "Ananya Iyer", "SALE")],
    "TN02KK6789": [("2023-03-11", "Lakshmi Narayanan", "Karthik Subramanian", "SALE")],
    "BR01XY6655": [("2021-05-05", "Manoj Sinha", "Ritu Kumari", "INHERITANCE")],
}

# plate -> RC status override (default VALID)
RC_STATUS_OVERRIDES = {
    "GJ01AB7777": "SUSPENDED",     # theft intimation received
    "AS01BC4433": "SUSPENDED",     # theft intimation received
    "HP01CC2323": "SUSPENDED",     # scrap application under process
    # WB02K0001 intentionally stays VALID although the vehicle is scrapped (cross-DB conflict)
}

# plate -> extra (event_date, event_type, description)
REGISTRATION_EXTRA_EVENTS = {
    "KA05MJ5555": [("2022-11-03", "COLOUR_CHANGE_ENDORSEMENT", "Colour endorsed on RC as 'Fire Red' after repaint (registry still shows 'Crimson Red').")],
    "GJ01AB7777": [("2023-08-12", "THEFT_INTIMATION", "Theft intimation received from Navrangpura Police Station (FIR GJ-NAV-2023-0457); RC suspended.")],
    "AS01BC4433": [("2024-02-20", "THEFT_INTIMATION", "Theft intimation received from Dispur Police Station (FIR AS-DSP-2024-0112); RC suspended.")],
    "HP01CC2323": [("2024-04-01", "SCRAP_APPLICATION", "Application for deregistration received; awaiting Certificate of Deposit from RVSF.")],
    "CH01AA1111": [("2020-08-04", "HYPOTHECATION_ADDED", "Hypothecation in favour of HDFC Bank endorsed.")],
    "DL03CC8899": [("2023-06-14", "ADDRESS_CHANGE", "Owner address updated within Delhi South jurisdiction.")],
    "UP16BT9900": [("2023-11-10", "HYPOTHECATION_REMOVED", "Loan closure; hypothecation removed.")],
}

POLICE_STATIONS = [
    ("DL-PS-CP", "Connaught Place Police Station", "New Delhi", "Delhi"),
    ("GJ-PS-NAV", "Navrangpura Police Station", "Ahmedabad", "Gujarat"),
    ("AS-PS-DSP", "Dispur Police Station", "Guwahati", "Assam"),
    ("TN-PS-ANN", "Anna Nagar Police Station", "Chennai", "Tamil Nadu"),
    ("TN-PS-KOY", "Koyambedu Police Station", "Chennai", "Tamil Nadu"),
    ("MH-PS-SHV", "Shivajinagar Police Station", "Pune", "Maharashtra"),
]

# plate -> (fir, date, station_code, location, report_status, description, investigation, recovery)
THEFT_REPORTS = {
    "GJ01AB7777": ("GJ-NAV-2023-0457", "2023-08-10", "GJ-PS-NAV", "Outside a shopping complex, C.G. Road, Ahmedabad", "OPEN",
                   "Owner reported white Mahindra XUV700 missing from roadside parking at 22:40.",
                   ("SI Harshad Patel", "ACTIVE", "2026-09-30",
                    "CCTV reviewed; vehicle sighted crossing the Gujarat-Rajasthan border on 2023-08-11. Interstate alert issued."),
                   None),
    "AS01BC4433": ("AS-DSP-2024-0112", "2024-02-14", "AS-PS-DSP", "Residential parking, Beltola, Guwahati", "OPEN",
                   "Silver Maruti Suzuki WagonR stolen overnight from apartment parking.",
                   ("SI Bikash Bora", "DORMANT", "2025-03-01", "No leads after 12 months; case kept open pending recovery."),
                   None),
    "TN02KK6789": ("TN-ANN-2022-0890", "2022-05-20", "TN-PS-ANN", "2nd Avenue, Anna Nagar, Chennai", "RECOVERED",
                   "Gold Tata Altroz stolen from street parking.",
                   ("SI R. Meena", "CLOSED", "2022-06-05", "Vehicle recovered; accused apprehended; case closed."),
                   ("2022-06-02", "TN-PS-KOY", "Koyambedu market parking, Chennai", "Minor damage; fake number plates fitted")),
}

# plate -> (certificate_number, facility, application_date, scrap_date, status)
SCRAPPING_RECORDS = {
    "WB02K0001": ("COD-WB-2021-00087", "Kolkata Registered Vehicle Scrapping Facility", "2021-02-01", "2021-03-01", "SCRAPPED"),
    "HP01CC2323": (None, "Shimla Registered Vehicle Scrapping Facility", "2024-04-01", None, "PENDING_SCRAP"),
}

REVIEWERS = [
    ("dashboard-reviewer", "Dashboard Reviewer", "DATA_STEWARD"),
    ("a.verma", "Anita Verma", "SENIOR_DATA_STEWARD"),
    ("r.khan", "Rahul Khan", "DATA_STEWARD"),
]

# Historical (synthetic) review decisions so the audit trail has context to discover.
# record_id = position in SYNTHETIC_REGISTRY_DATA (ids are sequential on a fresh seed);
# vehicle_plate is stored as well, so the audit query also matches by plate.
SEED_AUDIT_HISTORY = [
    {"plate": "KA05MJ5555", "field_name": "colour", "old_value": "Crimson Red", "new_value": None,
     "reviewer_decision": "UNRESOLVED", "reviewer": "a.verma", "session_code": "SES-20260915-a.verma",
     "reason": "Synthetic seed history: RTO shows 'Fire Red'; awaiting physical inspection before correcting registry.",
     "evidence": {"source": "registration_authority", "field": "colour", "value": "Fire Red", "plate_similarity": 1.0,
                  "description": "RTO colour endorsement 2022-11-03"}},
    {"plate": "KL07BQ8899", "field_name": "model", "old_value": "Baleno", "new_value": None,
     "reviewer_decision": "REJECTED", "reviewer": "r.khan", "session_code": "SES-20261002-r.khan",
     "reason": "Synthetic seed history: insurance and inspection documents show Baleno; RTO 'Swift' suspected clerical error.",
     "evidence": {"source": "registration_authority", "field": "model", "value": "Swift", "plate_similarity": 1.0,
                  "description": "RTO registration record"}},
]


def _registry_record_id(plate: str) -> int:
    return next(i + 1 for i, row in enumerate(SYNTHETIC_REGISTRY_DATA) if row[0] == plate)


def _code(prefix: str, value: str, length: int = 8) -> str:
    return prefix + hashlib.sha1(value.encode()).hexdigest()[:length].upper()


def _add_years(date_str: str, years: int) -> str:
    d = datetime.date.fromisoformat(date_str)
    try:
        return d.replace(year=d.year + years).isoformat()
    except ValueError:
        return d.replace(year=d.year + years, day=28).isoformat()


def current_rto_owner(plate: str):
    transfers = OWNERSHIP_TRANSFERS.get(plate)
    if transfers:
        return transfers[-1][2]
    owner = REGISTRY_OWNERS.get(plate)
    return owner[0] if owner else None


def original_owner(plate: str):
    transfers = OWNERSHIP_TRANSFERS.get(plate)
    if transfers:
        return transfers[0][1]
    owner = REGISTRY_OWNERS.get(plate)
    return owner[0] if owner else None


# =============================================================================
# Seeders (ORM, idempotent: core rows only if empty, related rows only if missing)
# =============================================================================
def _seed_registry(session):
    from databases.registry import Manufacturer, Vehicle, VehicleCategory, VehicleOwner, get_or_create_model
    counts = {"vehicles": 0, "vehicle_owners": 0}
    if session.query(Vehicle).count() == 0:
        for plate, make, model, colour, v_type, reg_d, st in SYNTHETIC_REGISTRY_DATA:
            vm = get_or_create_model(session, make, model, v_type, FUEL_TYPES.get(model, "Petrol"))
            session.add(Vehicle(registration_number=plate, model_id=vm.id, colour=colour,
                                registration_date=reg_d, state=st))
            counts["vehicles"] += 1
        session.flush()
    for m in session.query(Manufacturer).filter(Manufacturer.country.is_(None)):
        m.country = MANUFACTURER_COUNTRIES.get(m.name)
    for c in session.query(VehicleCategory).filter(VehicleCategory.description.is_(None)):
        c.description = CATEGORY_DESCRIPTIONS.get(c.name)
    owners_by_name = {o.full_name: o for o in session.query(VehicleOwner).all()}
    for v in session.query(Vehicle).order_by(Vehicle.id):
        if v.owner_id is None and v.registration_number in REGISTRY_OWNERS:
            name, o_type, city = REGISTRY_OWNERS[v.registration_number]
            owner = owners_by_name.get(name)
            if owner is None:
                owner = VehicleOwner(owner_code=f"OWN-{len(owners_by_name) + 1:04d}", full_name=name, owner_type=o_type,
                                     city=city, state=v.state, phone_masked=f"+91-XXXXXX{int(hashlib.sha1(name.encode()).hexdigest(), 16) % 9000 + 1000}")
                session.add(owner)
                session.flush()
                owners_by_name[name] = owner
                counts["vehicle_owners"] += 1
            v.owner_id = owner.id
        if v.chassis_number is None:
            v.chassis_number = _code("MA", v.registration_number, 15)
            v.engine_number = _code("EN", v.registration_number, 10)
    session.commit()
    return counts


def _seed_insurance(session):
    from databases.insurance import (CoverageDetail, InsuranceClaim, InsurancePolicy, InsuranceProvider,
                                     PolicyHolder, get_or_create_provider)
    counts = {"insurance_policies": 0, "policy_holders": 0, "coverage_details": 0, "insurance_claims": 0}
    if session.query(InsurancePolicy).count() == 0:
        for pol, veh, ins, s_date, e_date, status in SYNTHETIC_INSURANCE_DATA:
            provider = get_or_create_provider(session, ins)
            session.add(InsurancePolicy(policy_number=pol, recorded_vehicle_number=veh, provider_id=provider.id,
                                        policy_start_date=s_date, expiry_date=e_date, policy_status=status))
            counts["insurance_policies"] += 1
        session.flush()
    for p in session.query(InsuranceProvider).filter(InsuranceProvider.irdai_code.is_(None)):
        info = INSURANCE_PROVIDER_INFO.get(p.name)
        if info:
            p.irdai_code, p.claims_helpline = info
    holders = {h.full_name: h for h in session.query(PolicyHolder).all()}
    for p in session.query(InsurancePolicy).order_by(InsurancePolicy.id):
        if p.holder_id is None:
            name = POLICY_HOLDER_OVERRIDES.get(p.policy_number) or (REGISTRY_OWNERS.get(p.recorded_vehicle_number) or (None,))[0]
            if name:
                holder = holders.get(name)
                if holder is None:
                    city = (REGISTRY_OWNERS.get(p.recorded_vehicle_number) or (None, None, None))[2]
                    holder = PolicyHolder(holder_code=f"PH-{len(holders) + 1:04d}", full_name=name, city=city)
                    session.add(holder)
                    session.flush()
                    holders[name] = holder
                    counts["policy_holders"] += 1
                p.holder_id = holder.id
        if not p.coverages:
            comprehensive = p.id % 3 != 0
            base = 250000 + (p.id * 37000) % 900000
            session.add(CoverageDetail(policy_id=p.id, coverage_type="Comprehensive Own Damage" if comprehensive else "Third Party Liability",
                                       sum_insured=float(base if comprehensive else 750000), premium=round(base * 0.028, 2),
                                       deductible=1000.0 if comprehensive else 0.0))
            session.add(CoverageDetail(policy_id=p.id, coverage_type="Personal Accident Cover (Owner-Driver)",
                                       sum_insured=1500000.0, premium=330.0, deductible=0.0))
            counts["coverage_details"] += 2
            if comprehensive and p.id % 2 == 0:
                session.add(CoverageDetail(policy_id=p.id, coverage_type="Zero Depreciation Add-on",
                                           sum_insured=None, premium=round(base * 0.006, 2), deductible=0.0))
                counts["coverage_details"] += 1
        if not p.claims:
            for claim in INSURANCE_CLAIMS.get(p.policy_number, []):
                number, c_date, c_type, amount, c_status, desc = claim
                if not session.query(InsuranceClaim).filter(InsuranceClaim.claim_number == number).first():
                    session.add(InsuranceClaim(policy_id=p.id, claim_number=number, claim_date=c_date, claim_type=c_type,
                                               claim_amount=amount, claim_status=c_status, description=desc))
                    counts["insurance_claims"] += 1
    session.commit()
    return counts


def _seed_registration(session):
    from databases.registration import (OwnershipTransfer, RegistrationCertificate, RegistrationEvent, RTOOffice,
                                        RTORegistration, get_or_create_office, office_code_for_plate)
    counts = {"rto_registrations": 0, "registration_certificates": 0, "ownership_transfers": 0, "registration_events": 0}
    if session.query(RTORegistration).count() == 0:
        for plate, make, model, colour, reg_d, st, ref in SYNTHETIC_REGISTRATION_DATA:
            office = get_or_create_office(session, plate, st)
            session.add(RTORegistration(plate_identifier=plate, office_id=office.id, make=make, model=model,
                                        colour=colour, registration_date=reg_d, state=st, authority_reference=ref))
            counts["rto_registrations"] += 1
        session.flush()
    for office in session.query(RTOOffice):
        info = RTO_OFFICE_INFO.get(office.office_code)
        if info and office.office_name.startswith("RTO "):
            office.office_name, office.city = info
    for r in session.query(RTORegistration).order_by(RTORegistration.id):
        plate = r.plate_identifier
        if not r.certificates:
            session.add(RegistrationCertificate(
                registration_id=r.id, rc_number=f"RC-{plate}-{r.registration_date[:4]}", issue_date=r.registration_date,
                valid_until=_add_years(r.registration_date, 15), rc_status=RC_STATUS_OVERRIDES.get(plate, "VALID"),
                registered_owner=current_rto_owner(plate)))
            counts["registration_certificates"] += 1
        if not r.transfers:
            for t_date, prev, new, reason in OWNERSHIP_TRANSFERS.get(plate, []):
                session.add(OwnershipTransfer(registration_id=r.id, office_id=r.office_id, transfer_date=t_date,
                                              previous_owner=prev, new_owner=new, transfer_reason=reason))
                counts["ownership_transfers"] += 1
        if not r.events:
            first_owner = original_owner(plate) or "registered owner"
            events = [(r.registration_date, "NEW_REGISTRATION", f"New registration issued to {first_owner}.")]
            events += [(t[0], "OWNERSHIP_TRANSFER", f"Ownership transferred from {t[1]} to {t[2]} ({t[3].lower()}).")
                       for t in OWNERSHIP_TRANSFERS.get(plate, [])]
            events += REGISTRATION_EXTRA_EVENTS.get(plate, [])
            for e_date, e_type, desc in sorted(events):
                session.add(RegistrationEvent(registration_id=r.id, office_id=r.office_id, event_date=e_date,
                                              event_type=e_type, description=desc))
                counts["registration_events"] += 1
    session.commit()
    return counts


def _seed_theft(session):
    from databases.theft import (InvestigationDetail, PoliceStation, RecoveryRecord, ScrappingRecord, TheftReport,
                                 TheftScrappingRecord)
    counts = {"theft_scrapping_records": 0, "police_stations": 0, "theft_reports": 0, "scrapping_records": 0}
    if session.query(TheftScrappingRecord).count() == 0:
        for plate, t_status, r_date, s_status in SYNTHETIC_THEFT_DATA:
            session.add(TheftScrappingRecord(reported_plate=plate, theft_status=t_status, report_date=r_date,
                                             scrapping_status=s_status))
            counts["theft_scrapping_records"] += 1
        session.flush()
    stations = {s.station_code: s for s in session.query(PoliceStation).all()}
    for code, name, city, state in POLICE_STATIONS:
        if code not in stations:
            stations[code] = PoliceStation(station_code=code, station_name=name, city=city, state=state)
            session.add(stations[code])
            counts["police_stations"] += 1
    session.flush()
    for plate, (fir, r_date, st_code, loc, status, desc, inv, rec) in THEFT_REPORTS.items():
        hub = session.query(TheftScrappingRecord).filter(TheftScrappingRecord.reported_plate == plate).first()
        if hub is None or session.query(TheftReport).filter(TheftReport.fir_number == fir).first():
            continue
        report = TheftReport(vehicle_record_id=hub.id, station_id=stations[st_code].id, fir_number=fir, report_date=r_date,
                             incident_location=loc, report_status=status, description=desc)
        session.add(report)
        session.flush()
        counts["theft_reports"] += 1
        officer, i_status, updated, notes = inv
        session.add(InvestigationDetail(theft_report_id=report.id, investigating_officer=officer,
                                        investigation_status=i_status, last_updated=updated, notes=notes))
        if rec:
            rec_date, rec_station, rec_loc, condition = rec
            session.add(RecoveryRecord(theft_report_id=report.id, station_id=stations[rec_station].id,
                                       recovery_date=rec_date, recovery_location=rec_loc, vehicle_condition=condition))
    for plate, (cert, facility, app_date, scrap_date, status) in SCRAPPING_RECORDS.items():
        hub = session.query(TheftScrappingRecord).filter(TheftScrappingRecord.reported_plate == plate).first()
        if hub is None or hub.scrapping_records:
            continue
        session.add(ScrappingRecord(vehicle_record_id=hub.id, certificate_number=cert, facility_name=facility,
                                    application_date=app_date, scrap_date=scrap_date, scrap_status=status))
        counts["scrapping_records"] += 1
    session.commit()
    return counts


def _seed_audit(session):
    from databases.audit import AuditLog, Reviewer, create_audit_entry
    counts = {"reviewers": 0, "cleansing_audit_log": 0}
    for username, name, role in REVIEWERS:
        if not session.query(Reviewer).filter(Reviewer.username == username).first():
            session.add(Reviewer(username=username, full_name=name, role=role))
            counts["reviewers"] += 1
    session.commit()
    for item in SEED_AUDIT_HISTORY:
        exists = session.query(AuditLog).filter(AuditLog.vehicle_plate == item["plate"],
                                                AuditLog.field_name == item["field_name"],
                                                AuditLog.reason == item["reason"]).first()
        if exists:
            continue
        create_audit_entry(session, {
            "affected_source": "vehicle_registry", "record_id": _registry_record_id(item["plate"]),
            "vehicle_plate": item["plate"], "client": "seed", **{k: v for k, v in item.items() if k != "plate"},
        })
        counts["cleansing_audit_log"] += 1
    return counts


SEEDERS = {
    "vehicle_registry": _seed_registry,
    "insurance_records": _seed_insurance,
    "registration_authority": _seed_registration,
    "theft_scrapping": _seed_theft,
    "audit_log": _seed_audit,
}


def seed(key: str, session):
    return SEEDERS[key](session)


# -----------------------------------------------------------------------------
# Backwards-compatible entry points (used by older launch scripts)
# -----------------------------------------------------------------------------
def _init(key, db_path=None, reset=False):
    from databases import initialize_database
    initialize_database(key, db_path, reset=reset, verbose=True)


def seed_database_1(db_path=None):
    _init("vehicle_registry", db_path)


def seed_database_2(db_path=None):
    _init("insurance_records", db_path)


def seed_database_3(db_path=None):
    _init("registration_authority", db_path)


def seed_database_4(db_path=None):
    _init("theft_scrapping", db_path)


def seed_database_5(db_path=None):
    _init("audit_log", db_path)


def seed_all_databases(keys=None, reset=False):
    import config
    keys = keys or config.ALL_SERVICE_KEYS
    print(f"VehicleTrust AI: initializing {len(keys)} database(s) (non-destructive{'; RESET requested' if reset else ''})...")
    for key in keys:
        _init(key, reset=reset)
    print("Database initialization completed.")


if __name__ == "__main__":
    import argparse
    import config

    parser = argparse.ArgumentParser(description="Initialize / migrate / seed VehicleTrustAI databases")
    parser.add_argument("--only", choices=sorted(config.MACHINE_GROUPS), help="initialize only this machine's databases")
    parser.add_argument("--reset", action="store_true", help="back up, delete and re-create the selected databases")
    args = parser.parse_args()
    selected = None
    if args.only:
        selected = [config.NODE_TO_KEY[n] for n in config.MACHINE_GROUPS[args.only]]
    seed_all_databases(selected, reset=args.reset)
