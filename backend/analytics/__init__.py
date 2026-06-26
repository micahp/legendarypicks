"""Analytics compute for M7 — EV, CLV, calibration.

Pure-Python compute consumed by the FastAPI endpoints in sports_service.py.
SQL stays thin in the service layer; the math lives here (design §7.2).
"""
