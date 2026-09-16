# Project 1: Uninsured Vehicle Identification

This is a runnable SQLite prototype for turning heterogeneous transport data into an auditable, decision-centric vehicle history.

## Source systems

`database_setup.py` creates five isolated SQLite files with intentionally different key names and formats:

1. `road_capture`: roadside ANPR observations and vehicle descriptions.
2. `insurance_policy`: insurer policy and validity data.
3. `vehicle_registration`: authoritative registration and ownership data.
4. `theft_scrap_case`: police theft and authorised dismantling cases.
5. `ministry_report`: generated reports for the Ministry of Transportation.

The shared business identity is the vehicle registration number, but each source represents it differently (`plate_text`, `registration_no`, `reg_no`, and `plate`). The canonical view normalises case, spaces, and hyphens before matching. A VIN fragment is also available as a secondary theft match field.

## Run it

```bash
python3 server.py
```

The report decisions are:

- `CLEAR`: valid registration and active policy at capture time.
- `INSURANCE_EXPIRED`: a policy exists but is not active on the capture date.
- `UNINSURED`: no policy matched the registered vehicle.
- `STOP_AND_REPORT`: an open theft case matched the vehicle.
- `REGISTRATION_REVIEW`: the registration exists but is not valid.
- `UNRESOLVED_IDENTITY`: the observation could not be matched to an authoritative registration.

## Trust and integration notes

- Raw source rows are retained; the canonical view never overwrites evidence.
- Every decision includes `decision_reason`, source identifiers, capture time, and camera ID.
- The gateway requests source snapshots over HTTP at query time; it does not open or merge remote database files.
- The sample data intentionally includes a capture-only vehicle to make unresolved identity explicit instead of silently treating it as uninsured.
- Production use would require authenticated source ingestion, schema/version metadata, encryption and access controls, retention rules, human review for high-impact actions, and a stronger identity-resolution model with confidence scores.

## Roadside webpage

The interface is a dependency-free field inspection prototype served by the local API with:

- live-style ANPR capture context and recent detections;
- plate lookup across the seeded vehicle states;
- clear, expired, uninsured, stolen, and unresolved decisions;
- source-by-source vehicle evidence; and
- Ministry reporting and inspection-hold actions with visible confirmation.

For the database-backed version, start the localhost service instead:

```bash
python3 source_service.py --source capture --host 0.0.0.0 --port 8101
python3 source_service.py --source insurance --host 0.0.0.0 --port 8102
python3 source_service.py --source registry --host 0.0.0.0 --port 8103
python3 source_service.py --source cases --host 0.0.0.0 --port 8104
python3 source_service.py --source ministry --host 0.0.0.0 --port 8105
python3 server.py
```

Then open `http://localhost:8000`. In deployment, run each `source_service.py` process on the laptop that owns that source database. The gateway fetches snapshots and forwards writes over HTTP; it does not open or attach the remote database files.

Set known laptop addresses on the gateway with environment variables before starting it:

```bash
CAPTURE_URL=http://192.168.1.21:8101 \
INSURANCE_URL=http://192.168.1.22:8102 \
REGISTRY_URL=http://192.168.1.23:8103 \
CASES_URL=http://192.168.1.24:8104 \
MINISTRY_URL=http://192.168.1.25:8105 \
python3 server.py
```

## Three-laptop deployment

Use three identical copies of this project folder. The copies contain the same code, but each source database is owned and changed by only one laptop. Do not open or copy another laptop's `.db` file.

Example allocation:

| Laptop | Run | Database owner |
| --- | --- | --- |
| 1 | `capture` and `insurance` source services | `source_databases/road_capture.db`, `insurance.db` |
| 2 | `registry` and `cases` source services | `source_databases/registry.db`, `cases.db` |
| 3 | `ministry` source service and the gateway | `source_databases/ministry.db` and the web UI |

On the master copy, run `python database_setup.py` once to create all five databases with the current schema. Copy this complete project folder, including the initialized `source_databases` folder, to the three laptops. Do not run `database_setup.py` on the destination laptops after copying, because it resets all five databases. Starting `source_service.py` later does not reset an existing database, so inserts and deletes survive service restarts.

The Manage data page now uses numeric controls for integer IDs, date controls for date fields, date-time controls for timestamps, dropdowns for status/type/severity values, and marks database-required fields with `*`. SQLite stores dates as ISO text (`YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS`) because SQLite has no native date type; the application controls the input format.

Laptop 1:

```powershell
python source_service.py --source capture --host 0.0.0.0 --port 8101
python source_service.py --source insurance --host 0.0.0.0 --port 8102
```

Laptop 2:

```powershell
python source_service.py --source registry --host 0.0.0.0 --port 8103
python source_service.py --source cases --host 0.0.0.0 --port 8104
```

Laptop 3:

```powershell
python source_service.py --source ministry --host 0.0.0.0 --port 8105
$env:GATEWAY_HOST = "0.0.0.0"
$env:CAPTURE_URL = "http://LAPTOP1-IP:8101"
$env:INSURANCE_URL = "http://LAPTOP1-IP:8102"
$env:REGISTRY_URL = "http://LAPTOP2-IP:8103"
$env:CASES_URL = "http://LAPTOP2-IP:8104"
$env:MINISTRY_URL = "http://LAPTOP3-IP:8105"
python server.py
```

Replace the three `LAPTOP*-IP` values with the LAN IPv4 addresses shown by `ipconfig`. Open `http://LAPTOP3-IP:8000` from any laptop on the same LAN. Allow Python through the private-network firewall, and keep ports 8000 and 8101-8105 available.

There should be three folders, one per laptop, rather than three different codebases or three different database copies. Only the source service that owns a database writes it. A change made in the UI is sent to that owner over HTTP; the next lookup requests fresh snapshots from all five owners, so the change is visible to every user immediately. Changes made directly in a database file will not appear safely until the owning service is running, so use the UI/API for shared updates.

For local development, the default URLs are `127.0.0.1:8101` through `127.0.0.1:8105`, which simulate five independent machines as five independent processes.

The site has four pages:

- `index.html`: roadside inspection and vehicle history.
- `help.html`: project explanation and live schema metadata from SQLite `PRAGMA`.
- `sql.html`: read-only `SELECT` or `WITH` queries across the attached databases, capped at 200 rows.
- `data.html`: source/action dropdowns that generate visible `INSERT` or `DELETE` SQL and execute only after confirmation.