# TaskBoard

個人用の課題管理アプリである。  
Flask と PostgreSQL を用いて、タスク管理機能を実装した。

## 主な機能
- タスクの追加・編集・削除（CRUD）
- 科目（Project）管理
- 期限・優先度・タグ管理
- タスクの固定順並び替え
- PostgreSQL を用いたデータ永続化

## 使用技術
- Python / Flask
- PostgreSQL
- SQLAlchemy
- Docker Compose

## 起動方法

### 1. リポジトリを取得
```bash
git clone https://github.com/＜自分のユーザー名＞/taskboard.git
cd taskboard
```

### 2. データベースを起動（Docker）
```bash
docker compose up -d
```

### 3. 環境変数を設定
```bash
cp .env.example .env
export $(cat .env | xargs)
```

### 4. Python 仮想環境を作成
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 5. データベース初期化
```bash
docker exec -i taskboard-db-1 psql -U postgres -d taskboard < schema.sql
docker exec -i taskboard-db-1 psql -U postgres -d taskboard < seed.sql
```

### 6. アプリ起動
```bash
python3 app.py
```

ブラウザで以下にアクセス：
```
http://localhost:5001
```

## 備考
- macOS では AirPlay の影響で 5000 番ポートが使用できない場合があるため、本アプリは 5001 番ポートを使用している。
