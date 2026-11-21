"""VehicleTrust multi-machine launcher.

Two-laptop 2+3 deployment
  Laptop 1:  python start_node.py machine-1   -> Theft (8104), Audit (8105), Gateway (8000), Streamlit (8501)
  Laptop 2:  python start_node.py machine-2   -> Registry (8101), Insurance (8102), Registration (8103)
Single laptop (development / simulation)
             python start_node.py all         -> all five services + Gateway + Streamlit

Other commands
  python start_node.py init machine-2         initialize / migrate / seed ONLY that machine's databases
  python start_node.py init all --reset       back up and recreate all databases
  python start_node.py check                  health of every configured service URL (from .env)
  python start_node.py configure machine-1 --machine2-ip 192.168.1.50   write .env for Laptop 1
  python start_node.py package machine-2      clean project copy + zip for the teammate (dist/)
  python start_node.py package space          folder for the hosted demo (Hugging Face Space, Docker)
  python start_node.py registry|insurance|registration|theft|audit|frontend   one component only

Each machine only initializes and opens the SQLite files it owns; everything else is HTTP.
"""
import argparse
import datetime
import importlib
import os
import shutil
import socket
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
import config  # noqa: E402  (loads .env)

PYTHON_BIN = sys.executable
MACHINE_GROUPS = dict(config.MACHINE_GROUPS, local=config.MACHINE_GROUPS["machine-1"])  # "local" kept as alias
NODE_CONFIG = {
    spec["node"]: {"key": key, "service": spec["module"], "title": spec["label"], "db_env": spec["db_env"],
                   "db": spec["db_default"]}
    for key, spec in config.SERVICES.items()
}
CORE_DEPENDENCIES = ["fastapi", "uvicorn", "sqlalchemy", "pydantic", "httpx", "dotenv", "rapidfuzz"]
FRONTEND_DEPENDENCIES = ["streamlit", "pandas", "numpy", "pypdf"]
OPTIONAL_DEPENDENCIES = {"cv2": "OpenCV (image preprocessing for OCR)", "easyocr": "EasyOCR (plate OCR)"}
PACKAGE_EXCLUDE_DIRS = {".venv", "venv", "linux_venv", "__pycache__", ".pytest_cache", "backups", "dist", ".git",
                        ".idea", ".vscode"}
PACKAGE_EXCLUDE_EXT = {".db", ".db-journal", ".pyc", ".log", ".zip"}


def local_excludes() -> set:
    """File names listed in the repository's private exclude file (.git/info/exclude) are never packaged."""
    path = os.path.join(BASE_DIR, ".git", "info", "exclude")
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as fh:
        return {ln.strip() for ln in fh if ln.strip() and not ln.startswith("#") and not ln.strip().endswith("/")}


def banner(text: str) -> None:
    print("=" * 74)
    print(f"VehicleTrust - {text}")
    print("=" * 74)


def lan_addresses():
    addrs = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addrs.add(info[4][0])
    except OSError:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 80))  # no packet is sent; selects the outbound interface
        addrs.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(a for a in addrs if not a.startswith("127."))


# ----------------------------------------------------------------------------- checks
def check_dependencies(with_frontend: bool) -> None:
    required = CORE_DEPENDENCIES + (FRONTEND_DEPENDENCIES if with_frontend else [])
    missing = []
    for mod in required:
        try:
            importlib.import_module(mod)
        except Exception as exc:  # ImportError or a blocked DLL
            missing.append(f"{mod} ({type(exc).__name__}: {exc})")
    if missing:
        print("[Error] Missing or unloadable Python packages:")
        for m in missing:
            print(f"   - {m}")
        print(f"Install them with:  {PYTHON_BIN} -m pip install -r requirements.txt")
        sys.exit(1)
    if with_frontend:
        for mod, label in OPTIONAL_DEPENDENCIES.items():
            try:
                importlib.import_module(mod)
            except Exception:
                print(f"[Warn] Optional {label} not available - manual plate entry still works.")


def port_free(port: int, host: str) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host if host != "localhost" else "127.0.0.1", port))
            return True
        except OSError:
            return False


