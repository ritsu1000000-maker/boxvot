# PayPayリンク式 Discord 自販機Bot

## 現在の構成

- `main.py` : 元のBot本体
- `runner.py` : 0円・在庫数・スラッシュコマンド・ヘルスチェックを追加する実行版
- `start.py` : `runner.py` が落ちたとき自動再起動するWatchdog
- `render.yaml` : Render設定
- `requirements.txt` : Python依存関係
- `START.bat` : Windows起動用

## 商品機能

- 0円商品対応
  - PayPayリンク不要
  - 「無料で受け取る」ボタン
  - DMへ自動納品
- 1円以上
  - PayPay受け取りリンクの金額確認
  - 金額一致時にDMへ自動納品
- 商品作成時に在庫数を指定
- `-1` = 無限在庫
- 無限在庫は販売パネルで `-` 表示
- `/shopadmin stock_set` であとから在庫変更

## 管理者コマンド

- `/shopadmin product_add`
- `/shopadmin stock_add`
- `/shopadmin stock_set`
- `/shopadmin panel`
- `/shopadmin orders`
- `/shopadmin product_delete`

購入者はスラッシュコマンドを使いません。

## Render

Build Command:

```text
pip install -r requirements.txt
```

Start Command:

```text
python -u start.py
```

Health Check Path:

```text
/health
```

Environment Variables:

```text
DISCORD_TOKEN
GUILD_ID
ADMIN_USER_ID
ADMIN_CHANNEL_ID
```

`ADMIN_CHANNEL_ID` は省略可能です。

## 自動復旧

`start.py` が `runner.py` を監視します。Botプロセスが終了した場合、数秒待って自動再起動します。Discord側の一時切断にはdiscord.pyの再接続も使用します。

## 注意

PayPayリンクの金額一致だけでは、PayPay上で実際に残高を受け取ったことまでは証明できません。このBotはPayPayアカウントへログインしたり、残高を自動受取したりしません。

Render Free Web Service自体のスピンダウンはBotコードだけでは防げません。また、Renderの一時ファイルシステムでは商品ファイルが再デプロイ等で消える場合があります。本番利用では永続ストレージを使用してください。
