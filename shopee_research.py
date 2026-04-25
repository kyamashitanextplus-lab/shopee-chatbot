#!/usr/bin/env python3
# ============================================================
# Shopee リサーチ自動化スクリプト v3.0
# 山下さん専用 / Claude Code管理版
#
# 機能：
#   1. Perplexity APIで新商品10件＋トレンド10件をリサーチ
#   2. Claude APIで英語タイトル・説明文を生成
#   3. 化粧品はD〜I列を「未依頼」に自動設定
#   4. スプシに18行目から自動転記
#   5. 目標利益率35%
# ============================================================

import os
import json
import re
import time
import requests
import gspread
import anthropic
from datetime import datetime
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
from bs4 import BeautifulSoup

load_dotenv()

# ========== 設定 ==========
PERPLEXITY_API_KEY    = os.getenv("PERPLEXITY_API_KEY")
CLAUDE_API_KEY        = os.getenv("CLAUDE_API_KEY")
CLAUDE_MODEL          = "claude-sonnet-4-5"
GOOGLE_CREDS_PATH     = os.getenv("GOOGLE_CREDENTIALS_PATH")
SPREADSHEET_ID        = os.getenv("SPREADSHEET_ID")
SHEET_NAME            = os.getenv("SHEET_NAME", "AIリサーチ")
RESEARCH_COUNT        = 10
START_ROW             = 18

# ========== 除外キーワード ==========

COSMETIC_KEYWORDS = [
    "コスメ", "化粧品", "スキンケア", "ファンデーション",
    "アイシャドウ", "チーク", "マスカラ", "アイライナー", "コンシーラー",
    "美容液", "乳液", "化粧水", "フェイスクリーム", "美白", "日焼け止め",
    "サンスクリーン", "UVケア", "UVプロテクション", "パック", "シートマスク", "洗顔",
    "クレンジング", "メイク落とし", "シャンプー", "コンディショナー",
    "トリートメント", "ヘアオイル", "ヘアケア",
    "cosmetic", "skincare", "makeup", "beauty", "serum", "face cream", "lotion",
    "化粧液", "リップスティック", "リップグロス", "リップクリーム", "リップライナー",
    "DHCオイル", "バージンオイル", "美容クリーム"
]

AIR_NG_KEYWORDS = [
    "ネイル", "マニキュア", "ネイルポリッシュ", "ネイルリムーバー",
    "香水", "フレグランス", "コロン", "オードトワレ", "パルファム",
    "塗料", "ペンキ", "ラッカー", "シンナー",
    "ガス缶", "カセットボンベ", "スプレー缶",
    "ライター", "マッチ", "花火",
    "植物", "種子", "観葉植物",
    "perfume", "fragrance", "nail polish", "paint",
    "モバイルバッテリー", "mobile battery", "充電器", "ポータブル充電",
    "ハンドソープ", "歯磨き粉", "歯磨き", "toothpaste", "hand soap",
    "洗剤", "柔軟剤", "漂白剤", "トイレットペーパー", "ティッシュ",
    # サプリ・医薬品・成分NG（アカウント凍結リスク）
    "サプリ", "サプリメント", "配合錠", "錠剤", "カプセル",
    "ビタミン", "コラーゲン", "プロテイン", "栄養補助", "栄養補給",
    "supplement", "tablet", "capsule",
    "アゼライン酸", "azelaic acid",
    "ハイドロキノン", "hydroquinone",
    "ミノキシジル", "minoxidil",
    "gaba", "ガバ",
    "hemp", "ヘンプ", "大麻", "cbd", "カンナビジオール",
    "ガンピール", "gun pill",
    "ネオスチグミン", "neostigmine",
    # 食品・飲料（完全NG・アカウント凍結リスク）
    "食品", "飲料", "健康食品", "機能性食品",
    "ビール", "ワイン", "酒", "日本酒", "ウイスキー", "チューハイ", "アルコール",
    "クロワッサン", "パン", "ケーキ", "スナック", "お菓子", "チョコ",
    "グミ", "ガム", "飴", "キャンディ", "ラムネ", "せんべい", "クッキー",
    "コンビニ", "セブンイレブン", "ローソン", "ファミマ",
    "フカヒレ", "shark fin",
    "パチンコ", "pachinko",
    "インスタントラーメン", "ラーメン", "カレー", "スープ",
    "果汁グミ", "プリッツ", "グルコサミン",
    # 本・雑誌
    "新書", "文庫", "単行本", "雑誌", "出版", "書籍",
    "集英社", "小学館", "講談社", "青春出版",
    # 医薬品・目薬
    "目薬", "eye drop", "点眼", "アイボン",
    "ペアアクネ", "acne cream",
]

