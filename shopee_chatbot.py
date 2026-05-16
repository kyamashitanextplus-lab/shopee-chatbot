#!/usr/bin/env python3
# ============================================================
# Shopee カスタマーサポート 返信生成ツール
# 山下さん専用 / 外注スタッフ向け
# v3.0 - 履歴テンプレ自動生成対応
# ============================================================

import os
import re
import json
import requests
import anthropic
import streamlit as st
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
# Streamlit Cloud は st.secrets、ローカルは .env から取得
CLAUDE_API_KEY     = st.secrets.get("CLAUDE_API_KEY",     os.getenv("CLAUDE_API_KEY", ""))
PERPLEXITY_API_KEY = st.secrets.get("PERPLEXITY_API_KEY", os.getenv("PERPLEXITY_API_KEY", ""))

MODEL = "claude-sonnet-4-5"
TRANSLATION_MODEL = MODEL  # 後方互換

HISTORY_FILE        = os.path.join(os.path.dirname(__file__), "inquiry_history.json")
LEARNED_FILE        = os.path.join(os.path.dirname(__file__), "learned_examples.json")
SIMILAR_THRESHOLD       = 0.35   # プロンプト注入・参考表示の閾値
AUTO_USE_THRESHOLD      = 0.60   # 自動採用候補として優先表示する閾値
TEMPLATE_MIN_COUNT      = 2
LEARNED_INJECT_MAX      = 3      # プロンプトに注入する学習済み例の最大数

# キーワード抽出用 (カテゴリ判定強化)
KEYWORD_HINTS = {
    "shipping":  ["配送", "発送", "shipping", "delivery", "送", "ส่ง", "จัดส่ง", "tracking", "พัสดุ", "海運", "貨運"],
    "refund":    ["返金", "refund", "money back", "คืนเงิน", "退款"],
    "return":    ["返品", "return", "send back", "ส่งคืน", "退貨"],
    "stock":     ["在庫", "stock", "available", "มี", "stok", "庫存"],
    "size":      ["サイズ", "size", "ขนาด", "尺寸", "尺碼"],
    "color":     ["色", "color", "colour", "สี", "顏色", "warna"],
    "authentic": ["本物", "正規", "original", "authentic", "ของแท้", "正品", "asli"],
    "damage":    ["破損", "壊れ", "broken", "damaged", "เสีย", "ชำรุด", "rosak", "壞了"],
    "wrong":     ["違う", "間違い", "wrong", "incorrect", "ผิด", "salah", "錯誤"],
    "voucher":   ["クーポン", "voucher", "discount", "วาวเชอร์", "ส่วนลด", "優惠券"],
}

def extract_keywords(text: str) -> set:
    text = text.lower()
    hits = set()
    for k, words in KEYWORD_HINTS.items():
        for w in words:
            if w.lower() in text:
                hits.add(k)
                break
    return hits


# ========== 学習済み返信例の管理 ==========

