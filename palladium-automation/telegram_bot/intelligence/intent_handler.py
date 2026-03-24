def detect_intent(message: str) -> str:
    msg = message.lower().strip()

    if "delete proxy" in msg or "remove proxy" in msg or "clear proxy" in msg:
        return "DELETE_PROXY"

    if "delete setup" in msg or "remove setup" in msg or "clear setup" in msg:
        return "DELETE_SETUP"

    if msg in ["hi", "hey", "hello", "start"]:
        return "GREETING"

    return "UNKNOWN"