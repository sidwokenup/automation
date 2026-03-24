from enum import Enum, auto

class ErrorType(Enum):
    AUTH = auto()
    RATE_LIMIT = auto()
    CAPTCHA = auto()
    NETWORK = auto()
    SELECTOR = auto()
    UNKNOWN = auto()

def classify_error(error_msg: str) -> ErrorType:
    """Classifies an error message into a specific ErrorType."""
    if not error_msg:
        return ErrorType.UNKNOWN
        
    error_msg = str(error_msg).lower()
    
    if any(keyword in error_msg for keyword in ["login failed", "invalid credentials", "unauthorized", "wrong password"]):
        return ErrorType.AUTH
        
    if any(keyword in error_msg for keyword in ["too many requests", "rate limit", "wait", "cooldown", "429"]):
        return ErrorType.RATE_LIMIT
        
    if any(keyword in error_msg for keyword in ["captcha", "challenge", "bot detection", "cloudflare", "verify you are human"]):
        return ErrorType.CAPTCHA
        
    if any(keyword in error_msg for keyword in ["network", "timeout", "disconnected", "connrefused", "econnreset", "net::"]):
        return ErrorType.NETWORK
        
    if any(keyword in error_msg for keyword in ["selector", "not found", "element", "locator", "waiting for locator", "failed to find", "is not visible"]):
        return ErrorType.SELECTOR
        
    return ErrorType.UNKNOWN