def load_learned() -> list:
    if not os.path.exists(LEARNED_FILE):
        return []
    try:
        with open(LEARNED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_learned(examples: list):
    with open(LEARNED_FILE, "w", encoding="utf-8") as f:
        json.dump(examples, f, ensure_ascii=False, indent=2)

def add_learned_example(inquiry: str, reply: str, reply_ja: str = ""):
    """承認済み返信例を保存（類似があれば上書き）"""
    examples = load_learned()
    for ex in examples:
        if similarity(inquiry, ex["inquiry"]) >= 0.8:
            ex["reply"] = reply
            if reply_ja:
                ex["reply_ja"] = reply_ja
            ex["updated"] = datetime.now().strftime("%Y-%m-%d")
            save_learned(examples)
            return
    entry = {
        "inquiry": inquiry,
        "reply": reply,
        "date": datetime.now().strftime("%Y-%m-%d"),
    }
    if reply_ja:
        entry["reply_ja"] = reply_ja
    examples.append(entry)
    save_learned(examples)

def get_learned_examples(inquiry: str) -> list:
    """類似度が高い学習済み返信例を返す"""
    examples = load_learned()
    scored = [(similarity(inquiry, ex["inquiry"]), ex) for ex in examples]
    scored = [(s, ex) for s, ex in scored if s >= SIMILAR_THRESHOLD]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [ex for _, ex in scored[:LEARNED_INJECT_MAX]]


# ========== 履歴管理 ==========

def load_history() -> list:
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_history(history: list):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def tokenize(text: str) -> set:
    """単語に分割（英語スペース区切り＋日本語は文字単位）"""
    text = text.lower()
    words = set(re.findall(r'[a-z0-9]+', text))
    # 日本語は2文字以上のn-gram
    jp_chars = re.findall(r'[\u3040-\u9fff]{2,}', text)
    for w in jp_chars:
        for i in range(len(w) - 1):
            words.add(w[i:i+2])
    return words

def similarity(a: str, b: str) -> float:
    ta, tb = tokenize(a), tokenize(b)
    if not ta or not tb:
        return 0.0
    base = len(ta & tb) / min(len(ta), len(tb))
    # キーワードカテゴリ一致でブースト (最大 +0.25)
    ka, kb = extract_keywords(a), extract_keywords(b)
    if ka and kb:
        overlap = len(ka & kb)
        boost = min(0.25, overlap * 0.10)
        base = min(1.0, base + boost)
    return base

def get_top_learned_match(inquiry: str):
    """最も似た学習済み返信を1件返す (score, example) or None"""
    examples = load_learned()
    if not examples:
        return None
    scored = [(similarity(inquiry, ex["inquiry"]), ex) for ex in examples]
    scored.sort(key=lambda x: x[0], reverse=True)
    top_score, top_ex = scored[0]
    return (top_score, top_ex) if top_score >= AUTO_USE_THRESHOLD else None

def find_similar(inquiry: str, history: list) -> list:
    """似た過去の問い合わせを返す（類似度の高い順）"""
    scored = []
    for item in history:
        score = similarity(inquiry, item["inquiry"])
        if score >= SIMILAR_THRESHOLD:
            scored.append((score, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:5]]

def add_to_history(inquiry: str, reply: str, category: str):
    history = load_history()
    # 同じ問い合わせが既にあれば count を増やす
    for item in history:
        if similarity(inquiry, item["inquiry"]) >= 0.85:
            item["count"] = item.get("count", 1) + 1
            item["reply"] = reply  # 最新の返信で上書き
            save_history(history)
            return
    history.append({
        "inquiry": inquiry,
        "reply": reply,
        "category": category,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "count": 1
    })
    save_history(history)


# ========== Perplexity 商品詳細調査 ==========

def search_product_details(product_name: str, question: str) -> tuple:
    """スペック情報と情報源URLのリストを返す (content, [urls])"""
    prompt = f"""以下の日本製商品について、お客様の質問に**直接**答えるための情報を調査してください。

商品名: {product_name}
お客様の質問: {question}

# 最重要ルール
1. **お客様の質問に対する明確な答え (Yes/No/具体的な値) を最初に書く**
2. 商品単体だけでなく、**専用アプリ・付属品・エコシステム全体**で機能が実現できるかも考慮する
   - 例: 本体にQR読取カメラがなくても、専用アプリ(スマホ)経由でQR読取できる場合は「QR読取**可能**」と回答
   - 例: 本体は日本語UIでも、海外で使えれば「海外使用**可能**」
3. 「本体には機能なし」だけで終わらせない。代替手段・周辺機能も明記
4. 不確実な情報は「おそらく」と前置き、確実な情報と区別する

# 出力フォーマット
**【質問への回答】**
(YesかNoか具体的な値を1〜2行で)

**【補足情報】**
- (関連スペックを箇条書き)

**【参考の汎用スペック (わかれば)】**
- 対応電圧 / サイズ / 重量 / 素材 / 対応言語 など

情報が見つからない場合はその旨を明記してください。"""

    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "sonar-pro",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 800
    }
    try:
        resp = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )
        resp.raise_for_status()
        data    = resp.json()
        content = data["choices"][0]["message"]["content"]
        sources = data.get("citations", [])   # Perplexityが返す情報源URLリスト
        return content, sources
    except Exception as e:
        return f"（Perplexity検索エラー: {e}）", []


def is_spec_question(text: str) -> bool:
    keywords = [
        "voltage", "volt", "220", "110", "240", "100v",
        "size", "dimension", "width", "height", "length", "cm", "mm", "inch",
        "weight", "heavy", "gram", "kg",
        "material", "made of", "fabric", "plastic", "metal",
        "compatible", "work in", "use in", "overseas",
        "language", "japanese only", "english",
        "color", "colour", "how many", "capacity",
        "specification", "spec", "detail",
        "電圧", "サイズ", "寸法", "重さ", "重量", "素材", "材質",
        "使えます", "対応", "対応して", "海外", "何語", "言語",
        "何センチ", "何グラム", "容量", "カラー", "色",
    ]
    lower = text.lower()
    return any(kw in lower for kw in keywords)

def fetch_name_from_asin(asin: str) -> str:
    """AmazonのASINから商品名を取得する"""
    import urllib.request
    url = f"https://www.amazon.co.jp/dp/{asin}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ja-JP,ja;q=0.9",
    }
    try:
        req  = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        from bs4 import BeautifulSoup
        soup  = BeautifulSoup(html, "lxml")
        title = soup.find(id="productTitle")
        if title:
            return title.get_text(strip=True)
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            return og["content"].strip()
    except Exception:
        pass
    return ""


def detect_category(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ["when", "arrive", "delivery", "how long", "いつ", "届く", "配送"]):
        return "配送・到着"
    if any(w in t for w in ["damage", "broken", "wrong", "defect", "not working", "破損", "不良", "壊れ"]):
        return "不良品・返品"
    if any(w in t for w in ["cancel", "mistake", "stop", "取り消し", "間違え"]):
        return "注文変更"
    if any(w in t for w in ["tracking", "track", "追跡", "番号"]):
        return "追跡番号"
    if any(w in t for w in ["refund", "return", "返金", "返品"]):
        return "返品・返金"
    if any(w in t for w in ["good", "worth", "recommend", "quality", "おすすめ", "品質"]):
        return "購入検討"
    if is_spec_question(text):
        return "商品スペック"
    return "その他"


