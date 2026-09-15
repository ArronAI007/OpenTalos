"""
日期查询技能脚本
"""

from datetime import datetime


def get_current_date() -> dict:
    """
    获取当前日期
    
    Returns:
        包含当前日期的字典
    """
    now = datetime.now()
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    weekday = weekdays[now.weekday()]
    
    return {
        "date": now.strftime("%Y-%m-%d"),
        "weekday": weekday,
        "formatted": now.strftime("%Y年%m月%d日") + f" {weekday}",
        "year": now.year,
        "month": now.month,
        "day": now.day,
    }


def main():
    """主函数"""
    result = get_current_date()
    print(f"当前日期: {result['formatted']}")
    return result


if __name__ == "__main__":
    main()
