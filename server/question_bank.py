"""Question bank for public matches: parameterized question generators, randomized per match, in four languages.

- Answers aren't hardcoded in the repo (parameters are random per match), so lookup-table cheating fails and questions don't repeat.
- Every question's prompt/context comes in four languages; each connected player gets their own language's version.
- Answers are language-independent (numbers, codes) or list each language's spelling (e.g. weekdays).
"""

from __future__ import annotations

import random
from typing import Any, Callable

LANGS = ("zh-TW", "zh-CN", "en", "ja")


def L(tw: str, cn: str, en: str, ja: str) -> dict[str, str]:
    return {"zh-TW": tw, "zh-CN": cn, "en": en, "ja": ja}


WEEKDAYS = {
    "zh-TW": ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"],
    "zh-CN": ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"],
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "ja": ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"],
}
WORDS = ["ARENA", "PROMPT", "AGENT", "MATRIX", "PYTHON", "VECTOR", "GALAXY", "CIPHER", "BINARY", "KERNEL"]

# Sentiment labels: scoring requires the correct label and none of the others
LABELS = {
    "positive": ["正面", "正面", "positive", "ポジティブ"],
    "neutral": ["中性", "中性", "neutral", "中立"],
    "negative": ["負面", "负面", "negative", "ネガティブ"],
}

Gen = Callable[[random.Random], dict[str, Any]]


# ---------------- quiz generators ----------------
def q_multiply(r: random.Random) -> dict[str, Any]:
    a, b = r.randint(12, 99), r.randint(11, 99)
    return {"prompt": L(f"{a} 乘以 {b} 等於多少？只回答數字。", f"{a} 乘以 {b} 等于多少？只回答数字。",
                        f"What is {a} × {b}? Answer with the number only.", f"{a} × {b} はいくつですか？数字だけで答えてください。"),
            "answer": str(a * b), "kind": "numeric"}


def q_chain(r: random.Random) -> dict[str, Any]:
    a, b, c = r.randint(100, 999), r.randint(10, 500), r.randint(10, 300)
    return {"prompt": L(f"計算 {a} + {b} − {c}，只回答數字。", f"计算 {a} + {b} − {c}，只回答数字。",
                        f"Compute {a} + {b} − {c}. Answer with the number only.", f"{a} + {b} − {c} を計算し、数字だけで答えてください。"),
            "answer": str(a + b - c), "kind": "numeric"}


def q_hex(r: random.Random) -> dict[str, Any]:
    n = r.randint(16, 4095)
    h = format(n, "X")
    return {"prompt": L(f"十六進位的 {h} 等於十進位多少？只回答數字。", f"十六进制的 {h} 等于十进制多少？只回答数字。",
                        f"What is hexadecimal {h} in decimal? Answer with the number only.", f"16 進数の {h} は 10 進数でいくつですか？数字だけで答えてください。"),
            "answer": str(n), "kind": "numeric"}


def q_mod(r: random.Random) -> dict[str, Any]:
    a, b = r.randint(100, 9999), r.randint(3, 29)
    return {"prompt": L(f"{a} 除以 {b} 的餘數是多少？只回答數字。", f"{a} 除以 {b} 的余数是多少？只回答数字。",
                        f"What is the remainder of {a} divided by {b}? Answer with the number only.", f"{a} を {b} で割った余りはいくつですか？数字だけで答えてください。"),
            "answer": str(a % b), "kind": "numeric"}


def q_sequence(r: random.Random) -> dict[str, Any]:
    start, step = r.randint(1, 40), r.randint(2, 17)
    seq = [start + step * i for i in range(4)]
    s = ", ".join(map(str, seq))
    return {"prompt": L(f"數列 {s}, ? 的下一個數是多少？只回答數字。", f"数列 {s}, ? 的下一个数是多少？只回答数字。",
                        f"What comes next in the sequence {s}, ? Answer with the number only.", f"数列 {s}, ? の次の数はいくつですか？数字だけで答えてください。"),
            "answer": str(start + step * 4), "kind": "numeric"}