# ========== ページ設定 ==========
st.set_page_config(
    page_title="Shopee 返信ツール",
    page_icon="🛍️",
    layout="wide",
    initial_sidebar_state="auto",  # モバイルは自動で折りたたみ
)

# ========== モバイル対応 CSS ==========
st.markdown("""
<style>
  /* スマホ表示の最適化 */
  @media (max-width: 768px) {
    /* メインエリアの余白を縮める */
    .block-container {
      padding-top: 1rem !important;
      padding-bottom: 2rem !important;
      padding-left: 0.8rem !important;
      padding-right: 0.8rem !important;
      max-width: 100% !important;
    }
    /* タイトルを小さく */
    h1 {
      font-size: 1.5rem !important;
      margin-bottom: 0.3rem !important;
    }
    h2 {
      font-size: 1.2rem !important;
    }
    h3 {
      font-size: 1.05rem !important;
    }
    /* ラジオボタンを縦並びに */
    .stRadio > div {
      flex-direction: column !important;
      gap: 0.3rem !important;
    }
    /* コードブロック(返信文)を読みやすく */
    pre {
      font-size: 0.95rem !important;
      white-space: pre-wrap !important;
      word-break: break-word !important;
      padding: 0.7rem !important;
    }
    code {
      font-size: 0.95rem !important;
      white-space: pre-wrap !important;
    }
    /* ボタンを大きく押しやすく */
    .stButton > button {
      min-height: 48px !important;
      font-size: 1rem !important;
      padding: 0.6rem 1rem !important;
    }
    /* テキストエリアの最低高さ */
    .stTextArea textarea {
      min-height: 100px !important;
      font-size: 16px !important; /* iOSでズーム抑止 */
    }
    .stTextInput input {
      font-size: 16px !important;
    }
    .stSelectbox > div > div {
      font-size: 16px !important;
    }
    /* 段組み崩しはStreamlitが自動でやるが、間隔を詰める */
    [data-testid="column"] {
      padding: 0 0.2rem !important;
    }
    /* メトリクスを横並びでコンパクトに */
    [data-testid="stMetricValue"] {
      font-size: 1.3rem !important;
    }
    [data-testid="stMetricLabel"] {
      font-size: 0.8rem !important;
    }
  }
  /* 全体共通: コードブロックを折り返し */
  pre, code {
    white-space: pre-wrap !important;
    word-break: break-word !important;
  }
</style>
""", unsafe_allow_html=True)

st.title("🛍️ Shopee 文章生成ツール")
st.caption("v4.2 - 返信 / 発信 / 学習 / モバイル / 認証")

# ========== パスワード認証 ==========
def _check_password() -> bool:
    """st.secretsまたは.envのAPP_PASSWORDで簡易認証 (未設定なら認証スキップ)"""
    expected = ""
    try:
        expected = st.secrets.get("APP_PASSWORD", "")
    except Exception:
        expected = ""
    if not expected:
        expected = os.getenv("APP_PASSWORD", "")
    if not expected:
        return True  # パスワード未設定なら認証なし(ローカル開発用)

    if st.session_state.get("auth_ok"):
        return True

    st.markdown("### 🔐 ログイン")
    with st.form("auth_form"):
        pwd = st.text_input("パスワード", type="password")
        submitted = st.form_submit_button("ログイン", type="primary", use_container_width=True)
    if submitted:
        if pwd == expected:
            st.session_state["auth_ok"] = True
            st.rerun()
        else:
            st.error("❌ パスワードが違います")
    st.caption("※ パスワードは管理者(山下さん)に確認してください")
    return False

if not _check_password():
    st.stop()

# ========== モード切替 ==========
mode = st.radio(
    "モード選択",
    ["📨 返信モード (お客様メッセージへの返信)", "💌 こちら発信モード (こちらから送る文章)"],
    horizontal=True,
    label_visibility="collapsed",
    key="mode_select",
)

