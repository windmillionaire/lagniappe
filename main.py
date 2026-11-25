from lagniappe.web import app


@app.route("/_ah/start")
def start() -> tuple[str, int]:
    return "OK", 200


@app.route("/_ah/warmup")
def warmup() -> tuple[str, int]:
    return "OK", 200


@app.route("/_ah/stop")
def stop() -> tuple[str, int]:
    return "OK", 200