def ensure_ports_free(ports, host: str) -> None:
    busy = [p for p in ports if not port_free(p, host)]
    if busy:
        print(f"[Error] Port(s) already in use: {', '.join(map(str, busy))}")
        print("        Another VehicleTrust instance (or another program) is running.")
        print("        Find it:  netstat -ano | findstr :<port>      Stop it:  taskkill /PID <pid> /F")
        sys.exit(1)


def http_ok(url: str, timeout: float = 2.0):
    import httpx
    try:
        r = httpx.get(url, timeout=timeout)
        return r.status_code == 200, (r.json() if r.status_code == 200 else {"error": f"HTTP {r.status_code}"})
    except Exception as exc:
        return False, {"error": f"{type(exc).__name__}: {exc}"}


def wait_for(url: str, process: subprocess.Popen, label: str, timeout: float = 45.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            print(f"[Error] {label} exited during startup (code {process.returncode}). See the log above.")
            return False
        ok, _ = http_ok(url, 1.0)
        if ok:
            return True
        time.sleep(0.5)
    print(f"[Error] {label} did not become healthy within {timeout:.0f}s ({url}).")
    return False


# ----------------------------------------------------------------------------- init
def init_databases(group: str, reset: bool = False) -> None:
    from databases import initialize_database
    nodes = MACHINE_GROUPS[group] if group in MACHINE_GROUPS else [group]
    banner(f"Initializing databases for {group}: {', '.join(nodes)}")
    for node in nodes:
        key = NODE_CONFIG[node]["key"]
        try:
            initialize_database(key, config.db_path(key), reset=reset, verbose=True)
        except Exception as exc:
            print(f"[Error] Could not initialize {key} ({config.db_path(key)}): {exc}")
            print("        A pre-migration backup (if any) is in the backups/ folder.")
            sys.exit(1)


# ----------------------------------------------------------------------------- start
def child_env():
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def start_uvicorn(module: str, port: int, host: str) -> subprocess.Popen:
    cmd = [PYTHON_BIN, "-m", "uvicorn", f"{module}:app", "--host", host, "--port", str(port), "--log-level", "warning"]
    return subprocess.Popen(cmd, cwd=BASE_DIR, env=child_env())


def stop_all(processes) -> None:
    for label, proc in reversed(processes):
        if proc.poll() is None:
            proc.terminate()
    for label, proc in processes:
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
        print(f"[Stop] {label} stopped.")


def run_group(group: str, host: str, with_frontend: bool, skip_checks: bool) -> None:
    nodes = MACHINE_GROUPS[group] if group in MACHINE_GROUPS else ([group] if group in NODE_CONFIG else [])
    frontend = with_frontend and (group in config.GROUPS_WITH_FRONTEND or group in ("local", "frontend"))
    banner(f"Starting {group}" + (f" ({', '.join(nodes)})" if nodes else ""))
    if not skip_checks:
        check_dependencies(frontend)
        ports = [config.service_port(NODE_CONFIG[n]["key"]) for n in nodes]
        if frontend:
            ports += [config.GATEWAY_PORT, config.STREAMLIT_PORT]
        ensure_ports_free(ports, host)
    for node in nodes:
        key = NODE_CONFIG[node]["key"]
        from databases import initialize_database
        initialize_database(key, config.db_path(key), verbose=True)

    processes = []
    try:
        for node in nodes:
            key, module = NODE_CONFIG[node]["key"], NODE_CONFIG[node]["service"]
            port = config.service_port(key)
            print(f"[Start] {config.SERVICES[key]['label']:<24} port {port}  db={config.db_path(key)}")
            proc = start_uvicorn(module, port, host)
            processes.append((config.SERVICES[key]["label"], proc))
            if not wait_for(f"http://127.0.0.1:{port}/health", proc, config.SERVICES[key]["label"]):
                raise SystemExit(1)
            print(f"        healthy  -> http://127.0.0.1:{port}/health")

        if frontend:
            urls = config.service_urls()
            print("\n[Check] Database services as configured for the gateway (.env):")
            for key, url in urls.items():
                ok, info = http_ok(f"{url}/health", 2.0)
                where = "local" if any(NODE_CONFIG[n]["key"] == key for n in nodes) else "remote"
                state = f"ONLINE ({info.get('record_count')} rows)" if ok else f"UNREACHABLE - {info.get('error', '')[:70]}"
                print(f"   {config.SERVICES[key]['label']:<24} {where:<6} {url:<28} {state}")
            if not all(http_ok(f"{u}/health", 1.0)[0] for u in urls.values()):
                print("   -> Starting anyway: queries will report the unreachable services as unavailable (partial results).")
            print_llm_status()
            print(f"\n[Start] API Gateway               port {config.GATEWAY_PORT}")
            gw = start_uvicorn("gateway", config.GATEWAY_PORT, host)
            processes.append(("Gateway", gw))
            if not wait_for(f"http://127.0.0.1:{config.GATEWAY_PORT}/api/topology", gw, "Gateway"):
                raise SystemExit(1)
            print(f"[Start] Streamlit dashboard       port {config.STREAMLIT_PORT}")
            st_cmd = [PYTHON_BIN, "-m", "streamlit", "run", "app.py", "--server.port", str(config.STREAMLIT_PORT),
                      "--server.headless", "true", "--server.address", host, "--browser.gatherUsageStats", "false"]
            processes.append(("Streamlit", subprocess.Popen(st_cmd, cwd=BASE_DIR, env=child_env())))

        print("\n" + "-" * 74)
        print(f"{group} is running. LAN address(es) of this machine: {', '.join(lan_addresses()) or 'unknown'}")
        if frontend:
            print(f"   Streamlit dashboard : http://127.0.0.1:{config.STREAMLIT_PORT}")
            print(f"   Web UI / API gateway: http://127.0.0.1:{config.GATEWAY_PORT}   (docs: /docs)")
        if group == "machine-2":
            print("   On Laptop 1 run:  python start_node.py configure machine-1 --machine2-ip <one of the addresses above>")
        print("Keep this window open. Press Ctrl+C to stop all services on this machine.")
        print("-" * 74)
        while True:
            for label, proc in processes:
                if proc.poll() is not None:
                    raise RuntimeError(f"{label} exited unexpectedly with code {proc.returncode}")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[Stop] Ctrl+C received - shutting down...")
    except RuntimeError as exc:
        print(f"\n[Error] {exc}")
    finally:
        stop_all(processes)


# ----------------------------------------------------------------------------- check / configure / package
def check_services() -> int:
    banner("Service health check (URLs from .env / config.py)")
    failures = 0
    local_down, remote_down = [], []
    for key, url in config.service_urls().items():
        ok, info = http_ok(f"{url}/health", 3.0)
        failures += not ok
        if not ok:
            (local_down if ("127.0.0.1" in url or "localhost" in url) else remote_down).append(config.SERVICES[key]["label"])
        detail = f"{info.get('record_count')} hub rows, {info.get('table_count')} tables" if ok else info.get("error", "")
        print(f"  {'OK  ' if ok else 'FAIL'}  {config.SERVICES[key]['label']:<24} {url:<30} {detail}")
    gw = config.gateway_url()
    ok, _ = http_ok(f"{gw}/api/topology", 3.0)
    print(f"  {'OK  ' if ok else 'n/a '}  {'API Gateway':<24} {gw:<30} {'running' if ok else 'not running on this machine'}")
    print_llm_status()
    if local_down:
        print(f"\nNot running on THIS machine: {', '.join(local_down)} -> start them with "
              "'python start_node.py machine-1' (or 'all' on a single laptop).")
    if remote_down:
        print(f"\nUnreachable on the other laptop: {', '.join(remote_down)}. Is 'python start_node.py machine-2' running "
              "there? Same Wi-Fi? Firewall rule for ports 8101-8103? Correct IP in .env "
              "('python start_node.py configure machine-1 --machine2-ip <IP>')?")
    return 1 if failures else 0


def print_llm_status() -> None:
    """Optional local LLM (Ollama) used for query understanding; the rule-based parser is the fallback."""
    import asyncio
    from llm_understanding import ollama_status
    st = asyncio.run(ollama_status())
    url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    if st["mode"] == "off":
        print(f"  off   {'LLM (Ollama)':<24} {'LLM_UNDERSTANDING=off':<30} rule-based understanding only")
    elif not st["reachable"]:
        print(f"  n/a   {'LLM (Ollama)':<24} {url:<30} not running -> rule-based understanding (start Ollama to enable)")
    elif not st["model_installed"]:
        print(f"  WARN  {'LLM (Ollama)':<24} {st['model']:<30} model not downloaded: run 'ollama pull {st['model']}'")
    else:
        print(f"  OK    {'LLM (Ollama)':<24} {st['model']:<30} ready (query understanding)")


def env_text(group: str, machine2_ip: str = "", machine1_ip: str = "") -> str:
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"# VehicleTrust environment for {group} (generated {stamp} by start_node.py)", ""]
    if group == "machine-1":
        ip = machine2_ip or "LAPTOP2_IP"
        lines += ["# Laptop 1: Theft (8104), Audit (8105), Gateway (8000), Streamlit (8501) run HERE.",
                  "# Laptop 2 (teammate) runs Registry/Insurance/Registration; set its LAN IP below.",
                  f"MACHINE2_HOST={ip}",
                  f"REGISTRY_API_URL=http://{ip}:8101", f"INSURANCE_API_URL=http://{ip}:8102",
                  f"REGISTRATION_API_URL=http://{ip}:8103",
                  "THEFT_API_URL=http://127.0.0.1:8104", "AUDIT_API_URL=http://127.0.0.1:8105"]
    elif group == "machine-2":
        lines += ["# Laptop 2: Registry (8101), Insurance (8102), Registration Authority (8103) run HERE.",
                  "# The services bind 0.0.0.0, so Laptop 1 reaches them at this laptop's LAN IP.",
                  "# No remote URLs are needed on this machine.",
                  "REGISTRY_PORT=8101", "INSURANCE_PORT=8102", "REGISTRATION_PORT=8103"]
        if machine1_ip:
            lines += ["", "# Optional dashboard on this laptop ('python start_node.py frontend'):",
                      "# its gateway reaches Theft/Audit on Laptop 1.",
                      f"MACHINE1_HOST={machine1_ip}",
                      "REGISTRY_API_URL=http://127.0.0.1:8101", "INSURANCE_API_URL=http://127.0.0.1:8102",
                      "REGISTRATION_API_URL=http://127.0.0.1:8103",
                      f"THEFT_API_URL=http://{machine1_ip}:8104", f"AUDIT_API_URL=http://{machine1_ip}:8105"]
    else:
        lines += ["# Single laptop: every service on localhost.",
                  "REGISTRY_API_URL=http://127.0.0.1:8101", "INSURANCE_API_URL=http://127.0.0.1:8102",
                  "REGISTRATION_API_URL=http://127.0.0.1:8103", "THEFT_API_URL=http://127.0.0.1:8104",
                  "AUDIT_API_URL=http://127.0.0.1:8105"]
    if group in ("machine-1", "all"):
        lines += ["", "# Optional local LLM for query understanding (rules are used if Ollama is not running)",
                  "LLM_UNDERSTANDING=auto", "OLLAMA_URL=http://127.0.0.1:11434", "OLLAMA_MODEL=llama3.2"]
    lines += ["", "# Optional: FEDERATION_TIMEOUT=4.0  (seconds per remote subquery)"]
    return "\n".join(lines) + "\n"