# ========== 💌 こちら発信モード ==========
if mode.startswith("💌"):
    st.markdown("### 💌 こちら発信モード — お客様へ送る文章を生成")
    st.caption("意図と必要情報を入れると、丁寧な発信文を生成します")

    # シーン選択
    SCENE_PRESETS = {
        "📦 配送遅延のお詫び": "配送が遅延していることへのお詫び。トラッキング確認をお願いし、補償(クーポン等)あれば添える",
        "🚚 発送完了の連絡": "商品を発送完了したお知らせ。トラッキング番号を伝え、到着予定を案内",
        "❌ 在庫切れの連絡": "ご注文商品が在庫切れになった旨のお詫び。代替案 or キャンセル(返金)選択を提示",
        "💰 返金処理完了": "返金処理が完了した連絡。反映に数日かかる旨を伝える",
        "⭐ レビュー依頼": "商品到着後のレビュー依頼。気に入ってもらえたか確認も含める",
        "🎁 セール/クーポン案内": "次回使えるクーポンやセール情報の案内",
        "❓ 商品質問への補足": "前の回答への追加情報・補足説明",
        "🛠 カスタム注文確認": "サイズ/カラー/数量等の特注確認",
        "🙏 お詫び一般": "何らかのトラブルへのお詫び(理由カスタム)",
        "✍️ 自由入力": "上記以外、自分で意図を書く",
    }
    scene = st.selectbox("シーン", list(SCENE_PRESETS.keys()), key="scene_select")
    scene_default_intent = SCENE_PRESETS.get(scene, "")

    col_o1, col_o2 = st.columns([1, 1], gap="large")

    with col_o1:
        st.subheader("📝 発信内容")
        intent = st.text_area(
            "意図 (日本語でOK)",
            value=scene_default_intent,
            height=100,
            help="お客様に何を伝えたいかを日本語で書きます",
            key="outgoing_intent",
        )
        extra_info = st.text_area(
            "追加情報 (任意)",
            placeholder="例: トラッキング番号 TH1234567 / +3日遅延予定 / クーポンコード SAVE10",
            height=80,
            key="outgoing_extra",
        )

        target_lang = st.selectbox(
            "お客様の言語",
            ["English", "ภาษาไทย (Thai)", "繁體中文 (Traditional Chinese)",
             "Bahasa Melayu (Malay)", "Português (Portuguese - Brazil)",
             "Filipino/English", "日本語"],
            key="outgoing_lang",
        )

        tone = st.selectbox(
            "トーン",
            ["丁寧でフレンドリー (標準)", "とても丁寧 (お詫び・トラブル時)",
             "カジュアル (常連客向け)", "簡潔・ビジネスライク"],
            key="outgoing_tone",
        )

        generate_out_btn = st.button("✨ 発信文を生成", type="primary", use_container_width=True, key="gen_out_btn")

    with col_o2:
        st.subheader("💬 発信文(コピー用)")
        st.caption("生成された文をコピペしてお客様に送れます")

        if generate_out_btn and intent.strip():
            out_prompt = f"""You are a customer support assistant for a Japanese product seller on Shopee.
Generate a polite OUTGOING message (from shop to customer) in {target_lang} based on the staff's intent below.

=== STAFF'S INTENT (in Japanese) ===
{intent}

=== EXTRA INFO ===
{extra_info or '(none)'}

=== TONE ===
{tone}

=== STRICT RULES ===
1. LANGUAGE: Output entire message in {target_lang}. Do NOT mix languages.
   - If Thai: use ค่ะ (female polite) consistently, never mix with ครับ
   - Thai e-commerce terms: voucher=วาวเชอร์ or คูปองส่วนลด (NEVER บัตรเดบิต/บัตรเครดิต), discount=ส่วนลด, order=คำสั่งซื้อ, refund=คืนเงิน, tracking=เลขพัสดุ
2. STRUCTURE: Start with greeting (e.g. "Hi!" "Dear customer"), state the purpose clearly, end with polite close
3. LENGTH: Short and direct. 2-4 sentences for simple notices. Up to 6 sentences for apologies/explanations.
4. NO BANNED WORDS: Never use "cancel" / "キャンセル". Use "we'll process this" / "we'll handle this" instead
5. BE PROACTIVE: If apologizing, suggest a concrete next step (compensation/tracking/refund timeline)
6. NO EMOJIS in the message body (greeting can have 1 if friendly)
7. NO FILLER: No "Thank you for your patience" stacking, no "I hope this helps" closings

=== OUTPUT FORMAT ===
First output the message in {target_lang}.
Then output a line "---" (three dashes).
Then output the same message translated to Japanese (for staff verification).
"""
            with st.spinner("発信文を生成中..."):
                try:
                    _client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
                    _msg = _client.messages.create(
                        model=MODEL,
                        max_tokens=1000,
                        messages=[{"role": "user", "content": out_prompt}],
                    )
                    raw = _msg.content[0].text.strip()

                    # --- で分割
                    parts = raw.split("---", 1)
                    main_text = parts[0].strip()
                    ja_text = parts[1].strip() if len(parts) > 1 else ""

                    st.code(main_text, language=None)
                    st.caption("↑ 右上アイコンでコピー")
                    if ja_text:
                        with st.expander("📖 日本語訳 (確認用)", expanded=True):
                            st.write(ja_text)
                except Exception as e:
                    st.error(f"生成エラー: {e}")
        else:
            st.info("← 左のフォームに入力して「発信文を生成」を押してください")

    st.divider()
    st.caption("💡 ヒント: 「自由入力」を選ぶと細かい意図を書けます。複雑な依頼でも対応できます")
    st.stop()

# ========== 以下、📨 返信モード (既存) ==========

