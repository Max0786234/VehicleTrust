# Two-Laptop Setup (2 + 3 split)

| Laptop | Runs | Ports | Owns DB files |
|---|---|---|---|
| **Laptop 1** (you) | Theft & Scrapping, Audit Log, Gateway, Streamlit | 8104, 8105, 8000, 8501 | `theft_scrapping.db`, `audit_log.db` |
| **Laptop 2** (teammate) | Vehicle Registry, Insurance, Registration Authority | 8101, 8102, 8103 | `vehicle_registry.db`, `insurance_records.db`, `registration_authority.db` |

All traffic between the laptops is HTTP/JSON. No SQLite file is shared or copied during operation.
Laptop 1's master folder keeps all five database definitions and seed data; `machine-1` simply never
opens the three Laptop-2 files.

All commands are PowerShell, run inside the project folder.

---

## 1. Prepare the teammate's copy (on Laptop 1)
```powershell
cd C:\Users\<you>\Downloads\VehicleTrust
python start_node.py package machine-2
```
This creates `dist\VehicleTrust-machine-2\` and `dist\VehicleTrust-machine-2.zip`: the whole code base,
documents and docs, **without** any `.db` file, virtualenv or backups, plus a `.env` and `DEPLOYMENT_ROLE.txt`.
Laptop 2 creates its three databases from the seed data. To ship the *current* contents of those three
databases instead, use `python start_node.py package machine-2 --with-data`.

Give the zip to the teammate (USB stick, shared drive, e-mail).

## 2. Laptop 2 (teammate)
```powershell
Expand-Archive .\VehicleTrust-machine-2.zip -DestinationPath C:\VehicleTrust
cd C:\VehicleTrust\VehicleTrust-machine-2

python --version                                   # Python 3.x must be installed (tested with 3.14)
python -m venv .venv                               # recommended
.\.venv\Scripts\Activate.ps1                       # if blocked: Set-ExecutionPolicy -Scope Process Bypass
python -m pip install -r requirements.txt

python start_node.py init machine-2                # creates the 3 databases (5 tables each)
ipconfig                                           # note the IPv4 address of the Wi-Fi adapter, e.g. 192.168.1.50
```
Allow the three ports through Windows Firewall (**PowerShell as Administrator**, once):
```powershell
New-NetFirewallRule -DisplayName "VehicleTrust Laptop2 APIs" -Direction Inbound -Protocol TCP -LocalPort 8101,8102,8103 -Action Allow -Profile Private,Domain
Get-NetConnectionProfile                           # NetworkCategory should be Private; otherwise:
# Set-NetConnectionProfile -InterfaceAlias "Wi-Fi" -NetworkCategory Private
```
Start the services and keep the window open:
```powershell
python start_node.py machine-2
```
The launcher checks dependencies and ports, initializes the databases, waits until every service answers
`/health`, then prints this laptop's LAN addresses.

> If `pip`/imports fail with *"An Application Control policy has blocked this file"*, Windows Smart App
> Control is blocking DLLs inside the venv. Skip the venv and install for the user instead:
> `python -m pip install --user -r requirements.txt`, then run the same commands with plain `python`.

## 3. Laptop 1 (you)
```powershell
cd C:\Users\<you>\Downloads\VehicleTrust
python -m pip install -r requirements.txt          # (or the venv variant above)
python -m pip install -r requirements-ocr.txt      # optional: plate-image OCR (EasyOCR + PyTorch)

python start_node.py init machine-1                # migrates/creates theft + audit databases (non-destructive)
python start_node.py configure machine-1 --machine2-ip 192.168.1.50
```
`configure` backs up the old `.env` to `.env.bak` and writes:
```dotenv
MACHINE2_HOST=192.168.1.50
REGISTRY_API_URL=http://192.168.1.50:8101
INSURANCE_API_URL=http://192.168.1.50:8102
REGISTRATION_API_URL=http://192.168.1.50:8103
THEFT_API_URL=http://127.0.0.1:8104
AUDIT_API_URL=http://127.0.0.1:8105
```
Optional, to let the teammate open your dashboard (Administrator):
```powershell
New-NetFirewallRule -DisplayName "VehicleTrust Laptop1 UI" -Direction Inbound -Protocol TCP -LocalPort 8000,8501 -Action Allow -Profile Private,Domain
```

## 4. Verify the connection (on Laptop 1)
```powershell
Test-NetConnection 192.168.1.50 -Port 8101         # TcpTestSucceeded : True
curl.exe http://192.168.1.50:8101/health
python start_node.py check                         # every remote service must show OK
```
Then start Laptop 1:
```powershell
python start_node.py machine-1
```
Open **http://127.0.0.1:8501** → *0. Federated Query (Phase 3)*. *1. Service Health* shows all five
services; the *Federated execution* tab shows each subquery's URL (`192.168.1.50:810x` = Laptop 2).
The teammate can open `http://<LAPTOP1_IP>:8501` if the optional firewall rule was added.