def q_weekday(r: random.Random) -> dict[str, Any]:
    d0, n = r.randint(0, 6), r.randint(10, 400)
    d1 = (d0 + n) % 7
    p = {lang: tpl.format(d=WEEKDAYS[lang][d0], n=n) for lang, tpl in L(
        "如果今天是{d}，{n} 天後是星期幾？只回答星期幾。", "如果今天是{d}，{n} 天后是星期几？只回答星期几。",
        "If today is {d}, what day of the week is it {n} days later? Answer with the weekday only.",
        "今日が{d}だとすると、{n} 日後は何曜日ですか？曜日だけで答えてください。").items()}
    others = sorted({WEEKDAYS[lang][d] for lang in LANGS for d in range(7) if d != d1})
    return {"prompt": p, "answer": sorted({WEEKDAYS[lang][d1] for lang in LANGS}), "kind": "contains",
            "distractors": others}


def q_letter(r: random.Random) -> dict[str, Any]:
    w = r.choice(WORDS)
    i = r.randint(1, len(w))
    return {"prompt": L(f"英文單字 {w} 的第 {i} 個字母是什麼？只回答一個大寫字母。", f"英文单词 {w} 的第 {i} 个字母是什么？只回答一个大写字母。",
                        f"What is letter number {i} of the word {w}? Answer with one capital letter only.", f"英単語 {w} の {i} 文字目は何ですか？大文字 1 文字だけで答えてください。"),
            "answer": w[i - 1], "kind": "choice"}


def q_count_letter(r: random.Random) -> dict[str, Any]:
    letters = "".join(r.choice("ABRST") for _ in range(r.randint(12, 20)))
    t = r.choice("ABRST")
    return {"prompt": L(f"字串 {letters} 裡有幾個 {t}？只回答數字。", f"字符串 {letters} 里有几个 {t}？只回答数字。",
                        f"How many times does {t} appear in {letters}? Answer with the number only.", f"文字列 {letters} に {t} は何個ありますか？数字だけで答えてください。"),
            "answer": str(letters.count(t)), "kind": "numeric"}


def q_max(r: random.Random) -> dict[str, Any]:
    nums = r.sample(range(-500, 1000), 6)
    s = ", ".join(map(str, nums))
    return {"prompt": L(f"這組數字中最大的是哪個：{s}？只回答數字。", f"这组数字中最大的是哪个：{s}？只回答数字。",
                        f"Which is the largest of these numbers: {s}? Answer with the number only.", f"次の数のうち最大はどれですか：{s}？数字だけで答えてください。"),
            "answer": str(max(nums)), "kind": "numeric"}


def q_order(r: random.Random) -> dict[str, Any]:
    names = r.sample(["A", "B", "C", "D", "E"], 3)
    tallest, middle, shortest = names
    return {"prompt": L(f"{tallest} 比 {middle} 高，{middle} 比 {shortest} 高。三人中誰最矮？只回答一個字母。",
                        f"{tallest} 比 {middle} 高，{middle} 比 {shortest} 高。三人中谁最矮？只回答一个字母。",
                        f"{tallest} is taller than {middle}, and {middle} is taller than {shortest}. Who is the shortest? Answer with one letter only.",
                        f"{tallest} は {middle} より背が高く、{middle} は {shortest} より背が高い。一番背が低いのは誰ですか？アルファベット 1 文字で答えてください。"),
            "answer": shortest, "kind": "choice"}


def q_minutes(r: random.Random) -> dict[str, Any]:
    h, m = r.randint(1, 12), r.choice([0, 15, 20, 30, 45, 50])
    return {"prompt": L(f"{h} 小時 {m} 分鐘總共是幾分鐘？只回答數字。", f"{h} 小时 {m} 分钟一共是多少分钟？只回答数字。",
                        f"How many minutes are in {h} hours and {m} minutes? Answer with the number only.", f"{h} 時間 {m} 分は合計何分ですか？数字だけで答えてください。"),
            "answer": str(h * 60 + m), "kind": "numeric"}


QUIZ_GENERATORS: list[Gen] = [q_multiply, q_chain, q_hex, q_mod, q_sequence, q_weekday,
                              q_letter, q_count_letter, q_max, q_order, q_minutes]