BRAND_NG_KEYWORDS = [
    # スポーツブランド
    "nike", "ナイキ", "adidas", "アディダス", "new balance", "ニューバランス",
    "puma", "プーマ", "under armour", "アンダーアーマー",
    "asics", "アシックス", "mizuno", "ミズノ", "reebok", "リーボック",
    "converse", "コンバース", "vans", "バンズ", "salomon", "サロモン",
    "wilson", "ウィルソン", "gregory", "グレゴリー",
    # ハイブランド
    "louis vuitton", "ルイヴィトン", "gucci", "グッチ", "chanel", "シャネル",
    "hermès", "エルメス", "prada", "プラダ", "dior", "ディオール",
    "rolex", "ロレックス", "coach", "コーチ", "kiehl's", "キールズ",
    "shu uemura", "シュウウエムラ", "sk-ii", "skii",
    # 現地Shopee公式店舗あり（競合になるため除外）
    "ニトリ", "nitori", "無印良品", "muji", "無印", "uniqlo", "ユニクロ",
    # 化粧品大手（公式ストアあり・競合）
    "資生堂", "shiseido",
    # 腕時計ブランドNG
    "casio", "カシオ", "seiko watch", "セイコーウオッチ", "g-shock", "gshock",
    "garmin", "ガーミン",
    # 食品・飲料ブランド（出品NG）
    "suntory", "サントリー", "meiji", "明治", "glico", "グリコ",
    "nestle", "ネスレ", "nescafe", "ネスカフェ",
    "house foods", "ハウス食品", "kewpie", "キューピー",
    "daiso", "ダイソー",
    # カメラ・電子機器
    "sony", "ソニー", "panasonic", "パナソニック",
    "logicool", "ロジクール",
    # アウトドア・バッグ
    "the north face", "ノースフェイス", "porter", "ポーター",
    # 音響機器
    "jbl", "jabra", "aviot", "tanchujim",
    # その他NG確定ブランド
    "zippo", "ジッポ",
    "mt metatron", "metatron",
    "ergobaby", "エルゴベビー",
    "moft", "モフト",
    "hogotech",
    "monvera",
    "cio", "シーアイオー",
    "kenko", "ケンコー",
    "porter", "ポーター",
    "phiten", "ファイテン",
    "hario", "ハリオ",
    "arimitsu", "arimino", "アリミノ",
    "moroccanoil", "モロッカンオイル",
    "la roche-posay", "ラロッシュポゼ",
    "johnson", "ジョンソンエンドジョンソン",
    "burt's bees", "バーツビーズ",
    "bioderma", "ビオデルマ",
    "minon", "ミノン",
    "refa", "リファ",
    "tsubaki", "ツバキ",
    "meiko", "メイコー",
    "quality 1st", "クオリティファースト",
    "hoyu", "ホーユー",
    "cielo", "シエロ",
    "sonny angel", "ソニーエンジェル",
    "pop mart", "ポップマート",
    "crocs", "クロックス",
    "zojirushi", "象印",
    "soundcore",
    "polite living",
]

# 大型・重量物・輸送困難NG
LARGE_ITEM_NG_KEYWORDS = [
    "ベッド", "bed frame", "ベッドフレーム",
    "ソファ", "sofa", "イージーチェア", "回転チェア", "リクライニング",
    "ドア", "室内ドア", "door",
    "冷蔵庫", "洗濯機", "電子レンジ", "オーブン",
    "炊飯器", "ドライヤー",
    "掃除機", "vacuum cleaner",
    "エアコン", "air conditioner",
    "テレビ", "モニター 27", "モニター 32",
    "ベビーカー", "チャイルドシート"
]

# 在庫切れ・小物アクセサリー等のNGキーワード
STOCK_NG_KEYWORDS = [
    "めじるしチャーム", "めじるしアクセサリー", "ブックマークチャーム",
    "カラビナマスコット", "カラビナチャーム",
    "スクイーズ", "スクイーシー",
    "耳つぼジュエリー", "耳つぼ",
]

USED_ITEM_NG_KEYWORDS = [
    "整備済み品", "整備済み", "refurbished", "renewed",
    "中古品", "中古", "used", "訳あり", "アウトレット品",
]

FOREIGN_BRAND_KEYWORDS = [
    # 韓国コスメ
    "peripera", "ペリペラ", "innisfree", "イニスフリー", "cosrx", "laneige", "ラネージュ",
    "etude house", "エチュードハウス", "rom&nd", "romand", "missha", "ミシャ",
    "3ce", "too cool for school", "the face shop", "nature republic",
    "holika holika", "tony moly", "clio", "clubclio",
    "some by mi", "dr.jart", "mediheal", "anua", "beauty of joseon",
    "i'm meme", "im meme", "perfect diary",
    # 欧米ブランド（家電・雑貨）
    "ninja", "ニンジャ", "dyson", "ダイソン", "philips", "フィリップス",
    "braun", "ブラウン", "de'longhi", "デロンギ",
    # 欧米コスメ
    "l'oreal", "loreal", "ロレアル", "maybelline", "メイベリン", "nyx", "revlon",
    "covergirl", "e.l.f", "elf cosmetics", "wet n wild",
    "charlotte tilbury", "urban decay", "too faced", "benefit",
    "mac cosmetics", "clinique", "estee lauder", "lancome",
    "make up for ever", "l'occitane", "ロクシタン",
    # 欧米ファッション
    "zara", "h&m", "gap", "forever 21", "dickies", "ディッキーズ",
    "carhartt", "カーハート", "supreme", "シュプリーム",
    # 中国ブランド
    "xiaomi", "シャオミ", "huawei", "ファーウェイ", "realme", "oppo", "vivo",
    "anker", "アンカー", "baseus", "ベースエウス", "ugreen",
    # その他外国ブランド
    "shure", "シュア",
    "avantree",
    "ikea", "イケア",
    "apple", "samsung", "サムスン", "lego", "レゴ",
]

