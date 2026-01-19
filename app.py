import os
from datetime import date, timedelta
from flask import Flask, request, redirect, url_for, render_template_string, abort
from sqlalchemy import create_engine, text

app = Flask(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL が未設定。export DATABASE_URL=... を先に実行すること")

engine = create_engine(DATABASE_URL, future=True)

BASE = """
<!doctype html><html><head><meta charset="utf-8">
<title>TaskBoard</title>
<style>
body{font-family:system-ui,-apple-system; margin:24px; max-width:1100px;}
a{margin-right:10px;}
h1{margin:0 0 6px;}
.small{color:#666; font-size:12px;}
.row{display:flex; gap:10px; flex-wrap:wrap; align-items:center;}
.card{border:1px solid #ddd; border-radius:12px; padding:12px; margin-top:12px;}
table{border-collapse:collapse; width:100%; margin-top:10px;}
th,td{border-bottom:1px solid #eee; padding:10px; vertical-align:top;}
th{color:#555; font-weight:600; text-align:left;}
.badge{display:inline-block; padding:2px 10px; border:1px solid #aaa; border-radius:999px; font-size:12px;}
.due_over{color:#b00020; font-weight:700;}
.due_soon{color:#8a4b00; font-weight:700;}
input,select,textarea,button{font-size:14px; padding:7px; border-radius:10px; border:1px solid #ccc;}
button{cursor:pointer;}
.mono{font-family:ui-monospace, SFMono-Regular, Menlo, monospace;}
</style>
</head><body>
<h1>TaskBoard</h1>
<div class="small">個人用（検索・フィルタ・期限・優先度・タグ・科目CRUD・並び順固定）</div>
<hr/>
{% block body %}{% endblock %}
</body></html>
"""

def render_page(body_html: str, **ctx):
    page = BASE.replace("{% block body %}{% endblock %}", body_html)
    return render_template_string(page, **ctx)

def today():
    return date.today()

def parse_date(s: str):
    s = (s or "").strip()
    if not s:
        return None
    return date.fromisoformat(s)

def normalize_tags(s: str):
    if not s:
        return ""
    parts = [p.strip() for p in s.replace("，", ",").split(",")]
    parts = [p for p in parts if p]
    return ",".join(parts)

def error_page(message: str, status_code: int = 400):
    body = """
    <div class="card">
      <h2>エラー</h2>
      <p>{{message}}</p>
      <a href="javascript:history.back()">←戻る</a>
    </div>
    """
    return render_page(body, message=message), status_code

@app.get("/")
def root():
    return redirect(url_for("tasks_list"))

# -------------------------
# Tasks
# -------------------------
@app.get("/tasks")
def tasks_list():
    view = request.args.get("view", "all")   # all / today / week / overdue / done
    q = request.args.get("q", "").strip()
    tag = request.args.get("tag", "").strip()
    status = request.args.get("status", "")  # TODO/DOING/DONE or ""
    sort = request.args.get("sort", "order") # order / due / priority / created

    where = []
    params = {}

    if status:
        where.append("t.status = :status")
        params["status"] = status

    if view == "today":
        where.append("t.due_date = CURRENT_DATE AND t.status != 'DONE'")
    elif view == "week":
        where.append("t.due_date >= CURRENT_DATE AND t.due_date <= (CURRENT_DATE + INTERVAL '6 days') AND t.status != 'DONE'")
    elif view == "overdue":
        where.append("t.due_date < CURRENT_DATE AND t.status != 'DONE'")
    elif view == "done":
        where.append("t.status = 'DONE'")

    if q:
        where.append("(t.title ILIKE :q OR COALESCE(t.description,'') ILIKE :q)")
        params["q"] = f"%{q}%"

    if tag:
        where.append("COALESCE(t.tags,'') ILIKE :tag")
        params["tag"] = f"%{tag}%"

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    # 並び
    if sort == "created":
        order_sql = "ORDER BY t.id DESC"
    elif sort == "due":
        order_sql = """
        ORDER BY
          CASE t.status WHEN 'TODO' THEN 1 WHEN 'DOING' THEN 2 ELSE 3 END,
          t.due_date NULLS LAST,
          t.sort_order NULLS LAST,
          t.id DESC
        """
    elif sort == "priority":
        order_sql = """
        ORDER BY
          CASE t.status WHEN 'TODO' THEN 1 WHEN 'DOING' THEN 2 ELSE 3 END,
          CASE t.priority WHEN 'HIGH' THEN 1 WHEN 'MID' THEN 2 ELSE 3 END,
          t.sort_order NULLS LAST,
          t.due_date NULLS LAST,
          t.id DESC
        """
    else:
        # order（固定順）
        order_sql = """
        ORDER BY
          CASE t.status WHEN 'TODO' THEN 1 WHEN 'DOING' THEN 2 ELSE 3 END,
          t.sort_order NULLS LAST,
          t.id ASC
        """

    sql = f"""
    SELECT
      t.id, t.project_id, t.title, t.status, t.priority, t.due_date, t.tags, t.completed_at,
      t.sort_order,
      p.name AS project_name
    FROM tasks t
    JOIN projects p ON p.id = t.project_id
    {where_sql}
    {order_sql};
    """

    with engine.connect() as conn:
        tasks = conn.execute(text(sql), params).mappings().all()
        projects = conn.execute(text("SELECT id, name FROM projects ORDER BY id;")).mappings().all()

    tagset = set()
    for t in tasks:
        raw = (t["tags"] or "").strip()
        if raw:
            for x in raw.split(","):
                x = x.strip()
                if x:
                    tagset.add(x)
    tags_sorted = sorted(tagset)

    body = """
    <div class="row">
      <a href="{{ url_for('task_new') }}"><button>＋ 新規タスク</button></a>

      <a href="{{ url_for('tasks_list', view='all') }}">全部</a>
      <a href="{{ url_for('tasks_list', view='today') }}">今日</a>
      <a href="{{ url_for('tasks_list', view='week') }}">今週</a>
      <a href="{{ url_for('tasks_list', view='overdue') }}">期限切れ</a>
      <a href="{{ url_for('tasks_list', view='done') }}">完了</a>

      <span class="small">｜</span>
      <a href="{{ url_for('projects_list') }}">科目管理</a>
    </div>

    <div class="card">
      <form method="get" class="row">
        <input name="q" placeholder="検索（タイトル/本文）" value="{{q}}" style="min-width:260px;">
        <input name="tag" placeholder="タグ（例：レポート）" value="{{tag}}">
        <select name="status">
          <option value="" {{ 'selected' if not status else '' }}>状態:ALL</option>
          <option value="TODO" {{ 'selected' if status=='TODO' else '' }}>TODO</option>
          <option value="DOING" {{ 'selected' if status=='DOING' else '' }}>DOING</option>
          <option value="DONE" {{ 'selected' if status=='DONE' else '' }}>DONE</option>
        </select>
        <select name="sort">
          <option value="order" {{ 'selected' if sort=='order' else '' }}>並び:固定順</option>
          <option value="due" {{ 'selected' if sort=='due' else '' }}>並び:期限</option>
          <option value="priority" {{ 'selected' if sort=='priority' else '' }}>並び:優先度</option>
          <option value="created" {{ 'selected' if sort=='created' else '' }}>並び:作成順</option>
        </select>
        <input type="hidden" name="view" value="{{view}}">
        <button type="submit">適用</button>
      </form>

      {% if tags_sorted %}
      <div class="small" style="margin-top:8px;">
        タグ候補：
        {% for t in tags_sorted %}
          <a class="badge" href="{{ url_for('tasks_list', tag=t) }}">{{t}}</a>
        {% endfor %}
      </div>
      {% endif %}

      <div class="small" style="margin-top:6px;">
        ※「固定順」で並び替えたいときは、右端の「↑↓」で入れ替える（同じ科目＋同じ状態の中で動く）。
      </div>
    </div>

    <div class="card">
      <div class="small">表示件数：{{tasks|length}} 件</div>
      <table>
        <tr>
          <th style="width:40px;">ID</th>
          <th>タスク</th>
          <th style="width:120px;">科目</th>
          <th style="width:90px;">状態</th>
          <th style="width:90px;">優先度</th>
          <th style="width:110px;">期限</th>
          <th style="width:220px;">操作</th>
        </tr>
        {% for t in tasks %}
        <tr>
          <td class="mono">{{t.id}}</td>
          <td>
            <div><b>{{t.title}}</b></div>
            {% if t.tags %}<div class="small"># {{t.tags}}</div>{% endif %}
          </td>
          <td>{{t.project_name}}</td>
          <td><span class="badge">{{t.status}}</span></td>
          <td><span class="badge">{{t.priority}}</span></td>
          <td>
            {% if t.due_date %}
              {% set due = t.due_date %}
              {% if t.status != 'DONE' and due < today %}
                <span class="due_over">{{due}}</span>
              {% elif t.status != 'DONE' and due <= soon %}
                <span class="due_soon">{{due}}</span>
              {% else %}
                {{due}}
              {% endif %}
            {% else %}
              -
            {% endif %}
          </td>
          <td>
            <a href="{{ url_for('task_edit', task_id=t.id) }}">編集</a>

            {% if t.status != 'DONE' %}
              <form style="display:inline" method="post" action="{{ url_for('task_done', task_id=t.id) }}">
                <button type="submit">完了</button>
              </form>
            {% else %}
              <form style="display:inline" method="post" action="{{ url_for('task_undo', task_id=t.id) }}">
                <button type="submit">戻す</button>
              </form>
            {% endif %}

            <form style="display:inline" method="post" action="{{ url_for('task_delete', task_id=t.id) }}" onsubmit="return confirm('削除する？')">
              <button type="submit">削除</button>
            </form>

            <form style="display:inline" method="post" action="{{ url_for('task_up', task_id=t.id) }}">
              <button type="submit">↑</button>
            </form>
            <form style="display:inline" method="post" action="{{ url_for('task_down', task_id=t.id) }}">
              <button type="submit">↓</button>
            </form>
          </td>
        </tr>
        {% endfor %}
      </table>
    </div>
    """
    return render_page(
        body,
        tasks=tasks,
        projects=projects,
        tags_sorted=tags_sorted,
        view=view,
        q=q,
        tag=tag,
        status=status,
        sort=sort,
        today=today(),
        soon=today() + timedelta(days=2),
    )

@app.get("/tasks/new")
def task_new():
    with engine.connect() as conn:
        projects = conn.execute(text("SELECT id, name FROM projects ORDER BY id;")).mappings().all()

    body = """
    <div class="row">
      <a href="{{ url_for('tasks_list') }}">← 戻る</a>
    </div>

    <h2>新規タスク</h2>
    <div class="card">
      <form method="post" action="{{ url_for('task_create') }}">
        <p>タイトル<br><input name="title" required style="width:100%"></p>
        <p>本文（メモ）<br><textarea name="description" rows="5" style="width:100%"></textarea></p>

        <div class="row">
          <label>科目
            <select name="project_id" required>
              {% for p in projects %}
                <option value="{{p.id}}">{{p.name}}</option>
              {% endfor %}
            </select>
          </label>

          <label>状態
            <select name="status">
              <option>TODO</option>
              <option>DOING</option>
              <option>DONE</option>
            </select>
          </label>

          <label>優先度
            <select name="priority">
              <option>LOW</option>
              <option selected>MID</option>
              <option>HIGH</option>
            </select>
          </label>

          <label>期限
            <input type="date" name="due_date">
          </label>
        </div>

        <p>タグ（カンマ区切り：例 レポート,試験）<br>
          <input name="tags" placeholder="レポート,試験" style="width:100%">
        </p>

        <button type="submit">作成</button>
      </form>
    </div>
    """
    return render_page(body, projects=projects)

@app.post("/tasks")
def task_create():
    title = (request.form.get("title") or "").strip()
    if not title:
        abort(400)

    project_id = int(request.form["project_id"])
    description = request.form.get("description", "")
    status = request.form.get("status", "TODO")
    priority = request.form.get("priority", "MID")
    due = parse_date(request.form.get("due_date"))
    tags = normalize_tags(request.form.get("tags", ""))

    with engine.begin() as conn:
        # sort_orderは「同じ科目＋同じ状態の末尾」に追加
        current_max = conn.execute(text("""
          SELECT COALESCE(MAX(sort_order), 0) AS m
          FROM tasks
          WHERE project_id=:pid AND status=:st
        """), {"pid": project_id, "st": status}).mappings().first()["m"]

        conn.execute(text("""
          INSERT INTO tasks (project_id, title, description, status, priority, due_date, tags, sort_order)
          VALUES (:project_id, :title, :description, :status, :priority, :due_date, :tags, :sort_order)
        """), dict(
            project_id=project_id,
            title=title,
            description=description,
            status=status,
            priority=priority,
            due_date=due,
            tags=tags,
            sort_order=int(current_max) + 1
        ))

    return redirect(url_for("tasks_list"))

@app.get("/tasks/<int:task_id>/edit")
def task_edit(task_id: int):
    with engine.connect() as conn:
        task = conn.execute(text("SELECT * FROM tasks WHERE id=:id"), {"id": task_id}).mappings().first()
        if not task:
            abort(404)
        projects = conn.execute(text("SELECT id, name FROM projects ORDER BY id;")).mappings().all()

    body = """
    <div class="row">
      <a href="{{ url_for('tasks_list') }}">← 戻る</a>
    </div>

    <h2>編集 #{{task.id}}</h2>
    <div class="card">
      <form method="post" action="{{ url_for('task_update', task_id=task.id) }}">
        <p>タイトル<br><input name="title" value="{{task.title}}" required style="width:100%"></p>
        <p>本文（メモ）<br><textarea name="description" rows="5" style="width:100%">{{task.description or ''}}</textarea></p>

        <div class="row">
          <label>科目
            <select name="project_id" required>
              {% for p in projects %}
                <option value="{{p.id}}" {{ 'selected' if p.id==task.project_id else '' }}>{{p.name}}</option>
              {% endfor %}
            </select>
          </label>

          <label>状態
            <select name="status">
              {% for s in ['TODO','DOING','DONE'] %}
                <option {{ 'selected' if task.status==s else '' }}>{{s}}</option>
              {% endfor %}
            </select>
          </label>

          <label>優先度
            <select name="priority">
              {% for p in ['LOW','MID','HIGH'] %}
                <option {{ 'selected' if task.priority==p else '' }}>{{p}}</option>
              {% endfor %}
            </select>
          </label>

          <label>期限
            <input type="date" name="due_date" value="{{task.due_date or ''}}">
          </label>
        </div>

        <p>タグ（カンマ区切り）<br>
          <input name="tags" value="{{task.tags or ''}}" style="width:100%">
        </p>

        <button type="submit">更新</button>
      </form>
    </div>
    """
    return render_page(body, task=task, projects=projects)

@app.post("/tasks/<int:task_id>")
def task_update(task_id: int):
    title = (request.form.get("title") or "").strip()
    if not title:
        abort(400)

    new_project_id = int(request.form["project_id"])
    description = request.form.get("description", "")
    new_status = request.form.get("status", "TODO")
    priority = request.form.get("priority", "MID")
    due = parse_date(request.form.get("due_date"))
    tags = normalize_tags(request.form.get("tags", ""))

    with engine.begin() as conn:
        old = conn.execute(text("SELECT project_id, status, sort_order FROM tasks WHERE id=:id"), {"id": task_id}).mappings().first()
        if not old:
            abort(404)

        # 科目 or 状態が変わったら、移動先グループの末尾に付け直す
        sort_order = old["sort_order"]
        if old["project_id"] != new_project_id or old["status"] != new_status:
            mx = conn.execute(text("""
              SELECT COALESCE(MAX(sort_order), 0) AS m
              FROM tasks
              WHERE project_id=:pid AND status=:st
            """), {"pid": new_project_id, "st": new_status}).mappings().first()["m"]
            sort_order = int(mx) + 1

        conn.execute(text("""
          UPDATE tasks
          SET project_id=:project_id,
              title=:title,
              description=:description,
              status=:status,
              priority=:priority,
              due_date=:due_date,
              tags=:tags,
              sort_order=:sort_order,
              updated_at=NOW()
          WHERE id=:id
        """), dict(
            id=task_id,
            project_id=new_project_id,
            title=title,
            description=description,
            status=new_status,
            priority=priority,
            due_date=due,
            tags=tags,
            sort_order=sort_order
        ))

        if new_status == "DONE":
            conn.execute(text("UPDATE tasks SET completed_at=COALESCE(completed_at, NOW()) WHERE id=:id"), {"id": task_id})
        else:
            conn.execute(text("UPDATE tasks SET completed_at=NULL WHERE id=:id"), {"id": task_id})

    return redirect(url_for("tasks_list"))

# --- 並び替え（同じ科目＋同じ状態の中でswap） ---
@app.post("/tasks/<int:task_id>/up")
def task_up(task_id: int):
    with engine.begin() as conn:
        cur = conn.execute(text("""
          SELECT id, project_id, status, sort_order
          FROM tasks WHERE id=:id
        """), {"id": task_id}).mappings().first()
        if not cur:
            abort(404)

        prev = conn.execute(text("""
          SELECT id, sort_order
          FROM tasks
          WHERE project_id=:pid AND status=:st
            AND sort_order < :so
          ORDER BY sort_order DESC
          LIMIT 1
        """), {"pid": cur["project_id"], "st": cur["status"], "so": cur["sort_order"]}).mappings().first()

        if prev:
            conn.execute(text("UPDATE tasks SET sort_order=:so WHERE id=:id"), {"so": prev["sort_order"], "id": cur["id"]})
            conn.execute(text("UPDATE tasks SET sort_order=:so WHERE id=:id"), {"so": cur["sort_order"], "id": prev["id"]})

    return redirect(url_for("tasks_list", sort="order"))

@app.post("/tasks/<int:task_id>/down")
def task_down(task_id: int):
    with engine.begin() as conn:
        cur = conn.execute(text("""
          SELECT id, project_id, status, sort_order
          FROM tasks WHERE id=:id
        """), {"id": task_id}).mappings().first()
        if not cur:
            abort(404)

        nxt = conn.execute(text("""
          SELECT id, sort_order
          FROM tasks
          WHERE project_id=:pid AND status=:st
            AND sort_order > :so
          ORDER BY sort_order ASC
          LIMIT 1
        """), {"pid": cur["project_id"], "st": cur["status"], "so": cur["sort_order"]}).mappings().first()

        if nxt:
            conn.execute(text("UPDATE tasks SET sort_order=:so WHERE id=:id"), {"so": nxt["sort_order"], "id": cur["id"]})
            conn.execute(text("UPDATE tasks SET sort_order=:so WHERE id=:id"), {"so": cur["sort_order"], "id": nxt["id"]})

    return redirect(url_for("tasks_list", sort="order"))

@app.post("/tasks/<int:task_id>/done")
def task_done(task_id: int):
    with engine.begin() as conn:
        conn.execute(text("""
          UPDATE tasks
          SET status='DONE',
              completed_at=NOW(),
              updated_at=NOW()
          WHERE id=:id
        """), {"id": task_id})
    return redirect(url_for("tasks_list"))

@app.post("/tasks/<int:task_id>/undo")
def task_undo(task_id: int):
    with engine.begin() as conn:
        # TODOに戻すときは、その科目TODOの末尾に付け直す
        with conn.begin_nested():
            cur = conn.execute(text("SELECT project_id FROM tasks WHERE id=:id"), {"id": task_id}).mappings().first()
            if not cur:
                abort(404)
            mx = conn.execute(text("""
              SELECT COALESCE(MAX(sort_order), 0) AS m
              FROM tasks
              WHERE project_id=:pid AND status='TODO'
            """), {"pid": cur["project_id"]}).mappings().first()["m"]

            conn.execute(text("""
              UPDATE tasks
              SET status='TODO',
                  completed_at=NULL,
                  sort_order=:so,
                  updated_at=NOW()
              WHERE id=:id
            """), {"id": task_id, "so": int(mx) + 1})

    return redirect(url_for("tasks_list", sort="order"))

@app.post("/tasks/<int:task_id>/delete")
def task_delete(task_id: int):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM tasks WHERE id=:id"), {"id": task_id})
    return redirect(url_for("tasks_list"))

# -------------------------
# Projects (CRUD)
# -------------------------
@app.get("/projects")
def projects_list():
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, name, description FROM projects ORDER BY id;")).mappings().all()

    body = """
    <div class="row">
      <a href="{{ url_for('tasks_list') }}">← Tasksに戻る</a>
      <a href="{{ url_for('project_new') }}"><button>＋ 科目を追加</button></a>
    </div>

    <h2>科目（Projects）</h2>
    <div class="card">
      <table>
        <tr><th style="width:60px;">ID</th><th>Name</th><th>Description</th><th style="width:200px;">操作</th></tr>
        {% for r in rows %}
          <tr>
            <td class="mono">{{r.id}}</td>
            <td>{{r.name}}</td>
            <td>{{r.description or ''}}</td>
            <td>
              <a href="{{ url_for('project_edit', project_id=r.id) }}">編集</a>
              <form style="display:inline" method="post" action="{{ url_for('project_delete', project_id=r.id) }}"
                    onsubmit="return confirm('この科目を削除する？（紐づくタスクがあると削除できない）')">
                <button type="submit">削除</button>
              </form>
            </td>
          </tr>
        {% endfor %}
      </table>
      <div class="small">※削除できない場合：その科目に紐づくtasksが残っている。</div>
    </div>
    """
    return render_page(body, rows=rows)

@app.get("/projects/new")
def project_new():
    body = """
    <div class="row">
      <a href="{{ url_for('projects_list') }}">← 戻る</a>
    </div>

    <h2>科目を追加</h2>
    <div class="card">
      <form method="post" action="{{ url_for('project_create') }}">
        <p>科目名<br><input name="name" required style="width:100%"></p>
        <p>説明<br><textarea name="description" rows="4" style="width:100%"></textarea></p>
        <button type="submit">作成</button>
      </form>
    </div>
    """
    return render_page(body)

@app.post("/projects")
def project_create():
    name = (request.form.get("name") or "").strip()
    desc = (request.form.get("description") or "").strip()
    if not name:
        return error_page("科目名が空である。")

    with engine.begin() as conn:
        conn.execute(text("INSERT INTO projects (name, description) VALUES (:n, :d)"), {"n": name, "d": desc})

    return redirect(url_for("projects_list"))

@app.get("/projects/<int:project_id>/edit")
def project_edit(project_id: int):
    with engine.connect() as conn:
        p = conn.execute(text("SELECT id, name, description FROM projects WHERE id=:id"), {"id": project_id}).mappings().first()
        if not p:
            abort(404)

    body = """
    <div class="row">
      <a href="{{ url_for('projects_list') }}">← 戻る</a>
    </div>

    <h2>科目編集 #{{p.id}}</h2>
    <div class="card">
      <form method="post" action="{{ url_for('project_update', project_id=p.id) }}">
        <p>科目名<br><input name="name" value="{{p.name}}" required style="width:100%"></p>
        <p>説明<br><textarea name="description" rows="4" style="width:100%">{{p.description or ''}}</textarea></p>
        <button type="submit">更新</button>
      </form>
    </div>
    """
    return render_page(body, p=p)

@app.post("/projects/<int:project_id>")
def project_update(project_id: int):
    name = (request.form.get("name") or "").strip()
    desc = (request.form.get("description") or "").strip()
    if not name:
        return error_page("科目名が空である。")

    with engine.begin() as conn:
        conn.execute(text("UPDATE projects SET name=:n, description=:d WHERE id=:id"), {"id": project_id, "n": name, "d": desc})

    return redirect(url_for("projects_list"))

@app.post("/projects/<int:project_id>/delete")
def project_delete(project_id: int):
    with engine.begin() as conn:
        cnt = conn.execute(text("SELECT COUNT(*) AS c FROM tasks WHERE project_id=:id"), {"id": project_id}).mappings().first()["c"]
        if cnt and int(cnt) > 0:
            return error_page(f"この科目には {cnt} 件のタスクが紐づいているため削除できない。先にタスクを移動/削除する。", 400)

        conn.execute(text("DELETE FROM projects WHERE id=:id"), {"id": project_id})

    return redirect(url_for("projects_list"))

# -------------------------
# (Usersは残しておく)
# -------------------------
@app.get("/users")
def users_list():
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, display_name, email FROM users ORDER BY id;")).mappings().all()

    body = """
    <div class="row">
      <a href="{{ url_for('tasks_list') }}">← Tasksに戻る</a>
    </div>

    <h2>Users（使ってないが残している）</h2>
    <div class="card">
      <table>
        <tr><th>ID</th><th>Name</th><th>Email</th></tr>
        {% for r in rows %}
          <tr><td class="mono">{{r.id}}</td><td>{{r.display_name}}</td><td>{{r.email or ''}}</td></tr>
        {% endfor %}
      </table>
      <div class="small">個人用運用なので、担当者機能はUIから削除している。</div>
    </div>
    """
    return render_page(body, rows=rows)

if __name__ == "__main__":
    # macOSのControl Centerが5000を取ることがあるので5001固定
    app.run(host="0.0.0.0", port=5001, debug=True)
