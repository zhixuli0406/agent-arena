"""Server message localization: reply in the language from the request's Accept-Language (Traditional Chinese is the default and source text)."""

from __future__ import annotations

SUPPORTED = ("zh-TW", "zh-CN", "en", "ja")
DEFAULT = "en"

MESSAGES: dict[str, dict[str, str]] = {
    "lobby_full": {"zh-TW": "大廳已滿，請稍後再試", "zh-CN": "大厅已满，请稍后再试",
                   "en": "The lobby is full. Please try again later.", "ja": "ロビーが満員です。しばらくしてからお試しください。"},
    "auth_failed": {"zh-TW": "玩家驗證失敗，請重新進入大廳", "zh-CN": "玩家验证失败，请重新进入大厅",
                    "en": "Player authentication failed. Please enter the lobby again.", "ja": "プレイヤー認証に失敗しました。ロビーに入り直してください。"},
    "in_match": {"zh-TW": "{names} 還在比賽中，打完這場再排", "zh-CN": "{names} 还在比赛中，打完这场再排",
                 "en": "{names} is still in a match. Finish it first.", "ja": "{names} はまだ対戦中です。終わってからにしてください。"},
    "player_unknown": {"zh-TW": "伺服器已不認得這位玩家（沒打過對局的訪客會被清掉），請重新進入大廳",
                       "zh-CN": "服务器已不认识这位玩家（没打过对局的访客会被清理），请重新进入大厅",
                       "en": "The server no longer knows this player (guests who never played are cleared). Please enter the lobby again.",
                       "ja": "サーバーはこのプレイヤーを認識していません（対戦していないゲストは削除されます）。ロビーに入り直してください。"},
    "bad_mode": {"zh-TW": "不支援的模式：{mode}", "zh-CN": "不支持的模式：{mode}",
                 "en": "Unsupported mode: {mode}", "ja": "対応していないモードです：{mode}"},
    "policy_ctf": {"zh-TW": "公開伺服器的資安模式只接受內建隔離靶場與固定安全限制",
                   "zh-CN": "公开服务器的安全模式只接受内置隔离靶场和固定安全限制",
                   "en": "Public CTF accepts only the built-in isolated target and fixed safety limits.",
                   "ja": "公開 CTF では、内蔵の隔離ターゲットと固定された安全制限のみ利用できます。"},
    "bad_size": {"zh-TW": "不支援的人數：{size}", "zh-CN": "不支持的人数：{size}",
                 "en": "Unsupported player count: {size}", "ja": "対応していない人数です：{size}"},
    "cooldown": {"zh-TW": "你剛拒絕或錯過對局，冷卻中（還有 {s} 秒）", "zh-CN": "你刚拒绝或错过了对局，冷却中（还有 {s} 秒）",
                 "en": "You just declined or missed a match. Cooldown: {s} s left.", "ja": "直前の対戦を辞退または逃したため待機中です（残り {s} 秒）"},
    "already_queued": {"zh-TW": "你已經在佇列或對局確認中", "zh-CN": "你已经在队列或对局确认中",
                       "en": "You're already in a queue or a match check.", "ja": "すでにキューまたは対戦確認中です"},
    "in_room": {"zh-TW": "你正在自訂房間裡，請先離開房間", "zh-CN": "你正在自定义房间里，请先离开房间",
                "en": "You're in a custom room. Leave it first.", "ja": "カスタムルームに参加中です。先に退出してください。"},
    "ticket_not_found": {"zh-TW": "找不到這張排隊單", "zh-CN": "找不到这张排队单",
                         "en": "Queue ticket not found.", "ja": "キューのチケットが見つかりません"},
    "busy": {"zh-TW": "你已在佇列或其他房間中", "zh-CN": "你已在队列或其他房间中",
             "en": "You're already in a queue or another room.", "ja": "すでにキューまたは別のルームにいます"},
    "room_not_found": {"zh-TW": "房間不存在", "zh-CN": "房间不存在", "en": "Room not found.", "ja": "ルームが存在しません"},
    "room_started": {"zh-TW": "房間已開局", "zh-CN": "房间已开局", "en": "The game in this room has already started.", "ja": "このルームは対戦開始済みです"},
    "room_full": {"zh-TW": "房間已滿", "zh-CN": "房间已满", "en": "The room is full.", "ja": "ルームが満員です"},
    "not_in_room": {"zh-TW": "你不在這個房間", "zh-CN": "你不在这个房间", "en": "You're not in this room.", "ja": "このルームに参加していません"},
    "host_only": {"zh-TW": "只有房主可以開局", "zh-CN": "只有房主可以开局", "en": "Only the host can start the game.", "ja": "対戦を開始できるのはホストだけです"},
    "need_two": {"zh-TW": "至少要 2 位玩家", "zh-CN": "至少需要 2 位玩家", "en": "At least 2 players are needed.", "ja": "2 人以上必要です"},
    "not_ready": {"zh-TW": "還有玩家沒準備：{names}", "zh-CN": "还有玩家没准备：{names}",
                  "en": "Not everyone is ready: {names}", "ja": "準備ができていないプレイヤーがいます：{names}"},
    "no_pending": {"zh-TW": "目前沒有待確認的對局", "zh-CN": "目前没有待确认的对局",
                   "en": "There's no match waiting for confirmation.", "ja": "確認待ちの対戦はありません"},
    "bad_config": {"zh-TW": "對戰設定不合法：{e}", "zh-CN": "对战设置不合法：{e}",
                   "en": "Invalid match settings: {e}", "ja": "対戦設定が不正です：{e}"},
    "unknown_match": {"zh-TW": "未知對局", "zh-CN": "未知对局", "en": "Unknown match.", "ja": "不明な対戦です"},
    "bad_token": {"zh-TW": "連線 token 無效或已過期", "zh-CN": "连接 token 无效或已过期",
                  "en": "The connection token is invalid or has expired.", "ja": "接続トークンが無効か期限切れです"},
    "unknown_action": {"zh-TW": "未知操作", "zh-CN": "未知操作", "en": "Unknown action.", "ja": "不明な操作です"},
    "policy_adapters": {"zh-TW": "公開伺服器只接受玩家自帶代理（remote）與示範代理（mock），不接受：{bad}",
                        "zh-CN": "公开服务器只接受玩家自带智能体（remote）和演示智能体（mock），不接受：{bad}",
                        "en": "Public servers only accept player-hosted agents (remote) and demo agents (mock), not: {bad}",
                        "ja": "公開サーバーが受け付けるのはプレイヤー自身のエージェント（remote）とデモ用（mock）のみです。対象外：{bad}"},
    "policy_mode": {"zh-TW": "公開伺服器只開放解題、日常任務與內建 warmup 資安場；不支援：{mode}",
                    "zh-CN": "公开服务器只开放答题、日常任务和内置 warmup 安全场；不支持：{mode}",
                    "en": "Public servers run quiz, everyday-task and built-in warmup CTF games, not: {mode}",
                    "ja": "公開サーバーで遊べるのはクイズ、日常タスク、内蔵 warmup CTF のみです。対象外：{mode}"},
    "max_agents": {"zh-TW": "一局最多 {n} 位代理", "zh-CN": "一局最多 {n} 个智能体",
                   "en": "At most {n} agents per game.", "ja": "1 戦あたりのエージェントは最大 {n} 体です"},
    "max_items": {"zh-TW": "一局最多 {n} 題", "zh-CN": "一局最多 {n} 题", "en": "At most {n} questions per game.", "ja": "1 戦あたりの問題は最大 {n} 問です"},
    "server_busy": {"zh-TW": "同時進行的對局已滿，請稍後再試", "zh-CN": "同时进行的对局已满，请稍后再试",
                    "en": "Too many games are running right now. Please try again later.", "ja": "同時対戦数が上限に達しています。しばらくしてからお試しください。"},
    "queue_full": {"zh-TW": "排隊人數已達上限，請稍後再試", "zh-CN": "排队人数已达上限，请稍后再试",
                   "en": "The matchmaking queue is full. Please try again later.", "ja": "マッチングの待機人数が上限に達しています。しばらくしてからお試しください。"},
    "ip_tickets": {"zh-TW": "同一個網路最多同時排 {n} 張單", "zh-CN": "同一个网络最多同时排 {n} 张单",
                   "en": "At most {n} queue tickets per network at a time.", "ja": "同じネットワークから同時に並べるのは {n} 件までです"},
    "kicked": {"zh-TW": "你已被房主移出這個房間", "zh-CN": "你已被房主移出这个房间",
               "en": "The host removed you from this room.", "ja": "ホストによってこのルームから退出させられました"},
    "host_only_kick": {"zh-TW": "只有房主可以踢人", "zh-CN": "只有房主可以踢人", "en": "Only the host can remove players.", "ja": "プレイヤーを退出させられるのはホストだけです"},
    "bad_kick": {"zh-TW": "無法移出這位玩家", "zh-CN": "无法移出这位玩家", "en": "That player can't be removed.", "ja": "このプレイヤーは退出させられません"},
    "bad_format": {"zh-TW": "不支援的對戰格式：{fmt}", "zh-CN": "不支持的对战格式：{fmt}",
                   "en": "Unsupported format: {fmt}", "ja": "対応していない形式です：{fmt}"},
    "party_ffa": {"zh-TW": "組隊只能排團隊佇列（2v2、3v3）；混戰裡隊友會互打，請先離隊再單排",
                  "zh-CN": "组队只能排团队队列（2v2、3v3）；混战里队友会互打，请先离队再单排",
                  "en": "Parties can only queue for team formats (2v2, 3v3). In free-for-all you'd be fighting each other, so leave the party to queue solo.",
                  "ja": "パーティーはチーム戦（2v2・3v3）のみキューできます。個人戦では味方同士が戦うことになるため、ソロで並ぶにはパーティーを抜けてください"},
    "party_too_big": {"zh-TW": "隊伍人數超過這個格式的每隊 {n} 人", "zh-CN": "队伍人数超过这个格式的每队 {n} 人",
                      "en": "Your party is bigger than this format's {n} per team.", "ja": "パーティーの人数がこの形式の 1 チーム {n} 人を超えています"},
    "party_spread": {"zh-TW": "隊員之間積分差距不能超過 {n} 分", "zh-CN": "队员之间积分差距不能超过 {n} 分",
                     "en": "Party members' ratings can't be more than {n} apart.", "ja": "メンバー間のレート差は {n} 以内にしてください"},
    "party_full": {"zh-TW": "隊伍已滿（最多 {n} 人）", "zh-CN": "队伍已满（最多 {n} 人）",
                   "en": "The party is full (max {n}).", "ja": "パーティーは満員です（最大 {n} 人）"},
    "party_queued": {"zh-TW": "隊伍正在排隊，請等隊長取消後再加入", "zh-CN": "队伍正在排队，请等队长取消后再加入",
                     "en": "This party is in queue. Join after the leader cancels.", "ja": "このパーティーはキュー中です。リーダーがキャンセルしてから参加してください"},
    "party_not_found": {"zh-TW": "找不到這個隊伍", "zh-CN": "找不到这个队伍", "en": "Party not found.", "ja": "パーティーが見つかりません"},
    "not_in_party": {"zh-TW": "你不在這個隊伍", "zh-CN": "你不在这个队伍", "en": "You're not in this party.", "ja": "このパーティーに参加していません"},
    "in_party": {"zh-TW": "你已在隊伍中，請先離隊", "zh-CN": "你已在队伍中，请先离队", "en": "You're in a party. Leave it first.", "ja": "パーティーに参加中です。先に抜けてください"},
    "leader_only": {"zh-TW": "只有隊長可以這麼做", "zh-CN": "只有队长可以这么做", "en": "Only the party leader can do that.", "ja": "パーティーリーダーのみ実行できます"},
    "party_in_check": {"zh-TW": "對局確認中不能離隊或踢人；不想打請按拒絕", "zh-CN": "对局确认中不能离队或踢人；不想打请点拒绝",
                       "en": "You can't leave or remove members during the ready check. Decline instead if you don't want to play.",
                       "ja": "対戦確認中はパーティーを抜けたりメンバーを外したりできません。参加しない場合は拒否してください"},
    "bad_limits": {"zh-TW": "這台伺服器不接受這麼長的時間上限", "zh-CN": "这台服务器不接受这么长的时间上限",
                   "en": "This server doesn't accept time limits that long.", "ja": "このサーバーではそこまで長い時間制限は使えません"},
    "agent_offline": {"zh-TW": "要先接上自己的代理才能上場：{names} 的代理不在線", "zh-CN": "要先接上自己的智能体才能上场：{names} 的智能体不在线",
                      "en": "Every player needs their own agent connected first. Agent offline: {names}", "ja": "参加するには自分のエージェントの接続が必要です。オフライン：{names}"},
    "link_invalid": {"zh-TW": "連結碼無效或已過期", "zh-CN": "链接码无效或已过期", "en": "That link code is invalid or has expired.", "ja": "リンクコードが無効か、有効期限切れです"},
    "party_kicked": {"zh-TW": "你已被隊長移出這個隊伍", "zh-CN": "你已被队长移出这个队伍",
                     "en": "The leader removed you from this party.", "ja": "リーダーによってこのパーティーから外されました"},
    "rate_limited": {"zh-TW": "操作太頻繁，請 {s} 秒後再試", "zh-CN": "操作太频繁，请 {s} 秒后再试",
                     "en": "Too many requests. Try again in {s} s.", "ja": "操作が多すぎます。{s} 秒後にもう一度お試しください。"},
    "too_large": {"zh-TW": "請求內容太大", "zh-CN": "请求内容太大", "en": "The request is too large.", "ja": "リクエストが大きすぎます"},
    "match_ended": {"zh-TW": "這一局已經結束", "zh-CN": "这一局已经结束", "en": "This game has already ended.", "ja": "この対戦はすでに終了しています"},
    "answers_full": {"zh-TW": "答案送太快了，請等這一題結算", "zh-CN": "答案发送太快了，请等这一题结算",
                     "en": "Answers are arriving too fast. Wait for this round to be graded.", "ja": "回答の送信が速すぎます。この問題の採点を待ってください。"},
    "bad_round": {"zh-TW": "round 必須是整數", "zh-CN": "round 必须是整数", "en": "round must be an integer.", "ja": "round は整数で指定してください"},
    "bad_public_summary": {"zh-TW": "公開策略摘要必須是 280 字以內的文字", "zh-CN": "公开策略摘要必须是 280 字以内的文字",
                           "en": "public_summary must be text no longer than 280 characters.",
                           "ja": "public_summary は 280 文字以内のテキストで指定してください"},
    "bad_field": {"zh-TW": "欄位 {field} 格式不對", "zh-CN": "字段 {field} 格式不对", "en": "Field {field} is malformed.", "ja": "{field} の形式が正しくありません"},
    "demo_busy": {"zh-TW": "示範賽同時場數已滿，請稍後再試", "zh-CN": "演示赛同时场数已满，请稍后再试",
                  "en": "Too many demo games are running. Please try again later.", "ja": "デモ対戦の同時実行数が上限です。しばらくしてからお試しください。"},
    "private_only": {"zh-TW": "公開伺服器不開放自訂開局，請用大廳配對或開房", "zh-CN": "公开服务器不开放自定义开局，请用大厅匹配或开房间",
                     "en": "Custom games are disabled on public servers. Use matchmaking or a room.", "ja": "公開サーバーではカスタム対戦は使えません。マッチングかルームを利用してください。"},
    "admin_only": {"zh-TW": "這個端點需要管理者 token（X-Admin-Token）", "zh-CN": "这个端点需要管理员 token（X-Admin-Token）",
                   "en": "This endpoint requires an admin token (X-Admin-Token).", "ja": "このエンドポイントには管理者トークン（X-Admin-Token）が必要です"},
    "bad_origin": {"zh-TW": "不接受來自其他網站的請求", "zh-CN": "不接受来自其他网站的请求",
                   "en": "Requests from other websites are not accepted.", "ja": "他のサイトからのリクエストは受け付けません"},
    "too_many_streams": {"zh-TW": "同時開啟的連線太多", "zh-CN": "同时打开的连接太多", "en": "Too many open streams.", "ja": "同時接続が多すぎます"},
}