# ========== サイドバー ==========
with st.sidebar:
    st.header("📌 ルール確認")
    st.markdown("""
    ✅ お客様の言語で返信
    ✅ 丁寧＆フレンドリーなトーン
    ✅ **必ずショップ側で会話を終わらせる**
    🚫 **「キャンセル」は使用禁止**
    📦 到着目安：注文から**7〜10日**
    🔍 商品詳細 → **Perplexityが自動調査**
    """)

    # ===== 学習統計 =====
    st.divider()
    _learned_count = len(load_learned())
    _history_count = len(load_history())
    st.header("🎓 学習状況")
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        st.metric("承認済み返信", _learned_count)
    with col_s2:
        st.metric("総質問履歴", _history_count)
    if _learned_count > 0:
        # カテゴリ別件数
        from collections import Counter
        _cat_counts = Counter()
        for ex in load_learned():
            _cat_counts[ex.get("category", "その他")] += 1
        with st.expander("📊 カテゴリ別", expanded=False):
            for cat, n in _cat_counts.most_common():
                st.write(f"・{cat}: {n}件")

    # ===== よく来る質問テンプレ（履歴から自動生成）=====
    st.divider()
    history = load_history()
    template_items = [h for h in history if h.get("count", 1) >= TEMPLATE_MIN_COUNT]
    if template_items:
        st.header("📂 よく来る質問テンプレ")
        st.caption(f"過去{TEMPLATE_MIN_COUNT}回以上来た問い合わせ")
        for item in sorted(template_items, key=lambda x: x.get("count", 1), reverse=True)[:8]:
            label = f"[{item['category']}] {item['inquiry'][:30]}{'...' if len(item['inquiry']) > 30 else ''} ×{item['count']}"
            if st.button(label, key=f"tpl_{item['inquiry'][:20]}", use_container_width=True):
                st.session_state["template_text"] = item["inquiry"]
                st.session_state["template_reply"] = item["reply"]
                st.rerun()


# ========== メインエリア ==========
col1, col2 = st.columns([1, 1], gap="large")

with col1:
    st.subheader("📨 お客様からのチャット")

    default_text    = st.session_state.get("template_text", "")
    default_product = st.session_state.get("template_product", "")

    # スクショ読み込み
    uploaded = st.file_uploader("スクショから読み込む（任意）", type=["png", "jpg", "jpeg"], label_visibility="collapsed")
    if uploaded:
        import base64
        img_bytes = uploaded.read()
        img_b64   = base64.standard_b64encode(img_bytes).decode()
        ext       = uploaded.name.rsplit(".", 1)[-1].lower()
        mime      = "image/png" if ext == "png" else "image/jpeg"
        ocr_key   = f"ocr_{hash(img_b64[:100])}"
        if ocr_key not in st.session_state:
            with st.spinner("スクショからチャット内容を読み取り中..."):
                try:
                    _c = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
                    ocr_msg = _c.messages.create(
                        model=MODEL,
                        max_tokens=800,
                        messages=[{
                            "role": "user",
                            "content": [
                                {"type": "image", "source": {"type": "base64", "media_type": mime, "data": img_b64}},
                                {"type": "text", "text": "This is a screenshot of a Shopee customer chat. Extract the full conversation in order, labeling each message as either 'Customer:' or 'Shop:'. Output the labeled conversation only, no explanation."}
                            ]
                        }]
                    )
                    st.session_state[ocr_key] = ocr_msg.content[0].text
                except Exception as e:
                    st.session_state[ocr_key] = ""
                    st.error(f"読み取りエラー: {e}")
        if st.session_state.get(ocr_key):
            default_text = st.session_state[ocr_key]
            st.success("スクショからチャット内容を読み取りました")

    inquiry_text = st.text_area(
        label="チャット内容（会話ごとコピペ推奨）",
        value=default_text,
        height=220,
        placeholder="例：\nHi, is this compatible with 220V? And what is the size?"
    )

    product_name_input = st.text_input(
        label="🛒 商品名 または ASINコード（スペック質問のときに使用）",
        value=default_product,
        placeholder="例：パナソニック ヘアドライヤー EH-NA0J　/ ASIN: B0XXXXXX",
    )
    st.caption("ASINコード（例：B0GPNJBQR2）を入力するとAmazonから商品名を自動取得します")

    # ASINなら商品名を自動取得
    asin_pattern = re.compile(r'^[A-Z0-9]{10}$')
    product_name = product_name_input.strip()
    if asin_pattern.match(product_name):
        asin_cache_key = f"asin_name_{product_name}"
        if asin_cache_key not in st.session_state:
            with st.spinner(f"Amazon から商品名を取得中（ASIN: {product_name}）..."):
                fetched = fetch_name_from_asin(product_name)
                st.session_state[asin_cache_key] = fetched
        fetched_name = st.session_state.get(asin_cache_key, "")
        if fetched_name:
            product_name = fetched_name
            st.success(f"商品名取得：{fetched_name}")
        else:
            st.warning("商品名を取得できませんでした。商品名を直接入力してください。")

    # お客様チャットの日本語訳（テキストが変わったときだけ翻訳）
    if inquiry_text.strip():
        cached_key = f"inq_tl_{hash(inquiry_text)}"
        if cached_key not in st.session_state:
            with st.spinner("日本語訳を生成中..."):
                try:
                    _c = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
                    tl = _c.messages.create(
                        model=TRANSLATION_MODEL,
                        max_tokens=600,
                        messages=[{"role": "user", "content": f"Translate the following Shopee customer chat into natural Japanese. Use proper e-commerce terms: 'original'→'正規品', 'cancel'→'注文キャンセル', 'tracking'→'追跡番号', 'voucher'→'バウチャー', 'coupon'→'クーポン', 'discount'→'割引', 'checkout'→'購入手続き', 'order'→'注文', 'refund'→'返金', 'return'→'返品'. Keep speaker labels if present. Output ONLY the translation:\n\n{inquiry_text}"}]
                    )
                    st.session_state[cached_key] = tl.content[0].text
                except Exception:
                    st.session_state[cached_key] = ""
        if st.session_state.get(cached_key):
            with st.expander("日本語訳", expanded=True):
                st.markdown(st.session_state[cached_key])

    # ===== 自動採用候補: 高類似度の学習済み返信があれば最初に表示 =====
    if inquiry_text and inquiry_text.strip():
        _match = get_top_learned_match(inquiry_text.strip())
        if _match:
            _score, _ex = _match
            with st.container(border=True):
                st.success(f"🎯 過去の承認済み返信が見つかりました (類似度 {_score*100:.0f}%)")
                st.caption(f"類似質問: 「{_ex['inquiry'][:60]}{'...' if len(_ex['inquiry']) > 60 else ''}」")
                st.code(_ex["reply"], language=None)
                col_use, _ = st.columns([1, 1])
                with col_use:
                    if st.button("✅ この返信を採用 (Claude呼ばない)", use_container_width=True, type="primary"):
                        st.session_state["edited_reply"] = _ex["reply"]
                        st.session_state["show_reply"] = _ex["reply"]
                        st.session_state["show_translation"] = _ex.get("reply_ja", "")
                        st.session_state["current_inquiry"] = inquiry_text
                        st.rerun()

    generate_btn = st.button("✨ 返信例を生成 (新規作成)", type="primary", use_container_width=True)

