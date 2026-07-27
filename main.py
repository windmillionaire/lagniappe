from lagniappe.web import app


@app.route("/_ah/start")
def start():
    return "OK", 200


@app.route("/_ah/warmup")
def warmup():
    return "OK", 200


@app.route("/_ah/stop")
def stop():
    return "OK", 200
