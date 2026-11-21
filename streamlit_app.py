"""Entry point for the hosted demo on Streamlit Community Cloud.

Community Cloud runs a single Streamlit app, so this file first starts the five database services and the gateway
as separate background processes on localhost (they still talk to each other only over HTTP), then renders the
normal dashboard (app.py). Local and two-laptop runs use start_node.py instead and never import this file.
"""
import os
import sys

# Demo settings must be in place before config is imported anywhere.
os.environ.setdefault("VEHICLETRUST_DEMO", "1")
os.environ.setdefault("VEHICLETRUST_KEEP_ENV", "1")
os.environ.setdefault("LLM_UNDERSTANDING", "off")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import runpy  # noqa: E402

import streamlit as st  # noqa: E402

import config  # noqa: E402


@st.cache_resource(show_spinner="Starting the five database services and the gateway (first visit only, about 30 seconds)...")
def start_backend():
    """Starts once per server process: initialise the databases, then each service and the gateway."""
    import start_node
    from databases import initialize_database

    processes = []
    for key in config.ALL_SERVICE_KEYS:
        initialize_database(key, config.db_path(key))
    for key in config.ALL_SERVICE_KEYS:
        port = config.service_port(key)
        proc = start_node.start_uvicorn(config.SERVICES[key]["module"], port, "127.0.0.1")
        processes.append(proc)
        if not start_node.wait_for(f"http://127.0.0.1:{port}/health", proc, config.SERVICES[key]["label"], 90):
            raise RuntimeError(f"{config.SERVICES[key]['label']} did not start")
    gw = start_node.start_uvicorn("gateway", config.GATEWAY_PORT, "127.0.0.1")
    processes.append(gw)
    if not start_node.wait_for(f"http://127.0.0.1:{config.GATEWAY_PORT}/api/topology", gw, "Gateway", 120):
        raise RuntimeError("Gateway did not start")
    return processes


def backend_alive(processes) -> bool:
    return all(p.poll() is None for p in processes)


procs = start_backend()
if not backend_alive(procs):  # a service crashed or the container was recycled: start again
    start_backend.clear()
    procs = start_backend()

runpy.run_path(os.path.join(BASE_DIR, "app.py"), run_name="__main__")