## 5. Daily use
```powershell
# Laptop 2
python start_node.py machine-2
# Laptop 1 (after Laptop 2 is up)
python start_node.py machine-1
```
If Laptop 2 received a new IP (DHCP), rerun `python start_node.py configure machine-1 --machine2-ip <new IP>`.
Stop with **Ctrl+C** in each window (all child services are stopped). Laptop 1 still starts if Laptop 2
is down: queries then report those services as unavailable instead of guessing.

## 5b. Dashboard on Laptop 2 as well (optional)
Option 1, simplest: on Laptop 2 open `http://<LAPTOP1_IP>:8501` in a browser. This needs the optional
"VehicleTrust Laptop1 UI" firewall rule on Laptop 1.

Option 2: Laptop 2 runs its own gateway and Streamlit, which federate across both laptops. Its databases
stay on Laptop 2 and Theft/Audit stay on Laptop 1.
```powershell
# Laptop 1 (Administrator, once): let Laptop 2's gateway reach Theft and Audit
New-NetFirewallRule -DisplayName "VehicleTrust Laptop1 APIs" -Direction Inbound -Protocol TCP -LocalPort 8104,8105 -Action Allow -Profile Private,Domain
# Laptop 2, once:
python start_node.py configure machine-2 --machine1-ip <LAPTOP1_IP>
# Laptop 2, every time: window 1
python start_node.py machine-2
# Laptop 2, every time: window 2
python start_node.py frontend          # then open http://127.0.0.1:8501 on Laptop 2
```
Both dashboards see the same data. Cleansing decisions made on either one update Laptop 2's registry
and Laptop 1's audit log.

## 6. Single-laptop simulation (before the second laptop is available)
Automated (real processes, two package copies, LAN IP when reachable, alternate ports 181xx):
```powershell
python -m pytest tests/test_distributed_simulation.py -v
```
Manual, with the real ports on one PC:
```powershell
python start_node.py package machine-2 --out C:\sim\laptop2
python start_node.py package machine-1 --out C:\sim\laptop1
# window A
cd C:\sim\laptop2\VehicleTrust-machine-2; python start_node.py machine-2
# window B (use this PC's own IPv4 from ipconfig)
cd C:\sim\laptop1\VehicleTrust-machine-1; python start_node.py configure machine-1 --machine2-ip 192.168.x.y; python start_node.py machine-1
```
Single laptop without any split: `python start_node.py all`.

## 7. Troubleshooting
| Symptom | Cause / fix |
|---|---|
| `Port(s) already in use: 8101` | Another instance is running. `netstat -ano \| findstr :8101` then `taskkill /PID <pid> /F`. |
| `check` shows Laptop-2 services `ConnectError`/timeout | Wrong IP in `.env` (rerun `configure`), Laptop 2 not running `machine-2`, laptops on different networks, or firewall. |
| `Test-NetConnection ... TcpTestSucceeded: False` but Laptop 2 is running | Firewall rule missing or network profile is *Public*; guest/campus Wi-Fi with client isolation (use a phone hotspot). |
| `check` says theft/audit "Not running on THIS machine" | Start `python start_node.py machine-1` (or `all`). |
| Query shows services *unavailable* / insurance *UNVERIFIED* | Expected partial-result behaviour when Laptop 2 is down; nothing is inferred from missing data. |
| `Missing or unloadable Python packages` | `python -m pip install -r requirements.txt` (or `--user`, see the note above). |
| Database initialization error | The message names the file; the pre-migration copy is in `backups\`. To start over: `python start_node.py init machine-2 --reset` (backs up first). |
| OCR says EasyOCR unavailable | Install `requirements-ocr.txt` on Laptop 1, or type the plate manually. |
| SQL console: "file is not on this machine" | The console reads only local files; use *9. Database Schemas & FK-PK*, which works over REST. |
