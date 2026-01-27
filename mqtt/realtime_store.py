import threading

_lock = threading.Lock()

latest = {
    "R": {},
    "S": {},
    "T": {}
}

def update(phase, data):
    with _lock:
        latest[phase] = data

def get_all():
    with _lock:
        return latest.copy()