def show_reply_and_translation(reply, translation, inquiry_text, client):
    """返信例と編集可能な日本語訳を表示する共通関数"""
    display_reply = st.session_state.get("edited_reply", reply)
    st.code(display_reply, language=None)
    st.caption("↑ 右上のアイコンでコピーできます")

    # 採用ボタン（学習）
    col_adopt, col_clear = st.columns([3, 1])
    with col_adopt:
        if st.button("✅ この返信を採用して学習", use_container_width=True, type="primary"):
            # 編集済みの日本語訳があればそれも保存
            current_ja = st.session_state.get("ja_edit_area", translation)
            add_learned_example(inquiry_text, display_reply, reply_ja=current_ja)
            st.success("✅ 学習しました！次回から似た質問に自動適用されます")
    with col_clear:
        if st.button("❌ スキップ", use_container_width=True):
            pass  # 何もしない

    with st.expander("日本語訳（編集すると返信例に反映）", expanded=True):
        edited_ja = st.text_area(
            "日本語訳を編集",
            value=st.session_state.get("edited_translation", translation),
            height=120,
            key="ja_edit_area",
            label_visibility="collapsed"
        )
        if st.button("✏️ この内容で返信例を更新", use_container_width=True):
            with st.spinner("返信例を更新中..."):
                try:
                    lang_detect = client.messages.create(
                        model=MODEL,
                        max_tokens=20,
                        messages=[{"role": "user", "content": f"What language is this text written in? Reply with only the language name in English (e.g. Thai, English, Chinese):\n\n{inquiry_text}"}]
                    )
                    customer_lang = lang_detect.content[0].text.strip()
                    retranslate_prompt = f"Translate the following Japanese customer support reply into {customer_lang}. Keep the same tone and length. If translating to Thai: use ค่ะ (female polite) consistently, and use correct e-commerce terms: バウチャー→วาวเชอร์ or คูปองส่วนลด (NEVER บัตรเดบิต/บัตรเงินสด), 割引→ส่วนลด, 注文→คำสั่งซื้อ, 返金→คืนเงิน. Output ONLY the translation:\n\n{edited_ja}"
                    new_reply_msg = client.messages.create(
                        model=TRANSLATION_MODEL,
                        max_tokens=500,
                        messages=[{"role": "user", "content": retranslate_prompt}]
                    )
                    st.session_state["edited_reply"] = new_reply_msg.content[0].text
                    st.session_state["edited_translation"] = edited_ja
                    st.session_state["show_reply"] = reply
                    st.session_state["show_translation"] = translation
                    st.rerun()
                except Exception as e:
                    st.error(f"更新エラー: {e}")

