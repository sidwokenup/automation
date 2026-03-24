from enum import Enum, auto
from telegram_bot.intelligence.error_classifier import ErrorType

class ActionType(Enum):
    STOP = auto()
    WAIT = auto()
    RETRY = auto()
    SELF_HEAL = auto()

def decide_action(error_type: ErrorType) -> ActionType:
    """Decides the best action based on the error type."""
    mapping = {
        ErrorType.AUTH: ActionType.STOP,
        ErrorType.RATE_LIMIT: ActionType.WAIT,
        ErrorType.CAPTCHA: ActionType.STOP,
        ErrorType.NETWORK: ActionType.RETRY,
        ErrorType.SELECTOR: ActionType.SELF_HEAL,
        ErrorType.UNKNOWN: ActionType.RETRY,
    }
    return mapping.get(error_type, ActionType.RETRY)

def get_user_friendly_message(error_type: ErrorType, details: str = "") -> str:
    """Returns a user-friendly message based on the error type."""
    if error_type == ErrorType.AUTH:
        return (
            "❌ *Login Failed*\n\n"
            "Possible reasons:\n"
            "• Invalid credentials\n"
            "• Password changed\n\n"
            "💡 *Recommendation:*\n"
            "Please check your credentials and try again."
        )
    elif error_type == ErrorType.RATE_LIMIT:
        return (
            "⚠️ *Rate Limited*\n\n"
            "The system is receiving too many requests.\n"
            "Applying a temporary cooldown. The bot will wait before retrying."
        )
    elif error_type == ErrorType.CAPTCHA:
        return (
            "🛑 *CAPTCHA Detected*\n\n"
            "The platform detected bot activity and presented a CAPTCHA.\n"
            "Automation has been paused to protect your account."
        )
    elif error_type == ErrorType.NETWORK:
        return "📡 *Network Issue*\n\nTemporary connectivity problem detected. Will retry automatically."
    elif error_type == ErrorType.SELECTOR:
        return "🔍 *UI Element Not Found*\n\nThe platform interface may have changed. Triggering AI self-healing..."
    
    return f"⚠️ *Unknown Error*\n\nDetails: {details}\n\nRetrying automatically..."
