from datetime import datetime, timezone, timedelta

# Zone Waktu Indonesia Barat (WIB) UTC+7
WIB = timezone(timedelta(hours=7))

def get_jakarta_now() -> datetime:
    """Mengembalikan datetime saat ini dalam zona waktu WIB (UTC+7)"""
    return datetime.now(WIB)
