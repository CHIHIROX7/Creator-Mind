# CreatorMind API

CreatorMind 的 FastAPI 后端。开发与启动方式见仓库根目录 `README.md`。

## 素材库与 RAG 联调

启动 PostgreSQL 和 MinIO，安装新的后端依赖并执行 `alembic upgrade head`。开发模式下第一次上传会在需要时创建配置的素材桶。素材库目前面向本地单工作区，生产环境的接口在接入认证和数据隔离前关闭。

如果本地无法拉取项目的 MinIO 镜像，可以先用 `docker compose up -d postgres redis` 启动数据库和 Redis，再在 `backend/.env` 中配置可访问的 S3 兼容服务。连接配置为 `CREATORMIND_S3_ENDPOINT_URL`、`CREATORMIND_S3_ACCESS_KEY`、`CREATORMIND_S3_SECRET_KEY` 和 `CREATORMIND_S3_BUCKET`。

| 接口 | 用途 |
| --- | --- |
| `POST /api/v1/sources` | 用 `multipart/form-data` 上传 `file`，可选 `source_url`，成功返回 201。 |
| `GET /api/v1/sources` | 按导入时间倒序分页，支持 `limit` 和 `offset`。 |
| `GET /api/v1/sources/{asset_id}` | 查询素材元数据。上传响应里的 `id` 就是 `asset_id`。 |

支持 PDF、Markdown 和 TXT，单文件上限为 20 MiB。可在 `/docs` 或前端「作品与素材库」验证上传。

可信的后台代码可调用 `await read_source_file(db, asset_id)`，函数位于 `app.services.source_storage`，返回 `(素材记录, 原文件字节)`，找不到素材时返回 `None`。RAG 的解析任务接入后可以传入这个 ID，解析与索引由任务执行。