WEAPON_NG_KEYWORDS = [
    "銃", "ガン", "gun", "pistol", "rifle", "weapon", "武器",
    "ピストル", "ライフル", "マシンガン", "machine gun",
    "BB弾", "エアガン", "air gun", "airsoft", "エアソフト",
    "サバゲー", "サバイバルゲーム",
    "刀", "剣", "sword", "knife", "ナイフ", "dagger", "ダガー",
    "爆弾", "bomb", "手榴弾", "grenade",
    # 刃物（航空便・輸出規制リスク）
    "包丁", "はさみ", "ハサミ", "剪定", "カッター", "替刃",
    "ペティナイフ", "牛刀", "出刃包丁", "刺身包丁",
    # G-SHOCK・腕時計ブランド（競合多・利益出にくい）
    "g-shock", "gshock", "g shock", "ジーショック",
]


# ========== 判定関数 ==========

def check_keywords(product, keywords):
    text = " ".join([
        product.get("name_ja", ""),
        product.get("category", ""),
        product.get("notes", ""),
        product.get("search_keyword", "")
    ]).lower()
    return any(kw.lower() in text for kw in keywords)

def is_cosmetic(p):       return check_keywords(p, COSMETIC_KEYWORDS)
def is_air_ng(p):         return check_keywords(p, AIR_NG_KEYWORDS)
def is_brand_ng(p):       return check_keywords(p, BRAND_NG_KEYWORDS)
def is_weapon(p):         return check_keywords(p, WEAPON_NG_KEYWORDS)
def is_stock_ng(p):       return check_keywords(p, STOCK_NG_KEYWORDS)
def is_used_item(p):      return check_keywords(p, USED_ITEM_NG_KEYWORDS)
def is_foreign_brand(p):  return check_keywords(p, FOREIGN_BRAND_KEYWORDS)

def is_large_item(p):
    # name_ja と category のみチェック（notes/search_keywordの誤検知防止）
    text = " ".join([
        p.get("name_ja", ""),
        p.get("category", ""),
    ]).lower()
    return any(kw.lower() in text for kw in LARGE_ITEM_NG_KEYWORDS)


# ========== Perplexity リサーチ ==========

