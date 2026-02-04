from threading import Lock

_store = {}
_lock = Lock()

def update(building_code: str, phase: str, data: dict):
    with _lock:
        if building_code not in _store:
            _store[building_code] = {}

        _store[building_code][phase] = data


def get_by_building(building_code: str):
    with _lock:
        return _store.get(building_code, {})


def get_all():
    with _lock:
        return _store.copy()
