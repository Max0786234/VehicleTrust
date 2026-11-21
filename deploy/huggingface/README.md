---
title: VehicleTrust
emoji: 🚗
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
short_description: Federated vehicle verification across five databases
---

# VehicleTrust: live demo

VehicleTrust answers natural-language questions about a vehicle. It decomposes each question into subqueries for five
independent database services, runs them in parallel over REST, and follows foreign-key relationships inside each
database. It then resolves the vehicle across sources despite noisy plates, retrieves supporting documents, and
returns an answer in which every statement is tagged with its source.

In this demo, all five database services, the gateway and the dashboard run as separate processes in one container.
In the full setup they are split across two machines. All data is synthetic and resets when the Space restarts.
Plate OCR (EasyOCR/PyTorch) and the local LLM (Ollama) run only in the local installation.
