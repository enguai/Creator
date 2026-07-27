# 造物者用户系统部署说明

## 本地使用

应用数据库迁移：

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

创建网站管理员：

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
```

管理员后台：

```text
http://127.0.0.1:8000/admin/
```

后台可以管理用户名、邮箱、启用状态、管理员权限、注册时间和最后登录时间，也可以重置用户密码。系统不会保存或显示用户的原始密码。

## PostgreSQL

正式服务器建议使用 PostgreSQL，并设置：

```text
DB_ENGINE=postgresql
DB_NAME=creator
DB_USER=creator
DB_PASSWORD=请填写高强度数据库密码
DB_HOST=127.0.0.1
DB_PORT=5432
DB_CONN_MAX_AGE=60
```

首次切换数据库前需要备份 SQLite 数据并执行数据迁移，不能直接删除 `db.sqlite3`。

## 邮箱找回

本地默认把找回邮件输出到 Django 日志。正式发送邮件需要配置 SMTP：

```text
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=SMTP服务器地址
EMAIL_PORT=587
EMAIL_HOST_USER=发件邮箱
EMAIL_HOST_PASSWORD=邮箱授权码
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=造物者 <no-reply@creatorlive.online>
FRONTEND_BASE_URL=https://creatorlive.online
```

## HTTPS

用户系统上线前必须先为 `creatorlive.online` 配置有效证书，然后设置：

```text
DJANGO_SECURE_SSL_REDIRECT=True
DJANGO_SECURE_COOKIES=True
DJANGO_CSRF_TRUSTED_ORIGINS=https://creatorlive.online
DJANGO_SECURE_HSTS_SECONDS=31536000
DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=True
```

修改服务器环境变量后，执行：

```bash
cd /var/www/creator
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
sudo systemctl restart creator
```
