from flask import Flask, jsonify, render_template_string
from datetime import datetime
from cache import cache_get
from logger_setup import system_log

app = Flask(__name__)

_signal_engine = None
_structure_engine = None
_data_store = None

def attach_engines(signal_engine, structure_engine, data_store):
    global _signal_engine, _structure_engine, _data_store
    _signal_engine = signal_engine
    _structure_engine = structure_engine
    _data_store = data_store

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>Nifty Institutional Bot – Signal Board</title>
<style>
body { font-family: Arial; background: #111; color: #eee; padding: 20px; }
.signal-box { background: #222; padding: 20px; border-radius: 8px; margin: 10px 0; border-left: 4px solid #f90; }
.status { display: inline-block; padding: 5px 10px; border-radius: 4px; }
.buy { background: #0a0; color: #fff; }
.sell { background: #a00; color: #fff; }
.neutral { background: #555; color: #fff; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.health-box { background: #1a1a1a; padding: 10px; border-radius: 4px; margin-top: 10px; }
</style>
</head>
<body>
<h1>📊 Nifty Institutional Bot – Signal Intelligence</h1>
<p>Last updated: {{ last_update }}</p>
<div class="grid">
  <div><h3>Market</h3><pre>{{ market_data | tojson(indent=2) }}</pre></div>
  <div><h3>Structure</h3><pre>{{ structure | tojson(indent=2) }}</pre></div>
</div>
<div class="signal-box">
  <h2>Latest Signal</h2>
  {% if signal %}
    <p><strong>Direction:</strong> <span class="status {{ 'buy' if signal.direction == 'BUY' else 'sell' }}">{{ signal.direction }}</span></p>
    <p><strong>Entry:</strong> {{ signal.entry }}</p>
    <p><strong>SL:</strong> {{ signal.sl }}</p>
    <p><strong>TP:</strong> {{ signal.tp }}</p>
    <p><strong>RR:</strong> {{ signal.rr }}</p>
    <p><strong>Confidence:</strong> {{ signal.confidence }}</p>
    <p><strong>Reason:</strong> {{ signal.reason }}</p>
    <p><strong>Layers:</strong> {{ signal.layers | join(', ') }}</p>
  {% else %}
    <p><em>No active signal – waiting for structure to align.</em></p>
  {% endif %}
</div>
<div class="health-box">
  <h3>Engine Health</h3>
  <ul>
  {% for name, status in health.modules.items() %}
    <li>{{ name }}: {{ status }}</li>
  {% endfor %}
    <li>CPU: {{ health.cpu }}%</li>
    <li>Memory: {{ health.memory }} MB</li>
    <li>DB Size: {{ health.db_size_mb }} MB</li>
  </ul>
</div>
</body>
</html>
"""

@app.route("/")
def index():
    sig = _signal_engine.get_last_signal() if _signal_engine else None
    struct = _structure_engine.get_structure("NIFTY") if _structure_engine else None
    mkt = _data_store.get("NIFTY") if _data_store else {}
    health = cache_get("health_status") or {"modules": {}, "cpu": 0, "memory": 0, "db_size_mb": 0}
    return render_template_string(HTML_TEMPLATE,
                                   signal=sig.to_dict() if sig else None,
                                   structure=struct.to_dict() if struct else None,
                                   market_data=mkt,
                                   health=health,
                                   last_update=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

@app.route("/api/signal")
def api_signal():
    if _signal_engine:
        sig = _signal_engine.get_last_signal()
        return jsonify(sig.to_dict() if sig else {})
    return jsonify({})

@app.route("/api/structure")
def api_structure():
    if _structure_engine:
        struct = _structure_engine.get_structure("NIFTY")
        return jsonify(struct.to_dict())
    return jsonify({})

@app.route("/api/health")
def api_health():
    health = cache_get("health_status") or {}
    return jsonify(health)

def run_dashboard():
    app.run(host="0.0.0.0", port=8080, debug=False)