def research_products(category, count):
    is_new = category == "新商品"

    prompt = f"""
あなたはShopeeの商品リサーチ専門家です。
山下さんはShopeeで日本の商品をシンガポール・フィリピン・マレーシア・タイ・台湾・ブラジルに販売しています。

【依頼】
2026年4月の{"日本の新発売商品" if is_new else "日本のトレンド・人気商品"}を{count}件リサーチしてください。
ネットで購入できる商品であれば、ジャンル問わずすべて対象にしてください。

【除外カテゴリ（絶対に含めないこと）】

■ 絶対NG（アカウント凍結リスク・出品禁止）
- 食品・飲料・お菓子・スナック・インスタント食品（完全禁止）
- 健康食品・サプリメント・栄養補助食品（完全禁止）
- 成分NG：アゼライン酸・ハイドロキノン・ミノキシジル・GABA・HEMP/ヘンプ/麻・CBD・ネオスチグミン
- 医薬品・目薬・アクネクリーム・育毛剤
- フカヒレ（Shark fin）・パチンコ・ガンピール
- 銃・武器・エアガン・刃物類

■ 航空便輸送不可のもの
- 香水・フレグランス（アルコール含有）
- ネイルポリッシュ・ネイルリムーバー（引火性）
- ガス缶・スプレー缶・ライター・花火
- 植物・種子（検疫対象）
- モバイルバッテリー・リチウム電池単体

■ ブランドNG（知財リスク・競合）
- ハイブランド（Louis Vuitton・Gucci・Chanel・Hermès・Prada・Dior等）
- スポーツブランド（Nike・Adidas・New Balance・Puma・Asics・Mizuno等）
- 資生堂・SK-II・Shu Uemura・Kiehl's（公式ストアあり）
- Sony・Panasonic・Apple・Samsung（家電メーカー）
- 外国ブランド全般（韓国・欧米・中国コスメ含む）

■ 在庫切れ・利益が出ないもの
- めじるしチャーム・カラビナマスコット等の小物アクセサリー
- スクイーズ・カプセルトイ（ネット購入不可）
- 数量限定・イベント限定商品
- ドライブレコーダー・カーナビ等のカー用品

■ 大型・重量物
- ベッド・ソファ・大型家電・ベビーカー

【対象カテゴリ（この4つのみ）】
1. おもちゃ・ホビー用品（トミカ・ポケモンカード・ガンプラ・ぬいぐるみ・フィギュア等）
2. ファッション・アクセサリー（日本ブランドのみ：SNIDEL・BEAMS・ネックレス・バッグ等）
3. 化粧品・美容（日本コスメ：KATE・Canmake・Cezanne・FASIO・コーセー等）
4. キャラクターグッズ・アニメグッズ（ポケモン・ワンピース・鬼滅・ジブリ等）

【仕入れ先について（重要）】
- ネット通販で購入できる商品のみ（楽天・Amazon・メルカリ・公式EC等）
- 実店舗でしか買えない商品は除外
- 仕入れ先URLは日本のサイトのみ（Amazon.co.jp・楽天市場・公式ECサイト等）
- 海外サイト（bungu.store・tokyopenshop.com等）のURLは絶対に使わない
- **source_urlは必ずAmazon.co.jpの実在する商品ページURL（/dp/ASIN形式）または楽天の実在する商品ページURLを記載すること**
- URLが確認できない場合は空欄にすること（推測や古いモデルのURLは絶対に使わない）

【ASINについて（最重要）】
- ASINはAmazon.co.jpで現在販売中の**最新モデル・最新版**のASINを記載すること
- 型番が新しくなっている場合は必ず最新型番のASINを使うこと
- 例：PS5なら最新モデルのASIN、AirPodsなら最新世代のASIN
- 確認できない場合は空欄にすること（古いモデルのASINを記載しない）

【商品名について（最重要）】
- 必ず「ブランド名＋商品名＋型番やシリーズ名＋発売年」を含む具体的な商品名を記載
- 「有線イヤホン」「シールセット」などカテゴリ名だけの曖昧な商品名は禁止
- **架空の商品・推測で作った型番は絶対に含めないこと**
- 実際にAmazon.co.jpまたは楽天市場で販売されていることを確認できた商品のみ
- **日本ブランド・日本メーカーの商品のみ（最重要）**
- 韓国ブランド（peripera・innisfree・COSRX・Laneige・Etude House・rom&nd等）は絶対に除外
- 欧米ブランド（Ninja・Dyson・Philips・L'Oréal・Maybelline・NYX等）は絶対に除外
- 中国ブランドは絶対に除外
- 日本で製造または日本ブランドが企画・販売している商品のみ対象
- 大型家具・ベッド・ソファ・ドア・大型家電は除外（国際配送不可）

【選定基準】
- 東南アジア・台湾・ブラジルで売れやすいもの
- 利益率35%以上が見込める価格帯
- 継続して仕入れ可能な定番商品を優先

【必須記入フィールド（空欄・省略禁止）】
- name_ja：必ずブランド名＋商品名＋型番を含む具体的な名前
- release_date：発売日が不明な場合でも「2026年発売」「2025年発売」など年単位で記入
- info_url：公式サイト・Amazon・楽天・PR TIMESなど参照したURLを必ず1つ以上記入
- info_source：「Amazon.co.jp」「楽天市場」「公式サイト」「PR TIMES」など参照元を必ず記入
- cost_price：「¥1,980」など税込価格を記入。不明な場合は「要確認」と記入

【出力形式（必ずJSONのみ出力）】
{{
  "products": [
    {{
      "name_ja": "商品名（ブランド名＋商品名＋型番必須）",
      "category": "カテゴリ",
      "source_url": "仕入れ先URL（Amazon /dp/ASIN形式 または 楽天商品ページURL。確認できた場合のみ）",
      "source_platform": "仕入れ先プラットフォーム名",
      "search_keyword": "Amazon・楽天で商品を検索するキーワード（型番含む）",
      "cost_price": "仕入れ価格（税込）※必須・不明なら「要確認」",
      "release_date": "発売日※必須（例：2026/03/15 または 2026年発売）",
      "info_url": "情報源URL※必須（参照したページのURL）",
      "info_source": "情報源の種類※必須（例：Amazon.co.jp、PR TIMES、公式サイト）",
      "sns_buzz": "SNSでの話題度（高・中・低）",
      "weight_g": "商品重量の目安（グラム）",
      "seasonality": "季節性（通年・春・夏・秋・冬・イベント）",
      "jan_code": "JANコード（13桁、わかる場合のみ。不明なら空欄）",
      "asin": "Amazon ASINコード（10桁英数字、Amazon仕入れの場合のみ。不明なら空欄）",
      "country_of_origin": "原産国（例：日本、中国、韓国。不明なら空欄）",
      "notes": "備考・仕入れ時の注意点"
    }}
  ]
}}
"""

    perplexity_headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json"
    }
    perplexity_payload = {
        "model": "sonar-deep-research",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 8000
    }

    for attempt in range(3):
        resp = requests.post("https://api.perplexity.ai/chat/completions", headers=perplexity_headers, json=perplexity_payload)
        resp.raise_for_status()

        report_content = resp.json()["choices"][0]["message"]["content"]

        # sonar-deep-researchはレポート形式で返すため、ClaudeでJSON化する
        print(f"  Perplexityレポート取得済み（{len(report_content)}文字）、ClaudeでJSON化中...")

        claude_client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        json_prompt = f"""以下はShopee販売用の商品リサーチレポートです。
このレポートから商品情報を抽出し、必ず以下のJSON形式のみで出力してください。
JSONのみ出力し、説明文・前置き・コードブロック記号は一切含めないこと。

出力形式:
{{
  "products": [
    {{
      "name_ja": "商品名（ブランド名＋商品名＋型番必須）",
      "category": "カテゴリ",
      "source_url": "仕入れ先URL（Amazon /dp/ASIN形式。不明なら空欄）",
      "source_platform": "仕入れ先プラットフォーム名",
      "search_keyword": "検索キーワード",
      "cost_price": "仕入れ価格（税込）",
      "release_date": "発売日",
      "info_url": "情報源URL",
      "info_source": "情報源の種類",
      "sns_buzz": "SNS話題度（高・中・低）",
      "weight_g": "重量（グラム）",
      "seasonality": "季節性",
      "jan_code": "",
      "asin": "ASINコード（わかる場合のみ）",
      "country_of_origin": "原産国",
      "notes": "備考"
    }}
  ]
}}

リサーチレポート:
{report_content[:6000]}"""

        try:
            claude_resp = claude_client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4000,
                messages=[{"role": "user", "content": json_prompt}]
            )
            json_text = claude_resp.content[0].text.strip()
            # コードブロックがある場合は除去
            json_text = re.sub(r'^```(?:json)?\s*', '', json_text)
            json_text = re.sub(r'\s*```$', '', json_text)
            parsed = json.loads(json_text)
            products = parsed.get("products", [])
            if len(products) >= 3:
                for p in products:
                    p["research_type"] = category
                print(f"  {len(products)}件取得成功")
                return products
        except (json.JSONDecodeError, Exception) as e:
            print(f"  Claude JSON化失敗: {e}")

        print(f"  JSON取得失敗（{attempt+1}/3）、30秒後リトライ...")
        time.sleep(30)

    print(f"  {category}リサーチ失敗")
    return []