# ---------------- task generators ----------------
FIRST = ["ann", "ben", "chen", "dora", "eli", "fang", "gina", "hiro", "ivy", "jun", "kai", "lin"]
DOMAINS = ["acme.tw", "example.jp", "mail.cn", "corp.io", "shop.com"]
CITIES = {"zh-TW": ["台北", "台中", "高雄", "台南"], "zh-CN": ["北京", "上海", "广州", "深圳"],
          "en": ["Boston", "Austin", "Denver", "Seattle"], "ja": ["東京", "大阪", "京都", "福岡"]}
PEOPLE = {"zh-TW": ["王小美", "陳大文", "林怡君"], "zh-CN": ["王小美", "陈大文", "林怡君"],
          "en": ["Mia Wong", "David Chen", "Iris Lin"], "ja": ["佐藤 美咲", "鈴木 大輔", "高橋 葵"]}
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December"]


def t_emails(r: random.Random) -> dict[str, Any]:
    emails = [f"{n}@{r.choice(DOMAINS)}" for n in r.sample(FIRST, r.randint(2, 4))]
    decoy = f"{r.choice(FIRST)}(at){r.choice(DOMAINS)}"
    joined = "、".join(emails)
    ctx = L(f"請聯絡 {joined}。舊格式 {decoy} 不是 email，請忽略。",
            f"请联系 {joined}。旧格式 {decoy} 不是 email，请忽略。",
            f"Please contact {', '.join(emails)}. The old form {decoy} is not an email address; ignore it.",
            f"{joined} に連絡してください。旧形式の {decoy} はメールアドレスではないので無視してください。")
    return {"prompt": L("從下面文字抽出所有 email，輸出成 JSON 陣列。", "从下面文字中抽出所有 email，输出成 JSON 数组。",
                        "Extract every email address from the text below and output them as a JSON array.",
                        "以下の文章からメールアドレスをすべて抜き出し、JSON 配列で出力してください。"),
            "context": ctx, "check": {"kind": "json_set", "values": emails}}


def t_order(r: random.Random) -> dict[str, Any]:
    oid = f"ORD-{r.randint(100000, 999999)}"
    other = r.randint(1000, 9999)
    ctx = L(f"您的訂單 {oid} 已出貨，客服單號 {other}，預計週五送達。", f"您的订单 {oid} 已发货，客服单号 {other}，预计周五送达。",
            f"Your order {oid} has shipped (support ticket {other}) and should arrive Friday.",
            f"ご注文 {oid} は発送済みです（問い合わせ番号 {other}）。金曜日に到着予定です。")
    return {"prompt": L("找出訂單編號（ORD- 加 6 位數字），只輸出編號。", "找出订单编号（ORD- 加 6 位数字），只输出编号。",
                        "Find the order number (ORD- followed by 6 digits). Output the number only.",
                        "注文番号（ORD- と 6 桁の数字）を見つけ、番号だけを出力してください。"),
            "context": ctx, "check": {"kind": "regex", "pattern": rf"\b{oid}\b"}}


def t_date(r: random.Random) -> dict[str, Any]:
    y, m, d = r.randint(2020, 2030), r.randint(1, 12), r.randint(1, 28)
    ctx = L(f"{y} 年 {m} 月 {d} 日", f"{y} 年 {m} 月 {d} 日", f"{MONTHS_EN[m - 1]} {d}, {y}", f"{y}年{m}月{d}日")
    return {"prompt": L("把下面的日期轉成 YYYY-MM-DD 格式，只輸出日期。", "把下面的日期转换成 YYYY-MM-DD 格式，只输出日期。",
                        "Convert the date below to YYYY-MM-DD. Output the date only.",
                        "以下の日付を YYYY-MM-DD 形式に変換し、日付だけを出力してください。"),
            "context": ctx, "check": {"kind": "regex", "pattern": rf"{y:04d}-{m:02d}-{d:02d}"}}