def configure(group: str, machine2_ip: str, machine1_ip: str) -> None:
    if group == "machine-1" and not machine2_ip:
        print("[Error] machine-1 needs Laptop 2's address:  python start_node.py configure machine-1 --machine2-ip 192.168.x.y")
        sys.exit(1)
    target = os.path.join(BASE_DIR, ".env")
    if os.path.exists(target):
        backup = target + ".bak"
        shutil.copy2(target, backup)
        print(f"[Config] Previous .env saved as {backup}")
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(env_text(group, machine2_ip, machine1_ip))
    print(f"[Config] Wrote {target} for {group}:")
    print(env_text(group, machine2_ip, machine1_ip))
    if group == "machine-1":
        print("Verify with:  python start_node.py check")


def package(group: str, out_dir: str, with_data: bool, machine2_ip: str) -> str:
    if group not in ("machine-1", "machine-2", "all", "space"):
        print("[Error] package expects machine-1, machine-2, all or space")
        sys.exit(1)
    dest_root = os.path.abspath(out_dir or os.path.join(BASE_DIR, "dist"))
    dest = os.path.join(dest_root, f"VehicleTrust-{group}")
    if os.path.exists(dest):
        shutil.rmtree(dest)
    skip_names = {".env", ".env.bak"} | local_excludes()
    for dirpath, dirnames, filenames in os.walk(BASE_DIR):
        dirnames[:] = [d for d in dirnames if d not in PACKAGE_EXCLUDE_DIRS and (d == ".streamlit" or not d.startswith("."))]
        if os.path.abspath(dirpath).startswith(dest_root):
            continue
        rel = os.path.relpath(dirpath, BASE_DIR)
        for name in filenames:
            if os.path.splitext(name)[1].lower() in PACKAGE_EXCLUDE_EXT or name in skip_names:
                continue
            if group == "space" and rel == "docs" and name.lower().endswith(".pdf"):
                continue  # personal study guide; not part of the public demo
            target_dir = os.path.join(dest, rel)
            os.makedirs(target_dir, exist_ok=True)
            shutil.copy2(os.path.join(dirpath, name), os.path.join(target_dir, name))
    if group == "space":  # Hugging Face Space (Docker SDK): the Space card replaces the GitHub README
        shutil.copy2(os.path.join(BASE_DIR, "deploy", "huggingface", "README.md"), os.path.join(dest, "README.md"))
        print(f"[Package] space: folder {dest}")
        print(f"[Package] upload it with:  hf upload <your-hf-username>/VehicleTrust \"{dest}\" . --repo-type=space")
        return dest
    copied_dbs = []
    if with_data:
        for node in MACHINE_GROUPS[group]:
            key = NODE_CONFIG[node]["key"]
            src = config.db_path(key)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(dest, os.path.basename(src)))
                copied_dbs.append(os.path.basename(src))
    with open(os.path.join(dest, ".env"), "w", encoding="utf-8") as fh:
        fh.write(env_text(group, machine2_ip))
    nodes = MACHINE_GROUPS[group]
    with open(os.path.join(dest, "DEPLOYMENT_ROLE.txt"), "w", encoding="utf-8") as fh:
        fh.write(f"VehicleTrust deployment copy for {group}\nServices: {', '.join(nodes)}\n"
                 f"Database files included: {', '.join(copied_dbs) or 'none (created from seed data on first start)'}\n\n"
                 f"1. python -m pip install -r requirements.txt\n2. python start_node.py init {group}\n"
                 f"3. python start_node.py {group}\nSee docs/DISTRIBUTED_SETUP.md\n")
    archive = shutil.make_archive(dest, "zip", root_dir=dest_root, base_dir=os.path.basename(dest))
    print(f"[Package] {group}: folder {dest}")
    print(f"[Package] {group}: zip    {archive}")
    print(f"[Package] databases included: {copied_dbs or 'none'} (each machine owns only its own DB files)")
    return dest