# ========== Claude 英語コンテンツ生成 ==========

def generate_english_content(product):
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

    cosmetic_note = "\nNote: This is a cosmetic product. Listing will be reviewed manually for ingredient compliance." if product.get("is_cosmetic") else ""
    jan_code = product.get("jan_code", "").strip()
    jan_note = f"\nJAN Code: {jan_code}" if jan_code else ""
    is_new_product = product.get("research_type", "") == "新商品"
    seo_hint = "New Release, New Arrival, " if is_new_product else "Best Seller, Popular, "

    # ページから取得した実データがあれば説明文生成に活用
    page_info   = product.get("page_info") or {}
    amazon_info = product.get("amazon_info", {})  # 後方互換
    real_title  = page_info.get("confirmed_title") or amazon_info.get("amazon_title", "")
    bullets     = page_info.get("bullets") or amazon_info.get("amazon_bullets", [])
    real_desc   = page_info.get("description") or amazon_info.get("amazon_description", "")

    page_section = ""
    if real_title:
        bullets_text = "\n".join(f"  - {b}" for b in bullets[:6])
        page_section = f"""
=== CONFIRMED PRODUCT DATA FROM ACTUAL PRODUCT PAGE (use as primary source) ===
Confirmed Title (Japanese): {real_title}
{"Features:" + chr(10) + bullets_text if bullets_text else ""}
{"Product Description: " + real_desc[:400] if real_desc else ""}
==="""

    prompt = f"""You are a professional copywriter creating Shopee product listings for Japanese products.

Product details:
- Product Name: {product.get('name_ja', '')}
- Category: {product.get('category', '')}
- Price: {product.get('cost_price', '')}
- Type: {"New Product" if is_new_product else "Trend/Popular"}
{jan_note}{cosmetic_note}{page_section}

REQUIREMENTS:

1. TITLE (max 120 characters):
   - Include brand name, product name, and key features
   - Include "Japan" or "Japanese" or "Made in Japan"
   - Add 2-3 SEO keywords relevant to the product (e.g. {seo_hint}Gift, Kawaii, Anime, Cute, Quality, Premium, Limited)
   - End the title with 【Direct From Japan】
   - Do NOT mention any platform names (Amazon, Rakuten, Lazada, Shopee, etc.)

2. DESCRIPTION (3-5 sentences):
   - If Amazon product data is provided above, USE IT as the primary source — extract real features, specs, and benefits
   - Write based on actual product features, materials, functions, and benefits
   - Focus on specific details: materials, size, design, functionality, quality
   - If JAN code is provided, include it as: "JAN: {jan_code}" (only if JAN code exists, otherwise omit)
   - Do NOT write generic phrases like "popular in Southeast Asia", "perfect for overseas buyers", "authentic Japanese product" etc.
   - Do NOT mention any platform names or include URLs/contact info

Output JSON only:
{{
  "title_en": "Shopee listing title in English",
  "description_en": "Product description in English"
}}"""

    for attempt in range(3):
        try:
            message = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}]
            )
            break
        except Exception as e:
            if attempt < 2:
                print(f"  Claude API 混雑中、30秒後にリトライ... ({attempt+1}/3)")
                time.sleep(30)
            else:
                print(f"  Claude API エラー: {e}")
                return {"title_en": "", "description_en": ""}

    content = message.content[0].text
    match = re.search(r'\{[\s\S]*\}', content)
    if not match:
        return {"title_en": "", "description_en": ""}
    return json.loads(match.group())


# ========== Amazon ASIN自動取得 ==========

def _score_asin_candidate(title: str, keywords: list) -> int:
    """商品名キーワードとのマッチ数でスコアリング"""
    title_lower = title.lower()
    return sum(1 for kw in keywords if kw.lower() in title_lower)

