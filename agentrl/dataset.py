"""内置的小型数学应用题 demo 数据集——不依赖 datasets 库下载任何外部数据，
SFT 用 (question, solution) 做有标注微调，GRPO 只用 (question, answer) 配合奖励函数。"""

DEMO_PROBLEMS: list[dict[str, str]] = [
    {"question": "小明有3个苹果，又买了5个，一共有多少个苹果？", "answer": "8", "solution": "3 + 5 = 8"},
    {"question": "小红有10颗糖，吃掉了4颗，还剩多少颗？", "answer": "6", "solution": "10 - 4 = 6"},
    {"question": "一个班有6个小组，每组5人，一共多少人？", "answer": "30", "solution": "6 * 5 = 30"},
    {"question": "24个苹果平均分给4个人，每人分几个？", "answer": "6", "solution": "24 / 4 = 6"},
    {"question": "小刚有7元钱，妈妈又给了他8元，他现在有多少钱？", "answer": "15", "solution": "7 + 8 = 15"},
    {"question": "书架上有20本书，借走了7本，还剩多少本？", "answer": "13", "solution": "20 - 7 = 13"},
    {"question": "一辆车每小时行驶60千米，行驶3小时能走多远？", "answer": "180", "solution": "60 * 3 = 180"},
    {"question": "36个橘子装进6个篮子，平均每个篮子装几个？", "answer": "6", "solution": "36 / 6 = 6"},
    {"question": "小丽有12支铅笔，又买了9支，一共多少支？", "answer": "21", "solution": "12 + 9 = 21"},
    {"question": "停车场有45辆车，开走了18辆，还剩多少辆？", "answer": "27", "solution": "45 - 18 = 27"},
    {"question": "一箱牛奶有12瓶，5箱一共多少瓶？", "answer": "60", "solution": "12 * 5 = 60"},
    {"question": "48颗糖平均分给8个小朋友，每人分几颗？", "answer": "6", "solution": "48 / 8 = 6"},
    {"question": "小王有25元，买东西花了9元，还剩多少钱？", "answer": "16", "solution": "25 - 9 = 16"},
    {"question": "操场上有14个男生和11个女生，一共多少人？", "answer": "25", "solution": "14 + 11 = 25"},
    {"question": "一个盒子装8支笔，7个盒子一共多少支笔？", "answer": "56", "solution": "8 * 7 = 56"},
    {"question": "63本书平均放进7个书架，每个书架放几本？", "answer": "9", "solution": "63 / 7 = 9"},
    {"question": "小张有16个玩具，弟弟又给了他5个，他现在有多少个？", "answer": "21", "solution": "16 + 5 = 21"},
    {"question": "水池里有50条鱼，捞走了22条，还剩多少条？", "answer": "28", "solution": "50 - 22 = 28"},
    {"question": "每排种9棵树，种了4排，一共种了多少棵？", "answer": "36", "solution": "9 * 4 = 36"},
    {"question": "72个鸡蛋装进9个盒子，每个盒子装几个？", "answer": "8", "solution": "72 / 9 = 8"},
    {"question": "小陈有18元，姐姐又给了他6元，他现在有多少钱？", "answer": "24", "solution": "18 + 6 = 24"},
    {"question": "停车场原有60辆车，开走了35辆，还剩多少辆？", "answer": "25", "solution": "60 - 35 = 25"},
    {"question": "一盒巧克力有6块，8盒一共多少块？", "answer": "48", "solution": "6 * 8 = 48"},
    {"question": "54支铅笔平均分给6个学生，每人分几支？", "answer": "9", "solution": "54 / 6 = 9"},
    {"question": "小林有9本漫画书，又买了13本，一共多少本？", "answer": "22", "solution": "9 + 13 = 22"},
    {"question": "果园里有40棵果树，砍掉了12棵，还剩多少棵？", "answer": "28", "solution": "40 - 12 = 28"},
    {"question": "一辆货车每次装7吨货物，运5次一共运多少吨？", "answer": "35", "solution": "7 * 5 = 35"},
    {"question": "81颗珠子平均穿成9条项链，每条用几颗？", "answer": "9", "solution": "81 / 9 = 9"},
    {"question": "小周有30元，花了12元买文具，还剩多少钱？", "answer": "18", "solution": "30 - 12 = 18"},
    {"question": "图书馆有28个男生和19个女生在看书，一共多少人？", "answer": "47", "solution": "28 + 19 = 47"},
    {"question": "一箱苹果有15个，4箱一共多少个？", "answer": "60", "solution": "15 * 4 = 60"},
    {"question": "42块糖平均分给6个小朋友，每人分几块？", "answer": "7", "solution": "42 / 6 = 7"},
    {"question": "小吴有21元，妹妹又给了他7元，他现在有多少钱？", "answer": "28", "solution": "21 + 7 = 28"},
    {"question": "仓库有85箱货物，运走了40箱，还剩多少箱？", "answer": "45", "solution": "85 - 40 = 45"},
    {"question": "每个篮子装12个鸡蛋，6个篮子一共多少个？", "answer": "72", "solution": "12 * 6 = 72"},
    {"question": "56本练习本平均分给7个班，每班分几本？", "answer": "8", "solution": "56 / 7 = 8"},
    {"question": "小郑有14个气球，又买了11个，一共多少个？", "answer": "25", "solution": "14 + 11 = 25"},
    {"question": "菜园里种了70棵白菜，摘掉了28棵，还剩多少棵？", "answer": "42", "solution": "70 - 28 = 42"},
    {"question": "一袋大米装5千克，9袋一共多少千克？", "answer": "45", "solution": "5 * 9 = 45"},
    {"question": "64个羽毛球平均分给8个人，每人分几个？", "answer": "8", "solution": "64 / 8 = 8"},
]


def load_problems(n: int) -> list[dict[str, str]]:
    """取数据集的前 n 条——固定顺序，调用方传入的 n 决定实际用于训练的样本数。"""
    if n <= 0:
        raise ValueError("n must be a positive integer")
    if n > len(DEMO_PROBLEMS):
        raise ValueError(f"only {len(DEMO_PROBLEMS)} demo problems available, requested {n}")
    return DEMO_PROBLEMS[:n]