_SEP = {"zh-TW": "、", "zh-CN": "、", "ja": "、", "en": ", "}


def pick_lang(header: str | None) -> str:
    """Pick the highest-priority supported language from Accept-Language."""
    if not header:
        return DEFAULT
    ranked: list[tuple[float, str]] = []
    for part in header.split(","):
        tag, _, q = part.strip().partition(";q=")
        try:
            weight = float(q) if q else 1.0
        except ValueError:
            weight = 0.0
        ranked.append((weight, tag.strip().lower()))
    for _, tag in sorted(ranked, key=lambda x: -x[0]):
        if tag.startswith(("zh-tw", "zh-hk", "zh-mo", "zh-hant")):
            return "zh-TW"
        if tag.startswith(("zh-cn", "zh-sg", "zh-hans")) or tag == "zh":
            return "zh-CN"
        if tag.startswith("en"):
            return "en"
        if tag.startswith("ja"):
            return "ja"
    return DEFAULT


def tr(key: str, lang: str = DEFAULT, **params: object) -> str:
    table = MESSAGES.get(key)
    if table is None:
        return key
    template = table.get(lang) or table[DEFAULT]
    sep = _SEP.get(lang, "、")
    values = {k: sep.join(map(str, v)) if isinstance(v, (list, tuple)) else v for k, v in params.items()}
    return template.format(**values)


class I18nError(Exception):
    """Error carrying a message key: str(e) is in the default language; the API layer re-translates it to the request language."""

    def __init__(self, key: str, code: int = 400, **params: object):
        super().__init__(tr(key, DEFAULT, **params))
        self.key, self.code, self.params = key, code, params

    def text(self, lang: str) -> str:
        return tr(self.key, lang, **self.params)
