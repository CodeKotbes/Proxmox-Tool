import threading
import uuid
from flask import Flask, jsonify, request, send_file

# Import modules
import config
from shared import JOBS
from proxmox_utils import get_proxmox_api
import tasks

app = Flask(__name__)

# --- ROUTES ---

@app.route("/")
def serve_index():
    try: 
        return send_file("index.html")
    except: 
        return "index.html missing", 404

@app.route("/api/storages", methods=["GET"])
def api_get_storages():
    proxmox = get_proxmox_api()
    if not proxmox:
        return jsonify({"error": "No connection"}), 500
    node = proxmox.nodes(config.NODE_NAME)
    storages = []
    try:
        for s in node.storage.get(content="images"): 
            if s.get("active") == 1:
                storages.append({
                    "id": s.get("storage"),
                    "type": s.get("type"),
                    "total": s.get("total"),
                    "used": s.get("used"),
                    "avail": s.get("avail")
                })
        return jsonify(storages)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/template", methods=["POST"])
def api_create_template():
    d = request.json
    jid = f"job-{uuid.uuid4().hex[:8]}"
    JOBS[jid] = {"status": "queued", "task": "TEMPLATE", "message": "Queued..."}
    
    # Start task in background thread
    threading.Thread(target=tasks.run_create_template_task, args=(
        jid, 
        d.get("vmid"), 
        d.get("name"), 
        d.get("image"), 
        d.get("storage")
    )).start()
    
    return jsonify({"status": "started", "job_id": jid}), 202

@app.route("/api/clone", methods=["POST"])
def api_clone_vm():
    d = request.json
    jid = f"job-{uuid.uuid4().hex[:8]}"
    JOBS[jid] = {"status": "queued", "task": "CLONE", "message": "Queued..."}
    
    # Start task in background thread
    threading.Thread(target=tasks.run_clone_task, args=(
        jid, 
        d.get("template_vmid"), 
        d.get("vm_name"), 
        d.get("cores"), 
        d.get("memory"), 
        d.get("disk_size"), 
        d.get("start_order"),
        d.get("tag"), 
        d.get("ci_user"), 
        d.get("ci_password"), 
        d.get("ssh_key"),
        d.get("ip_cidr"),
        d.get("gateway"),
        d.get("storage")
    )).start()
    return jsonify({"status": "started", "job_id": jid}), 202

@app.route("/api/redeploy", methods=["POST"])
def api_redeploy_vms():
    d = request.json
    jid = f"job-{uuid.uuid4().hex[:8]}"
    JOBS[jid] = {"status": "queued", "task": "REDEPLOY", "message": "Queued..."}
    
    # Start task in background thread
    threading.Thread(target=tasks.run_redeploy_task, args=(
        jid, 
        d.get("old_tag"), 
        d.get("new_template_id"), 
        d.get("new_tag")
    )).start()
    return jsonify({"status": "started", "job_id": jid}), 202

@app.route("/api/jobs", methods=["GET"])
def api_jobs(): 
    return jsonify(JOBS)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)