def t_person(r: random.Random) -> dict[str, Any]:
    i, age, c = r.randint(0, 2), r.randint(18, 80), r.randint(0, 3)
    ctx = {lang: (f"{PEOPLE[lang][i]}，{age} 歲，住在{CITIES[lang][c]}。" if lang == "zh-TW" else
                  f"{PEOPLE[lang][i]}，{age} 岁，住在{CITIES[lang][c]}。" if lang == "zh-CN" else
                  f"{PEOPLE[lang][i]} is {age} years old and lives in {CITIES[lang][c]}." if lang == "en" else
                  f"{PEOPLE[lang][i]}、{age} 歳、{CITIES[lang][c]}在住。") for lang in LANGS}
    return {"prompt": L("把人員資料轉成 JSON 物件，鍵為 name、age、city（age 用數字）。", "把人员资料转换成 JSON 对象，键为 name、age、city（age 用数字）。",
                        "Turn the person below into a JSON object with keys name, age and city (age as a number).",
                        "以下の人物情報を、キーが name・age・city の JSON オブジェクトにしてください（age は数値）。"),
            "context": ctx, "check": {"kind": "json_fields", "fields": {"age": age}, "keys": ["name", "age", "city"]}}


REVIEWS = {
    "negative": L("等了三個禮拜才到貨，打客服也沒人接，非常失望。", "等了三个星期才到货，打客服也没人接，非常失望。",
                  "It took three weeks to arrive and nobody answered the support line. Very disappointed.",
                  "届くまで 3 週間かかり、サポートに電話しても誰も出ませんでした。とてもがっかりです。"),
    "positive": L("隔天就到，包裝仔細，客服回覆也很快，下次還會再買。", "第二天就到了，包装仔细，客服回复也很快，下次还会再买。",
                  "Arrived the next day, carefully packed, and support replied fast. I'll buy again.",
                  "翌日に届き、梱包も丁寧で、サポートの返信も早かったです。また買います。"),
    "neutral": L("商品和描述一致，配送時間普通，沒有特別的感想。", "商品和描述一致，配送时间一般，没有特别的感想。",
                 "The item matches the description and delivery took the usual time. No strong feelings.",
                 "商品は説明どおりで、配送も普通でした。特に感想はありません。"),
}


def t_sentiment(r: random.Random) -> dict[str, Any]:
    label = r.choice(list(REVIEWS))
    return {"prompt": L("判斷這則評論的情緒，只回答「正面」「中性」或「負面」。", "判断这条评论的情绪，只回答「正面」「中性」或「负面」。",
                        "Classify the sentiment of this review. Answer only Positive, Neutral or Negative.",
                        "このレビューの感情を判定し、「ポジティブ」「中立」「ネガティブ」のいずれかだけで答えてください。"),
            "context": REVIEWS[label], "check": {"kind": "label", "label": label}}


def t_receipt(r: random.Random) -> dict[str, Any]:
    prices = [r.randint(20, 400) for _ in range(r.randint(3, 5))]
    lines_tw = "\n".join(f"品項 {i + 1}：{p} 元" for i, p in enumerate(prices))
    lines_cn = "\n".join(f"品项 {i + 1}：{p} 元" for i, p in enumerate(prices))
    lines_en = "\n".join(f"Item {i + 1}: ${p}" for i, p in enumerate(prices))
    lines_ja = "\n".join(f"品目 {i + 1}：{p} 円" for i, p in enumerate(prices))
    return {"prompt": L("把這張收據的金額加總，只回答數字。", "把这张收据的金额加总，只回答数字。",
                        "Add up the amounts on this receipt. Answer with the number only.",
                        "このレシートの金額を合計し、数字だけで答えてください。"),
            "context": L(lines_tw, lines_cn, lines_en, lines_ja), "check": {"kind": "numeric", "value": str(sum(prices))}}


TASK_GENERATORS: list[Gen] = [t_emails, t_order, t_date, t_person, t_sentiment, t_receipt]


def pick(mode: str, n: int | None = None, rng: random.Random | None = None) -> dict[str, Any]:
    """Build the mode_config for one match (parameters differ every match)."""
    rng = rng or random.Random()
    if mode == "task":
        gens = rng.sample(TASK_GENERATORS, k=min(n or 3, len(TASK_GENERATORS)))
        return {"tasks": [{"id": f"t{i + 1}", **g(rng)} for i, g in enumerate(gens)]}
    gens = rng.sample(QUIZ_GENERATORS, k=min(n or 5, len(QUIZ_GENERATORS)))
    return {"questions": [{"id": f"q{i + 1}", **g(rng)} for i, g in enumerate(gens)]}