def fetch_asin_from_amazon(product_name: str) -> str:
    """
    Amazon.co.jp検索結果から最も一致するASINを返す。
    取得できない場合は空文字を返す。
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ja-JP,ja;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        search_url = f"https://www.amazon.co.jp/s?k={requests.utils.quote(product_name)}"
        resp = requests.get(search_url, headers=headers, timeout=12)
        soup = BeautifulSoup(resp.text, "lxml")

        # 検索キーワードをトークン化（スペース・記号で分割）
        keywords = [w for w in re.split(r'[\s\-・　]+', product_name) if len(w) >= 2]

        candidates = []
        for item in soup.select("div.s-result-item[data-asin]")[:10]:
            asin = item.get("data-asin", "").strip()
            if not asin or len(asin) != 10:
                continue
            title_el = item.select_one("h2 span")
            title = title_el.get_text(strip=True) if title_el else ""
            score = _score_asin_candidate(title, keywords)
            candidates.append((score, asin, title))

        if not candidates:
            return ""

        # スコア順に並べて最高スコアのASINを返す
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_asin, best_title = candidates[0]

        # スコアが低すぎる場合（1つもキーワードが一致しない）は信頼性低いためスキップ
        if best_score == 0:
            return ""

        print(f"  🔎 ASIN取得: {best_asin} (スコア:{best_score}) → {best_title[:50]}")
        return best_asin

    except Exception as e:
        print(f"  ASIN取得エラー: {e}")
        return ""


def _fetch_page_info(url: str) -> dict:
    """
    指定URLのページから商品タイトル・特徴・説明を取得する汎用関数。
    Amazon / 楽天 / 一般サイトに対応。
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ja-JP,ja;q=0.9",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=12)
        soup = BeautifulSoup(resp.text, "lxml")
        title, bullets, description, price = "", [], "", ""

        if "amazon.co.jp" in url:
            # Amazon専用パース
            title_el = soup.select_one("#productTitle")
            title = title_el.get_text(strip=True) if title_el else ""
            price_el = soup.select_one(".a-price .a-offscreen") or soup.select_one("#priceblock_ourprice")
            price = price_el.get_text(strip=True) if price_el else ""
            for li in soup.select("#feature-bullets ul li span.a-list-item")[:6]:
                t = li.get_text(strip=True)
                if t and len(t) > 5:
                    bullets.append(t)
            desc_el = soup.select_one("#productDescription p") or soup.select_one("#aplus")
            description = desc_el.get_text(strip=True)[:500] if desc_el else ""

        elif "rakuten.co.jp" in url:
            # 楽天専用パース
            title_el = soup.select_one("h1.item-name") or soup.select_one("h1") or soup.select_one(".item_name")
            title = title_el.get_text(strip=True) if title_el else ""
            price_el = soup.select_one(".price2") or soup.select_one(".price")
            price = price_el.get_text(strip=True) if price_el else ""
            desc_el = soup.select_one("#item-description") or soup.select_one(".item-description")
            description = desc_el.get_text(strip=True)[:500] if desc_el else ""

        else:
            # 一般サイト（公式サイト等）
            title_el = soup.select_one("h1")
            title = title_el.get_text(strip=True) if title_el else ""
            desc_el = soup.select_one("meta[name='description']")
            description = desc_el.get("content", "")[:500] if desc_el else ""

        if title:
            print(f"  📄 商品情報取得: {title[:55]}")

        return {
            "confirmed_title": title,
            "confirmed_price": price,
            "bullets": bullets,
            "description": description,
        }
    except Exception as e:
        print(f"  商品情報取得エラー ({url[:40]}): {e}")
        return {}


def fetch_amazon_product_info(asin: str) -> dict:
    """後方互換性のためのラッパー"""
    if not asin:
        return {}
    info = _fetch_page_info(f"https://www.amazon.co.jp/dp/{asin}")
    return {
        "amazon_title": info.get("confirmed_title", ""),
        "amazon_price": info.get("confirmed_price", ""),
        "amazon_bullets": info.get("bullets", []),
        "amazon_description": info.get("description", ""),
    }


