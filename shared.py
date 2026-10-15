import threading
import time

_lock = threading.Lock()
_pending = {}     
_decisions = {}  
_log = []        


def submit(thread_id, payload):
    with _lock:
        _pending[thread_id] = payload


def cancel(thread_id):
    with _lock:
        _pending.pop(thread_id, None)
        _decisions.pop(thread_id, None)


def list_pending():
    with _lock:
        return list(_pending.items())


def decide(thread_id, approved, approver="supervisor"):
    with _lock:
        payload = _pending.pop(thread_id, None)
        if payload is None:          # already handled
            return
        _decisions[thread_id] = {"approved": approved, "approver": approver}
        _log.insert(0, {"order_id": payload["order_id"], "amount": payload["amount"],
                        "approved": approved, "time": time.strftime("%H:%M:%S")})
        del _log[20:]


def take_decision(thread_id):
    with _lock:
        return _decisions.pop(thread_id, None)


def recent():
    with _lock:
        return list(_log)