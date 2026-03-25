def classify_error(message: str):
    msg = message.lower()
    
    if "target page" in msg or "browser has been closed" in msg:
        return "BROWSER_CRASH"
        
    if "timeout" in msg:
        return "TIMEOUT"
        
    if "proxy" in msg:
        return "PROXY_ERROR"
        
    if "login" in msg:
        return "AUTH_ERROR"
        
    return "UNKNOWN"