with col2:
    st.subheader("💬 返信例")
    st.caption("この返信例をコピーして、そのままお客様に送ってください")

    # テンプレから選んだ場合は即表示
    if "template_reply" in st.session_state and not generate_btn:
        st.info("過去の返信テンプレを表示しています")
        st.code(st.session_state["template_reply"], language=None)
        st.caption("↑ 右上のアイコンでコピーできます")
        if st.button("クリア", key="clear_tpl"):
            del st.session_state["template_reply"]
            del st.session_state["template_text"]
            st.rerun()

    # 更新ボタン後のrerun時に返信を再表示
    elif not generate_btn and "show_reply" in st.session_state:
        _client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        show_reply_and_translation(
            st.session_state["show_reply"],
            st.session_state["show_translation"],
            st.session_state.get("current_inquiry", ""),
            _client
        )

    elif generate_btn and inquiry_text.strip():
        # テンプレ・編集済み内容をクリア
        st.session_state.pop("template_reply", None)
        st.session_state.pop("edited_reply", None)
        st.session_state.pop("edited_translation", None)

        country_code  = "SG"
        lower_inquiry = inquiry_text.lower()
        category      = detect_category(inquiry_text)

        # ===== 過去の似た問い合わせを表示 =====
        history = load_history()
        similar = find_similar(inquiry_text, history)
        if similar:
            with st.expander(f"過去の似た返信 ({len(similar)}件) — クリックで確認", expanded=False):
                for i, item in enumerate(similar):
                    st.markdown(f"**[{item['category']}]** `{item['date']}` ×{item.get('count',1)}回")
                    st.code(item["reply"], language=None)
                    if i < len(similar) - 1:
                        st.divider()

        # ===== 商品スペック質問かどうか判定 =====
        # 商品名が入力されていれば常にPerplexityで調査（キーワード不問）
        spec_question    = is_spec_question(inquiry_text)
        product_details  = ""
        product_sources  = []

        if product_name.strip():
            with st.spinner(f"Perplexityで「{product_name}」のスペックを調査中..."):
                product_details, product_sources = search_product_details(product_name, inquiry_text)

        # ===== Claudeへの返信生成プロンプト =====
        spec_section = ""
        if product_details:
            spec_section = f"""
=== PRODUCT SPECS (researched from Perplexity — use this information in your reply) ===
{product_details}
===
"""
        # ===== 学習済み返信例をプロンプトに注入 =====
        learned = get_learned_examples(inquiry_text)
        learned_section = ""
        if learned:
            learned_section = "\n=== APPROVED REPLIES (highest priority — owner approved these exact replies) ===\n"
            for i, ex in enumerate(learned, 1):
                learned_section += f'\nApproved Example {i}:\nCustomer: "{ex["inquiry"]}"\nShop reply: "{ex["reply"]}"\n'
            learned_section += "===\n"

        prompt = f"""You are a customer support assistant for a Japanese product seller on Shopee. Your job is to write replies that sound exactly like the shop owner's real replies shown below.
{spec_section}{learned_section}
=== REPLY STYLE (learn from these real examples) ===

Example 1 — Authenticity question:
Customer: "is this original sony?"
Shop reply: "Of course, it is original sony. I will send you photos of the actual item."

Example 2 — Usage/compatibility question:
Customer: "is this item suits for metallic paint?"
Shop reply: "This product is suitable for use with metal paint."
Customer: "genuine iwata?" / "not metal paint but silver metallic paint"
Shop reply: "Yes, this is a genuine Iwata product. It is also suitable for silver metallic paint."

Example 3 — Product knowledge question (multiple questions):
Customer: "Hello! Can I ask 2 questions: How to clean this futon? How long this futon lasts before need to replace? Thank u!"
Shop reply: "Hello! For cleaning this futon, please use a vacuum cleaner and dry it in the shade. Depending on usage, it can be used for about 4–5 years. This is based on the manufacturer's information, but in practice, it may last even longer."

Example 4 — Missing information, ask back:
Customer: "I bought the keyboard but there's no sound. Why? Is there smth else I need to get?"
Shop reply: "Are you connecting it to a PC?"

=== STRICT RULES ===

1. LANGUAGE: You MUST reply in the EXACT same language as the customer's message. This is the most important rule.
   English→English / ภาษาไทย→ภาษาไทย / 中文→繁體中文 / Bahasa→Bahasa Melayu / Português→Português / 日本語→日本語
   If the customer writes in Thai, your entire reply must be in Thai. Never switch languages.
   IF REPLYING IN THAI: Use ค่ะ (female polite) consistently. NEVER mix ค่ะ and ครับ in the same reply.
   IF REPLYING IN THAI: Use confident expressions — มีสต็อกอยู่ not คงสต็อก. Avoid คง (probably) — be direct.
   IF REPLYING IN THAI: E-commerce terms: voucher=วาวเชอร์ or คูปองส่วนลด (NEVER บัตรเดบิต/บัตรเครดิต/บัตรเงินสด), discount=ส่วนลด, checkout=ชำระเงิน, order=คำสั่งซื้อ, refund=คืนเงิน, tracking=เลขพัสดุ

2. TONE & LENGTH: Short, direct, friendly. No emojis. No filler.
   - Start with a brief greeting like "Hi!" or "Hello!" is fine
   - If the answer is simple → 1–2 sentences max
   - If details are needed → use a numbered list like Example 3
   - If info is missing → ask ONE clarifying question like Example 4
   - Never pad with "I hope this helps" / "Thank you for your patience" / "Great question!"

3. CONVERSATION ENDING: Always end so the shop has the last word.
   Simple close: "Feel free to ask anytime!" or just a question back to the customer.

4. BANNED WORD: NEVER write "cancel" / "キャンセル". Use "we'll sort it out" / "対応いたします".

5. DELIVERY: "Usually 7–10 business days from order date."
   If delayed → tell customer to check tracking on Shopee app themselves.
   NEVER say you will check / contact courier / look into it.
   NEVER ask for order number — the shop can already see it in the chat.

6. PRODUCT SPECS: If product specs were researched (see above), use that info to answer directly and specifically.
   - The PRODUCT SPECS section starts with 【質問への回答】 — use that direct Yes/No/value answer first.
   - Consider the WHOLE product ecosystem: companion app, accessories, included parts. If a feature works via the official app or accessory, the answer is YES (don't reply "the device itself doesn't have this" if the app provides it).
   - Example: If the customer asks "Does it read QR codes?" and the device has no camera but the dedicated app reads QR codes → reply "Yes, you can scan QR codes using the official app."
   If no specs are provided but the customer asks about product details → give a general helpful answer based on the product type.

7. DAMAGE / WRONG ITEM: Brief empathy, then guide through Shopee's return process.

=== CUSTOMER CHAT ===
{inquiry_text}

=== OUTPUT ===
Write ONLY the shop's reply. No labels, no explanation."""

        with st.spinner("返信例を生成中..."):
            try:
                client  = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
                message = client.messages.create(
                    model=MODEL,
                    max_tokens=1000,
                    messages=[{"role": "user", "content": prompt}]
                )
                reply = message.content[0].text

                # 禁止ワードチェック
                banned    = ["cancel", "キャンセル"]
                has_banned = any(w.lower() in reply.lower() for w in banned)

                # セッションに保存
                st.session_state["current_inquiry"] = inquiry_text

                # 日本語訳を生成（学習済みの日本語訳があればそれを優先使用）
                if f"translation_{hash(reply)}" not in st.session_state:
                    # 学習済み例に日本語訳があれば翻訳をスキップ
                    learned_ja = next(
                        (ex.get("reply_ja", "") for ex in get_learned_examples(inquiry_text)
                         if ex.get("reply_ja")),
                        ""
                    )
                    if learned_ja:
                        st.session_state[f"translation_{hash(reply)}"] = learned_ja
                    else:
                        with st.spinner("日本語訳を生成中..."):
                            try:
                                translate_prompt = f"Translate the following customer support reply into natural Japanese. Use correct e-commerce terms: voucher→バウチャー (NOT キャッシュカード/デビットカード), coupon→クーポン, discount→割引, checkout→購入手続き, order→注文, refund→返金, return→返品, tracking→追跡番号. Output ONLY the translation, no labels.\n\n{reply}"
                                trans_msg = client.messages.create(
                                    model=TRANSLATION_MODEL,
                                    max_tokens=1000,
                                    messages=[{"role": "user", "content": translate_prompt}]
                                )
                                st.session_state[f"translation_{hash(reply)}"] = trans_msg.content[0].text
                            except Exception:
                                st.session_state[f"translation_{hash(reply)}"] = ""

                translation = st.session_state.get(f"translation_{hash(reply)}", "")
                st.session_state["show_reply"] = reply
                st.session_state["show_translation"] = translation

                show_reply_and_translation(reply, translation, inquiry_text, client)

                if has_banned:
                    st.error("⚠️ 禁止ワード（cancel / キャンセル）が含まれています！送信前に修正してください。")

                if product_details:
                    with st.expander("🔍 Perplexityが調査したスペック情報（参考）"):
                        st.markdown(product_details)
                        if product_sources:
                            st.divider()
                            st.caption("📎 情報源")
                            for i, url in enumerate(product_sources, 1):
                                st.markdown(f"{i}. {url}")
                    st.success("✅ Perplexityの実データを使って返信を生成しました")
                elif spec_question and not product_name.strip():
                    st.warning("スペックに関する質問のようです。左の「商品名またはASINコード」を入力するとPerplexityが自動で調査して返信に反映します。")

                # カテゴリバッジ
                st.info(f"問い合わせ種別：{category}")

                # ===== 履歴に保存 =====
                add_to_history(inquiry_text, reply, category)

            except Exception as e:
                st.error(f"エラーが発生しました: {e}")

    elif generate_btn and not inquiry_text.strip():
        st.warning("お客様のチャット内容を入力してください")
    else:
        st.markdown("""
        <div style='background:#f8f9fa; padding:30px; border-radius:12px; text-align:center;
                    height:280px; display:flex; align-items:center; justify-content:center; flex-direction:column;'>
            <p style='font-size:48px; margin:0;'>💬</p>
            <p style='color:#666; margin-top:12px;'>左にお客様のチャットを貼り付けて<br>「返信例を生成」を押してください</p>
        </div>
        """, unsafe_allow_html=True)

# ========== フッター ==========
st.divider()
st.markdown("""
<div style='background:#1a3a4a; padding:12px 18px; border-radius:8px; border-left:4px solid #2196F3; color:#ffffff;'>
<b>📌 スタッフへ</b>：生成された返信はあくまで「例」です。送信前に内容を確認してください。<br>
返信を生成するたびに履歴が自動保存され、同じ問い合わせが増えるとサイドバーにテンプレが自動表示されます。
</div>
""", unsafe_allow_html=True)