def main() -> None:
    os.chdir(BASE_DIR)
    try:  # show launcher output immediately even when redirected to a file
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass
    start_targets = sorted(set(MACHINE_GROUPS) | set(NODE_CONFIG) | {"frontend"})
    parser = argparse.ArgumentParser(description="VehicleTrust multi-machine launcher",
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("command", choices=start_targets + ["init", "check", "configure", "package"])
    parser.add_argument("group", nargs="?", help="machine group for init / configure / package")
    parser.add_argument("--host", default="0.0.0.0", help="bind address for services (default 0.0.0.0 = all interfaces)")
    parser.add_argument("--reset", action="store_true", help="init: back up and recreate the databases")
    parser.add_argument("--machine2-ip", default="", help="configure/package: Laptop 2 LAN IP")
    parser.add_argument("--machine1-ip", default="", help="configure: Laptop 1 LAN IP (optional)")
    parser.add_argument("--out", default="", help="package: output folder (default dist/)")
    parser.add_argument("--with-data", action="store_true", help="package: include this machine's current DB files")
    parser.add_argument("--no-ui", action="store_true", help="start services without gateway/Streamlit")
    parser.add_argument("--skip-checks", action="store_true", help="skip dependency and port checks")
    args = parser.parse_args()

    if args.command == "init":
        init_databases(args.group or "all", args.reset)
    elif args.command == "check":
        sys.exit(check_services())
    elif args.command == "configure":
        configure(args.group or "all", args.machine2_ip, args.machine1_ip)
    elif args.command == "package":
        package(args.group or "machine-2", args.out, args.with_data, args.machine2_ip)
    elif args.command == "frontend":
        run_group("frontend", args.host, True, args.skip_checks)
    else:
        run_group(args.command, args.host, not args.no_ui, args.skip_checks)


if __name__ == "__main__":
    main()
