from datetime import datetime
from zoneinfo import ZoneInfo

WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def format_today() -> str:
    # The sandbox container's system clock runs in UTC, not China time -- this skill is
    # Chinese-language-facing, so the date must be computed in Asia/Shanghai (UTC+8) explicitly,
    # or it would silently show yesterday's date for roughly 16:00-24:00 Beijing time every day.
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    weekday = WEEKDAYS[now.weekday()]
    return f"{now.strftime('%Y年%m月%d日')} {weekday}"


if __name__ == "__main__":
    print(format_today())