def resolve_product(product: dict) -> str:
    """
    商品の仕入れ先URLを確定し、実際のページから商品名・説明を取得して
    product辞書を上書きする。確定したURLを返す。

    優先順位:
      1. Perplexityが返したASIN → Amazon商品ページ
      2. Perplexityが返したsource_url（Amazon/楽天/公式）
      3. 商品名でAmazonスクレイピング → ASIN取得
      4. フォールバック（検索URL）
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ja-JP,ja;q=0.9",
    }

    confirmed_url = ""

    # 1. Perplexityが返したASIN
    asin = product.get("asin", "").strip()
    if asin and len(asin) == 10 and re.match(r'^[A-Z0-9]{10}$', asin):
        confirmed_url = f"https://www.amazon.co.jp/dp/{asin}"

    # 2. Perplexityが返したsource_url
    if not confirmed_url:
        source_url = product.get("source_url", "").strip()
        if source_url:
            # AmazonならASIN抽出してクリーンなURLに
            if "amazon.co.jp" in source_url:
                extracted = extract_asin_from_url(source_url)
                if extracted:
                    product["asin"] = extracted
                    confirmed_url = f"https://www.amazon.co.jp/dp/{extracted}"
                elif "/dp/" in source_url:
                    confirmed_url = source_url.split("?")[0]
            # 楽天・公式サイトはそのまま使用
            elif "rakuten.co.jp" in source_url or "item.rakuten" in source_url:
                confirmed_url = source_url.split("?")[0]
            elif source_url.startswith("http"):
                confirmed_url = source_url.split("?")[0]

    # 3. Amazonスクレイピングでアシン取得（楽天・ZOZOでない場合）
    if not confirmed_url:
        platform = product.get("source_platform", "").lower()
        if "楽天" not in platform and "rakuten" not in platform \
                and "zozo" not in platform and "qoo10" not in platform:
            scraped_asin = fetch_asin_from_amazon(
                product.get("search_keyword") or product.get("name_ja", "")
            )
            if scraped_asin:
                product["asin"] = scraped_asin
                confirmed_url = f"https://www.amazon.co.jp/dp/{scraped_asin}"
                time.sleep(1.5)

    # 4. URLが確定したら実際のページから商品名・説明を取得して上書き
    if confirmed_url:
        page_info = _fetch_page_info(confirmed_url)
        confirmed_title = page_info.get("confirmed_title", "")

        if confirmed_title:
            # ✅ 商品名をページの実際の名前で上書き（Perplexityの推測名を使わない）
            product["name_ja"] = confirmed_title
            print(f"  ✅ 商品名確定: {confirmed_title[:55]}")

        if page_info.get("confirmed_price") and not product.get("cost_price"):
            product["cost_price"] = page_info["confirmed_price"]

        # 説明文生成用にページ情報を保存
        product["page_info"] = page_info
        return confirmed_url

    # 5. フォールバック（検索URL）
    name = product.get("name_ja", "")
    release_date = product.get("release_date", "")
    year_match = re.search(r'(20\d{2})', release_date)
    year_suffix = f" {year_match.group(1)}" if year_match else ""
    search_term = (product.get("search_keyword") or name) + year_suffix
    keyword = requests.utils.quote(search_term.strip())

    platform = product.get("source_platform", "").lower()
    if "楽天" in platform or "rakuten" in platform:
        return f"https://search.rakuten.co.jp/search/mall/{keyword}/"
    else:
        return f"https://www.amazon.co.jp/s?k={keyword}"


# ========== 仕入れ先URL生成 ==========

def extract_asin_from_url(url):
    """Amazon URLからASINを抽出する"""
    if not url:
        return ""
    # /dp/XXXXXXXXXX 形式
    match = re.search(r'/dp/([A-Z0-9]{10})', url)
    if match:
        return match.group(1)
    # /gp/product/XXXXXXXXXX 形式
    match = re.search(r'/gp/product/([A-Z0-9]{10})', url)
    if match:
        return match.group(1)
    return ""

def build_search_url(product):
    # 1. ASINフィールドが直接ある場合
    asin = product.get("asin", "").strip()
    if asin and len(asin) == 10 and re.match(r'^[A-Z0-9]{10}$', asin):
        return f"https://www.amazon.co.jp/dp/{asin}"

    # 2. source_urlがAmazonの商品ページならそこからASINを抽出して使用
    source_url = product.get("source_url", "").strip()
    if source_url and "amazon.co.jp" in source_url:
        extracted_asin = extract_asin_from_url(source_url)
        if extracted_asin:
            return f"https://www.amazon.co.jp/dp/{extracted_asin}"
        if "/dp/" in source_url or "/gp/product/" in source_url:
            return source_url.split("?")[0]

    # 3. source_urlが楽天の商品ページならそのまま使う
    if source_url and ("item.rakuten.co.jp" in source_url or "rakuten.co.jp/item" in source_url):
        return source_url.split("?")[0]

    # 4. Amazonスクレイピングで自動ASIN取得（楽天・ZOZO以外）
    platform = product.get("source_platform", "").lower()
    name = product.get("name_ja", "")
    if "楽天" not in platform and "rakuten" not in platform \
            and "zozo" not in platform and "qoo10" not in platform:
        scraped_asin = fetch_asin_from_amazon(
            product.get("search_keyword") or name
        )
        if scraped_asin:
            # 取得したASINをproductに保存（備考欄にも反映されるよう）
            product["asin"] = scraped_asin
            return f"https://www.amazon.co.jp/dp/{scraped_asin}"
        time.sleep(1)  # Amazon連続アクセス防止

    # 5. 検索URLにフォールバック（商品名＋発売年）
    release_date = product.get("release_date", "")
    year_match = re.search(r'(20\d{2})', release_date)
    year_suffix = f" {year_match.group(1)}" if year_match else ""
    search_term = (product.get("search_keyword") or name) + year_suffix
    keyword = requests.utils.quote(search_term.strip())

    if "楽天" in platform or "rakuten" in platform:
        return f"https://search.rakuten.co.jp/search/mall/{keyword}/"
    elif "zozo" in platform:
        return f"https://zozo.jp/search/?p_keywordand={keyword}"
    elif "qoo10" in platform:
        return f"https://www.qoo10.jp/gmkt.inc/Search/Search.aspx?keyword={keyword}"
    else:
        return f"https://www.amazon.co.jp/s?k={keyword}"


# ========== 備考欄生成 ==========

def build_notes(product):
    parts = []
    if product.get("country_of_origin"): parts.append(f"原産国:{product['country_of_origin']}")
    if product.get("weight_g"):          parts.append(f"重量:{product['weight_g']}g")
    asin = product.get("asin", "").strip()
    if asin and len(asin) == 10:         parts.append(f"ASIN:{asin}")
    if product.get("info_source"):       parts.append(f"情報源:{product['info_source']}")
    if product.get("is_cosmetic"):       parts.append("⚠️化粧品：成分確認必要")
    if product.get("is_air_ng"):         parts.append("🚫航空便NG確認")
    if product.get("is_brand_ng"):       parts.append("🚫ブランド権侵害リスク確認")
    if product.get("notes"):             parts.append(product["notes"])
    return " / ".join(parts)


# ========== スプシ書き込み ==========

def get_next_row(sheet):
    last_row = len(sheet.get_all_values())
    return max(last_row + 1, START_ROW)

def get_last_index(sheet):
    """A列の最後の通し番号を取得して次の番号を返す"""
    try:
        col_a = sheet.col_values(1)
        for val in reversed(col_a):
            if str(val).isdigit():
                return int(val) + 1
    except Exception:
        pass
    return 1


def write_to_sheet(sheet, row_num, research_date, product, english_content, index):
    # A〜C列（通し番号・日付・区分）
    ac_data = [
        index,                                          # A: 通し番号
        research_date,                                  # B: リサーチ日
        product.get("research_type", ""),               # C: リサーチ区分
    ]
    # J〜R列（D〜Iはドロップダウン保護のためスキップ）
    jr_data = [
        product.get("name_ja", ""),                     # J: 商品名
        build_search_url(product),                      # K: 仕入れ先URL
        product.get("cost_price", ""),                  # L: 仕入れ価格
        product.get("release_date", ""),                # M: 発売日
        product.get("info_url", ""),                    # N: 情報源URL
        english_content.get("title_en", ""),            # O: Shopeeタイトル（英語）
        english_content.get("description_en", ""),      # P: 商品説明文（英語）
        "35%",                                          # Q: 目標利益率
        build_notes(product)                            # R: 備考
    ]

    sheet.update(range_name=f"A{row_num}", values=[ac_data])
    sheet.update(range_name=f"J{row_num}", values=[jr_data])

    # 化粧品のみD〜I列に「未依頼」を設定
    if product.get("is_cosmetic"):
        sheet.update(range_name=f"D{row_num}:I{row_num}", values=[["未依頼"] * 6])

    print(f"  転記完了: {product.get('name_ja', '')} {'[化粧品→未依頼]' if product.get('is_cosmetic') else ''}")


# ========== メイン ==========

def run_weekly_research():
    print("=== Shopeeリサーチ自動化 v3.0 開始 ===")

    # Google Sheets接続
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(GOOGLE_CREDS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(SPREADSHEET_ID)
    sheet = spreadsheet.worksheet(SHEET_NAME)

    research_date = datetime.now().strftime("%Y/%m/%d")
    next_row = get_next_row(sheet)
    start_index = get_last_index(sheet)
    print(f"開始行: {next_row}行目 / 開始通し番号: {start_index}")

    # 新商品リサーチ
    print("新商品リサーチ中...")
    new_products = research_products("新商品", RESEARCH_COUNT)

    # トレンドリサーチ
    print("トレンド商品リサーチ中...")
    trend_products = research_products("トレンド", RESEARCH_COUNT)

    all_products_raw = new_products + trend_products

    # NGフィルタリング＋ブランド重複制限（同ブランド最大2件）
    all_products = []
    brand_count = {}
    for p in all_products_raw:
        if is_weapon(p):
            print(f"  💪武器NG除外: {p.get('name_ja', '')}")
            continue
        if is_used_item(p):
            print(f"  🔄中古品NG除外: {p.get('name_ja', '')}")
            continue
        if is_brand_ng(p):
            print(f"  🚫ブランドNG除外: {p.get('name_ja', '')}")
            continue
        if is_foreign_brand(p):
            print(f"  🌏外国ブランドNG除外: {p.get('name_ja', '')}")
            continue
        if is_stock_ng(p):
            print(f"  🚫在庫リスクNG除外: {p.get('name_ja', '')}")
            continue
        if is_large_item(p):
            print(f"  📦大型輸送NG除外: {p.get('name_ja', '')}")
            continue
        if is_air_ng(p):
            print(f"  ✈️航空便NG除外: {p.get('name_ja', '')}")
            continue
        # ブランド重複チェック（同ブランド最大2件）
        brand = p.get("name_ja", "").split()[0] if p.get("name_ja") else "不明"
        brand_count[brand] = brand_count.get(brand, 0) + 1
        if brand_count[brand] > 2:
            print(f"  🔁ブランド重複除外: {p.get('name_ja', '')}")
            continue
        all_products.append(p)
    print(f"NGフィルタ後: {len(all_products)}件")

    # 転記
    print("スプシに転記中...")
    row_num = next_row

    for i, product in enumerate(all_products, start=start_index):
        product["is_cosmetic"] = is_cosmetic(product)
        product["is_air_ng"]   = is_air_ng(product)
        product["is_brand_ng"] = is_brand_ng(product)

        # URL確定 + 商品名上書き + ページ情報取得を一括実行
        final_url = resolve_product(product)
        time.sleep(1.5)  # 連続アクセス防止

        english_content = generate_english_content(product)
        write_to_sheet(sheet, row_num, research_date, product, english_content, i)
        row_num += 1
        time.sleep(1)

    print(f"=== 完了！{len(all_products)}件を転記しました ===")


if __name__ == "__main__":
    run_weekly_research()
